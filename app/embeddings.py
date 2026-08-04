"""Embeddings locales vía Ollama, para la búsqueda semántica de
app/busqueda.py — mismo estilo `urllib` que app/ai_local.py, endpoint
distinto (`/api/embed`, no `/api/chat`).

## Verificado en vivo antes de escribir este módulo

Contra un Ollama real con el modelo `nomic-embed-text` descargado:
`POST /api/embed` con `{"model": "nomic-embed-text", "input": "texto"}`
devuelve `{"embeddings": [[...]], ...}` — una LISTA DE LISTAS incluso
para una sola entrada (formato por lotes), dimensión real 768. Este
módulo asume ese formato porque se confirmó así, no por documentación.

Degradación con gracia: si Ollama no está disponible (no está
instalado, o el modelo no está descargado), `generar_embedding()`
devuelve `None` en vez de lanzar — la búsqueda semántica es una mejora
opcional sobre la búsqueda por palabra clave que ya existe, nunca debe
impedir indexar o buscar (mismo criterio que el resto de integraciones
opcionales del proyecto)."""
import json
import os
import urllib.error
import urllib.request

OLLAMA_EMBED_URL = os.environ.get("OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
TIMEOUT_SEGUNDOS = 15


def generar_embedding(texto: str) -> list[float] | None:
    """Vector de embedding de `texto`, o None si Ollama no está
    disponible o el modelo no está descargado — nunca lanza."""
    if not texto.strip():
        return None
    payload = {"model": OLLAMA_EMBED_MODEL, "input": texto}
    req = urllib.request.Request(
        OLLAMA_EMBED_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            datos = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    embeddings = datos.get("embeddings")
    if not embeddings or not isinstance(embeddings, list):
        return None
    return embeddings[0]
