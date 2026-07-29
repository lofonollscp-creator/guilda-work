"""Cliente de la Platform API de Chatwoot (Fase 7c: alta automática de
usuarios desde el backoffice en herramientas sin SSO, ver
app/rutas_backoffice.py).

Chatwoot tiene DOS APIs de gestión de usuarios:
- La normal ("Application API", cuentas → agentes) exige que el agente
  nuevo confirme su email — no vale para un alta automática sin SMTP.
- La **Platform API** (`/platform/api/v1/...`) sí crea el usuario ya
  confirmado (`skip_confirmation!`, confirmado leyendo
  `app/controllers/platform/api/v1/users_controller.rb` del propio
  contenedor de Chatwoot) — pensada para integraciones como esta.

La Platform API no tiene UI en la edición self-hosted — el `PlatformApp`
y su token se crean una sola vez por consola de Rails:

    docker exec -it guilda-work-chatwoot-web bundle exec rails runner "
      app = PlatformApp.find_or_create_by!(name: 'Guilda Work')
      app.platform_app_permissibles.find_or_create_by!(permissible: Account.find(1))
      puts app.access_token.token
    "

y se guarda como CHATWOOT_PLATFORM_API_TOKEN.
"""
import json
import os
import urllib.error
import urllib.request

CHATWOOT_URL = os.environ.get("HERRAMIENTA_CHATWOOT_URL", "http://127.0.0.1:8011")
CHATWOOT_PLATFORM_API_TOKEN = os.environ.get("CHATWOOT_PLATFORM_API_TOKEN")
CHATWOOT_ACCOUNT_ID = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
# Token de un AGENTE normal (Perfil → Ajustes de acceso a la API, en la
# propia web de Chatwoot) — distinto de CHATWOOT_PLATFORM_API_TOKEN. La
# Platform API (usada arriba) solo gestiona cuentas/usuarios a nivel de
# instalación; conversaciones/mensajes viven en la Application API
# normal, que exige el token de un agente real con acceso a la cuenta
# (Fase MCP, ver mcp_server.py).
CHATWOOT_AGENT_API_TOKEN = os.environ.get("CHATWOOT_AGENT_API_TOKEN")
TIMEOUT_SEGUNDOS = 10


class ErrorChatwoot(Exception):
    """Error legible para mostrar en el backoffice cuando Chatwoot falla."""


def _peticion(url: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "api_access_token": CHATWOOT_PLATFORM_API_TOKEN or ""}
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
        raise ErrorChatwoot(
            f"No se ha podido conectar con Chatwoot ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorChatwoot(f"Tiempo de espera agotado al contactar con Chatwoot ({url}).")


def _peticion_agente(url: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    """Igual que _peticion, pero autenticada con CHATWOOT_AGENT_API_TOKEN
    (Application API) en vez de CHATWOOT_PLATFORM_API_TOKEN."""
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "api_access_token": CHATWOOT_AGENT_API_TOKEN or ""}
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
        raise ErrorChatwoot(
            f"No se ha podido conectar con Chatwoot ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorChatwoot(f"Tiempo de espera agotado al contactar con Chatwoot ({url}).")


def crear_usuario(email: str, contrasena: str, nombre: str = "") -> int:
    """Crea (o reutiliza, si ya existe ese email) un usuario global de
    Chatwoot ya confirmado, y lo añade como agente a CHATWOOT_ACCOUNT_ID."""
    if not CHATWOOT_PLATFORM_API_TOKEN:
        raise ErrorChatwoot("CHATWOOT_PLATFORM_API_TOKEN no está configurado.")
    estado, cuerpo = _peticion(
        f"{CHATWOOT_URL}/platform/api/v1/users",
        metodo="POST",
        cuerpo={"name": nombre or email.split("@")[0], "email": email, "password": contrasena},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorChatwoot(f"No se ha podido crear el usuario en Chatwoot: {mensaje}")
    usuario_id = cuerpo["id"]

    estado, cuerpo = _peticion(
        f"{CHATWOOT_URL}/platform/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/account_users",
        metodo="POST",
        cuerpo={"user_id": usuario_id, "role": "agent"},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorChatwoot(f"Usuario creado, pero no se ha podido añadir como agente: {mensaje}")
    return usuario_id


# --- Conversaciones (Fase MCP: Application API, no la Platform API) --------

def listar_conversaciones(estado_filtro: str = "open", limite: int = 20) -> list[dict]:
    """Lista conversaciones de la bandeja de soporte. `estado_filtro`:
    open/resolved/pending/all. Devuelve [] si CHATWOOT_AGENT_API_TOKEN no
    está configurado."""
    if not CHATWOOT_AGENT_API_TOKEN:
        return []
    estado, cuerpo = _peticion_agente(
        f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations?status={estado_filtro}"
    )
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorChatwoot(f"No se han podido listar las conversaciones de Chatwoot: {mensaje}")
    conversaciones = cuerpo.get("data", {}).get("payload", [])
    return conversaciones[:limite]


def leer_conversacion(conversacion_id: int) -> list[dict]:
    """Devuelve los mensajes de una conversación."""
    if not CHATWOOT_AGENT_API_TOKEN:
        raise ErrorChatwoot("CHATWOOT_AGENT_API_TOKEN no está configurado.")
    estado, cuerpo = _peticion_agente(
        f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversacion_id}/messages"
    )
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorChatwoot(f"No se ha podido leer la conversación {conversacion_id} de Chatwoot: {mensaje}")
    return cuerpo.get("payload", [])


def responder_conversacion(conversacion_id: int, texto: str) -> dict:
    """Envía una respuesta (mensaje saliente) en una conversación existente."""
    if not CHATWOOT_AGENT_API_TOKEN:
        raise ErrorChatwoot("CHATWOOT_AGENT_API_TOKEN no está configurado.")
    estado, cuerpo = _peticion_agente(
        f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversacion_id}/messages",
        metodo="POST",
        cuerpo={"content": texto, "message_type": "outgoing"},
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorChatwoot(f"No se ha podido responder en la conversación {conversacion_id} de Chatwoot: {mensaje}")
    return cuerpo
