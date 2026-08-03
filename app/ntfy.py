"""Cliente de ntfy (notificaciones push autoalojadas, ver mcp_tools.py y
HOSTING.md) — licencia Apache-2.0/GPLv2 dual, instancia compartida con
aislamiento real por tenant vía usuario + control de acceso (ACL) de
topic, nativos de ntfy.

## Aprovisionamiento — verificado en vivo contra un contenedor real

1. **Crear el usuario** (`POST /v1/users`, Basic Auth como el admin de
   ntfy): funciona por API HTTP normal, sin pasos manuales. Idempotente
   por diseño propio de ntfy — reintentar con el mismo `username` da
   `409 conflict: user already exists`, tratado aquí como éxito.
2. **Conceder acceso al topic** (`ntfy access <usuario> <topic> rw`):
   **no existe equivalente HTTP** — confirmado en la propia ayuda de la
   CLI de ntfy (`ntfy access --help`: "This is a server-only command...
   directly manages the user.db"). Se ejecuta vía `docker exec` contra
   el contenedor de ntfy, mismo patrón que ya usa este proyecto para
   comandos de un solo uso dentro de un contenedor (ver
   `app/facturascripts.py:_ejecutar_psql`). Idempotente (volver a
   conceder el mismo acceso no falla, verificado en vivo).
3. **Generar un token de acceso** (`POST /v1/account/token`, Basic Auth
   como el propio usuario del tenant, no el admin): sí es HTTP puro. **No
   es idempotente** — cada llamada genera un token nuevo, así que solo se
   invoca una vez en `aprovisionar_tenant()` (mismo criterio que
   Documenso/Listmonk: el secreto no se puede volver a leer después).

El envío de notificaciones (`enviar()`) usa ese token como
`Authorization: Bearer <token>` contra `PUT/POST /<topic>` — API pública
de ntfy, sin necesidad de credenciales de admin.

Mismo criterio que el resto de `app/*.py`: solo `urllib`/`subprocess` de
la librería estándar.
"""
import base64
import json
import os
import secrets
import string
import subprocess
import urllib.error
import urllib.request

NTFY_URL = os.environ.get("HERRAMIENTA_NTFY_URL", "http://127.0.0.1:8027")
NTFY_ADMIN_USER = os.environ.get("NTFY_ADMIN_USER")
NTFY_ADMIN_PASSWORD = os.environ.get("NTFY_ADMIN_PASSWORD")
# Nombre del contenedor para el paso de `docker exec` (punto 2 del
# docstring) — ver `container_name` en docker-compose.yml.
NTFY_CONTENEDOR = os.environ.get("NTFY_CONTENEDOR", "guilda-work-ntfy")
TIMEOUT_SEGUNDOS = 10


class ErrorNtfy(Exception):
    """Error legible para mostrar cuando ntfy falla."""


def _slug(nombre: str) -> str:
    permitidos = string.ascii_lowercase + string.digits
    bruto = "".join(ch if ch in permitidos else "-" for ch in nombre.lower().strip())
    while "--" in bruto:
        bruto = bruto.replace("--", "-")
    return bruto.strip("-") or "tenant"


def _cabecera_basic(usuario: str, contrasena: str) -> str:
    return "Basic " + base64.b64encode(f"{usuario}:{contrasena}".encode()).decode()


def _peticion(endpoint: str, *, usuario: str, contrasena: str, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(
        f"{NTFY_URL}{endpoint}",
        data=datos,
        method=metodo,
        headers={
            "Authorization": _cabecera_basic(usuario, contrasena),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read()
            return json.loads(cuerpo_resp) if cuerpo_resp else None
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")
        raise ErrorNtfy(f"ntfy ha rechazado la petición a {endpoint} (HTTP {e.code}): {detalle}") from e
    except urllib.error.URLError as e:
        raise ErrorNtfy(
            f"No se ha podido conectar con ntfy ({NTFY_URL}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorNtfy(f"Tiempo de espera agotado al contactar con ntfy ({NTFY_URL}).")


def _conceder_acceso(usuario: str, topic: str) -> None:
    """`ntfy access` es un comando de servidor sin equivalente HTTP (ver
    docstring del módulo) — se ejecuta dentro del propio contenedor."""
    resultado = subprocess.run(
        ["docker", "exec", NTFY_CONTENEDOR, "ntfy", "access", usuario, topic, "rw"],
        capture_output=True, text=True, timeout=30,
    )
    if resultado.returncode != 0:
        raise ErrorNtfy(f"'ntfy access' falló para {usuario}/{topic}: {resultado.stderr.strip()}")


def aprovisionar_tenant(tenant_id: int, nombre_tenant: str) -> dict:
    """Crea (si no existe ya) el usuario de ntfy de este tenant, le
    concede acceso exclusivo a su propio topic, y genera un token nuevo.
    [] o excepción si NTFY_ADMIN_USER/PASSWORD no están configuradas —
    mismo criterio que el resto de integraciones opcionales."""
    if not NTFY_ADMIN_USER or not NTFY_ADMIN_PASSWORD:
        raise ErrorNtfy("NTFY_ADMIN_USER/NTFY_ADMIN_PASSWORD no están configuradas.")

    usuario = f"tenant_{tenant_id}"
    topic = f"guilda-{_slug(nombre_tenant)}-{tenant_id}"
    contrasena = secrets.token_urlsafe(24)

    try:
        _peticion(
            "/v1/users", usuario=NTFY_ADMIN_USER, contrasena=NTFY_ADMIN_PASSWORD, metodo="POST",
            cuerpo={"username": usuario, "password": contrasena, "role": "user"},
        )
    except ErrorNtfy as e:
        if "conflict" not in str(e).lower():
            raise
        # Usuario ya existente de una ejecución anterior — no podemos
        # recuperar su contraseña original (ntfy no la expone nunca), así
        # que no se puede generar un token nuevo sin ella. Este caso solo
        # se da si aprovisionar_tenant() se reintenta a mano tras un
        # fallo a mitad; se documenta como límite conocido en HOSTING.md.
        raise ErrorNtfy(
            f"El usuario {usuario} ya existe en ntfy de un intento anterior — "
            "hay que borrarlo a mano (`docker exec ... ntfy user del`) antes de reintentar."
        ) from e

    _conceder_acceso(usuario, topic)

    resultado = _peticion(
        "/v1/account/token", usuario=usuario, contrasena=contrasena, metodo="POST",
        cuerpo={"label": "guilda-work"},
    )
    return {"topic": topic, "token": resultado["token"]}


def desaprovisionar_tenant(tenant_id: int) -> None:
    """Borra el usuario de ntfy de este tenant (`ntfy user del`, mismo
    mecanismo de solo-CLI que `_conceder_acceso` — ver el docstring del
    módulo) — sus entradas de ACL se borran solas junto con él."""
    resultado = subprocess.run(
        ["docker", "exec", NTFY_CONTENEDOR, "ntfy", "user", "del", f"tenant_{tenant_id}"],
        capture_output=True, text=True, timeout=30,
    )
    if resultado.returncode != 0:
        raise ErrorNtfy(f"'ntfy user del' falló para tenant_{tenant_id}: {resultado.stderr.strip()}")


def enviar(topic: str, token: str, titulo: str, mensaje: str, prioridad: str = "default", click_url: str | None = None) -> None:
    """Envía una notificación push al topic de un tenant. `prioridad`:
    min|low|default|high|urgent (nombres propios de ntfy)."""
    cabeceras = {"Authorization": f"Bearer {token}", "Title": titulo, "Priority": prioridad}
    if click_url:
        cabeceras["Click"] = click_url
    req = urllib.request.Request(
        f"{NTFY_URL}/{topic}", data=mensaje.encode("utf-8"), method="POST", headers=cabeceras,
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS):
            pass
    except urllib.error.HTTPError as e:
        raise ErrorNtfy(f"ntfy ha rechazado el envío al topic {topic} (HTTP {e.code}).") from e
    except urllib.error.URLError as e:
        raise ErrorNtfy(f"No se ha podido conectar con ntfy ({NTFY_URL}). Detalle: {e.reason}") from e
