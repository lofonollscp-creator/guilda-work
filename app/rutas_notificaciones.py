"""Centro de notificaciones unificado (app/notificaciones.py -- el
registro en BD; este blueprint solo sirve el desplegable de la topbar).
Vive en su propio Blueprint, mismo patrón que app/rutas_tareas.py."""
import json

from flask import Blueprint, g, jsonify, request

from . import db, push
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


@notificaciones_bp.route("/<int:notificacion_id>/eliminar", methods=["POST"])
@login_required
def eliminar(notificacion_id: int):
    db.eliminar_notificacion(g.usuario_id, notificacion_id)
    return jsonify({"ok": True})


@notificaciones_bp.route("/vaciar", methods=["POST"])
@login_required
def vaciar():
    db.eliminar_todas_notificaciones(g.usuario_id)
    return jsonify({"ok": True})


# --- Avisos push en el navegador / webapp (Web Push, ver app/push.py) ---

@notificaciones_bp.route("/push/clave")
@login_required
def push_clave():
    """Clave pública VAPID para suscribirse; vacía si el servidor no tiene el canal web activado."""
    return jsonify({"clave": push.VAPID_PUBLICA if push.web_configurado() else ""})


def _endpoint_valido(endpoint) -> bool:
    return isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) <= 1000


@notificaciones_bp.route("/push/suscribir", methods=["POST"])
@login_required
def push_suscribir():
    datos = request.get_json(silent=True) or {}
    claves = datos.get("keys") or {}
    endpoint = datos.get("endpoint")
    if not push.web_configurado() or not _endpoint_valido(endpoint) or not all(isinstance(claves.get(k), str) and 0 < len(claves[k]) <= 200 for k in ("p256dh", "auth")):
        return jsonify({"ok": False}), 400
    suscripcion = json.dumps({"endpoint": endpoint, "keys": {"p256dh": claves["p256dh"], "auth": claves["auth"]}}, separators=(",", ":"))
    db.registrar_suscripcion_web(g.usuario_id, suscripcion, endpoint)
    return jsonify({"ok": True})


@notificaciones_bp.route("/push/baja", methods=["POST"])
@login_required
def push_baja():
    endpoint = (request.get_json(silent=True) or {}).get("endpoint")
    if _endpoint_valido(endpoint):
        db.eliminar_suscripcion_web(g.usuario_id, endpoint)
    return jsonify({"ok": True})
