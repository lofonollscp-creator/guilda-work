"""Pantalla de los honorarios por tramos de Guilda Fiscal (ver app/honorarios.py): las reglas, un simulador, los vencimientos presentados que esperan honorario y los ya confirmados."""
from __future__ import annotations

from urllib.parse import quote

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from . import acceso, honorarios, verticales
from .auth import login_required
from .honorarios import ErrorHonorarios

honorarios_bp = Blueprint("honorarios", __name__, url_prefix="/guilda-fiscal/honorarios")


@honorarios_bp.before_request
def _solo_con_el_modulo():
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, "fiscal"):
        abort(404)
    if request.method not in ("GET", "HEAD", "OPTIONS") and g.get("usuario_id") is not None and acceso.es_solo_auditor(g.tenant_id, g.usuario_id):
        abort(403)


def _vuelta(**consulta):
    return redirect(url_for("honorarios.inicio", **consulta))


def _error(e: Exception):
    return redirect(url_for("honorarios.inicio") + f"?error={quote(str(e)[:300])}")


@honorarios_bp.route("/")
@login_required
def inicio():
    reglas = honorarios.listar_reglas(g.tenant_id)
    editar = request.args.get("editar", type=int)
    regla = honorarios.obtener_regla(g.tenant_id, editar) if editar else None
    simulacion = None
    if request.args.get("sim_modelo") is not None:
        simulacion = honorarios.simular(g.tenant_id, request.args.get("sim_modelo", ""), request.args.get("sim_forma", ""), request.args.get("sim_apuntes", "0"))
    return render_template("honorarios.html", reglas=reglas, regla=regla, tramos_texto=honorarios.tramos_a_texto(regla["tramos"]) if regla and regla["calculo"] == "tramos" else "",
                           simulacion=simulacion, sim=request.args, pendientes=honorarios.pendientes_de_confirmar(g.tenant_id, g.usuario_id),
                           aplicados=honorarios.aplicados(g.tenant_id, g.usuario_id, limite=100), puede_gestionar=acceso.puede_autorizar(g.tenant_id, g.usuario_id),
                           calculos=honorarios.CALCULOS, formas=honorarios.FORMAS_JURIDICAS, euros=honorarios.euros, error=(request.args.get("error") or "")[:300] or None)


@honorarios_bp.route("/reglas", methods=["POST"])
@login_required
def guardar_regla():
    f = request.form
    datos = {"nombre": f.get("nombre"), "prioridad": f.get("prioridad"), "modelo": f.get("modelo"), "forma_juridica": f.get("forma_juridica"), "calculo": f.get("calculo"),
             "importe": f.get("importe"), "unidad": f.get("unidad"), "minimo": f.get("minimo")}
    try:
        if f.get("calculo") == "tramos":
            datos["tramos"] = honorarios.tramos_desde_texto(f.get("tramos", ""))
        regla_id = f.get("regla_id", type=int)
        if regla_id:
            honorarios.editar_regla(g.tenant_id, g.usuario_id, regla_id, datos)
        else:
            honorarios.crear_regla(g.tenant_id, g.usuario_id, datos)
    except ErrorHonorarios as e:
        return _error(e)
    return _vuelta()


@honorarios_bp.route("/reglas/<int:regla_id>/activar", methods=["POST"])
@login_required
def activar_regla(regla_id: int):
    try:
        honorarios.alternar_regla(g.tenant_id, g.usuario_id, regla_id)
    except ErrorHonorarios as e:
        return _error(e)
    return _vuelta()


@honorarios_bp.route("/reglas/<int:regla_id>/eliminar", methods=["POST"])
@login_required
def eliminar_regla(regla_id: int):
    try:
        honorarios.eliminar_regla(g.tenant_id, g.usuario_id, regla_id)
    except ErrorHonorarios as e:
        return _error(e)
    return _vuelta()


@honorarios_bp.route("/vencimientos/<int:vencimiento_id>/confirmar", methods=["POST"])
@login_required
def confirmar(vencimiento_id: int):
    try:
        honorarios.confirmar(g.tenant_id, g.usuario_id, vencimiento_id, importe=request.form.get("importe"))
    except ErrorHonorarios as e:
        return _error(e)
    return _vuelta()


@honorarios_bp.route("/aplicados/<int:aplicado_id>/facturar", methods=["POST"])
@login_required
def facturar(aplicado_id: int):
    try:
        honorarios.marcar_facturado(g.tenant_id, g.usuario_id, aplicado_id, request.form.get("referencia", ""))
    except ErrorHonorarios as e:
        return _error(e)
    return _vuelta()


@honorarios_bp.route("/aplicados/<int:aplicado_id>/anular", methods=["POST"])
@login_required
def anular(aplicado_id: int):
    try:
        honorarios.anular(g.tenant_id, g.usuario_id, aplicado_id, request.form.get("motivo", ""))
    except ErrorHonorarios as e:
        return _error(e)
    return _vuelta()
