"""Rutas del Asistente IA (chat con OpenRouter + herramientas del MCP), en
su propio Blueprint, mismo patrón que app/rutas_correo.py."""
from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from . import db, ia_asistente as asistente

ia_bp = Blueprint("ia", __name__, url_prefix="/ia")

MODELOS_SUGERIDOS = [
    "anthropic/claude-sonnet-4.5",
    "openai/gpt-4o-mini",
    "meta-llama/llama-3.1-70b-instruct",
]


@ia_bp.route("/")
def asistente_vista():
    return render_template(
        "ia_asistente.html",
        mensajes=db.listar_mensajes_ia(),
        pendiente=asistente.pendiente_actual(),
        preferencias=db.obtener_preferencias_ia(),
        panel_flotante=False,
    )


@ia_bp.route("/mensaje", methods=["POST"])
def enviar_mensaje():
    datos = request.get_json(silent=True) or {}
    try:
        resultado = asistente.procesar_turno(datos.get("texto", ""))
        return jsonify({"ok": True, **resultado})
    except asistente.ErrorIA as e:
        return jsonify({"ok": False, "error": str(e)})


@ia_bp.route("/confirmar", methods=["POST"])
def confirmar():
    datos = request.get_json(silent=True) or {}
    try:
        resultado = asistente.confirmar_pendiente(bool(datos.get("aceptar")))
        return jsonify({"ok": True, **resultado})
    except asistente.ErrorIA as e:
        return jsonify({"ok": False, "error": str(e)})


@ia_bp.route("/vaciar", methods=["POST"])
def vaciar():
    db.vaciar_mensajes_ia()
    return "", 204


@ia_bp.route("/ajustes")
def ajustes():
    return render_template(
        "ia_ajustes.html",
        preferencias=db.obtener_preferencias_ia(),
        modelos_sugeridos=MODELOS_SUGERIDOS,
        api_key_configurada=bool(asistente.obtener_api_key()),
    )


@ia_bp.route("/ajustes", methods=["POST"])
def guardar_ajustes():
    modelo = request.form.get("modelo", "").strip()
    if not modelo:
        modelo = request.form.get("modelo_personalizado", "").strip()
    db.guardar_preferencias_ia(
        modelo=modelo,
        modo_autonomo=request.form.get("modo_autonomo") == "on",
    )

    nueva_clave = request.form.get("api_key", "").strip()
    if nueva_clave:
        asistente.guardar_api_key(nueva_clave)
    if request.form.get("borrar_api_key") == "on":
        asistente.borrar_api_key()

    return redirect(url_for("ia.ajustes"))
