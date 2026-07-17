"""Rutas del cliente de correo (IMAP/POP3 de lectura, SMTP de envío), con una
vista de bandeja de 3 paneles al estilo New Outlook (rail de cuentas +
carpetas + lista de mensajes + panel de lectura, todo en la misma ruta
`/correo/`). Vive en su propio Blueprint, mismo patrón que app/rutas_tareas.py.
"""
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, g, jsonify, redirect, render_template, request, url_for

from . import correo, db
from .auth import login_required
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


@correo_bp.app_template_filter("tamano_legible")
def tamano_legible(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.0f} KB"
    return f"{bytes_ / (1024 * 1024):.1f} MB"


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


def _mensaje_de_usuario_o_404(mensaje_id: int):
    """Trae el mensaje y comprueba que cuelga de una cuenta del usuario
    actual — sin esto, cualquiera podría leer/mover/borrar un mensaje de
    otro usuario adivinando su id en la URL."""
    if not db.mensaje_correo_pertenece_a_usuario(g.usuario_id, mensaje_id):
        abort(404)
    return correo.obtener_mensaje(mensaje_id)


def _render_redactar(
    *, cuenta_id=None, destinatarios="", cc="", bcc="", asunto="", cuerpo_html="",
    en_respuesta_a="", error=None, titulo="Nuevo mensaje",
):
    cuentas_con_smtp = [c for c in db.listar_cuentas_correo(g.usuario_id) if c["smtp_host"]]
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
@login_required
def cuentas():
    return render_template("correo_cuentas.html", cuentas=db.listar_cuentas_correo(g.usuario_id), error=None)


@correo_bp.route("/cuentas", methods=["POST"])
@login_required
def crear_cuenta():
    try:
        correo.guardar_cuenta(
            g.usuario_id,
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
        return render_template("correo_cuentas.html", cuentas=db.listar_cuentas_correo(g.usuario_id), error=str(e))
    return redirect(url_for("correo.cuentas"))


@correo_bp.route("/cuentas/<int:cuenta_id>/eliminar", methods=["POST"])
@login_required
def eliminar_cuenta(cuenta_id: int):
    correo.eliminar_cuenta(g.usuario_id, cuenta_id)
    return redirect(url_for("correo.cuentas"))


@correo_bp.route("/cuentas/<int:cuenta_id>/probar", methods=["POST"])
@login_required
def probar_cuenta(cuenta_id: int):
    try:
        correo.probar_conexion(g.usuario_id, cuenta_id)
        error = None
    except correo.ErrorCorreo as e:
        error = str(e)
    return render_template("correo_cuentas.html", cuentas=db.listar_cuentas_correo(g.usuario_id), error=error)


def _contexto_bandeja(cuenta_id, carpeta, q, solo_no_leidos, error, incluir_pospuestos=False):
    cuentas_disponibles = db.listar_cuentas_correo(g.usuario_id)
    no_leidos_por_cuenta = {c["id"]: db.contar_no_leidos_correo(c["id"]) for c in cuentas_disponibles}
    carpetas = correo.listar_carpetas(g.usuario_id, cuenta_id) if cuenta_id is not None else []
    preferencias = db.obtener_preferencias_correo(g.usuario_id)

    mensajes = []
    if cuenta_id is not None:
        mensajes = correo.listar_mensajes(
            cuenta_id, carpeta=carpeta, solo_no_leidos=solo_no_leidos, texto=q,
            limite=preferencias["limite_mensajes"], incluir_pospuestos=incluir_pospuestos,
        )

    categorias = db.listar_categorias_correo(g.usuario_id)
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
        "incluir_pospuestos": incluir_pospuestos,
        "error": error,
    }


@correo_bp.route("/")
@login_required
def bandeja():
    cuenta_id = request.args.get("cuenta_id", type=int)
    cuentas_disponibles = db.listar_cuentas_correo(g.usuario_id)
    if cuenta_id is None and cuentas_disponibles:
        cuenta_id = cuentas_disponibles[0]["id"]
    carpeta = request.args.get("carpeta") or "INBOX"
    q = request.args.get("q") or None
    solo_no_leidos = request.args.get("no_leidos") == "1"
    incluir_pospuestos = request.args.get("pospuestos") == "1"

    if cuenta_id is not None and db.obtener_cuenta_correo(g.usuario_id, cuenta_id) is None:
        abort(404)

    contexto = _contexto_bandeja(cuenta_id, carpeta, q, solo_no_leidos, None, incluir_pospuestos)

    mensaje_seleccionado = None
    mensaje_id = request.args.get("mensaje_id", type=int)
    if cuenta_id is not None and mensaje_id is not None:
        mensaje_seleccionado = _mensaje_de_usuario_o_404(mensaje_id)
        preferencias = db.obtener_preferencias_correo(g.usuario_id)
        if (
            mensaje_seleccionado is not None and not mensaje_seleccionado["leido"]
            and preferencias["marcar_leido_automatico"]
        ):
            correo.marcar_leido(mensaje_id, True)
            mensaje_seleccionado = correo.obtener_mensaje(mensaje_id)
            contexto["no_leidos_por_cuenta"][cuenta_id] = db.contar_no_leidos_correo(cuenta_id)

    contexto["mensaje_seleccionado"] = mensaje_seleccionado
    contexto["adjuntos_mensaje"] = db.listar_adjuntos_correo(mensaje_id) if mensaje_seleccionado else []

    remitente_confiable = False
    cuerpo_html_mostrado = None
    imagenes_bloqueadas = False
    if mensaje_seleccionado is not None:
        direccion_remitente = correo.direccion_email(mensaje_seleccionado["remitente"])
        remitente_confiable = db.es_remitente_confiable(g.usuario_id, direccion_remitente)
        mostrar_imagenes = request.args.get("mostrar_imagenes") == "1"
        if remitente_confiable or mostrar_imagenes:
            cuerpo_html_mostrado = mensaje_seleccionado["cuerpo_html"]
        else:
            cuerpo_html_mostrado, imagenes_bloqueadas = correo.html_con_imagenes_bloqueadas(
                mensaje_seleccionado["cuerpo_html"]
            )
    contexto["remitente_confiable"] = remitente_confiable
    contexto["cuerpo_html_mostrado"] = cuerpo_html_mostrado
    contexto["imagenes_bloqueadas"] = imagenes_bloqueadas
    return render_template("correo_bandeja.html", **contexto)


@correo_bp.route("/sincronizar", methods=["POST"])
@login_required
def sincronizar():
    cuenta_id = request.form.get("cuenta_id", type=int)
    carpeta = request.form.get("carpeta") or "INBOX"
    error = None
    try:
        correo.sincronizar_bandeja(g.usuario_id, cuenta_id)
    except correo.ErrorCorreo as e:
        error = str(e)
    if error:
        contexto = _contexto_bandeja(cuenta_id, carpeta, None, False, error)
        contexto["mensaje_seleccionado"] = None
        return render_template("correo_bandeja.html", **contexto)
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id, carpeta=carpeta))


@correo_bp.route("/<int:mensaje_id>")
@login_required
def ver_mensaje(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"], mensaje_id=mensaje_id,
    ))


TIPOS_PREVISUALIZABLES = ("application/pdf",)


@correo_bp.route("/<int:mensaje_id>/adjunto/<int:adjunto_id>")
@login_required
def descargar_adjunto(mensaje_id: int, adjunto_id: int):
    if not db.adjunto_correo_pertenece_a_usuario(g.usuario_id, adjunto_id):
        abort(404)
    adjunto = db.obtener_adjunto_correo(adjunto_id)
    if adjunto is None or adjunto["mensaje_id"] != mensaje_id:
        abort(404)
    previsualizable = adjunto["tipo_mime"].startswith("image/") or adjunto["tipo_mime"] in TIPOS_PREVISUALIZABLES
    disposicion = "inline" if previsualizable else "attachment"
    return Response(
        adjunto["contenido"],
        mimetype=adjunto["tipo_mime"],
        headers={"Content-Disposition": f'{disposicion}; filename="{adjunto["nombre_archivo"]}"'},
    )


@correo_bp.route("/<int:mensaje_id>/confiar-remitente", methods=["POST"])
@login_required
def confiar_en_remitente_del_mensaje(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    direccion = correo.direccion_email(mensaje["remitente"])
    if direccion:
        correo.confiar_en_remitente(g.usuario_id, direccion)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"],
        mensaje_id=mensaje_id, mostrar_imagenes=1,
    ))


@correo_bp.route("/<int:mensaje_id>/eliminar", methods=["POST"])
@login_required
def eliminar_mensaje(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    cuenta_id, carpeta = mensaje["cuenta_id"], mensaje["carpeta"]
    correo.eliminar_mensaje(mensaje_id)
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id, carpeta=carpeta))


@correo_bp.route("/<int:mensaje_id>/alternar-leido", methods=["POST"])
@login_required
def alternar_leido(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    correo.marcar_leido(mensaje_id, not mensaje["leido"])
    return redirect(url_for("correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"]))


@correo_bp.route("/<int:mensaje_id>/categoria", methods=["POST"])
@login_required
def asignar_categoria(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    categoria_id = request.form.get("categoria_id", type=int)
    correo.asignar_categoria(mensaje_id, categoria_id)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"], mensaje_id=mensaje_id,
    ))


@correo_bp.route("/<int:mensaje_id>/mover", methods=["POST"])
@login_required
def mover_mensaje(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    cuenta_id = mensaje["cuenta_id"]
    carpeta_origen = mensaje["carpeta"]
    carpeta_destino = request.form.get("carpeta_destino", "")
    error = None
    try:
        correo.mover_mensaje(g.usuario_id, mensaje_id, carpeta_destino)
    except correo.ErrorCorreo as e:
        error = str(e)
    if error:
        contexto = _contexto_bandeja(cuenta_id, carpeta_origen, None, False, error)
        contexto["mensaje_seleccionado"] = correo.obtener_mensaje(mensaje_id)
        return render_template("correo_bandeja.html", **contexto)
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id, carpeta=carpeta_origen))


@correo_bp.route("/<int:mensaje_id>/destacar", methods=["POST"])
@login_required
def destacar_mensaje(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    destacado = request.form.get("destacado") == "on"
    fecha_aviso = request.form.get("fecha_aviso") or None
    correo.destacar_mensaje(mensaje_id, destacado, fecha_aviso)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"], mensaje_id=mensaje_id,
    ))


@correo_bp.route("/<int:mensaje_id>/posponer", methods=["POST"])
@login_required
def posponer_mensaje(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    hasta = request.form.get("hasta") or None
    correo.posponer_mensaje(mensaje_id, hasta)
    # Al posponer, el mensaje se oculta de la lista por defecto — no tiene
    # sentido dejarlo seleccionado en el panel de lectura.
    return redirect(url_for("correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"]))


@correo_bp.route("/redactar")
@login_required
def redactar():
    cuenta_id = request.args.get("cuenta_id", type=int)
    if cuenta_id is None:
        cuentas_con_smtp = [c for c in db.listar_cuentas_correo(g.usuario_id) if c["smtp_host"]]
        cuenta_id = cuentas_con_smtp[0]["id"] if cuentas_con_smtp else None
    cuerpo_html = correo.preparar_cuerpo_inicial(g.usuario_id, cuenta_id, es_respuesta=False) if cuenta_id else ""
    return _render_redactar(cuenta_id=cuenta_id, cuerpo_html=cuerpo_html)


@correo_bp.route("/<int:mensaje_id>/responder")
@login_required
def responder(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("re:"):
        asunto = f"Re: {asunto}"
    original_html = mensaje["cuerpo_html"] or correo.texto_a_html(mensaje["cuerpo_texto"] or "")
    cita = (
        f"<p>{correo.texto_a_html(mensaje['remitente'] or '')} escribió:</p>"
        f'<blockquote style="border-left:2px solid #ccc;margin:0 0 0 8px;padding-left:12px;color:#555;">{original_html}</blockquote>'
    )
    cuerpo_html = correo.preparar_cuerpo_inicial(g.usuario_id, mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=cita)
    return _render_redactar(
        cuenta_id=mensaje["cuenta_id"], destinatarios=mensaje["remitente"] or "",
        asunto=asunto, cuerpo_html=cuerpo_html, en_respuesta_a=mensaje["message_id"], titulo="Responder",
    )


@correo_bp.route("/<int:mensaje_id>/responder-a-todos")
@login_required
def responder_a_todos(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    cuenta = db.obtener_cuenta_correo(g.usuario_id, mensaje["cuenta_id"])
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("re:"):
        asunto = f"Re: {asunto}"
    original_html = mensaje["cuerpo_html"] or correo.texto_a_html(mensaje["cuerpo_texto"] or "")
    cita = (
        f"<p>{correo.texto_a_html(mensaje['remitente'] or '')} escribió:</p>"
        f'<blockquote style="border-left:2px solid #ccc;margin:0 0 0 8px;padding-left:12px;color:#555;">{original_html}</blockquote>'
    )
    cuerpo_html = correo.preparar_cuerpo_inicial(g.usuario_id, mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=cita)
    destinatarios = correo.destinatarios_responder_a_todos(mensaje, cuenta["usuario"] if cuenta else None)
    return _render_redactar(
        cuenta_id=mensaje["cuenta_id"], destinatarios=destinatarios,
        asunto=asunto, cuerpo_html=cuerpo_html, en_respuesta_a=mensaje["message_id"], titulo="Responder a todos",
    )


@correo_bp.route("/<int:mensaje_id>/reenviar")
@login_required
def reenviar(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
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
    cuerpo_html = correo.preparar_cuerpo_inicial(g.usuario_id, mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=cita)
    return _render_redactar(cuenta_id=mensaje["cuenta_id"], asunto=asunto, cuerpo_html=cuerpo_html, titulo="Reenviar")


@correo_bp.route("/enviar", methods=["POST"])
@login_required
def enviar():
    cuenta_id = request.form.get("cuenta_id", type=int)
    destinatarios = request.form.get("destinatarios", "")
    cc = request.form.get("cc", "")
    bcc = request.form.get("bcc", "")
    asunto = request.form.get("asunto", "")
    cuerpo_html = request.form.get("cuerpo_html", "")
    en_respuesta_a = request.form.get("en_respuesta_a") or None
    adjuntos = [
        {"nombre": f.filename, "tipo": f.mimetype or "application/octet-stream", "bytes": f.read()}
        for f in request.files.getlist("adjuntos") if f.filename
    ]
    try:
        correo.construir_y_enviar(
            g.usuario_id,
            cuenta_id, destinatarios, asunto, cuerpo_html, cc=cc, bcc=bcc,
            en_respuesta_a=en_respuesta_a, adjuntos=adjuntos,
        )
    except correo.ErrorCorreo as e:
        return _render_redactar(
            cuenta_id=cuenta_id, destinatarios=destinatarios, cc=cc, bcc=bcc, asunto=asunto,
            cuerpo_html=cuerpo_html, en_respuesta_a=en_respuesta_a, error=str(e),
        )
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id))


# --- Ajustes: preferencias, categorías y firma --------------------------------

def _render_ajustes(*, error=None, cuenta_firma_id=None):
    cuentas = db.listar_cuentas_correo(g.usuario_id)
    if cuenta_firma_id is None and cuentas:
        cuenta_firma_id = cuentas[0]["id"]
    cuenta_firma = db.obtener_cuenta_correo(g.usuario_id, cuenta_firma_id) if cuenta_firma_id else None
    return render_template(
        "correo_ajustes.html",
        preferencias=db.obtener_preferencias_correo(g.usuario_id),
        categorias=db.listar_categorias_correo(g.usuario_id),
        cuentas=cuentas,
        cuenta_firma_id=cuenta_firma_id,
        cuenta_firma=cuenta_firma,
        remitentes_confiables=db.listar_remitentes_confiables(g.usuario_id),
        reglas_categoria=db.listar_reglas_categoria_correo(g.usuario_id),
        error=error,
    )


@correo_bp.route("/ajustes")
@login_required
def ajustes():
    cuenta_firma_id = request.args.get("cuenta_firma_id", type=int)
    return _render_ajustes(cuenta_firma_id=cuenta_firma_id)


@correo_bp.route("/ajustes/preferencias", methods=["POST"])
@login_required
def guardar_preferencias():
    try:
        limite = int(request.form.get("limite_mensajes") or 50)
    except ValueError:
        limite = 50
    db.guardar_preferencias_correo(
        g.usuario_id,
        densidad=request.form.get("densidad", "normal"),
        marcar_leido_automatico=request.form.get("marcar_leido_automatico") == "on",
        limite_mensajes=max(10, min(limite, 500)),
    )
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/categorias", methods=["POST"])
@login_required
def crear_categoria():
    try:
        correo.crear_categoria(g.usuario_id, request.form.get("nombre", ""), request.form.get("color", "#7c8ba1"))
    except correo.ErrorCorreo as e:
        return _render_ajustes(error=str(e))
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/categorias/<int:categoria_id>/eliminar", methods=["POST"])
@login_required
def eliminar_categoria(categoria_id: int):
    correo.eliminar_categoria(g.usuario_id, categoria_id)
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/remitentes-confiables", methods=["POST"])
@login_required
def crear_remitente_confiable():
    try:
        correo.confiar_en_remitente(g.usuario_id, request.form.get("direccion", ""))
    except correo.ErrorCorreo as e:
        return _render_ajustes(error=str(e))
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/remitentes-confiables/<int:remitente_id>/eliminar", methods=["POST"])
@login_required
def eliminar_remitente_confiable(remitente_id: int):
    correo.eliminar_remitente_confiable(g.usuario_id, remitente_id)
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/reglas", methods=["POST"])
@login_required
def crear_regla_categoria():
    try:
        correo.crear_regla_categoria(
            g.usuario_id,
            request.form.get("remitente_patron", ""),
            request.form.get("categoria_id", type=int),
        )
    except correo.ErrorCorreo as e:
        return _render_ajustes(error=str(e))
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/reglas/<int:regla_id>/eliminar", methods=["POST"])
@login_required
def eliminar_regla_categoria(regla_id: int):
    correo.eliminar_regla_categoria(g.usuario_id, regla_id)
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/destinatarios-recientes")
@login_required
def destinatarios_recientes():
    q = request.args.get("q", "")
    filas = db.buscar_destinatarios_recientes(g.usuario_id, q)
    return jsonify([dict(f) for f in filas])


@correo_bp.route("/ajustes/firma", methods=["POST"])
@login_required
def guardar_firma():
    cuenta_id = request.form.get("cuenta_id", type=int)
    correo.guardar_firma(
        g.usuario_id,
        cuenta_id,
        request.form.get("firma_html", ""),
        en_nuevos=request.form.get("firma_en_nuevos") == "on",
        en_respuestas=request.form.get("firma_en_respuestas") == "on",
    )
    return redirect(url_for("correo.ajustes", cuenta_firma_id=cuenta_id))


# --- Acciones en lote (selección múltiple, llamadas por fetch desde
# app/static/correo_seleccion.js — no son formularios, así que no
# redirigen: solo recorren los ids llamando a la función individual ya
# existente en app/correo.py, sin lógica de negocio nueva) --------------------

def _ids_del_body() -> list[int]:
    datos = request.get_json(silent=True) or {}
    return [int(i) for i in datos.get("ids", []) if str(i).isdigit()]


def _ids_propios_del_usuario(ids: list[int]) -> list[int]:
    """Filtra los ids que de verdad pertenecen al usuario actual, para que
    una acción en lote no pueda tocar mensajes de otro usuario coleados en
    el body de la petición."""
    return [i for i in ids if db.mensaje_correo_pertenece_a_usuario(g.usuario_id, i)]


@correo_bp.route("/mensajes/eliminar", methods=["POST"])
@login_required
def eliminar_mensajes_lote():
    ids = _ids_propios_del_usuario(_ids_del_body())
    for mensaje_id in ids:
        correo.eliminar_mensaje(mensaje_id)
    return {"procesados": len(ids)}


@correo_bp.route("/mensajes/marcar-leido", methods=["POST"])
@login_required
def marcar_leido_mensajes_lote():
    datos = request.get_json(silent=True) or {}
    leido = bool(datos.get("leido", True))
    ids = _ids_propios_del_usuario(_ids_del_body())
    for mensaje_id in ids:
        correo.marcar_leido(mensaje_id, leido)
    return {"procesados": len(ids)}


@correo_bp.route("/mensajes/destacar", methods=["POST"])
@login_required
def destacar_mensajes_lote():
    datos = request.get_json(silent=True) or {}
    destacado = bool(datos.get("destacado", True))
    ids = _ids_propios_del_usuario(_ids_del_body())
    for mensaje_id in ids:
        correo.destacar_mensaje(mensaje_id, destacado)
    return {"procesados": len(ids)}


@correo_bp.route("/mensajes/mover", methods=["POST"])
@login_required
def mover_mensajes_lote():
    datos = request.get_json(silent=True) or {}
    carpeta_destino = datos.get("carpeta", "")
    ids = _ids_propios_del_usuario(_ids_del_body())
    errores = []
    for mensaje_id in ids:
        try:
            correo.mover_mensaje(g.usuario_id, mensaje_id, carpeta_destino)
        except correo.ErrorCorreo as e:
            errores.append(str(e))
    return {"procesados": len(ids) - len(errores), "errores": errores}
