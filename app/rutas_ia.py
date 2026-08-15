"""Rutas del Asistente IA (chat con OpenRouter + herramientas del MCP), en
su propio Blueprint, mismo patrón que app/rutas_correo.py."""
import json

from flask import Blueprint, Response, g, jsonify, redirect, render_template, request, stream_with_context, url_for

from . import db, ia_asistente as asistente
from .auth import login_required

ia_bp = Blueprint("ia", __name__, url_prefix="/ia")


def _sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


@ia_bp.route("/")
@login_required
def asistente_vista():
    return render_template(
        "ia_asistente.html",
        mensajes=db.listar_mensajes_ia(g.usuario_id),
        pendiente=asistente.pendiente_actual(g.usuario_id),
        preferencias=db.obtener_preferencias_ia(g.usuario_id),
        panel_flotante=False,
    )


@ia_bp.route("/mensaje", methods=["POST"])
@login_required
def enviar_mensaje():
    datos = request.get_json(silent=True) or {}
    try:
        resultado = asistente.procesar_turno(g.usuario_id, datos.get("texto", ""))
        return jsonify({"ok": True, **resultado})
    except asistente.ErrorIA as e:
        return jsonify({"ok": False, "error": str(e)})


_ADJUNTO_TAMANO_MAXIMO_BYTES = 1 * 1024 * 1024  # 1 MB -- son ficheros de texto/CSV pequeños, no documentos grandes


@ia_bp.route("/adjuntos", methods=["POST"])
@login_required
def subir_adjunto():
    """Sube un fichero de texto/CSV al chat -- el asistente lo lee bajo
    demanda con la tool leer_adjunto_chat (app/ia_herramientas.py) cuando
    el usuario se refiera al id devuelto aquí. Sin soporte de PDF/binarios
    en esta fase (no hay ninguna librería de extracción de PDF en el
    proyecto, añadirla es una decisión aparte, no forzada por esto)."""
    fichero = request.files.get("adjunto")
    if not fichero or not fichero.filename:
        return jsonify({"ok": False, "error": "Falta el archivo."})
    datos = fichero.read(_ADJUNTO_TAMANO_MAXIMO_BYTES + 1)
    if len(datos) > _ADJUNTO_TAMANO_MAXIMO_BYTES:
        return jsonify({"ok": False, "error": "El archivo pesa demasiado (máximo 1 MB)."})
    try:
        datos.decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"ok": False, "error": "Solo se admiten archivos de texto o CSV (UTF-8)."})
    adjunto_id = db.crear_adjunto_ia(g.usuario_id, fichero.filename, fichero.mimetype, datos)
    return jsonify({"ok": True, "id": adjunto_id, "nombre_archivo": fichero.filename})


@ia_bp.route("/confirmar", methods=["POST"])
@login_required
def confirmar():
    datos = request.get_json(silent=True) or {}
    try:
        resultado = asistente.confirmar_pendiente(g.usuario_id, bool(datos.get("aceptar")))
        return jsonify({"ok": True, **resultado})
    except asistente.ErrorIA as e:
        return jsonify({"ok": False, "error": str(e)})


# --- Variantes en streaming (asistente de voz, Fase V1 del plan
# "eventual-herding-kitten") ------------------------------------------------
# Formato Server-Sent Events: cada línea "data: {...}\n\n" es uno de los
# eventos que ya documenta ia_asistente.procesar_turno_stream (delta de
# texto / mensaje persistido / confirmación pendiente / error / fin). Las
# rutas /mensaje y /confirmar de arriba NO se tocan -- se quedan para quien
# no necesite ir leyendo la respuesta en voz alta según llega.


@ia_bp.route("/mensaje/stream", methods=["POST"])
@login_required
def enviar_mensaje_stream():
    datos = request.get_json(silent=True) or {}
    texto = datos.get("texto", "")
    usuario_id = g.usuario_id

    def generar():
        try:
            for evento in asistente.procesar_turno_stream(usuario_id, texto):
                yield _sse(evento)
        except Exception as e:  # noqa: BLE001 -- el stream ya está abierto, no se puede devolver un 500
            yield _sse({"tipo": "error", "mensaje": str(e)})

    return Response(stream_with_context(generar()), mimetype="text/event-stream")


@ia_bp.route("/confirmar/stream", methods=["POST"])
@login_required
def confirmar_stream():
    datos = request.get_json(silent=True) or {}
    aceptar = bool(datos.get("aceptar"))
    usuario_id = g.usuario_id

    def generar():
        try:
            for evento in asistente.confirmar_pendiente_stream(usuario_id, aceptar):
                yield _sse(evento)
        except Exception as e:  # noqa: BLE001
            yield _sse({"tipo": "error", "mensaje": str(e)})

    return Response(stream_with_context(generar()), mimetype="text/event-stream")


@ia_bp.route("/vaciar", methods=["POST"])
@login_required
def vaciar():
    db.vaciar_mensajes_ia(g.usuario_id)
    return "", 204


@ia_bp.route("/modelos")
@login_required
def modelos():
    """Modelos gratuitos de OpenRouter (ver ia_asistente.listar_modelos_gratuitos),
    usado tanto por el <select> de /ia/ajustes como por el datalist de
    proveedor=openrouter en /historial (informes)."""
    return jsonify(asistente.listar_modelos_gratuitos())


@ia_bp.route("/ajustes")
@login_required
def ajustes():
    return render_template(
        "ia_ajustes.html",
        preferencias=db.obtener_preferencias_ia(g.usuario_id),
        modelos_sugeridos=asistente.listar_modelos_gratuitos(),
        num_claves_configuradas=len(asistente.obtener_api_keys(g.usuario_id)),
    )


@ia_bp.route("/ajustes", methods=["POST"])
@login_required
def guardar_ajustes():
    modelo = request.form.get("modelo", "").strip()
    if not modelo:
        modelo = request.form.get("modelo_personalizado", "").strip()
    db.guardar_preferencias_ia(
        g.usuario_id,
        modelo=modelo,
        modo_autonomo=request.form.get("modo_autonomo") == "on",
    )

    nuevas_claves = request.form.get("api_keys", "").splitlines()
    if any(c.strip() for c in nuevas_claves):
        asistente.guardar_api_keys(g.usuario_id, nuevas_claves)
    if request.form.get("borrar_api_keys") == "on":
        asistente.borrar_api_key(g.usuario_id)

    return redirect(url_for("ia.ajustes"))
