"""Pantallas de los cambios en lote de los vencimientos fiscales (ver app/fiscal_masivo.py): revisar la propuesta, confirmarla, deshacerla y ver el historial."""
from __future__ import annotations

from urllib.parse import quote

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from . import acceso, db, fiscal_masivo, verticales
from .auth import login_required
from .fiscal_masivo import ErrorMasivoFiscal

fiscal_masivo_bp = Blueprint("fiscal_masivo", __name__, url_prefix="/guilda-fiscal/masivo")


@fiscal_masivo_bp.before_request
def _solo_con_el_modulo():
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, "fiscal"):
        abort(404)
    if request.method not in ("GET", "HEAD", "OPTIONS") and g.get("usuario_id") is not None and acceso.es_solo_auditor(g.tenant_id, g.usuario_id):
        abort(403)


def _con_error(endpoint: str, e: Exception, **valores):
    return redirect(url_for(endpoint, **valores) + f"?error={quote(str(e)[:300])}")


def _accion_o_404(accion_id: int) -> dict:
    a = fiscal_masivo.obtener(g.tenant_id, g.usuario_id, accion_id)
    if a is None:
        abort(404)
    return a


@fiscal_masivo_bp.route("/")
@login_required
def historial():
    return render_template("fiscal_masivo_historial.html", acciones=fiscal_masivo.historial(g.tenant_id, g.usuario_id), error=(request.args.get("error") or "")[:300] or None)


@fiscal_masivo_bp.route("/proponer", methods=["POST"])
@login_required
def proponer():
    f = request.form
    parametros = {"usuario_id": f.get("usuario_id"), "dias": f.get("dias"), "motivo": f.get("motivo")}
    try:
        a = fiscal_masivo.proponer(g.tenant_id, g.usuario_id, f.get("tipo", ""), f.getlist("ids"), parametros)
    except ErrorMasivoFiscal as e:
        return _con_error("guilda_fiscal.vencimientos", e)
    return redirect(url_for("fiscal_masivo.ver", accion_id=a["id"]))


@fiscal_masivo_bp.route("/<int:accion_id>")
@login_required
def ver(accion_id: int):
    return render_template("fiscal_masivo_ver.html", a=_accion_o_404(accion_id), error=(request.args.get("error") or "")[:300] or None)


@fiscal_masivo_bp.route("/<int:accion_id>/aplicar", methods=["POST"])
@login_required
def aplicar(accion_id: int):
    try:
        fiscal_masivo.aplicar(g.tenant_id, g.usuario_id, accion_id)
    except ErrorMasivoFiscal as e:
        return _con_error("fiscal_masivo.ver", e, accion_id=accion_id)
    return redirect(url_for("fiscal_masivo.ver", accion_id=accion_id))


@fiscal_masivo_bp.route("/<int:accion_id>/cancelar", methods=["POST"])
@login_required
def cancelar(accion_id: int):
    try:
        fiscal_masivo.cancelar(g.tenant_id, g.usuario_id, accion_id)
    except ErrorMasivoFiscal as e:
        return _con_error("fiscal_masivo.ver", e, accion_id=accion_id)
    return redirect(url_for("guilda_fiscal.vencimientos"))


@fiscal_masivo_bp.route("/<int:accion_id>/deshacer", methods=["POST"])
@login_required
def deshacer(accion_id: int):
    try:
        fiscal_masivo.deshacer(g.tenant_id, g.usuario_id, accion_id)
    except ErrorMasivoFiscal as e:
        return _con_error("fiscal_masivo.ver", e, accion_id=accion_id)
    return redirect(url_for("fiscal_masivo.ver", accion_id=accion_id))
