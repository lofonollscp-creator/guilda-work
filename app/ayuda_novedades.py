"""Aviso de «Novedades» del centro de ayuda dentro de la aplicación.

El centro de ayuda publica un feed Atom por idioma (`<ayuda>/feed.xml`, `<ayuda>/<idioma>/feed.xml`). La entrada más reciente de la colección Novedades (URL con `/novedades/`) se enseña en el menú
de ajustes con un punto hasta que la persona la abre (lo recuerda su navegador: ver static/ayuda_novedades.js).

Nunca bloquea una pantalla ni la rompe: la lectura del feed se hace en un hilo aparte, con plazo corto y como mucho una vez por hora y idioma; si falla, simplemente no hay aviso."""
from __future__ import annotations

import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

from . import ayuda

REFRESCO_SEGUNDOS = 3600
REINTENTO_SEGUNDOS = 300          # tras un fallo no se insiste antes
TIMEOUT_SEGUNDOS = 4
MAX_BYTES = 512 * 1024
ATOM = "{http://www.w3.org/2005/Atom}"

_cache: dict[str, tuple[float, dict | None]] = {}      # idioma -> (cuándo se pidió, novedad)
_en_curso: set[str] = set()
_cerrojo = threading.Lock()


def _url_feed(idioma: str) -> str:
    return f"{ayuda.base()}/{idioma}/feed.xml" if idioma in ayuda.IDIOMAS else f"{ayuda.base()}/feed.xml"


def leer_novedad(xml: bytes) -> dict | None:
    """La entrada más reciente de Novedades de un feed Atom: `{id, titulo, url}`, o None."""
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for e in raiz.findall(ATOM + "entry"):
        enlace = e.find(ATOM + "link")
        url = enlace.get("href", "") if enlace is not None else ""
        titulo = (e.findtext(ATOM + "title") or "").strip()
        if "/novedades/" in url and url.startswith(("https://", "http://")) and titulo:
            return {"id": url, "titulo": titulo[:120], "url": url}
    return None


def _descargar(idioma: str) -> dict | None:
    req = urllib.request.Request(_url_feed(idioma), headers={"Accept": "application/atom+xml", "User-Agent": "guilda-work"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as r:      # noqa: S310 -- la URL sale de GUILDA_AYUDA_URL, no de quien usa la app
        return leer_novedad(r.read(MAX_BYTES))


def _refrescar(idioma: str) -> None:
    try:
        try:
            novedad = _descargar(idioma)
        except Exception:  # noqa: BLE001 -- la ayuda caída no debe notarse
            anterior = _cache.get(idioma)
            novedad = anterior[1] if anterior else None
            _cache[idioma] = (time.time() - REFRESCO_SEGUNDOS + REINTENTO_SEGUNDOS, novedad)
            return
        _cache[idioma] = (time.time(), novedad)
    finally:
        with _cerrojo:
            _en_curso.discard(idioma)


def novedad(idioma: str) -> dict | None:
    """La última novedad conocida para ese idioma (sin esperar a la red). Lanza la actualización en segundo plano si toca."""
    idioma = idioma if idioma in ayuda.IDIOMAS else "es"
    cuando, valor = _cache.get(idioma, (0.0, None))
    if time.time() - cuando >= REFRESCO_SEGUNDOS:
        with _cerrojo:
            if idioma not in _en_curso:
                _en_curso.add(idioma)
                threading.Thread(target=_refrescar, args=(idioma,), daemon=True).start()
    return valor
