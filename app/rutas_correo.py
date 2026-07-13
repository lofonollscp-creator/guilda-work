"""Rutas del cliente de correo (IMAP/POP3 de lectura, SMTP de envío). Vive en
su propio Blueprint, mismo patrón que app/rutas_tareas.py.
"""
from flask import Blueprint, abort, redirect, render_template, request, url_for

from . import correo, db

correo_bp = Blueprint("correo", __name__, url_prefix="/correo")


def _render_redactar(*, cuenta_id=None, destinatarios="", asunto="", cuerpo="", en_respuesta_a="", error=None):
    cuentas_con_smtp = [c for c in db.listar_cuentas_correo() if c["smtp_host"]]
    return render_template(
        "correo_redactar.html",
        cuentas=cuentas_con_smtp,
        cuenta_id=cuenta_id,
        destinatarios=destinatarios,
        asunto=asunto,
        cuerpo=cuerpo,
        en_respuesta_a=en_respuesta_a or "",
        error=error,
    )


@correo_bp.route("/cuentas")
def cuentas():
    return render_template("correo_cuentas.html", cuentas=db.listar_cuentas_correo(), error=None)


@correo_bp.route("/cuentas", methods=["POST"])
def crear_cuenta():
    try:
        correo.guardar_cuenta(
            nombre=request.form.get("nombre", ""),
            protocolo=request.form.get("protocolo", "imap"),
            host=request.form.get("host", ""),
            puerto=int(request.form.get("puerto") or 993),
            usuario=request.form.get("usuario", ""),
            contrasena=request.form.get("contrasena", ""),
            usa_tls=request.form.get("usa_tls") == "on",
            smtp_host=request.form.get("smtp_host") or None,
            smtp_puerto=int(request.form["smtp_puerto"]) if request.form.get("smtp_puerto") else None,
            smtp_tls=request.form.get("smtp_tls") == "on",
        )
    except correo.ErrorCorreo as e:
        return render_template("correo_cuentas.html", cuentas=db.listar_cuentas_correo(), error=str(e))
    return redirect(url_for("correo.cuentas"))


@correo_bp.route("/cuentas/<int:cuenta_id>/eliminar", methods=["POST"])
def eliminar_cuenta(cuenta_id: int):
    correo.eliminar_cuenta(cuenta_id)
    return redirect(url_for("correo.cuentas"))


@correo_bp.route("/cuentas/<int:cuenta_id>/probar", methods=["POST"])
def probar_cuenta(cuenta_id: int):
    try:
        correo.probar_conexion(cuenta_id)
        error = None
    except correo.ErrorCorreo as e:
        error = str(e)
    return render_template("correo_cuentas.html", cuentas=db.listar_cuentas_correo(), error=error)


@correo_bp.route("/")
def bandeja():
    cuenta_id = request.args.get("cuenta_id", type=int)
    cuentas_disponibles = db.listar_cuentas_correo()
    if cuenta_id is None and cuentas_disponibles:
        cuenta_id = cuentas_disponibles[0]["id"]

    mensajes = []
    error = None
    if cuenta_id is not None:
        if db.obtener_cuenta_correo(cuenta_id) is None:
            abort(404)
        solo_no_leidos = request.args.get("no_leidos") == "1"
        q = request.args.get("q") or None
        mensajes = correo.listar_mensajes(cuenta_id, solo_no_leidos=solo_no_leidos, texto=q)

    return render_template(
        "correo_bandeja.html",
        cuentas=cuentas_disponibles,
        cuenta_id=cuenta_id,
        mensajes=mensajes,
        q=request.args.get("q", ""),
        solo_no_leidos=request.args.get("no_leidos") == "1",
        error=error,
    )


@correo_bp.route("/sincronizar", methods=["POST"])
def sincronizar():
    cuenta_id = request.form.get("cuenta_id", type=int)
    error = None
    try:
        correo.sincronizar_bandeja(cuenta_id)
    except correo.ErrorCorreo as e:
        error = str(e)
    if error:
        mensajes = correo.listar_mensajes(cuenta_id) if cuenta_id else []
        return render_template(
            "correo_bandeja.html", cuentas=db.listar_cuentas_correo(), cuenta_id=cuenta_id,
            mensajes=mensajes, q="", solo_no_leidos=False, error=error,
        )
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id))


@correo_bp.route("/<int:mensaje_id>")
def ver_mensaje(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    if not mensaje["leido"]:
        correo.marcar_leido(mensaje_id, True)
        mensaje = correo.obtener_mensaje(mensaje_id)
    return render_template("correo_mensaje.html", mensaje=mensaje)


@correo_bp.route("/redactar")
def redactar():
    cuenta_id = request.args.get("cuenta_id", type=int)
    if cuenta_id is None:
        cuentas_con_smtp = [c for c in db.listar_cuentas_correo() if c["smtp_host"]]
        cuenta_id = cuentas_con_smtp[0]["id"] if cuentas_con_smtp else None
    return _render_redactar(cuenta_id=cuenta_id)


@correo_bp.route("/<int:mensaje_id>/responder")
def responder(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("re:"):
        asunto = f"Re: {asunto}"
    citado = "\n".join(f"> {linea}" for linea in (mensaje["cuerpo_texto"] or "").splitlines())
    cuerpo = f"\n\n{mensaje['remitente']} escribió:\n{citado}" if citado else ""
    return _render_redactar(
        cuenta_id=mensaje["cuenta_id"], destinatarios=mensaje["remitente"] or "",
        asunto=asunto, cuerpo=cuerpo, en_respuesta_a=mensaje["message_id"],
    )


@correo_bp.route("/<int:mensaje_id>/reenviar")
def reenviar(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("fwd:"):
        asunto = f"Fwd: {asunto}"
    cuerpo = (
        f"\n\n---------- Mensaje reenviado ----------\n"
        f"De: {mensaje['remitente']}\nAsunto: {mensaje['asunto']}\n\n{mensaje['cuerpo_texto'] or ''}"
    )
    return _render_redactar(cuenta_id=mensaje["cuenta_id"], asunto=asunto, cuerpo=cuerpo)


@correo_bp.route("/enviar", methods=["POST"])
def enviar():
    cuenta_id = request.form.get("cuenta_id", type=int)
    destinatarios = request.form.get("destinatarios", "")
    asunto = request.form.get("asunto", "")
    cuerpo = request.form.get("cuerpo", "")
    en_respuesta_a = request.form.get("en_respuesta_a") or None
    try:
        correo.construir_y_enviar(cuenta_id, destinatarios, asunto, cuerpo, en_respuesta_a=en_respuesta_a)
    except correo.ErrorCorreo as e:
        return _render_redactar(
            cuenta_id=cuenta_id, destinatarios=destinatarios, asunto=asunto,
            cuerpo=cuerpo, en_respuesta_a=en_respuesta_a, error=str(e),
        )
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id))
