"""Centro de notificaciones unificado (app/notificaciones.py -- el
registro en BD; este blueprint solo sirve el desplegable de la topbar).
Vive en su propio Blueprint, mismo patrón que app/rutas_tareas.py."""
from flask import Blueprint, g, jsonify

from . import db
from .auth import login_required

notificaciones_bp = Blueprint("notificaciones", __name__, url_prefix="/notificaciones")


@notificaciones_bp.route("/recientes")
@login_required
def recientes():
    """Las últimas notificaciones del usuario, para pintar el
    desplegable de la campana -- no marca nada como leído (eso es una
    acción explícita aparte, ver /marcar-leidas), así que se puede
    llamar tantas veces como haga falta sin perder el contador."""
    filas = db.listar_notificaciones(g.usuario_id, limite=10)
    return jsonify([
        {
            "id": f["id"], "tipo": f["tipo"], "titulo": f["titulo"], "cuerpo": f["cuerpo"],
            "url": f["url"], "creado_en": f["creado_en"], "leido": f["leido_en"] is not None,
        }
        for f in filas
    ])


@notificaciones_bp.route("/marcar-leidas", methods=["POST"])
@login_required
def marcar_leidas():
    db.marcar_notificaciones_leidas(g.usuario_id)
    return jsonify({"ok": True})
