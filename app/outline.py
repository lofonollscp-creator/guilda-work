"""Cliente de la API de Outline (Fase MCP: buscar/leer/crear documentos de
la wiki desde un asistente, ver mcp_server.py).

La API de Outline es "RPC sobre HTTP": todos los endpoints son POST con
un cuerpo JSON, sin verbos GET/PUT/DELETE (a diferencia del resto de
integraciones de este proyecto) — confirmado en su documentación
oficial.

Auth: OUTLINE_API_TOKEN (cabecera `Authorization: Bearer ...`), se genera
una vez a mano en Outline: Ajustes → API Keys. Opcional a propósito,
mismo criterio que el resto de app/*.py — sin él, las tools de solo
lectura devuelven listas vacías.

Mismo criterio que el resto de app/*.py de integraciones: solo `urllib`
de la librería estándar.
"""
import json
import os
import urllib.error
import urllib.request

OUTLINE_URL = os.environ.get("HERRAMIENTA_OUTLINE_URL", "http://127.0.0.1:3001")
OUTLINE_API_TOKEN = os.environ.get("OUTLINE_API_TOKEN")
TIMEOUT_SEGUNDOS = 10


class ErrorOutline(Exception):
    """Error legible para mostrar cuando Outline falla."""


def _peticion(endpoint: str, cuerpo: dict | None = None):
    datos = json.dumps(cuerpo or {}).encode("utf-8")
    cabeceras = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OUTLINE_API_TOKEN or ''}",
    }
    req = urllib.request.Request(f"{OUTLINE_URL}/api/{endpoint}", data=datos, headers=cabeceras, method="POST")
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
        raise ErrorOutline(
            f"No se ha podido conectar con Outline ({OUTLINE_URL}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorOutline(f"Tiempo de espera agotado al contactar con Outline ({OUTLINE_URL}).")


def listar_colecciones() -> list[dict]:
    """Lista las colecciones (carpetas de nivel superior) existentes —
    para saber a qué `coleccion_id` apuntar al crear un documento. []
    si OUTLINE_API_TOKEN no está configurado."""
    if not OUTLINE_API_TOKEN:
        return []
    estado, cuerpo = _peticion("collections.list", {"limit": 100})
    if estado != 200:
        mensaje = cuerpo.get("error") or cuerpo
        raise ErrorOutline(f"No se han podido listar las colecciones de Outline: {mensaje}")
    return cuerpo.get("data", [])


def buscar_documentos(texto: str, limite: int = 20) -> list[dict]:
    """Búsqueda de texto completo en todos los documentos. [] si
    OUTLINE_API_TOKEN no está configurado."""
    if not OUTLINE_API_TOKEN:
        return []
    estado, cuerpo = _peticion("documents.search", {"query": texto, "limit": limite})
    if estado != 200:
        mensaje = cuerpo.get("error") or cuerpo
        raise ErrorOutline(f"No se ha podido buscar '{texto}' en Outline: {mensaje}")
    return [r["document"] for r in cuerpo.get("data", [])]


def leer_documento(documento_id: str) -> dict:
    """Devuelve un documento completo (título, texto en Markdown...)."""
    if not OUTLINE_API_TOKEN:
        raise ErrorOutline("OUTLINE_API_TOKEN no está configurado.")
    estado, cuerpo = _peticion("documents.info", {"id": documento_id})
    if estado != 200:
        mensaje = cuerpo.get("error") or cuerpo
        raise ErrorOutline(f"No se ha podido leer el documento {documento_id} de Outline: {mensaje}")
    return cuerpo.get("data", {})


def crear_documento(coleccion_id: str, titulo: str, texto: str = "", publicar: bool = True) -> dict:
    """Crea un documento nuevo en una colección existente (ver
    listar_colecciones)."""
    if not OUTLINE_API_TOKEN:
        raise ErrorOutline("OUTLINE_API_TOKEN no está configurado.")
    estado, cuerpo = _peticion("documents.create", {
        "collectionId": coleccion_id, "title": titulo, "text": texto, "publish": publicar,
    })
    if estado != 200:
        mensaje = cuerpo.get("error") or cuerpo
        raise ErrorOutline(f"No se ha podido crear el documento '{titulo}' en Outline: {mensaje}")
    return cuerpo.get("data", {})
