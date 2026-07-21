"""Cliente de la API de Metabase (Fase 7c: alta automática de usuarios
desde el backoffice en herramientas sin SSO, ver app/rutas_backoffice.py).

Limitación real de Metabase (a diferencia de OpenProject/Chatwoot):
`POST /api/user` no acepta una contraseña elegida — o manda invitación
por email (si hay SMTP configurado) o la persona tiene que completar el
alta con "¿Olvidaste tu contraseña?" la primera vez. Por eso aquí solo se
crea la cuenta (email/nombre) — no se pretende fijar una contraseña.

METABASE_API_KEY es opcional a propósito (igual que
CHATWOOT_WEBSITE_TOKEN): sin ella, `crear_usuario` no hace nada y
devuelve None, para no romper el alta de las demás herramientas. Se
genera una vez a mano: Admin → Configuración → Autenticación → Claves de
API.
"""
import json
import os
import urllib.error
import urllib.request

METABASE_URL = os.environ.get("HERRAMIENTA_METABASE_URL", "http://127.0.0.1:3000")
METABASE_API_KEY = os.environ.get("METABASE_API_KEY")
TIMEOUT_SEGUNDOS = 10


class ErrorMetabase(Exception):
    """Error legible para mostrar en el backoffice cuando Metabase falla."""


def _peticion(url: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "x-api-key": METABASE_API_KEY or ""}
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
        raise ErrorMetabase(
            f"No se ha podido conectar con Metabase ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorMetabase(f"Tiempo de espera agotado al contactar con Metabase ({url}).")


def crear_usuario(email: str, nombre: str = "", apellidos: str = "") -> int | None:
    """Devuelve None (sin hacer nada) si METABASE_API_KEY no está
    configurada — Metabase es opcional en esta integración, igual que el
    widget de Chatwoot lo es sin CHATWOOT_WEBSITE_TOKEN."""
    if not METABASE_API_KEY:
        return None
    estado, cuerpo = _peticion(
        f"{METABASE_URL}/api/user",
        metodo="POST",
        cuerpo={
            "email": email,
            "first_name": nombre or email.split("@")[0],
            "last_name": apellidos or "",
        },
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo.get("errors") or cuerpo
        raise ErrorMetabase(f"No se ha podido crear el usuario en Metabase: {mensaje}")
    return cuerpo["id"]
