"""Recogida anónima de votos y búsquedas sin resultado del centro de ayuda público (ver app/ayuda_metricas.py).

Lo llama el navegador desde `https://help.guildawork.com` con `fetch(..., {mode: "no-cors", credentials: "omit"})` y cuerpo `text/plain` con JSON: es una «petición simple», no hace falta CORS y no se envía ninguna cookie.
No se lee la respuesta. Sin sesión, sin guardar IP; la IP solo la ve el limitador de ritmo."""
from __future__ import annotations

import json

from flask import Blueprint, make_response, request

from . import ayuda_metricas
from .auth import limiter

ayuda_metricas_bp = Blueprint("ayuda_metricas", __name__, url_prefix="/ayuda-metricas")
ORIGEN_AYUDA = "https://help.guildawork.com"


def _datos() -> dict | None:
    """Cuerpo JSON (aunque llegue como text/plain); None si el origen no es el de la ayuda o el cuerpo no es válido."""
    origen = request.headers.get("Origin")
    if origen is not None and origen != ORIGEN_AYUDA:
        return None
    if request.content_length is not None and request.content_length > 2048:
        return None
    try:
        datos = json.loads(request.get_data(as_text=True) or "null")
    except ValueError:
        return None
    return datos if isinstance(datos, dict) else None


@ayuda_metricas_bp.route("/valoracion", methods=["POST"])
@limiter.limit("40/hour")
def valoracion():
    datos = _datos()
    ok = bool(datos) and isinstance(datos.get("util"), bool) and ayuda_metricas.registrar_valoracion(str(datos.get("pagina") or ""), str(datos.get("idioma") or ""), datos["util"])
    return make_response("", 204 if ok else 400)


@ayuda_metricas_bp.route("/busqueda", methods=["POST"])
@limiter.limit("30/hour")
def busqueda():
    datos = _datos()
    ok = bool(datos) and ayuda_metricas.registrar_busqueda(str(datos.get("consulta") or ""), str(datos.get("idioma") or ""))
    return make_response("", 204 if ok else 400)
