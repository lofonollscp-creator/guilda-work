"""Agenda de citas (Cal.diy) -- tercera ronda de mejoras. A diferencia de
lo que su nombre podría sugerir, NO es "mi" agenda personal: Cal.diy se
aprovisiona con un único usuario de servicio POR TENANT (ver
app/calcom.py:aprovisionar_tenant), un calendario compartido de toda la
gestoría, no uno por empleado -- así que esta vista muestra las reservas
de TODO el tenant, visibles para cualquiera de sus usuarios, igual que
el calendario fiscal.

Vive en su propio Blueprint, mismo patrón que app/rutas_tiquets.py."""
from datetime import date

from flask import Blueprint, abort, g, render_template

from . import calcom, db
from .auth import login_required

citas_bp = Blueprint("citas", __name__, url_prefix="/citas")


@citas_bp.route("/")
@login_required
def agenda():
    if g.tenant_id is None:
        abort(403)
    tenant = db.obtener_tenant(g.tenant_id)
    api_key = tenant["calcom_api_key"] if tenant else None
    reservas = []
    error = None
    if api_key:
        try:
            reservas = calcom.listar_reservas(api_key, desde=date.today().isoformat())
        except calcom.ErrorCalcom as e:
            error = str(e)
    return render_template("citas.html", reservas=reservas, api_key_configurada=bool(api_key), error=error)
