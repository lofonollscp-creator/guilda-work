"""Rutas del cliente de correo (IMAP/POP3 de lectura, SMTP de envío), con una
vista de bandeja de 3 paneles al estilo New Outlook (rail de cuentas +
carpetas + lista de mensajes + panel de lectura, todo en la misma ruta
`/correo/`). Vive en su propio Blueprint, mismo patrón que app/rutas_tareas.py.
"""
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, redirect, render_template, request, url_for

from . import correo, db
from .rutas_tareas import color_categoria

correo_bp = Blueprint("correo", __name__, url_prefix="/correo")

MESES_ABREV = ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
DIAS_ABREV = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


@correo_bp.app_template_filter("avatar_color")
def avatar_color(texto: str | None) -> str:
    """Color estable por remitente (mismo hash que color_categoria de Tareas)."""
    return color_categoria(texto)


@correo_bp.app_template_filter("iniciales")
def iniciales(remitente: str | None) -> str:
    """1-2 letras para el avatar: del nombre si hay "Nombre <email>", si no del email."""
    if not remitente:
        return "?"
    remitente = remitente.strip()
    nombre = remitente.split("<")[0].strip().strip('"') if "<" in remitente else remitente.split("@")[0]
    palabras = [p for p in re.split(r"[\s._-]+", nombre) if p]
    if not palabras:
        return "?"
    if len(palabras) == 1:
        return palabras[0][:2].upper()
    return (palabras[0][0] + palabras[1][0]).upper()


@correo_bp.app_template_filter("fecha_relativa")
def fecha_relativa(valor: str | None) -> str:
    """"10:32" si es hoy, "Ayer", abreviatura de día si es esta semana, o "13 jul"."""
    if not valor:
        return ""
    try:
        dt = datetime.fromisoformat(valor)
    except ValueError:
        return valor[:16].replace("T", " ")
    hoy = date.today()
    d = dt.date()
    if d == hoy:
        return dt.strftime("%H:%M")
    if d == hoy - timedelta(days=1):
        return "Ayer"
    if (hoy - d).days < 7:
        return DIAS_ABREV[d.weekday()]
    return f"{d.day} {MESES_ABREV[d.month]}"


@correo_bp.app_template_filter("vista_previa")
def vista_previa(mensaje, longitud: int = 100) -> str:
    """Fragmento de texto plano del cuerpo, para la línea de previsualización en la lista."""
    texto = mensaje["cuerpo_texto"]
    if not texto and mensaje["cuerpo_html"]:
        texto = correo.html_a_texto_plano(mensaje["cuerpo_html"])
    if not texto:
        return ""
    return " ".join(texto.split())[:longitud]


def _render_redactar(
    *, cuenta_id=None, destinatarios="", cc="", bcc="", asunto="", cuerpo_html="",
    en_respuesta_a="", error=None, titulo="Nuevo mensaje",
):
    cuentas_con_smtp = [c for c in db.listar_cuentas_correo() if c["smtp_host"]]
    return render_template(
        "correo_redactar.html",
        cuentas=cuentas_con_smtp,
        cuenta_id=cuenta_id,
        destinatarios=destinatarios,
        cc=cc,
        bcc=bcc,
        asunto=asunto,
        cuerpo_html=cuerpo_html,
        en_respuesta_a=en_respuesta_a or "",
        error=error,
        titulo=titulo,
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


def _contexto_bandeja(cuenta_id, carpeta, q, solo_no_leidos, error):
    cuentas_disponibles = db.listar_cuentas_correo()
    no_leidos_por_cuenta = {c["id"]: db.contar_no_leidos_correo(c["id"]) for c in cuentas_disponibles}
    carpetas = correo.listar_carpetas(cuenta_id) if cuenta_id is not None else []
    preferencias = db.obtener_preferencias_correo()

    mensajes = []
    if cuenta_id is not None:
        mensajes = correo.listar_mensajes(
            cuenta_id, carpeta=carpeta, solo_no_leidos=solo_no_leidos, texto=q,
            limite=preferencias["limite_mensajes"],
        )

    categorias = db.listar_categorias_correo()
    return {
        "cuentas": cuentas_disponibles,
        "cuenta_id": cuenta_id,
        "carpeta": carpeta,
        "carpetas": carpetas,
        "mensajes": mensajes,
        "no_leidos_por_cuenta": no_leidos_por_cuenta,
        "categorias": categorias,
        "categorias_por_id": {c["id"]: c for c in categorias},
        "densidad": preferencias["densidad"],
        "q": q or "",
        "solo_no_leidos": solo_no_leidos,
        "error": error,
    }


@correo_bp.route("/")
def bandeja():
    cuenta_id = request.args.get("cuenta_id", type=int)
    cuentas_disponibles = db.listar_cuentas_correo()
    if cuenta_id is None and cuentas_disponibles:
        cuenta_id = cuentas_disponibles[0]["id"]
    carpeta = request.args.get("carpeta") or "INBOX"
    q = request.args.get("q") or None
    solo_no_leidos = request.args.get("no_leidos") == "1"

    if cuenta_id is not None and db.obtener_cuenta_correo(cuenta_id) is None:
        abort(404)

    contexto = _contexto_bandeja(cuenta_id, carpeta, q, solo_no_leidos, None)

    mensaje_seleccionado = None
    mensaje_id = request.args.get("mensaje_id", type=int)
    if cuenta_id is not None and mensaje_id is not None:
        mensaje_seleccionado = correo.obtener_mensaje(mensaje_id)
        preferencias = db.obtener_preferencias_correo()
        if (
            mensaje_seleccionado is not None and not mensaje_seleccionado["leido"]
            and preferencias["marcar_leido_automatico"]
        ):
            correo.marcar_leido(mensaje_id, True)
            mensaje_seleccionado = correo.obtener_mensaje(mensaje_id)
            contexto["no_leidos_por_cuenta"][cuenta_id] = db.contar_no_leidos_correo(cuenta_id)

    contexto["mensaje_seleccionado"] = mensaje_seleccionado
    return render_template("correo_bandeja.html", **contexto)


@correo_bp.route("/sincronizar", methods=["POST"])
def sincronizar():
    cuenta_id = request.form.get("cuenta_id", type=int)
    carpeta = request.form.get("carpeta") or "INBOX"
    error = None
    try:
        correo.sincronizar_bandeja(cuenta_id)
    except correo.ErrorCorreo as e:
        error = str(e)
    if error:
        contexto = _contexto_bandeja(cuenta_id, carpeta, None, False, error)
        contexto["mensaje_seleccionado"] = None
        return render_template("correo_bandeja.html", **contexto)
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id, carpeta=carpeta))


@correo_bp.route("/<int:mensaje_id>")
def ver_mensaje(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"], mensaje_id=mensaje_id,
    ))


@correo_bp.route("/<int:mensaje_id>/eliminar", methods=["POST"])
def eliminar_mensaje(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    cuenta_id, carpeta = mensaje["cuenta_id"], mensaje["carpeta"]
    correo.eliminar_mensaje(mensaje_id)
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id, carpeta=carpeta))


@correo_bp.route("/<int:mensaje_id>/alternar-leido", methods=["POST"])
def alternar_leido(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    correo.marcar_leido(mensaje_id, not mensaje["leido"])
    return redirect(url_for("correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"]))


@correo_bp.route("/<int:mensaje_id>/categoria", methods=["POST"])
def asignar_categoria(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    categoria_id = request.form.get("categoria_id", type=int)
    correo.asignar_categoria(mensaje_id, categoria_id)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"], mensaje_id=mensaje_id,
    ))


@correo_bp.route("/redactar")
def redactar():
    cuenta_id = request.args.get("cuenta_id", type=int)
    if cuenta_id is None:
        cuentas_con_smtp = [c for c in db.listar_cuentas_correo() if c["smtp_host"]]
        cuenta_id = cuentas_con_smtp[0]["id"] if cuentas_con_smtp else None
    cuerpo_html = correo.preparar_cuerpo_inicial(cuenta_id, es_respuesta=False) if cuenta_id else ""
    return _render_redactar(cuenta_id=cuenta_id, cuerpo_html=cuerpo_html)


@correo_bp.route("/<int:mensaje_id>/responder")
def responder(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("re:"):
        asunto = f"Re: {asunto}"
    original_html = mensaje["cuerpo_html"] or correo.texto_a_html(mensaje["cuerpo_texto"] or "")
    cita = (
        f"<p>{correo.texto_a_html(mensaje['remitente'] or '')} escribió:</p>"
        f'<blockquote style="border-left:2px solid #ccc;margin:0 0 0 8px;padding-left:12px;color:#555;">{original_html}</blockquote>'
    )
    cuerpo_html = correo.preparar_cuerpo_inicial(mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=cita)
    return _render_redactar(
        cuenta_id=mensaje["cuenta_id"], destinatarios=mensaje["remitente"] or "",
        asunto=asunto, cuerpo_html=cuerpo_html, en_respuesta_a=mensaje["message_id"], titulo="Responder",
    )


@correo_bp.route("/<int:mensaje_id>/reenviar")
def reenviar(mensaje_id: int):
    mensaje = correo.obtener_mensaje(mensaje_id)
    if mensaje is None:
        abort(404)
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("fwd:"):
        asunto = f"Fwd: {asunto}"
    original_html = mensaje["cuerpo_html"] or correo.texto_a_html(mensaje["cuerpo_texto"] or "")
    cita = (
        "<p>---------- Mensaje reenviado ----------</p>"
        f"<p>De: {correo.texto_a_html(mensaje['remitente'] or '')}<br>"
        f"Asunto: {correo.texto_a_html(mensaje['asunto'] or '')}</p>"
        f"<blockquote style=\"border-left:2px solid #ccc;margin:0 0 0 8px;padding-left:12px;color:#555;\">{original_html}</blockquote>"
    )
    cuerpo_html = correo.preparar_cuerpo_inicial(mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=cita)
    return _render_redactar(cuenta_id=mensaje["cuenta_id"], asunto=asunto, cuerpo_html=cuerpo_html, titulo="Reenviar")


@correo_bp.route("/enviar", methods=["POST"])
def enviar():
    cuenta_id = request.form.get("cuenta_id", type=int)
    destinatarios = request.form.get("destinatarios", "")
    cc = request.form.get("cc", "")
    bcc = request.form.get("bcc", "")
    asunto = request.form.get("asunto", "")
    cuerpo_html = request.form.get("cuerpo_html", "")
    en_respuesta_a = request.form.get("en_respuesta_a") or None
    try:
        correo.construir_y_enviar(cuenta_id, destinatarios, asunto, cuerpo_html, cc=cc, bcc=bcc, en_respuesta_a=en_respuesta_a)
    except correo.ErrorCorreo as e:
        return _render_redactar(
            cuenta_id=cuenta_id, destinatarios=destinatarios, cc=cc, bcc=bcc, asunto=asunto,
            cuerpo_html=cuerpo_html, en_respuesta_a=en_respuesta_a, error=str(e),
        )
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id))


# --- Ajustes: preferencias, categorías y firma --------------------------------

def _render_ajustes(*, error=None, cuenta_firma_id=None):
    cuentas = db.listar_cuentas_correo()
    if cuenta_firma_id is None and cuentas:
        cuenta_firma_id = cuentas[0]["id"]
    cuenta_firma = db.obtener_cuenta_correo(cuenta_firma_id) if cuenta_firma_id else None
    return render_template(
        "correo_ajustes.html",
        preferencias=db.obtener_preferencias_correo(),
        categorias=db.listar_categorias_correo(),
        cuentas=cuentas,
        cuenta_firma_id=cuenta_firma_id,
        cuenta_firma=cuenta_firma,
        error=error,
    )


@correo_bp.route("/ajustes")
def ajustes():
    cuenta_firma_id = request.args.get("cuenta_firma_id", type=int)
    return _render_ajustes(cuenta_firma_id=cuenta_firma_id)


@correo_bp.route("/ajustes/preferencias", methods=["POST"])
def guardar_preferencias():
    try:
        limite = int(request.form.get("limite_mensajes") or 50)
    except ValueError:
        limite = 50
    db.guardar_preferencias_correo(
        densidad=request.form.get("densidad", "normal"),
        marcar_leido_automatico=request.form.get("marcar_leido_automatico") == "on",
        limite_mensajes=max(10, min(limite, 500)),
    )
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/categorias", methods=["POST"])
def crear_categoria():
    try:
        correo.crear_categoria(request.form.get("nombre", ""), request.form.get("color", "#7c8ba1"))
    except correo.ErrorCorreo as e:
        return _render_ajustes(error=str(e))
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/categorias/<int:categoria_id>/eliminar", methods=["POST"])
def eliminar_categoria(categoria_id: int):
    correo.eliminar_categoria(categoria_id)
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/firma", methods=["POST"])
def guardar_firma():
    cuenta_id = request.form.get("cuenta_id", type=int)
    correo.guardar_firma(
        cuenta_id,
        request.form.get("firma_html", ""),
        en_nuevos=request.form.get("firma_en_nuevos") == "on",
        en_respuestas=request.form.get("firma_en_respuestas") == "on",
    )
    return redirect(url_for("correo.ajustes", cuenta_firma_id=cuenta_id))
