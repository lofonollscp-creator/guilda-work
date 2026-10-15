"""Pantalla de la libreta de contactos del despacho (app/contactos.py) y su acceso rápido desde Correo."""
from __future__ import annotations

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from . import acceso, contactos, nucleo
from .auth import login_required

contactos_bp = Blueprint("contactos", __name__, url_prefix="/contactos")


def _tenant() -> int:
    if g.get("tenant_id") is None:
        abort(404)
    return g.tenant_id


def _puede_modificar(t: int) -> bool:
    return not acceso.es_solo_auditor(t, g.usuario_id)


def _a_la_libreta(error: str | None = None, **valores):
    if error:
        valores["error"] = error[:200]
    return redirect(url_for("contactos.lista", **valores))


@contactos_bp.route("/")
@login_required
def lista():
    t = _tenant()
    q, grupo_id = (request.args.get("q") or "").strip(), request.args.get("grupo", type=int)
    editar_id = request.args.get("editar", type=int)
    return render_template(
        "contactos.html", contactos=contactos.listar(t, g.usuario_id, q, grupo_id), grupos=contactos.listar_grupos(t, g.usuario_id), q=q, grupo_id=grupo_id,
        editando=contactos.obtener(t, g.usuario_id, editar_id) if editar_id else None, grupos_del_editado=contactos.grupos_de(t, editar_id) if editar_id else [],
        clientes=nucleo.listar_clientes(t, None, None, None, limite=500, pagina=1)[0], puede_modificar=_puede_modificar(t), error=(request.args.get("error") or "")[:200] or None,
    )


def _datos() -> dict:
    return {c: request.form.get(c, "") for c in ("nombre", "email", "telefono", "empresa", "notas")} | {"cliente_id": request.form.get("cliente_id", type=int)}


@contactos_bp.route("/", methods=["POST"])
@login_required
def crear():
    t = _tenant()
    if not _puede_modificar(t):
        abort(403)
    try:
        contactos.crear(t, g.usuario_id, **_datos())
    except ValueError as e:
        return _a_la_libreta(str(e))
    return _a_la_libreta()


@contactos_bp.route("/<int:contacto_id>", methods=["POST"])
@login_required
def editar(contacto_id: int):
    t = _tenant()
    if not _puede_modificar(t):
        abort(403)
    try:
        contactos.editar(t, g.usuario_id, contacto_id, **_datos())
        for grupo in contactos.listar_grupos(t, g.usuario_id):
            contactos.poner_en_grupo(t, g.usuario_id, grupo["id"], contacto_id, str(grupo["id"]) in request.form.getlist("grupos"))
    except ValueError as e:
        return _a_la_libreta(str(e), editar=contacto_id)
    return _a_la_libreta()


@contactos_bp.route("/<int:contacto_id>/eliminar", methods=["POST"])
@login_required
def eliminar(contacto_id: int):
    t = _tenant()
    if not _puede_modificar(t):
        abort(403)
    if not contactos.eliminar(t, g.usuario_id, contacto_id):
        abort(404)
    return _a_la_libreta()


@contactos_bp.route("/grupos", methods=["POST"])
@login_required
def crear_grupo():
    t = _tenant()
    if not _puede_modificar(t):
        abort(403)
    try:
        contactos.crear_grupo(t, request.form.get("nombre", ""))
    except ValueError as e:
        return _a_la_libreta(str(e))
    return _a_la_libreta()


@contactos_bp.route("/grupos/<int:grupo_id>/eliminar", methods=["POST"])
@login_required
def eliminar_grupo(grupo_id: int):
    t = _tenant()
    if not _puede_modificar(t):
        abort(403)
    contactos.eliminar_grupo(t, grupo_id)
    return _a_la_libreta()
