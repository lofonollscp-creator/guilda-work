"""Facturación conectada al trabajo del despacho (ver app/facturacion_despacho.py): facturar desde un expediente y el estado de cobro de cada cliente."""
from __future__ import annotations

from flask import Blueprint, abort, g, redirect, request, url_for
from flask_babel import gettext as _

from . import facturacion_despacho as fd
from . import nucleo
from .auth import login_required

cobros_bp = Blueprint("cobros", __name__, url_prefix="/expedientes")


def _supervisor() -> bool:
    return bool(g.get("supervisor_tenant") or g.get("es_admin"))


@cobros_bp.route("/<int:expediente_id>/facturar", methods=["POST"])
@login_required
def facturar(expediente_id: int):
    if g.get("tenant_id") is None:
        abort(404)
    destino = url_for("expedientes.ficha", expediente_id=expediente_id)
    if request.form.get("confirmo") != "1":
        return redirect(url_for("expedientes.ficha", expediente_id=expediente_id, error=_("Marca la casilla para confirmar que quieres emitir la factura.")) + "#facturacion")
    try:
        r = fd.facturar_expediente(g.tenant_id, g.usuario_id, _supervisor(), expediente_id, request.form.get("concepto"), request.form.get("importe"))
    except fd.facturascripts.ErrorFacturaScripts as e:
        return redirect(url_for("expedientes.ficha", expediente_id=expediente_id, error=_("FacturaScripts no ha podido crear la factura: %(motivo)s", motivo=str(e)[:150])) + "#facturacion")
    except ValueError as e:
        return redirect(url_for("expedientes.ficha", expediente_id=expediente_id, error=str(e)[:200]) + "#facturacion")
    return redirect(destino + "#facturacion")


@cobros_bp.app_context_processor
def _ayudas_de_plantilla():
    """Funciones que usan las plantillas de la ficha del expediente y de la ficha fiscal; solo trabajan si se las llama."""
    def panel_facturacion(expediente):
        if g.get("tenant_id") is None:
            return {"disponible": False}
        s = fd.situacion(g.tenant_id, g.usuario_id, _supervisor(), expediente)
        if s["disponible"]:
            s["facturas"] = fd.facturas_del_expediente(g.tenant_id, expediente["id"])
        return s

    return {"panel_facturacion": panel_facturacion, "estado_de_factura": fd.estado_de, "resumen_cobro": fd.resumen_cobro}
