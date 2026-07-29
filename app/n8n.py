"""Cliente de la API pública de n8n (Fase MCP: listar/ejecutar flujos de
automatización desde un asistente, ver mcp_server.py).

Auth: N8N_API_KEY (cabecera X-N8N-API-KEY), se genera una vez a mano en
n8n: Ajustes → API. Opcional a propósito, mismo criterio que
METABASE_API_KEY/ESPOCRM_API_KEY — sin ella, las tools de solo lectura
devuelven listas vacías y `ejecutar_flujo` falla con un mensaje claro.

Solo ejecuta flujos YA CREADOS desde la propia UI de n8n (por id) — no
crea ni modifica flujos por prompt, evita el riesgo de que un prompt
reprograme una automatización existente.

Mismo criterio que el resto de app/*.py de integraciones: solo `urllib`
de la librería estándar.
"""
import json
import os
import urllib.error
import urllib.request

N8N_URL = os.environ.get("HERRAMIENTA_N8N_URL", "http://127.0.0.1:5678")
N8N_API_KEY = os.environ.get("N8N_API_KEY")
TIMEOUT_SEGUNDOS = 15


class ErrorN8n(Exception):
    """Error legible para mostrar cuando n8n falla."""


def _peticion(url: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json", "X-N8N-API-KEY": N8N_API_KEY or ""}
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
        raise ErrorN8n(
            f"No se ha podido conectar con n8n ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorN8n(f"Tiempo de espera agotado al contactar con n8n ({url}).")


def listar_flujos(limite: int = 20) -> list[dict]:
    """Lista los flujos de automatización existentes. [] si N8N_API_KEY
    no está configurada."""
    if not N8N_API_KEY:
        return []
    estado, cuerpo = _peticion(f"{N8N_URL}/api/v1/workflows?limit={limite}")
    if estado != 200:
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorN8n(f"No se han podido listar los flujos de n8n: {mensaje}")
    return cuerpo.get("data", [])


def ejecutar_flujo(flujo_id: str) -> dict:
    """Ejecuta un flujo existente por su id (el mismo flujo debe estar
    activo y aceptar ejecución manual/por API)."""
    if not N8N_API_KEY:
        raise ErrorN8n("N8N_API_KEY no está configurada.")
    estado, cuerpo = _peticion(f"{N8N_URL}/api/v1/workflows/{flujo_id}/execute", metodo="POST")
    if estado not in (200, 201):
        mensaje = cuerpo.get("message") or cuerpo.get("error") or cuerpo
        raise ErrorN8n(f"No se ha podido ejecutar el flujo {flujo_id} de n8n: {mensaje}")
    return cuerpo
