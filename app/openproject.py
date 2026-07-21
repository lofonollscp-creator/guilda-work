"""Cliente de la API v3 de OpenProject (Fase 7c: alta automática de usuarios
desde el backoffice en herramientas sin SSO, ver app/rutas_backoffice.py).

Auth: token de API personal (Basic Auth, usuario literal `apikey`, el
token como contraseña — convención propia de OpenProject, no es una
contraseña de usuario). Se genera una vez a mano en OpenProject:
"Mi cuenta → Tokens de acceso", y se guarda como OPENPROJECT_API_TOKEN.

Mismo criterio que app/kratos.py/app/hydra.py: solo `urllib` de la
librería estándar, ningún cliente HTTP nuevo como dependencia.
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

OPENPROJECT_URL = os.environ.get("HERRAMIENTA_OPENPROJECT_URL", "http://127.0.0.1:8010")
OPENPROJECT_API_TOKEN = os.environ.get("OPENPROJECT_API_TOKEN")
TIMEOUT_SEGUNDOS = 10


class ErrorOpenProject(Exception):
    """Error legible para mostrar en el backoffice cuando OpenProject falla."""


def _cabecera_auth() -> dict:
    credenciales = base64.b64encode(f"apikey:{OPENPROJECT_API_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {credenciales}"}


def _peticion(url: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", **_cabecera_auth()}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {})
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error)
        except json.JSONDecodeError:
            return e.code, {"error": cuerpo_error}
    except urllib.error.URLError as e:
        raise ErrorOpenProject(
            f"No se ha podido conectar con OpenProject ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorOpenProject(f"Tiempo de espera agotado al contactar con OpenProject ({url}).")


def _buscar_por_email(email: str) -> int | None:
    filtro = json.dumps([{"email": {"operator": "=", "values": [email]}}])
    estado, cuerpo = _peticion(
        f"{OPENPROJECT_URL}/api/v3/users?filters={urllib.parse.quote(filtro)}"
    )
    if estado != 200:
        return None
    elementos = cuerpo.get("_embedded", {}).get("elements", [])
    return elementos[0]["id"] if elementos else None


def crear_usuario(email: str, contrasena: str, nombre: str = "", apellidos: str = "") -> int:
    """Crea un usuario activo (no invitado) con la contraseña ya en la mano
    — evita el flujo de invitación por email. Si ya existe un usuario con
    ese email, devuelve su id existente en vez de fallar (alta idempotente,
    igual que ya hace Chatwoot en su Platform API)."""
    if not OPENPROJECT_API_TOKEN:
        raise ErrorOpenProject("OPENPROJECT_API_TOKEN no está configurado.")
    estado, cuerpo = _peticion(
        f"{OPENPROJECT_URL}/api/v3/users",
        metodo="POST",
        cuerpo={
            "login": email,
            "email": email,
            "password": contrasena,
            "firstName": nombre or email.split("@")[0],
            "lastName": apellidos or "",
            "status": "active",
        },
    )
    if estado == 201:
        return cuerpo["id"]
    if estado == 422:
        existente = _buscar_por_email(email)
        if existente is not None:
            return existente
    mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
    raise ErrorOpenProject(f"No se ha podido crear el usuario en OpenProject: {mensaje}")
