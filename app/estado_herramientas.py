"""Qué herramientas conectadas responden DE VERDAD (Fase 1 de docs/hoja-de-ruta.md).

El catálogo (`app/herramientas.py`) anuncia más herramientas de las que el servidor tiene en marcha, y varias herramientas del asistente de IA y del MCP (CRM, citas, newsletter, hojas, analítica…)
hablan con esos servicios. Sin esto, una persona veía un enlace muerto y el asistente intentaba usar un servicio caído. Reglas:

- **Una herramienta está disponible** si no está marcada `disponible: False` en el catálogo (decisión de configuración: «no se despliega») **y** responde ahora. Responder = su puerto contesta por HTTP
  con cualquier código (un 401 o un 302 también es «viva»); un rechazo de conexión o un tiempo agotado es «no responde».
- **Se comprueba poco y barato**: una petición corta (1,5 s) por herramienta, en paralelo, con el resultado guardado 45 segundos. Nunca se sigue una redirección (no salimos del servicio que se comprueba).
- **Quien usa la plataforma solo ve lo que funciona** (web y app móvil); la dirección ve además cuáles no responden. El asistente de IA no se ofrece las herramientas de un servicio caído, y el MCP y el
  asistente responden con un mensaje claro («el servicio X no responde ahora») en vez de un error técnico.
- **Un servicio no registrado en el catálogo** (o una herramienta que no depende de ninguno) se considera disponible: esto solo recorta, nunca inventa dependencias."""
from __future__ import annotations

import concurrent.futures
import threading
import time
import urllib.error
import urllib.request

from . import herramientas

TTL_SEGUNDOS = 45
ESPERA_SEGUNDOS = 1.5

# Herramienta del asistente de IA / MCP -> id del catálogo del que depende. Por prefijo del nombre y, para los nombres sueltos, por nombre exacto.
PREFIJOS_DE_SERVICIO: dict[str, str] = {
    "crm_": "crm", "citas_": "citas", "newsletter_": "newsletter", "analitica_": "metabase", "hojas_": "hojas", "drive_": "drive", "firmas_": "firmas", "documentos_": "documentos",
    "documentacion_": "outline", "chat_": "chat", "soporte_": "chatwoot", "proyectos_": "openproject", "almacenamiento_": "minio", "automatizaciones_": "n8n",
    "correo_stalwart_": "correo-stalwart", "monitorizacion_": "uptime-kuma", "videollamadas_": "videollamadas",
}
SERVICIO_POR_NOMBRE: dict[str, str] = {
    "enviar_archivo_drive_al_chat": "drive", "listar_tablas_hojas": "hojas", "listar_filas_hoja": "hojas",
    "listar_documentos_firma": "firmas", "crear_documento_firma": "firmas", "enviar_documento_a_firma": "firmas", "enviar_documento_firmado_al_chat": "firmas",
}

# Si es False se ignora la marca `disponible: False` del catálogo (solo lo hacen los tests, que simulan servicios que en el servidor real no se despliegan).
CONSIDERAR_MARCA_ESTATICA = True

_lock = threading.Lock()
_cache: dict = {"hasta": 0.0, "estados": {}}


def _sondear(url: str) -> bool:
    """¿Contesta algo ese puerto? (cualquier respuesta HTTP, incluida una de error, cuenta)."""
    class _SinRedireccion(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    abridor = urllib.request.build_opener(_SinRedireccion)
    try:
        abridor.open(urllib.request.Request(url, method="GET", headers={"User-Agent": "GuildaWork-salud/1"}), timeout=ESPERA_SEGUNDOS).close()
        return True
    except urllib.error.HTTPError:
        return True                                   # contestó (401, 403, 404, 302…): el servicio está vivo
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _catalogo() -> dict[str, dict]:
    return {h["id"]: h for h in herramientas.HERRAMIENTAS}


def estados(forzar: bool = False) -> dict[str, bool]:
    """{id de herramienta: ¿responde?}. Las marcadas `disponible: False` ni se comprueban (valen False)."""
    with _lock:
        if not forzar and time.monotonic() < _cache["hasta"]:
            return dict(_cache["estados"])
    catalogo = _catalogo()
    a_comprobar = {i: h["url"] for i, h in catalogo.items() if (h.get("disponible") is not False or not CONSIDERAR_MARCA_ESTATICA) and h.get("url")}
    resultado = {i: False for i in catalogo}
    if a_comprobar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(a_comprobar))) as pool:
            futuros = {pool.submit(_sondear, url): i for i, url in a_comprobar.items()}
            try:
                for f in concurrent.futures.as_completed(futuros, timeout=ESPERA_SEGUNDOS * 4 + 1):
                    try:
                        resultado[futuros[f]] = bool(f.result())
                    except Exception:  # noqa: BLE001
                        resultado[futuros[f]] = False
            except concurrent.futures.TimeoutError:
                pass                                    # lo que no contestó a tiempo se queda en «no responde»
    with _lock:
        _cache.update({"hasta": time.monotonic() + TTL_SEGUNDOS, "estados": dict(resultado)})
    _latido(catalogo, resultado)
    return resultado


def reiniciar_cache() -> None:
    with _lock:
        _cache.update({"hasta": 0.0, "estados": {}})


def _latido(catalogo: dict, resultado: dict) -> None:
    """Anota en el panel de salud cuáles de las herramientas que SE DEBERÍAN poder usar no responden. Nunca rompe a quien pregunta."""
    try:
        from . import salud
        caidas = sorted(catalogo[i]["nombre"] for i, vivo in resultado.items() if not vivo and catalogo[i].get("disponible") is not False)
        if caidas:
            salud.registrar_error("herramientas_conectadas", 3600, "No responden: " + ", ".join(caidas))
        else:
            salud.registrar_ok("herramientas_conectadas", 3600, "Todas responden", minimo_segundos=300)
    except Exception:  # noqa: BLE001
        pass


def disponible(herramienta_id: str) -> bool:
    """¿Se puede usar ahora? Id desconocido = sí (nunca se inventa una dependencia)."""
    if herramienta_id not in _catalogo():
        return True
    return bool(estados().get(herramienta_id))


def servicio_de(nombre_herramienta: str) -> str | None:
    """El id del catálogo del que depende una herramienta del asistente/MCP, o None si no depende de ninguno."""
    if nombre_herramienta in SERVICIO_POR_NOMBRE:
        return SERVICIO_POR_NOMBRE[nombre_herramienta]
    return next((s for p, s in PREFIJOS_DE_SERVICIO.items() if nombre_herramienta.startswith(p)), None)


def herramienta_usable(nombre_herramienta: str) -> bool:
    servicio = servicio_de(nombre_herramienta)
    return servicio is None or disponible(servicio)


def mensaje_no_disponible(nombre_herramienta: str) -> str:
    servicio = servicio_de(nombre_herramienta)
    nombre = _catalogo().get(servicio, {}).get("nombre", servicio)
    return f"El servicio «{nombre}» no está disponible ahora mismo en este servidor, así que esta herramienta no se puede usar. Avisa a la dirección si lo necesitas."


def exigir_servicio(nombre_herramienta: str) -> None:
    """Lanza ValueError con un mensaje claro si el servicio del que depende la herramienta no responde."""
    if not herramienta_usable(nombre_herramienta):
        raise ValueError(mensaje_no_disponible(nombre_herramienta))
