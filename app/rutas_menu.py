"""Ajustes › Menú: ocultar lo que no se usa y fijar accesos directos (ver app/navegacion.py)."""
from __future__ import annotations

from flask import Blueprint, g, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import db, navegacion, verticales
from .auth import login_required

menu_bp = Blueprint("menu", __name__, url_prefix="/ajustes/menu")


def _contexto() -> tuple[bool, bool]:
    hay = g.get("tenant_id") is not None
    return hay, bool(hay and "gestoria" in verticales.activos_de(g.tenant_id))


@menu_bp.route("/", methods=["GET"])
@login_required
def pantalla():
    hay, gestoria = _contexto()
    return render_template("ajustes_menu.html", prefs=navegacion.leer(db.obtener_perfil_usuario(g.usuario_id)), elementos=navegacion.disponibles(hay, gestoria),
                           max_fijados=navegacion.MAX_FIJADOS, aviso=request.args.get("aviso"))


@menu_bp.route("/", methods=["POST"])
@login_required
def guardar():
    hay, gestoria = _contexto()
    posibles = {e["clave"] for e in navegacion.disponibles(hay, gestoria)}
    if request.form.get("restablecer"):
        navegacion.guardar(g.usuario_id, [], [])
        return redirect(url_for("menu.pantalla", aviso="restablecido"))
    mostrar = set(request.form.getlist("mostrar"))
    fijar = [k for k in request.form.getlist("fijar") if k in posibles]
    ocultos = [e["clave"] for e in navegacion.disponibles(hay, gestoria) if e["ocultable"] and e["clave"] not in mostrar]
    # lo que no está disponible para esta persona (p. ej. sin despacho) no se toca: se conserva lo que ya hubiera
    previas = navegacion.leer(db.obtener_perfil_usuario(g.usuario_id))
    ocultos += [k for k in previas["ocultos"] if k not in posibles]
    fijar += [k for k in previas["fijados"] if k not in posibles]
    navegacion.guardar(g.usuario_id, ocultos, fijar)
    return redirect(url_for("menu.pantalla", aviso="guardado"))
