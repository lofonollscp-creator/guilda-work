"""Cliente del Client-Server API de Matrix/Synapse (Fase MCP: listar salas
y enviar mensajes en el chat desde un asistente, ver mcp_server.py).

Auth: SYNAPSE_BOT_ACCESS_TOKEN, el token de acceso de un usuario "bot"
dedicado (se crea una vez con `register_new_matrix_user`, ver
HOSTING.md) — nunca el token de una persona real, para que quede claro en
el propio chat qué mensajes manda el asistente y cuáles una persona.
Opcional a propósito, mismo criterio que el resto de app/*.py — sin él,
`listar_salas` devuelve [].

Usa el mismo hostname/puerto que ya expone `app/herramientas.py` para
Element (`HERRAMIENTA_MATRIX_HOMESERVER_URL`) — el homeserver de verdad,
no la interfaz web.

Mismo criterio que el resto de app/*.py de integraciones: solo `urllib`
de la librería estándar.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

SYNAPSE_URL = os.environ.get("HERRAMIENTA_MATRIX_HOMESERVER_URL", "http://127.0.0.1:8008")
SYNAPSE_BOT_ACCESS_TOKEN = os.environ.get("SYNAPSE_BOT_ACCESS_TOKEN")
TIMEOUT_SEGUNDOS = 10


class ErrorSynapse(Exception):
    """Error legible para mostrar cuando Synapse falla."""


def _peticion(ruta: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "Authorization": f"Bearer {SYNAPSE_BOT_ACCESS_TOKEN or ''}"}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{SYNAPSE_URL}{ruta}", data=datos, headers=cabeceras, method=metodo)
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
        raise ErrorSynapse(
            f"No se ha podido conectar con Synapse ({SYNAPSE_URL}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorSynapse(f"Tiempo de espera agotado al contactar con Synapse ({SYNAPSE_URL}).")


def listar_salas() -> list[dict]:
    """Lista las salas a las que pertenece el usuario bot, con su nombre
    si lo tiene. [] si SYNAPSE_BOT_ACCESS_TOKEN no está configurado."""
    if not SYNAPSE_BOT_ACCESS_TOKEN:
        return []
    estado, cuerpo = _peticion("/_matrix/client/v3/joined_rooms")
    if estado != 200:
        mensaje = cuerpo.get("error") or cuerpo
        raise ErrorSynapse(f"No se han podido listar las salas de Synapse: {mensaje}")
    salas = []
    for sala_id in cuerpo.get("joined_rooms", []):
        nombre = None
        estado_nombre, cuerpo_nombre = _peticion(
            f"/_matrix/client/v3/rooms/{urllib.parse.quote(sala_id)}/state/m.room.name"
        )
        if estado_nombre == 200:
            nombre = cuerpo_nombre.get("name")
        salas.append({"sala_id": sala_id, "nombre": nombre})
    return salas


def enviar_mensaje(sala_id: str, texto: str) -> dict:
    """Envía un mensaje de texto a una sala (el bot tiene que ser ya
    miembro de ella)."""
    if not SYNAPSE_BOT_ACCESS_TOKEN:
        raise ErrorSynapse("SYNAPSE_BOT_ACCESS_TOKEN no está configurado.")
    txn_id = uuid.uuid4().hex
    estado, cuerpo = _peticion(
        f"/_matrix/client/v3/rooms/{urllib.parse.quote(sala_id)}/send/m.room.message/{txn_id}",
        metodo="PUT",
        cuerpo={"msgtype": "m.text", "body": texto},
    )
    if estado != 200:
        mensaje = cuerpo.get("error") or cuerpo
        raise ErrorSynapse(f"No se ha podido enviar el mensaje a la sala {sala_id} de Synapse: {mensaje}")
    return cuerpo
