"""Asistente IA dentro de la propia app: chat con un modelo alojado en
OpenRouter (nube) con acceso, vía "tool calling", a las mismas 27
herramientas que ya expone mcp_server.py por MCP (ver app/ia_herramientas.py).

Usa exclusivamente `urllib` de la librería estándar (mismo estilo que
app/ai_local.py, sin dependencias nuevas). La clave de API NUNCA se guarda
en registro.db: vive en el almacén de credenciales del sistema (keyring),
igual que las contraseñas de correo en app/correo.py.

Cualquier herramienta que MODIFIQUE datos pide confirmación explícita antes
de ejecutarse, salvo que el modo autónomo esté activado en Ajustes — con la
excepción dura de enviar_borrador_correo (envío real de correo, acción
externa irreversible), que siempre pide confirmación pase lo que pase.
"""
import json
import urllib.error
import urllib.request

import keyring

from . import db, ia_herramientas as herramientas

SERVICIO_KEYRING_IA = "guilda-work-ia"
CLAVE_API_OPENROUTER = "openrouter-api-key"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SEGUNDOS = 30

# Cuántas veces puede el modelo encadenar llamadas a herramientas en un
# mismo turno antes de forzar una respuesta final — evita bucles sin fin
# (y su coste) si el modelo se queda pidiendo herramientas indefinidamente.
MAX_ITERACIONES_HERRAMIENTAS = 8

PROMPT_SISTEMA = (
    "Eres el asistente integrado en Guilda Work, una app de registro de "
    "actividad, tareas y correo. Puedes leer y modificar los datos de la "
    "persona usuaria a través de las herramientas disponibles. Sé breve, "
    "directo y responde siempre en español. Antes de dar por hecho un id "
    "(de nota, tarea, mensaje o categoría) que no te haya dado explícitamente "
    "la persona usuaria, consúltalo primero con una herramienta de lectura."
)


class ErrorIA(Exception):
    """Error legible para mostrar en el chat cuando el asistente falla."""


def guardar_api_key(clave: str) -> None:
    keyring.set_password(SERVICIO_KEYRING_IA, CLAVE_API_OPENROUTER, clave)


def obtener_api_key() -> str | None:
    return keyring.get_password(SERVICIO_KEYRING_IA, CLAVE_API_OPENROUTER)


def borrar_api_key() -> None:
    try:
        keyring.delete_password(SERVICIO_KEYRING_IA, CLAVE_API_OPENROUTER)
    except keyring.errors.PasswordDeleteError:
        pass


def _post_json(url: str, payload: dict, api_key: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/lofonollscp-creator/guilda-work",
            "X-Title": "Guilda Work",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")
        raise ErrorIA(f"OpenRouter devolvió un error ({e.code}): {detalle}") from e
    except urllib.error.URLError as e:
        raise ErrorIA(f"No se ha podido conectar con OpenRouter. Detalle: {e.reason}") from e
    except TimeoutError as e:
        raise ErrorIA("Tiempo de espera agotado al contactar con OpenRouter.") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise ErrorIA(f"Respuesta inválida de OpenRouter: {e}") from e


def _mensajes_para_openrouter() -> list[dict]:
    mensajes = [{"role": "system", "content": PROMPT_SISTEMA}]
    for fila in db.listar_mensajes_ia():
        if fila["rol"] == "assistant":
            mensaje = {"role": "assistant", "content": fila["contenido"]}
            if fila["tool_calls_json"]:
                mensaje["tool_calls"] = json.loads(fila["tool_calls_json"])
            mensajes.append(mensaje)
        elif fila["rol"] == "tool":
            mensajes.append({
                "role": "tool",
                "tool_call_id": fila["tool_call_id"],
                "content": fila["contenido"] or "",
            })
        else:
            mensajes.append({"role": "user", "content": fila["contenido"]})
    return mensajes


def _tool_call_id_pendiente() -> str | None:
    """Si el último mensaje `assistant` pidió herramientas y a alguna todavía
    le falta su fila `tool` de respuesta, devuelve el primer tool_call_id sin
    resolver (en el orden en que el modelo los pidió). Si no hay nada
    pendiente, devuelve None."""
    mensajes = db.listar_mensajes_ia()
    if not mensajes or mensajes[-1]["rol"] != "assistant" or not mensajes[-1]["tool_calls_json"]:
        return None
    tool_calls = json.loads(mensajes[-1]["tool_calls_json"])
    ids_pedidos = [tc["id"] for tc in tool_calls]
    ids_respondidos = {m["tool_call_id"] for m in mensajes if m["rol"] == "tool"}
    for tool_call_id in ids_pedidos:
        if tool_call_id not in ids_respondidos:
            return tool_call_id
    return None


def _tool_call_por_id(tool_call_id: str) -> dict | None:
    mensajes = db.listar_mensajes_ia()
    for fila in reversed(mensajes):
        if fila["rol"] == "assistant" and fila["tool_calls_json"]:
            for tc in json.loads(fila["tool_calls_json"]):
                if tc["id"] == tool_call_id:
                    return tc
    return None


def _ejecutar_tool_call(tool_call: dict) -> str:
    """Ejecuta una herramienta y devuelve el resultado como texto (JSON),
    listo para guardarse como contenido de un mensaje `tool`."""
    nombre = tool_call["function"]["name"]
    argumentos = json.loads(tool_call["function"]["arguments"] or "{}")
    try:
        resultado = herramientas.ejecutar(nombre, argumentos)
        return json.dumps(resultado, ensure_ascii=False, default=str)
    except herramientas.ErrorHerramientaIA as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _pendiente_dict(tool_call: dict) -> dict:
    return {
        "tool_call_id": tool_call["id"],
        "herramienta": tool_call["function"]["name"],
        "argumentos": json.loads(tool_call["function"]["arguments"] or "{}"),
    }


def _continuar_conversacion() -> dict:
    preferencias = db.obtener_preferencias_ia()
    modelo = preferencias["modelo"]
    modo_autonomo = bool(preferencias["modo_autonomo"])
    api_key = obtener_api_key()

    if not modelo.strip():
        raise ErrorIA("No hay ningún modelo configurado. Elige uno en Ajustes del Asistente IA.")
    if not api_key:
        raise ErrorIA("No hay ninguna clave de API de OpenRouter configurada. Añádela en Ajustes del Asistente IA.")

    ids_antes = {m["id"] for m in db.listar_mensajes_ia()}

    for _ in range(MAX_ITERACIONES_HERRAMIENTAS):
        # Si queda un tool_call pendiente de confirmación, se para aquí sin
        # llamar a OpenRouter (se resolverá con confirmar_pendiente()).
        tool_call_id_pendiente = _tool_call_id_pendiente()
        if tool_call_id_pendiente is not None:
            tool_call = _tool_call_por_id(tool_call_id_pendiente)
            return {
                "mensajes_nuevos": _mensajes_nuevos_desde(ids_antes),
                "pendiente": _pendiente_dict(tool_call),
            }

        respuesta = _post_json(
            OPENROUTER_URL,
            {"model": modelo, "messages": _mensajes_para_openrouter(), "tools": herramientas.HERRAMIENTAS},
            api_key,
        )
        try:
            mensaje = respuesta["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise ErrorIA(f"Respuesta inesperada de OpenRouter: {respuesta}") from e

        tool_calls = mensaje.get("tool_calls") or []
        if not tool_calls:
            db.agregar_mensaje_ia("assistant", contenido=mensaje.get("content") or "")
            return {"mensajes_nuevos": _mensajes_nuevos_desde(ids_antes), "pendiente": None}

        db.agregar_mensaje_ia(
            "assistant", contenido=mensaje.get("content"),
            tool_calls_json=json.dumps(tool_calls, ensure_ascii=False),
        )

        for tool_call in tool_calls:
            nombre = tool_call["function"]["name"]
            if herramientas.necesita_confirmacion(nombre, modo_autonomo):
                return {
                    "mensajes_nuevos": _mensajes_nuevos_desde(ids_antes),
                    "pendiente": _pendiente_dict(tool_call),
                }
            contenido = _ejecutar_tool_call(tool_call)
            db.agregar_mensaje_ia(
                "tool", contenido=contenido, tool_call_id=tool_call["id"], nombre_herramienta=nombre,
            )

    raise ErrorIA(
        "El asistente ha encadenado demasiadas llamadas a herramientas sin dar una "
        "respuesta final. Inténtalo de nuevo o reformula la petición."
    )


def _mensajes_nuevos_desde(ids_antes: set[int]) -> list[dict]:
    return [dict(m) for m in db.listar_mensajes_ia() if m["id"] not in ids_antes]


def procesar_turno(texto_usuario: str) -> dict:
    if not texto_usuario.strip():
        raise ErrorIA("Escribe un mensaje.")
    if _tool_call_id_pendiente() is not None:
        raise ErrorIA(
            "Hay una acción esperando confirmación. Acéptala o recházala antes de seguir la conversación."
        )
    db.agregar_mensaje_ia("user", contenido=texto_usuario.strip())
    return _continuar_conversacion()


def pendiente_actual() -> dict | None:
    """Devuelve la acción esperando confirmación ahora mismo, si la hay."""
    tool_call_id = _tool_call_id_pendiente()
    if tool_call_id is None:
        return None
    return _pendiente_dict(_tool_call_por_id(tool_call_id))


def confirmar_pendiente(aceptar: bool) -> dict:
    tool_call_id = _tool_call_id_pendiente()
    if tool_call_id is None:
        raise ErrorIA("No hay ninguna acción esperando confirmación.")
    tool_call = _tool_call_por_id(tool_call_id)
    nombre = tool_call["function"]["name"]

    if aceptar:
        contenido = _ejecutar_tool_call(tool_call)
    else:
        contenido = json.dumps(
            {"rechazado": True, "motivo": "El usuario ha rechazado esta acción."}, ensure_ascii=False,
        )
    db.agregar_mensaje_ia("tool", contenido=contenido, tool_call_id=tool_call_id, nombre_herramienta=nombre)
    return _continuar_conversacion()
