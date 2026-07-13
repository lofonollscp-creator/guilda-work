"""Integración con IA local (Ollama / LM Studio) — Fase 2.

No añade dependencias externas: usa urllib de la librería estándar.
Si el servicio local no está disponible, falla de forma clara y rápida
(timeout corto) sin bloquear el resto de la aplicación.
"""
import json
import urllib.error
import urllib.request

TIMEOUT_SEGUNDOS = 20

OLLAMA_URL = "http://localhost:11434/api/chat"
LMSTUDIO_URL = "http://localhost:1234/v1/chat/completions"

PROMPT_SISTEMA_PREGUNTAS = (
    "Eres un asistente que responde preguntas sobre el registro de actividad diaria "
    "de la persona usuaria (notas, eventos instantáneos y tareas con duración, "
    "agrupados por categoría). A continuación tienes esos datos en JSON. Responde "
    "solo con lo que se pueda deducir de ellos; si falta información para responder "
    "con seguridad, dilo claramente en vez de inventar. Sé breve y directo, y "
    "responde siempre en español.\n\nDatos (JSON):\n{datos}"
)

# Cuántos mensajes previos (usuario+asistente) se reenvían como contexto de
# la conversación. Suficiente para preguntas de seguimiento sin dejar crecer
# el prompt sin límite.
MAX_MENSAJES_HISTORIAL = 20


class ErrorIALocal(Exception):
    """Error legible para mostrar en la interfaz cuando la IA local falla."""


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ErrorIALocal(
            f"No se ha podido conectar con {url}. "
            "¿Está encendido el servicio local (Ollama o LM Studio)? "
            f"Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorIALocal(f"Tiempo de espera agotado al contactar con {url}.") from e
    except (json.JSONDecodeError, ValueError) as e:
        raise ErrorIALocal(f"Respuesta inválida desde {url}: {e}") from e


def _chat(proveedor: str, modelo: str, mensajes: list[dict]) -> str:
    """Envía una lista de mensajes (formato OpenAI/Ollama: role+content) y
    devuelve el texto de la respuesta del asistente."""
    if not modelo.strip():
        raise ErrorIALocal("Indica el nombre del modelo cargado en tu IA local (ej. 'llama3.1').")

    payload = {"model": modelo.strip(), "messages": mensajes, "stream": False}

    if proveedor == "lmstudio":
        respuesta = _post_json(LMSTUDIO_URL, payload)
        try:
            return respuesta["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as e:
            raise ErrorIALocal(f"Respuesta inesperada de LM Studio: {respuesta}") from e

    # Ollama por defecto
    respuesta = _post_json(OLLAMA_URL, payload)
    if "error" in respuesta:
        raise ErrorIALocal(f"Ollama devolvió un error: {respuesta['error']}")
    try:
        return respuesta["message"]["content"].strip()
    except (KeyError, TypeError) as e:
        raise ErrorIALocal(f"Respuesta inesperada de Ollama: {respuesta}") from e


def _datos_como_texto(datos_export: dict) -> str:
    return json.dumps(datos_export, ensure_ascii=False, indent=2)


def generar_informe(datos_export: dict, instruccion: str, proveedor: str, modelo: str) -> str:
    """Envía los datos exportados a un modelo local en una sola pasada y
    devuelve el texto generado (informe/resumen, sin conversación)."""
    prompt = (
        f"{instruccion}\n\n"
        "Estos son mis datos de actividad en formato JSON "
        "(cada registro es una nota, un evento instantáneo o una tarea con duración, "
        "agrupados por categoría):\n\n"
        f"{_datos_como_texto(datos_export)}"
    )
    return _chat(proveedor, modelo, [{"role": "user", "content": prompt}])


def preguntar(
    datos_export: dict,
    historial_mensajes: list[dict],
    pregunta: str,
    proveedor: str,
    modelo: str,
) -> str:
    """Modo "pregunta libre": conversación con memoria sobre los datos.

    `historial_mensajes` es la conversación previa visible en el chat
    ([{"role": "user"|"assistant", "content": "..."}]); los datos no viajan
    ahí, se anteponen como mensaje de sistema en cada llamada para que el
    modelo siempre tenga el contexto completo aunque no tenga memoria propia.
    """
    if not pregunta.strip():
        raise ErrorIALocal("Escribe una pregunta.")

    sistema = {"role": "system", "content": PROMPT_SISTEMA_PREGUNTAS.format(datos=_datos_como_texto(datos_export))}
    mensajes = [sistema, *historial_mensajes[-MAX_MENSAJES_HISTORIAL:], {"role": "user", "content": pregunta.strip()}]
    return _chat(proveedor, modelo, mensajes)
