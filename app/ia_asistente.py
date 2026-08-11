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
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

import keyring

from . import db, ia_herramientas as herramientas

SERVICIO_KEYRING_IA = "guilda-work-ia"
CLAVE_API_OPENROUTER = "openrouter-api-key"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELOS_URL = "https://openrouter.ai/api/v1/models"
TIMEOUT_SEGUNDOS = 30

# Modelos que se ofrecen si la llamada a OpenRouter falla (sin red, caído...)
# y todavía no hay nada en caché — mismos 3 que antes vivían hardcodeados en
# rutas_ia.py, ahora solo como último recurso.
MODELOS_GRATUITOS_RESPALDO = [
    {"id": "meta-llama/llama-3.1-70b-instruct:free", "nombre": "Llama 3.1 70B (gratuito)"},
    {"id": "google/gemini-2.0-flash-exp:free", "nombre": "Gemini 2.0 Flash (gratuito)"},
    {"id": "deepseek/deepseek-chat:free", "nombre": "DeepSeek Chat (gratuito)"},
]

# Cuántas veces puede el modelo encadenar llamadas a herramientas en un
# mismo turno antes de forzar una respuesta final — evita bucles sin fin
# (y su coste) si el modelo se queda pidiendo herramientas indefinidamente.
MAX_ITERACIONES_HERRAMIENTAS = 8

# Nombre del idioma en el propio idioma meta-instrucción (español, para que
# el modelo entienda la instrucción sin ambigüedad) por cada código que ya
# soporta la web (app/main.py:IDIOMAS_DISPONIBLES) -- antes el prompt
# forzaba español siempre pase lo que pase (bug real: si el usuario tenía
# la interfaz en catalán/inglés/francés, el asistente le contestaba en
# español igualmente). "es" por defecto si el usuario no ha elegido ninguno
# (usuarios.idioma NULL), mismo criterio que default_locale="es" en Babel.
_NOMBRES_IDIOMA = {"es": "español", "ca": "catalán", "en": "inglés", "fr": "francés"}


def _prompt_sistema(idioma: str) -> str:
    nombre_idioma = _NOMBRES_IDIOMA.get(idioma, _NOMBRES_IDIOMA["es"])
    return (
        "Eres el asistente integrado en Guilda Work, una app de registro de "
        "actividad, tareas y correo. Puedes leer y modificar los datos de la "
        f"persona usuaria a través de las herramientas disponibles. Sé breve, "
        f"directo y responde siempre en {nombre_idioma}. Antes de dar por hecho un id "
        "(de nota, tarea, mensaje o categoría) que no te haya dado explícitamente "
        "la persona usuaria, consúltalo primero con una herramienta de lectura."
    )


class ErrorIA(Exception):
    """Error legible para mostrar en el chat cuando el asistente falla.
    `codigo_http` solo se rellena si el error viene de una respuesta HTTP
    real de OpenRouter (None en errores de red/timeout/parseo) -- lo usa
    _post_json_con_fallback para decidir si vale la pena probar otra clave."""

    def __init__(self, mensaje: str, codigo_http: int | None = None):
        super().__init__(mensaje)
        self.codigo_http = codigo_http


def _clave_keyring_api(usuario_id: int) -> str:
    return f"{CLAVE_API_OPENROUTER}-usuario-{usuario_id}"


# Códigos HTTP que indican que el problema es de ESA clave concreta (sin
# crédito, inválida, límite de peticiones alcanzado) y por tanto vale la
# pena reintentar con la siguiente de la lista. Cualquier otro código (400
# de payload mal formado, 500 del propio OpenRouter...) se propaga de
# inmediato: cambiar de clave no lo arreglaría.
_CODIGOS_FALLBACK = {401, 402, 403, 429}


def guardar_api_keys(usuario_id: int, claves: list[str]) -> None:
    """Guarda la lista de claves en orden de preferencia (la primera se
    prueba primero; si falla por un motivo propio de esa clave, se pasa a
    la siguiente, ver _post_json_con_fallback). Lista vacía = borrar todo."""
    claves = [c.strip() for c in claves if c.strip()]
    if claves:
        keyring.set_password(SERVICIO_KEYRING_IA, _clave_keyring_api(usuario_id), json.dumps(claves))
    else:
        borrar_api_key(usuario_id)


def obtener_api_keys(usuario_id: int) -> list[str]:
    valor = keyring.get_password(SERVICIO_KEYRING_IA, _clave_keyring_api(usuario_id))
    if not valor:
        return []
    try:
        datos = json.loads(valor)
        if isinstance(datos, list):
            return [str(c) for c in datos if c]
    except (json.JSONDecodeError, TypeError):
        pass
    # Guardado antes de soportar varias claves: una sola clave en texto
    # plano (no JSON) -- se trata como lista de una.
    return [valor]


def borrar_api_key(usuario_id: int) -> None:
    try:
        keyring.delete_password(SERVICIO_KEYRING_IA, _clave_keyring_api(usuario_id))
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
        raise ErrorIA(f"OpenRouter devolvió un error ({e.code}): {detalle}", codigo_http=e.code) from e
    except urllib.error.URLError as e:
        raise ErrorIA(f"No se ha podido conectar con OpenRouter. Detalle: {e.reason}") from e
    except TimeoutError as e:
        raise ErrorIA("Tiempo de espera agotado al contactar con OpenRouter.") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise ErrorIA(f"Respuesta inválida de OpenRouter: {e}") from e


# --- Variante en streaming (Server-Sent Events) -----------------------------
# Mismo servicio, mismo payload, pero con "stream": true: OpenRouter devuelve
# el cuerpo trozo a trozo en vez de todo de golpe, como líneas
# "data: {...}\n\n" terminadas en "data: [DONE]" (formato SSE estándar,
# igual que usa la propia API de OpenAI). Se usa para el asistente de voz
# (Fase V1 del plan "eventual-herding-kitten"): sin esto habría que esperar
# a que el modelo termine de pensar toda la respuesta antes de poder
# empezar a leerla en voz alta.


def _abrir_stream(url: str, payload: dict, api_key: str):
    data = json.dumps({**payload, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/lofonollscp-creator/guilda-work",
            "X-Title": "Guilda Work",
            "Accept": "text/event-stream",
        },
    )
    try:
        return urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS)
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="replace")
        raise ErrorIA(f"OpenRouter devolvió un error ({e.code}): {detalle}", codigo_http=e.code) from e
    except urllib.error.URLError as e:
        raise ErrorIA(f"No se ha podido conectar con OpenRouter. Detalle: {e.reason}") from e
    except TimeoutError as e:
        raise ErrorIA("Tiempo de espera agotado al contactar con OpenRouter.") from e


def _lineas_sse(resp) -> Iterator[dict]:
    """Lee la respuesta HTTP de OpenRouter línea a línea y devuelve cada
    "data: {...}" ya parseada a dict, parando en "data: [DONE]". Ignora
    las líneas en blanco (separadores SSE) y cualquier "data:" que no sea
    JSON válido (algunos proxies mandan comentarios de keep-alive)."""
    try:
        for linea_bytes in resp:
            linea = linea_bytes.decode("utf-8").strip()
            if not linea or not linea.startswith("data:"):
                continue
            contenido = linea[len("data:"):].strip()
            if contenido == "[DONE]":
                return
            try:
                yield json.loads(contenido)
            except json.JSONDecodeError:
                continue
    finally:
        resp.close()


def _post_json_stream_con_fallback(url: str, payload: dict, claves: list[str]) -> Iterator[dict]:
    """Misma lógica de fallback entre claves que _post_json_con_fallback,
    pero para la variante en streaming: el fallback solo puede decidirse
    al ABRIR la conexión (esos códigos de error llegan de inmediato, antes
    de que OpenRouter empiece a mandar trozos) -- un fallo a mitad del
    streaming ya no tiene sentido resolverlo cambiando de clave, se
    propaga tal cual."""
    ultimo_error: ErrorIA | None = None
    for clave in claves:
        try:
            resp = _abrir_stream(url, payload, clave)
        except ErrorIA as e:
            if e.codigo_http not in _CODIGOS_FALLBACK:
                raise
            ultimo_error = e
            continue
        yield from _lineas_sse(resp)
        return
    raise ultimo_error


def _post_json_con_fallback(url: str, payload: dict, claves: list[str]) -> dict:
    """Prueba cada clave en orden hasta que una funcione. Si todas fallan
    con un código de la lista de fallback, se propaga el error de la
    ÚLTIMA clave probada (la más informativa: ya se sabe que las
    anteriores tampoco valían)."""
    ultimo_error: ErrorIA | None = None
    for clave in claves:
        try:
            return _post_json(url, payload, clave)
        except ErrorIA as e:
            if e.codigo_http not in _CODIGOS_FALLBACK:
                raise
            ultimo_error = e
    raise ultimo_error


# --- Listado de modelos gratuitos de OpenRouter -----------------------------
# Endpoint público (sin autenticación) que devuelve TODOS los modelos
# disponibles en OpenRouter; se filtra aquí a los gratuitos (precio 0 tanto
# en prompt como en completion) para no mostrar en el selector modelos de
# pago por error. Se cachea en memoria del proceso (mismo patrón que
# _jwt_admin_cache en app/baserow.py) porque este listado cambia poco y así
# no se golpea la API de OpenRouter en cada carga de la pantalla de ajustes.
_CACHE_MODELOS_TTL_SEGUNDOS = 3600
_cache_modelos_gratuitos: list[dict] | None = None
_cache_modelos_expira_en: float = 0.0


def _es_modelo_gratuito(modelo: dict) -> bool:
    precios = modelo.get("pricing") or {}
    try:
        return float(precios.get("prompt", 1)) == 0 and float(precios.get("completion", 1)) == 0
    except (TypeError, ValueError):
        return str(modelo.get("id", "")).endswith(":free")


def listar_modelos_gratuitos(*, forzar_recarga: bool = False) -> list[dict]:
    """Devuelve [{"id": ..., "nombre": ...}] solo con los modelos gratuitos
    de OpenRouter. Si la petición falla, devuelve la caché anterior si la
    hay (aunque haya caducado) o si no, la lista de respaldo fija — nunca
    lanza, para no romper ninguna pantalla que dependa de este listado."""
    global _cache_modelos_gratuitos, _cache_modelos_expira_en
    if not forzar_recarga and _cache_modelos_gratuitos is not None and time.monotonic() < _cache_modelos_expira_en:
        return _cache_modelos_gratuitos

    req = urllib.request.Request(OPENROUTER_MODELOS_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo = json.loads(resp.read().decode("utf-8"))
        modelos = [
            {"id": m["id"], "nombre": m.get("name") or m["id"]}
            for m in cuerpo.get("data", [])
            if m.get("id") and _es_modelo_gratuito(m)
        ]
        modelos.sort(key=lambda m: m["nombre"].lower())
        _cache_modelos_gratuitos = modelos
        _cache_modelos_expira_en = time.monotonic() + _CACHE_MODELOS_TTL_SEGUNDOS
        return modelos
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, KeyError):
        return _cache_modelos_gratuitos if _cache_modelos_gratuitos is not None else list(MODELOS_GRATUITOS_RESPALDO)


def _mensajes_para_openrouter(usuario_id: int) -> list[dict]:
    idioma = db.idioma_usuario(usuario_id) or "es"
    mensajes = [{"role": "system", "content": _prompt_sistema(idioma)}]
    for fila in db.listar_mensajes_ia(usuario_id):
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


def _tool_call_id_pendiente(usuario_id: int) -> str | None:
    """Si el último mensaje `assistant` pidió herramientas y a alguna todavía
    le falta su fila `tool` de respuesta, devuelve el primer tool_call_id sin
    resolver (en el orden en que el modelo los pidió). Si no hay nada
    pendiente, devuelve None."""
    mensajes = db.listar_mensajes_ia(usuario_id)
    if not mensajes or mensajes[-1]["rol"] != "assistant" or not mensajes[-1]["tool_calls_json"]:
        return None
    tool_calls = json.loads(mensajes[-1]["tool_calls_json"])
    ids_pedidos = [tc["id"] for tc in tool_calls]
    ids_respondidos = {m["tool_call_id"] for m in mensajes if m["rol"] == "tool"}
    for tool_call_id in ids_pedidos:
        if tool_call_id not in ids_respondidos:
            return tool_call_id
    return None


def _tool_call_por_id(usuario_id: int, tool_call_id: str) -> dict | None:
    mensajes = db.listar_mensajes_ia(usuario_id)
    for fila in reversed(mensajes):
        if fila["rol"] == "assistant" and fila["tool_calls_json"]:
            for tc in json.loads(fila["tool_calls_json"]):
                if tc["id"] == tool_call_id:
                    return tc
    return None


def _ejecutar_tool_call(usuario_id: int, tool_call: dict) -> str:
    """Ejecuta una herramienta y devuelve el resultado como texto (JSON),
    listo para guardarse como contenido de un mensaje `tool`."""
    nombre = tool_call["function"]["name"]
    argumentos = json.loads(tool_call["function"]["arguments"] or "{}")
    try:
        resultado = herramientas.ejecutar(usuario_id, nombre, argumentos)
        return json.dumps(resultado, ensure_ascii=False, default=str)
    except herramientas.ErrorHerramientaIA as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _pendiente_dict(tool_call: dict) -> dict:
    return {
        "tool_call_id": tool_call["id"],
        "herramienta": tool_call["function"]["name"],
        "argumentos": json.loads(tool_call["function"]["arguments"] or "{}"),
    }


def _continuar_conversacion(usuario_id: int) -> dict:
    preferencias = db.obtener_preferencias_ia(usuario_id)
    modelo = preferencias["modelo"]
    modo_autonomo = bool(preferencias["modo_autonomo"])
    claves = obtener_api_keys(usuario_id)

    if not modelo.strip():
        raise ErrorIA("No hay ningún modelo configurado. Elige uno en Ajustes del Asistente IA.")
    if not claves:
        raise ErrorIA("No hay ninguna clave de API de OpenRouter configurada. Añádela en Ajustes del Asistente IA.")

    ids_antes = {m["id"] for m in db.listar_mensajes_ia(usuario_id)}

    for _ in range(MAX_ITERACIONES_HERRAMIENTAS):
        # Si queda un tool_call pendiente de confirmación, se para aquí sin
        # llamar a OpenRouter (se resolverá con confirmar_pendiente()).
        tool_call_id_pendiente = _tool_call_id_pendiente(usuario_id)
        if tool_call_id_pendiente is not None:
            tool_call = _tool_call_por_id(usuario_id, tool_call_id_pendiente)
            return {
                "mensajes_nuevos": _mensajes_nuevos_desde(usuario_id, ids_antes),
                "pendiente": _pendiente_dict(tool_call),
            }

        respuesta = _post_json_con_fallback(
            OPENROUTER_URL,
            {"model": modelo, "messages": _mensajes_para_openrouter(usuario_id), "tools": herramientas.HERRAMIENTAS},
            claves,
        )
        try:
            mensaje = respuesta["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise ErrorIA(f"Respuesta inesperada de OpenRouter: {respuesta}") from e

        tool_calls = mensaje.get("tool_calls") or []
        if not tool_calls:
            db.agregar_mensaje_ia(usuario_id, "assistant", contenido=mensaje.get("content") or "")
            return {"mensajes_nuevos": _mensajes_nuevos_desde(usuario_id, ids_antes), "pendiente": None}

        db.agregar_mensaje_ia(
            usuario_id, "assistant", contenido=mensaje.get("content"),
            tool_calls_json=json.dumps(tool_calls, ensure_ascii=False),
        )

        for tool_call in tool_calls:
            nombre = tool_call["function"]["name"]
            if herramientas.necesita_confirmacion(nombre, modo_autonomo):
                return {
                    "mensajes_nuevos": _mensajes_nuevos_desde(usuario_id, ids_antes),
                    "pendiente": _pendiente_dict(tool_call),
                }
            contenido = _ejecutar_tool_call(usuario_id, tool_call)
            db.agregar_mensaje_ia(
                usuario_id, "tool", contenido=contenido, tool_call_id=tool_call["id"], nombre_herramienta=nombre,
            )

    raise ErrorIA(
        "El asistente ha encadenado demasiadas llamadas a herramientas sin dar una "
        "respuesta final. Inténtalo de nuevo o reformula la petición."
    )


def _mensajes_nuevos_desde(usuario_id: int, ids_antes: set[int]) -> list[dict]:
    return [dict(m) for m in db.listar_mensajes_ia(usuario_id) if m["id"] not in ids_antes]


def procesar_turno(usuario_id: int, texto_usuario: str) -> dict:
    if not texto_usuario.strip():
        raise ErrorIA("Escribe un mensaje.")
    if _tool_call_id_pendiente(usuario_id) is not None:
        raise ErrorIA(
            "Hay una acción esperando confirmación. Acéptala o recházala antes de seguir la conversación."
        )
    db.agregar_mensaje_ia(usuario_id, "user", contenido=texto_usuario.strip())
    return _continuar_conversacion(usuario_id)


def pendiente_actual(usuario_id: int) -> dict | None:
    """Devuelve la acción esperando confirmación ahora mismo, si la hay."""
    tool_call_id = _tool_call_id_pendiente(usuario_id)
    if tool_call_id is None:
        return None
    return _pendiente_dict(_tool_call_por_id(usuario_id, tool_call_id))


def confirmar_pendiente(usuario_id: int, aceptar: bool) -> dict:
    tool_call_id = _tool_call_id_pendiente(usuario_id)
    if tool_call_id is None:
        raise ErrorIA("No hay ninguna acción esperando confirmación.")
    tool_call = _tool_call_por_id(usuario_id, tool_call_id)
    nombre = tool_call["function"]["name"]

    if aceptar:
        contenido = _ejecutar_tool_call(usuario_id, tool_call)
    else:
        contenido = json.dumps(
            {"rechazado": True, "motivo": "El usuario ha rechazado esta acción."}, ensure_ascii=False,
        )
    db.agregar_mensaje_ia(usuario_id, "tool", contenido=contenido, tool_call_id=tool_call_id, nombre_herramienta=nombre)
    return _continuar_conversacion(usuario_id)


# --- Variantes en streaming de todo lo anterior (asistente de voz) ---------
# Mismo comportamiento pieza a pieza que procesar_turno/confirmar_pendiente/
# _continuar_conversacion de arriba (reutilizan exactamente las mismas
# funciones de herramientas/confirmación/persistencia) -- lo único que
# cambia es CÓMO se habla con OpenRouter (streaming en vez de bloque
# completo) y que en vez de devolver un dict al final, se van entregando
# eventos según ocurren: {"tipo": "delta", "texto": ...} por cada trozo de
# texto del asistente (para pintar/leer en voz alta incremental),
# {"tipo": "mensaje", "mensaje": {...}} por cada fila nueva ya persistida
# (mismo shape que "mensajes_nuevos" de la versión no-streaming),
# {"tipo": "pendiente", "pendiente": {...}} si hace falta confirmación, y
# {"tipo": "error"|"fin"} al terminar.


def _continuar_conversacion_stream(usuario_id: int) -> Iterator[dict]:
    preferencias = db.obtener_preferencias_ia(usuario_id)
    modelo = preferencias["modelo"]
    modo_autonomo = bool(preferencias["modo_autonomo"])
    claves = obtener_api_keys(usuario_id)

    if not modelo.strip():
        raise ErrorIA("No hay ningún modelo configurado. Elige uno en Ajustes del Asistente IA.")
    if not claves:
        raise ErrorIA("No hay ninguna clave de API de OpenRouter configurada. Añádela en Ajustes del Asistente IA.")

    for _ in range(MAX_ITERACIONES_HERRAMIENTAS):
        tool_call_id_pendiente = _tool_call_id_pendiente(usuario_id)
        if tool_call_id_pendiente is not None:
            tool_call = _tool_call_por_id(usuario_id, tool_call_id_pendiente)
            yield {"tipo": "pendiente", "pendiente": _pendiente_dict(tool_call)}
            return

        ids_antes = {m["id"] for m in db.listar_mensajes_ia(usuario_id)}
        payload = {"model": modelo, "messages": _mensajes_para_openrouter(usuario_id), "tools": herramientas.HERRAMIENTAS}
        contenido_acumulado = ""
        # Los tool_calls llegan troceados por índice a lo largo de varios
        # chunks (id/nombre/argumentos incompletos hasta que termina el
        # stream) -- se van concatenando aquí antes de poder ejecutarlos.
        tool_calls_acumulados: dict[int, dict] = {}

        for chunk in _post_json_stream_con_fallback(OPENROUTER_URL, payload, claves):
            try:
                delta = chunk["choices"][0].get("delta", {})
            except (KeyError, IndexError, TypeError):
                continue
            texto = delta.get("content")
            if texto:
                contenido_acumulado += texto
                yield {"tipo": "delta", "texto": texto}
            for tc_delta in delta.get("tool_calls") or []:
                idx = tc_delta.get("index", 0)
                actual = tool_calls_acumulados.setdefault(
                    idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if tc_delta.get("id"):
                    actual["id"] = tc_delta["id"]
                fn_delta = tc_delta.get("function") or {}
                if fn_delta.get("name"):
                    actual["function"]["name"] += fn_delta["name"]
                if fn_delta.get("arguments"):
                    actual["function"]["arguments"] += fn_delta["arguments"]

        tool_calls = [tool_calls_acumulados[i] for i in sorted(tool_calls_acumulados)]

        if not tool_calls:
            db.agregar_mensaje_ia(usuario_id, "assistant", contenido=contenido_acumulado)
            for mensaje in _mensajes_nuevos_desde(usuario_id, ids_antes):
                yield {"tipo": "mensaje", "mensaje": mensaje}
            return

        db.agregar_mensaje_ia(
            usuario_id, "assistant", contenido=contenido_acumulado or None,
            tool_calls_json=json.dumps(tool_calls, ensure_ascii=False),
        )
        for mensaje in _mensajes_nuevos_desde(usuario_id, ids_antes):
            yield {"tipo": "mensaje", "mensaje": mensaje}

        for tool_call in tool_calls:
            nombre = tool_call["function"]["name"]
            if herramientas.necesita_confirmacion(nombre, modo_autonomo):
                yield {"tipo": "pendiente", "pendiente": _pendiente_dict(tool_call)}
                return
            contenido = _ejecutar_tool_call(usuario_id, tool_call)
            ids_antes_tool = {m["id"] for m in db.listar_mensajes_ia(usuario_id)}
            db.agregar_mensaje_ia(
                usuario_id, "tool", contenido=contenido, tool_call_id=tool_call["id"], nombre_herramienta=nombre,
            )
            for mensaje in _mensajes_nuevos_desde(usuario_id, ids_antes_tool):
                yield {"tipo": "mensaje", "mensaje": mensaje}

    raise ErrorIA(
        "El asistente ha encadenado demasiadas llamadas a herramientas sin dar una "
        "respuesta final. Inténtalo de nuevo o reformula la petición."
    )


def procesar_turno_stream(usuario_id: int, texto_usuario: str) -> Iterator[dict]:
    try:
        if not texto_usuario.strip():
            raise ErrorIA("Escribe un mensaje.")
        if _tool_call_id_pendiente(usuario_id) is not None:
            raise ErrorIA(
                "Hay una acción esperando confirmación. Acéptala o recházala antes de seguir la conversación."
            )
        db.agregar_mensaje_ia(usuario_id, "user", contenido=texto_usuario.strip())
        yield from _continuar_conversacion_stream(usuario_id)
        yield {"tipo": "fin"}
    except ErrorIA as e:
        yield {"tipo": "error", "mensaje": str(e)}


def confirmar_pendiente_stream(usuario_id: int, aceptar: bool) -> Iterator[dict]:
    try:
        tool_call_id = _tool_call_id_pendiente(usuario_id)
        if tool_call_id is None:
            raise ErrorIA("No hay ninguna acción esperando confirmación.")
        tool_call = _tool_call_por_id(usuario_id, tool_call_id)
        nombre = tool_call["function"]["name"]

        if aceptar:
            contenido = _ejecutar_tool_call(usuario_id, tool_call)
        else:
            contenido = json.dumps(
                {"rechazado": True, "motivo": "El usuario ha rechazado esta acción."}, ensure_ascii=False,
            )
        db.agregar_mensaje_ia(usuario_id, "tool", contenido=contenido, tool_call_id=tool_call_id, nombre_herramienta=nombre)
        yield from _continuar_conversacion_stream(usuario_id)
        yield {"tipo": "fin"}
    except ErrorIA as e:
        yield {"tipo": "error", "mensaje": str(e)}
