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
import json

from flask import Blueprint, Response, abort, render_template, request

from . import documentacion_dev, openapi, sdk_generador

docs_bp = Blueprint("docs", __name__, url_prefix="/docs")


_DESCARGAS = {
    "guilda_work.py": ("text/x-python; charset=utf-8", lambda spec, base: sdk_generador.generar_python(spec, base)),
    "guilda-work.ts": ("application/typescript; charset=utf-8", lambda spec, base: sdk_generador.generar_typescript(spec, base)),
    "guilda-work.postman_collection.json": ("application/json", lambda spec, base: json.dumps(sdk_generador.generar_postman(spec, base), indent=2, ensure_ascii=False)),
}


@docs_bp.route("/sdk/<nombre>")
def descargar_sdk(nombre: str):
    """Cliente de Python, cliente de TypeScript o colección de Postman, generados AL MOMENTO del contrato OpenAPI de esta instancia
    (y ya apuntando a ella): nunca están desactualizados."""
    if nombre not in _DESCARGAS:
        abort(404)
    tipo, generar = _DESCARGAS[nombre]
    contenido = generar(openapi.generar_spec(), request.url_root.rstrip("/"))
    respuesta = Response(contenido, mimetype=tipo.split(";")[0], headers={"Content-Disposition": f'attachment; filename="{nombre}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})
    respuesta.charset = "utf-8"
    return respuesta


@docs_bp.route("/")
@docs_bp.route("/<path:slug>")
def pagina(slug: str = ""):
    datos = documentacion_dev.obtener_pagina(slug.rstrip("/"))
    if datos is None:
        abort(404)
    if datos.get("interactivo"):
        return render_template("docs/explorador_api.html")
    anterior, siguiente = documentacion_dev.pagina_adyacente(datos["slug"])
    return render_template(
        "docs/pagina.html",
        pagina=datos,
        navegacion=documentacion_dev.navegacion(),
        slug_actual=datos["slug"],
        indice_busqueda=documentacion_dev.indice_busqueda(),
        pagina_anterior=anterior,
        pagina_siguiente=siguiente,
    )
