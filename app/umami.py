"""Cliente de Umami (analítica web sin cookies, MIT) — instancia
compartida, aislamiento real por *Team*, verificado en vivo contra un
contenedor real (imagen oficial
`docker.umami.is/umami-software/umami:postgresql-latest`, sin licencia
de pago):

## Aislamiento por Team — verificado en vivo

- Un sitio (`website`) se crea ya asociado a un Team concreto
  (`POST /api/websites` con `teamId` en el cuerpo) — no existe un
  endpoint separado de "añadir sitio a equipo" (`POST/PUT
  /api/teams/{id}/websites` devuelven 404/vacío, confirmado en vivo).
- Un usuario `team-member` de ese Team ve exactamente los sitios de su
  Team (`GET /api/teams/{id}/websites`) y accede a sus estadísticas por
  id. Al intentar acceder por id a un sitio de OTRO tenant (fuera de su
  Team), el propio servidor responde **401** — confirmado en vivo, no
  un filtro de cliente.
- `DELETE /api/teams/{id}` borra en cascada los sitios de ese Team —
  confirmado en vivo (el sitio desaparece de `GET /api/websites` justo
  después), así que desaprovisionar un tenant es un único borrado.

## Bootstrap del admin — hallazgo real

Umami **no admite fijar la contraseña del admin inicial por variable
de entorno** (a diferencia de Listmonk/Cal.diy) — la primera migración
crea siempre el usuario `admin`/`umami` fijo. `bootstrap_admin()`
inicia sesión con esas credenciales de fábrica (o, si ya se ejecutó
antes, con `UMAMI_ADMIN_PASSWORD`) y cambia la contraseña a la
configurada. Idempotente.

**Otro hallazgo real, no documentado de forma obvia**: actualizar un
usuario (incl. su contraseña) es `POST /api/users/{id}`, NO `PUT` ni
`PATCH` — ambos devuelven 405, confirmado en vivo. Mismo tipo de
sorpresa que el `PATCH` vs `PUT` de Meilisearch (ver app/busqueda.py).

Mismo criterio que el resto de `app/*.py`: solo `urllib` de la librería
estándar.
"""
import json
import os
import string
import urllib.error
import urllib.request

UMAMI_URL = os.environ.get("HERRAMIENTA_UMAMI_URL", "http://127.0.0.1:8030")
UMAMI_ADMIN_USER = os.environ.get("UMAMI_ADMIN_USER", "admin")
UMAMI_ADMIN_PASSWORD = os.environ.get("UMAMI_ADMIN_PASSWORD")
TIMEOUT_SEGUNDOS = 10


class ErrorUmami(Exception):
    """Error legible para mostrar cuando Umami falla."""


def _slug(nombre: str) -> str:
    permitidos = string.ascii_lowercase + string.digits
    bruto = "".join(ch if ch in permitidos else "-" for ch in nombre.lower().strip())
    while "--" in bruto:
        bruto = bruto.replace("--", "-")
    return bruto.strip("-") or "tenant"


def _peticion(endpoint: str, *, metodo: str = "GET", cuerpo: dict | None = None, token: str | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json"}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{UMAMI_URL}{endpoint}", data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {})
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error)
        except json.JSONDecodeError:
            return e.code, {"message": cuerpo_error}
    except urllib.error.URLError as e:
        raise ErrorUmami(
            f"No se ha podido conectar con Umami ({UMAMI_URL}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError:
        raise ErrorUmami(f"Tiempo de espera agotado al contactar con Umami ({UMAMI_URL}).")


def _login(usuario: str, contrasena: str) -> str | None:
    estado, cuerpo = _peticion("/api/auth/login", metodo="POST", cuerpo={"username": usuario, "password": contrasena})
    if estado != 200:
        return None
    return cuerpo["token"]


def _token_admin() -> str:
    if not UMAMI_ADMIN_PASSWORD:
        raise ErrorUmami("UMAMI_ADMIN_PASSWORD no está configurada.")
    token = _login(UMAMI_ADMIN_USER, UMAMI_ADMIN_PASSWORD)
    if token is None:
        raise ErrorUmami("No se ha podido iniciar sesión en Umami como admin — revisa UMAMI_ADMIN_USER/PASSWORD.")
    return token


def bootstrap_admin() -> None:
    """Cambia la contraseña de fábrica (`admin`/`umami`) por
    UMAMI_ADMIN_PASSWORD. Paso de despliegue, se llama UNA VEZ (ver
    HOSTING.md), no desde `aprovisionar_tenant`. Idempotente: si ya se
    ejecutó antes (la contraseña de fábrica ya no funciona), no hace
    nada — se detecta porque el login con la contraseña YA configurada
    tiene éxito."""
    if not UMAMI_ADMIN_PASSWORD:
        raise ErrorUmami("Definí UMAMI_ADMIN_PASSWORD antes de arrancar Umami.")
    if _login(UMAMI_ADMIN_USER, UMAMI_ADMIN_PASSWORD) is not None:
        return
    token = _login(UMAMI_ADMIN_USER, "umami")
    if token is None:
        raise ErrorUmami(
            "No se ha podido iniciar sesión en Umami ni con UMAMI_ADMIN_PASSWORD ni con la "
            "contraseña de fábrica ('umami') — revisa que el contenedor esté recién desplegado."
        )
    estado, cuerpo = _peticion("/api/auth/login", metodo="POST", cuerpo={"username": UMAMI_ADMIN_USER, "password": "umami"})
    admin_id = cuerpo["user"]["id"]
    estado, cuerpo = _peticion(f"/api/users/{admin_id}", metodo="POST", token=token, cuerpo={"password": UMAMI_ADMIN_PASSWORD})
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorUmami(f"No se ha podido cambiar la contraseña de fábrica del admin de Umami: {mensaje}")


def aprovisionar_tenant(tenant_id: int, nombre_tenant: str) -> dict | None:
    """Crea el Team y el sitio (website) de un tenant, 100% automático.
    Devuelve {"team_id", "website_id"}, o None si UMAMI_ADMIN_PASSWORD
    no está configurada. El "domain" del sitio es solo descriptivo en
    Umami (no restringe desde dónde se puede enviar tracking,
    verificado en vivo) — se deja un valor provisional derivado del
    nombre; el propio tenant puede corregirlo después desde Umami una
    vez conozca el dominio real de su web."""
    if not UMAMI_ADMIN_PASSWORD:
        return None
    token = _token_admin()
    slug = _slug(nombre_tenant)

    estado, cuerpo = _peticion("/api/teams", metodo="POST", token=token, cuerpo={"name": f"tenant-{tenant_id}-{slug}"})
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorUmami(f"No se ha podido crear el Team de Umami para '{nombre_tenant}': {mensaje}")
    # El endpoint devuelve la lista [Team, TeamUser] tras crearlo, no solo el Team.
    team = next(r for r in cuerpo if "name" in r)
    team_id = team["id"]

    estado, cuerpo = _peticion(
        "/api/websites", metodo="POST", token=token,
        cuerpo={"name": nombre_tenant, "domain": f"{slug}.guilda-work.local", "teamId": team_id},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorUmami(f"No se ha podido crear el sitio de Umami para '{nombre_tenant}': {mensaje}")
    website_id = cuerpo["id"]

    return {"team_id": team_id, "website_id": website_id}


def crear_usuario_tenant(email: str, team_id: str, contrasena: str) -> None:
    """Da de alta un usuario humano de Umami y lo añade al Team de su
    tenant como `team-member` — sin SSO (Umami no lo tiene en su
    edición gratuita), así que se le asigna una contraseña temporal
    (mismo criterio que OpenProject/Chatwoot en
    rutas_backoffice.py:crear_usuario()). No hace nada si Umami no está
    configurado."""
    if not UMAMI_ADMIN_PASSWORD:
        return
    token = _token_admin()
    estado, cuerpo = _peticion(
        "/api/users", metodo="POST", token=token,
        cuerpo={"username": email, "password": contrasena, "role": "user"},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorUmami(f"No se ha podido dar de alta a '{email}' en Umami: {mensaje}")
    usuario_id = cuerpo["id"]

    estado, cuerpo = _peticion(
        f"/api/teams/{team_id}/users", metodo="POST", token=token,
        cuerpo={"userId": usuario_id, "role": "team-member"},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo
        raise ErrorUmami(f"No se ha podido añadir a '{email}' al Team de Umami: {mensaje}")


def desaprovisionar_tenant(team_id: str | None) -> None:
    """Borra el Team de Umami de un tenant — arrastra en cascada su(s)
    sitio(s), confirmado en vivo. No falla si ya no existe, ni si Umami
    no está configurado."""
    if not UMAMI_ADMIN_PASSWORD or not team_id:
        return
    token = _token_admin()
    _peticion(f"/api/teams/{team_id}", metodo="DELETE", token=token)
