"""Cliente de Uptime Kuma (Fase MCP: consultar el estado de los monitores
desde un asistente, ver mcp_server.py).

**Solo lectura, a propósito** — investigado y confirmado que Uptime Kuma
NO tiene una API REST de escritura: su gestión de monitores (crear/
editar/pausar) es exclusivamente vía Socket.IO, el mismo protocolo que ya
dio problemas reales de automatización (ver la sesión de despliegue de
Uptime Kuma/OpenVPN) — no se intenta replicar aquí. Lo único disponible
por HTTP normal es el endpoint `/metrics` (formato Prometheus), pensado
para integrarlo con Grafana/Prometheus, pero perfectamente legible para
un asistente.

Auth: UPTIME_KUMA_API_KEY (HTTP Basic Auth, usuario vacío, la API Key
como contraseña — confirmado en la documentación oficial). Se genera una
vez a mano en Uptime Kuma: Configuración → Claves API. Opcional a
propósito, mismo criterio que el resto de app/*.py.

Mismo criterio que el resto de app/*.py de integraciones: solo `urllib`
de la librería estándar (aquí ni siquiera hace falta `json`, el formato
es texto plano de Prometheus).
"""
import base64
import os
import re
import urllib.error
import urllib.request

UPTIME_KUMA_URL = os.environ.get("HERRAMIENTA_UPTIME_KUMA_URL", "http://127.0.0.1:8014")
UPTIME_KUMA_API_KEY = os.environ.get("UPTIME_KUMA_API_KEY")
TIMEOUT_SEGUNDOS = 10

# 0 = DOWN, 1 = UP, 2 = PENDING, 3 = MAINTENANCE — códigos fijos del
# propio exportador de Uptime Kuma.
_ESTADOS = {"0": "caido", "1": "activo", "2": "pendiente", "3": "mantenimiento"}

_LINEA_METRICA = re.compile(r'^(?P<metrica>\w+)\{(?P<etiquetas>[^}]*)\}\s+(?P<valor>[\d.eE+-]+)$')
_ETIQUETA = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


class ErrorUptimeKuma(Exception):
    """Error legible para mostrar cuando Uptime Kuma falla."""


def _obtener_metrics() -> str:
    cabeceras = {"Authorization": f"Basic {base64.b64encode(f':{UPTIME_KUMA_API_KEY}'.encode()).decode()}"}
    req = urllib.request.Request(f"{UPTIME_KUMA_URL}/metrics", headers=cabeceras, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ErrorUptimeKuma(f"Uptime Kuma ha rechazado la petición a /metrics (HTTP {e.code}).") from e
    except urllib.error.URLError as e:
        raise ErrorUptimeKuma(
            f"No se ha podido conectar con Uptime Kuma ({UPTIME_KUMA_URL}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorUptimeKuma(f"Tiempo de espera agotado al contactar con Uptime Kuma ({UPTIME_KUMA_URL}).")


def listar_monitores() -> list[dict]:
    """Estado actual de cada monitor (activo/caído/pendiente/mantenimiento),
    leído del endpoint /metrics (Prometheus). [] si UPTIME_KUMA_API_KEY no
    está configurada."""
    if not UPTIME_KUMA_API_KEY:
        return []
    texto = _obtener_metrics()
    monitores: dict[str, dict] = {}
    for linea in texto.splitlines():
        coincidencia = _LINEA_METRICA.match(linea.strip())
        if not coincidencia or coincidencia.group("metrica") not in ("monitor_status", "monitor_response_time"):
            continue
        etiquetas = dict(_ETIQUETA.findall(coincidencia.group("etiquetas")))
        nombre = etiquetas.get("monitor_name")
        if not nombre:
            continue
        registro = monitores.setdefault(nombre, {"nombre": nombre})
        if coincidencia.group("metrica") == "monitor_status":
            registro["estado"] = _ESTADOS.get(coincidencia.group("valor").split(".")[0], "desconocido")
        else:
            registro["tiempo_respuesta_ms"] = float(coincidencia.group("valor"))
    return list(monitores.values())
