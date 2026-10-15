"""Pantalla y recursos de la marca del despacho (app/marca.py)."""
from __future__ import annotations

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for

from . import acceso, marca
from .auth import login_required

marca_bp = Blueprint("marca", __name__, url_prefix="/marca")


def _dirige_el_despacho() -> bool:
    return g.get("tenant_id") is not None and acceso.es_directivo(g.usuario_id)


@marca_bp.route("/estilo.css")
@login_required
def estilo():
    r = Response(marca.css(marca.obtener(g.get("tenant_id"))), mimetype="text/css")
    r.headers["Cache-Control"] = "private, max-age=300"
    return r


@marca_bp.route("/logo")
@login_required
def logo():
    contenido = marca.logo(g.get("tenant_id"))
    if contenido is None:
        abort(404)
    r = Response(contenido, mimetype="image/png")
    r.headers["Cache-Control"] = "private, max-age=3600"
    r.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return r


@marca_bp.route("/p/<token>.png")
def logo_publico(token: str):
    """El logo del despacho para los clientes de correo (que no tienen sesión). El enlace va firmado: sin él no se ve nada."""
    t = marca.tenant_de_token(token)
    contenido = marca.logo(t) if t is not None else None
    if contenido is None:
        abort(404)
    r = Response(contenido, mimetype="image/png")
    r.headers["Cache-Control"] = "public, max-age=86400"
    r.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


@marca_bp.route("/", methods=["GET", "POST"])
@login_required
def ajustes():
    if not _dirige_el_despacho():
        abort(403)
    t = g.tenant_id
    error = None
    if request.method == "POST":
        try:
            if request.form.get("restablecer"):
                marca.guardar(t, restablecer=True)
            else:
                archivo = request.files.get("logo")
                marca.guardar(t, nombre=request.form.get("nombre"), color=request.form.get("color") if request.form.get("usar_color") else None,
                              logo_subido=archivo.read() if archivo and archivo.filename else None, quitar_logo=bool(request.form.get("quitar_logo")))
            return redirect(url_for("marca.ajustes", guardado=1))
        except ValueError as e:
            error = str(e)
    return render_template("marca.html", marca=marca.obtener(t), error=error, guardado=request.args.get("guardado") == "1")
