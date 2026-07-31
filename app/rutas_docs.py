"""Guía para desarrolladores (`/docs/*`) — documentación técnica pública
para quien quiera integrar su propio software con una instancia de
Guilda Work (API REST, MCP) o desplegar/extender el propio proyecto.

A propósito SIN `@login_required`: quien va a integrar un sistema
externo contra esta instancia no tiene por qué tener ya una cuenta —
igual que la documentación de cualquier producto con API pública (ver
https://docs.documenso.com/docs/developers, la referencia visual de
esta sección). El contenido en sí vive en `app/documentacion_dev.py`,
no aquí — esta ruta solo resuelve el slug y renderiza.
"""
from flask import Blueprint, abort, render_template

from . import documentacion_dev

docs_bp = Blueprint("docs", __name__, url_prefix="/docs")


@docs_bp.route("/")
@docs_bp.route("/<path:slug>")
def pagina(slug: str = ""):
    datos = documentacion_dev.obtener_pagina(slug.rstrip("/"))
    if datos is None:
        abort(404)
    return render_template(
        "docs/pagina.html",
        pagina=datos,
        navegacion=documentacion_dev.navegacion(),
        slug_actual=datos["slug"],
    )
