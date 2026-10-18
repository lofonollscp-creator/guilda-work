"""«Hoy»: la bandeja única de lo que necesita a la persona (ver app/bandeja_hoy.py)."""
from __future__ import annotations

from flask import Blueprint, Response, g, render_template

from . import bandeja_hoy
from .auth import login_required

hoy_bp = Blueprint("hoy", __name__, url_prefix="/hoy")


@hoy_bp.route("/")
@login_required
def bandeja():
    supervisor = bool(g.get("supervisor_tenant") or g.get("es_admin"))
    return render_template("hoy.html", bandeja=bandeja_hoy.reunir(g.usuario_id, supervisor))


@hoy_bp.route("/destacados")
@login_required
def destacados():
    """El panel «Necesita tu atención» del inicio (sin las tareas, que ya salen en «Mi día»): un fragmento que el inicio pide después de cargar. 204 si no hay nada."""
    supervisor = bool(g.get("supervisor_tenant") or g.get("es_admin"))
    b = bandeja_hoy.reunir(g.usuario_id, supervisor)
    elegidos = [i for i in b["destacados"] if i["clave"] != "tareas"][:5]
    if not elegidos:
        return Response(status=204)
    return render_template("_hoy_destacados.html", destacados=elegidos, total=b["total"])
