"""Rutas del cliente de correo (IMAP/POP3 de lectura, SMTP de envío), con una
vista de bandeja de 3 paneles al estilo New Outlook (rail de cuentas +
carpetas + lista de mensajes + panel de lectura, todo en la misma ruta
`/correo/`). Vive en su propio Blueprint, mismo patrón que app/rutas_tareas.py.
"""
import threading
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, g, jsonify, redirect, render_template, request, url_for
from flask_babel import get_locale
from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l

from . import correo, correo_ia, db, ia_asistente, notificaciones, peticion
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


def _cliente_del_mensaje_respondido(mensaje_id) -> int | None:
    """Cliente fiscal enlazado al mensaje que se responde (si es del usuario)."""
    try:
        mensaje_id = int(mensaje_id)
    except (TypeError, ValueError):
        return None
    if not db.mensaje_correo_pertenece_a_usuario(g.usuario_id, mensaje_id):
        return None
    mensaje = correo.obtener_mensaje(mensaje_id)
    return mensaje["cliente_fiscal_id"] if mensaje is not None else None


def _render_redactar(
    *, cuenta_id=None, destinatarios="", cc="", bcc="", asunto="", cuerpo_html="",
    en_respuesta_a="", error=None, titulo=_l("Nuevo mensaje"), borrador_id=None,
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
        plantillas=db.listar_plantillas_correo(g.usuario_id),
        clientes_fiscales=db.listar_clientes_fiscales(g.tenant_id) if g.tenant_id is not None else [],
        cliente_plantilla_id=_cliente_del_mensaje_respondido(en_respuesta_a),
        borrador_id=borrador_id,
        adjuntos_borrador=db.listar_adjuntos_borrador(g.usuario_id, borrador_id) if borrador_id else [],
        deshacer_segundos=db.obtener_preferencias_correo(g.usuario_id)["deshacer_segundos"],
    )


@correo_bp.route("/cuentas")
@login_required
def cuentas():
    return render_template(
        "correo_cuentas.html", cuentas=db.listar_cuentas_correo(g.usuario_id), error=None,
        operaciones_error=db.operaciones_correo_con_error(g.usuario_id),
    )


def _ids_de_operaciones():
    """None = todas; si no, los ids marcados (solo enteros)."""
    if request.form.get("todas") == "1":
        return None
    return [int(i) for i in request.form.getlist("id") if i.isdigit()]


@correo_bp.route("/cuentas/operaciones/reintentar", methods=["POST"])
@login_required
def reintentar_operaciones():
    for cuenta_id in db.reintentar_operaciones_correo(g.usuario_id, _ids_de_operaciones()):
        threading.Thread(target=correo.procesar_operaciones_cuenta, args=(cuenta_id, 0), daemon=True).start()
    return redirect(url_for("correo.cuentas"))


@correo_bp.route("/cuentas/operaciones/descartar", methods=["POST"])
@login_required
def descartar_operaciones():
    db.descartar_operaciones_correo(g.usuario_id, _ids_de_operaciones())
    return redirect(url_for("correo.cuentas"))


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


@correo_bp.route("/cuentas/<int:cuenta_id>/editar", methods=["POST"])
@login_required
def editar_cuenta(cuenta_id: int):
    try:
        correo.editar_cuenta(
            g.usuario_id, cuenta_id,
            nombre=request.form.get("nombre", ""),
            protocolo=request.form.get("protocolo", "imap"),
            host=request.form.get("host", ""),
            puerto=int(request.form.get("puerto") or 993),
            usuario=request.form.get("usuario", ""),
            usa_tls=request.form.get("usa_tls") == "on",
            smtp_host=request.form.get("smtp_host") or None,
            smtp_puerto=int(request.form["smtp_puerto"]) if request.form.get("smtp_puerto") else None,
            smtp_tls=request.form.get("smtp_tls") == "on",
            # Contraseña opcional: vacía = mantener la ya guardada (ver
            # correo.editar_cuenta) -- no se obliga a volver a teclearla
            # solo para corregir un host/puerto.
            contrasena=request.form.get("contrasena", "") or None,
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


def _filtros_de_la_peticion() -> dict:
    """Filtros avanzados de la bandeja leídos de la URL (solo los activos)."""
    filtros = {}
    if request.args.get("adjuntos") == "1":
        filtros["con_adjuntos"] = True
    if request.args.get("destacados") == "1":
        filtros["solo_destacados"] = True
    for clave, destino in (("categoria", "categoria_id"), ("cliente", "cliente_fiscal_id")):
        valor = request.args.get(clave, type=int)
        if valor is not None:
            filtros[destino] = valor
    for clave in ("desde", "hasta"):
        valor = (request.args.get(clave) or "").strip()
        try:
            datetime.strptime(valor, "%Y-%m-%d")
        except ValueError:
            continue
        filtros[clave] = valor
    return filtros


def _filtros_para_url(filtros: dict) -> dict:
    """Los mismos filtros con los nombres de parámetro de la URL, para
    propagarlos en los enlaces de la lista (`url_for(..., **filtros_url)`)."""
    return {
        "adjuntos": 1 if filtros.get("con_adjuntos") else None,
        "destacados": 1 if filtros.get("solo_destacados") else None,
        "categoria": filtros.get("categoria_id"), "cliente": filtros.get("cliente_fiscal_id"),
        "desde": filtros.get("desde"), "hasta": filtros.get("hasta"),
    }


def _contexto_bandeja(cuenta_id, carpeta, q, solo_no_leidos, error, incluir_pospuestos=False, filtros=None):
    filtros = filtros or {}
    cuentas_disponibles = db.listar_cuentas_correo(g.usuario_id)
    # Una sola consulta agregada (antes: una llamada a
    # contar_no_leidos_correo por cada cuenta, N+1, y solo contaba
    # INBOX -- el badge de la cuenta no reflejaba su total real).
    # Misma consulta que el badge del rail: una sola por petición.
    no_leidos_por_cuenta_y_carpeta = peticion.memo("no_leidos", lambda: db.contar_no_leidos_por_cuenta_y_carpeta(g.usuario_id))
    no_leidos_por_cuenta = {
        c["id"]: sum(no_leidos_por_cuenta_y_carpeta.get(c["id"], {}).values()) for c in cuentas_disponibles
    }
    no_leidos_carpetas = no_leidos_por_cuenta_y_carpeta.get(cuenta_id, {}) if cuenta_id is not None else {}
    carpetas = correo.listar_carpetas(g.usuario_id, cuenta_id) if cuenta_id is not None else []
    preferencias = db.obtener_preferencias_correo(g.usuario_id)

    mensajes = []
    consulta = correo.consulta_de_busqueda(g.usuario_id, g.tenant_id, q)
    if cuenta_id is not None:
        # Los operadores de la caja («de:ana adjunto:») se suman a los filtros de la barra; si chocan, gana el operador.
        mensajes = correo.listar_mensajes(
            cuenta_id, carpeta=carpeta, solo_no_leidos=solo_no_leidos or consulta.solo_no_leidos, texto=consulta.texto or None,
            limite=preferencias["limite_mensajes"], incluir_pospuestos=incluir_pospuestos, **{**filtros, **consulta.filtros},
        )

    # Conversaciones: un solo mensaje por hilo (el más reciente) con el nº de
    # mensajes del hilo; el resto se ve al abrirlo.
    hilo_total: dict[str, int] = {}
    if mensajes:
        hilo_total = db.contar_hilos_correo(cuenta_id, [m["hilo_clave"] for m in mensajes])
        vistos = set()
        unicos = []
        for m in mensajes:
            clave = m["hilo_clave"]
            if clave is not None:
                if clave in vistos:
                    continue
                vistos.add(clave)
            unicos.append(m)
        mensajes = unicos

    categorias = db.listar_categorias_correo(g.usuario_id)
    # Vínculo con un cliente fiscal (opt-in, solo si el usuario pertenece
    # a un tenant con calendario fiscal -- mismo criterio que el resto de
    # integraciones opcionales de esta sección).
    clientes_fiscales = db.listar_clientes_fiscales(g.tenant_id) if g.tenant_id is not None else []
    return {
        "cuentas": cuentas_disponibles,
        "cuenta_id": cuenta_id,
        "carpeta": carpeta,
        "carpetas": carpetas,
        "mensajes": mensajes,
        "hilo_total": hilo_total,
        "no_leidos_por_cuenta": no_leidos_por_cuenta,
        "no_leidos_carpetas": no_leidos_carpetas,
        "categorias": categorias,
        "categorias_por_id": {c["id"]: c for c in categorias},
        "clientes_fiscales": clientes_fiscales,
        "num_borradores": db.contar_borradores_correo(g.usuario_id),
        "densidad": preferencias["densidad"],
        "q": q or "",
        "busqueda_sin_resolver": consulta.sin_resolver,
        "solo_no_leidos": solo_no_leidos,
        "incluir_pospuestos": incluir_pospuestos,
        "filtros": filtros,
        "filtros_url": _filtros_para_url(filtros),
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
    # Doble clic en un mensaje (ver correo_bandeja.html + static/correo.js)
    # entra en modo "pantalla completa": oculta el rail de cuentas y la
    # lista para leer el mensaje sin las columnas fijas de 220px+340px
    # (que en pantallas de portátil/tablet dejan poco sitio a la
    # lectura). No hay ruta aparte porque el panel de lectura ya vive
    # dentro de esta misma vista -- es solo una clase CSS de más.
    completa = request.args.get("completa") == "1"

    if cuenta_id is not None and db.obtener_cuenta_correo(g.usuario_id, cuenta_id) is None:
        abort(404)

    contexto = _contexto_bandeja(
        cuenta_id, carpeta, q, solo_no_leidos, None, incluir_pospuestos, _filtros_de_la_peticion(),
    )
    contexto["aviso"] = request.args.get("aviso") or None
    contexto["num_programados"] = db.contar_envios_programados(g.usuario_id)
    contexto["envio_banner"] = None
    envio_id = request.args.get("envio_id", type=int)
    if envio_id is not None:
        envio = db.obtener_envio_correo(g.usuario_id, envio_id)
        if envio is not None and envio["estado"] == "pendiente":
            restante = (datetime.fromisoformat(envio["enviar_en"]) - datetime.now()).total_seconds()
            contexto["envio_banner"] = {
                "id": envio["id"], "programado": bool(envio["programado"]),
                "enviar_en": envio["enviar_en"].replace("T", " ")[:16], "segundos": max(0, int(restante)),
            }
    contexto["completa"] = completa

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
    contexto["equipo_correo"] = db.estado_correo_equipo(mensaje_id) if mensaje_seleccionado is not None else None
    contexto["notas_internas"] = db.listar_notas_internas_correo(g.usuario_id, mensaje_id) if mensaje_seleccionado is not None else []
    contexto["companeros"] = db.listar_companeros_tenant(g.usuario_id) if mensaje_seleccionado is not None else []
    contexto["adjuntos_mensaje"] = db.listar_adjuntos_correo(mensaje_id) if mensaje_seleccionado else []
    # Para guardar un adjunto en un vencimiento del cliente enlazado al mensaje.
    contexto["vencimientos_cliente"] = (
        db.listar_vencimientos_fiscales(g.tenant_id, cliente_fiscal_id=mensaje_seleccionado["cliente_fiscal_id"])
        if mensaje_seleccionado is not None and mensaje_seleccionado["cliente_fiscal_id"] and g.tenant_id is not None else []
    )
    contexto["hilo_mensajes"] = (
        [h for h in db.mensajes_del_hilo_correo(cuenta_id, mensaje_seleccionado["hilo_clave"]) if h["id"] != mensaje_id]
        if mensaje_seleccionado is not None else []
    )

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


# ---- Correo de equipo: asignar / compartir mensajes y notas internas ----------
# No se comparten cuentas ni contraseñas: el dueño de un mensaje lo asigna o
# comparte con un compañero del despacho, que lo ve en solo lectura (texto, sin
# adjuntos ni HTML) y puede dejar notas internas. Nada de esto sale al remitente.

def _avisar_correo(origen_id: int, destino_id: int, mensaje_id: int, titulo: str, verbo: str) -> None:
    try:
        if destino_id == origen_id or not db.notificacion_tipo_activa(destino_id, "tarea_asignada"):
            return
        m = db.obtener_correo_equipo(destino_id, mensaje_id)
        if m is None:
            return
        quien = db.nombre_mostrado_usuario(origen_id) or db.obtener_usuario(origen_id)["email"]
        notificaciones.crear_y_enviar(
            destino_id, "tarea_asignada", titulo, f"{quien} {verbo}: {m['asunto'] or '(sin asunto)'}",
            url=url_for("correo.equipo_mensaje", mensaje_id=mensaje_id), datos={"tipo": "correo_equipo", "mensaje_id": mensaje_id},
        )
    except Exception:  # noqa: BLE001
        pass


@correo_bp.route("/equipo")
@login_required
def equipo():
    vista = request.args.get("vista", "asignados")
    if vista not in ("asignados", "compartidos", "enviados"):
        vista = "asignados"
    return render_template(
        "correo_equipo.html", vista=vista, mensajes=db.listar_correo_equipo(g.usuario_id, vista),
        abiertos=db.contar_correo_asignado_abierto(g.usuario_id),
    )


@correo_bp.route("/equipo/<int:mensaje_id>")
@login_required
def equipo_mensaje(mensaje_id: int):
    m = db.obtener_correo_equipo(g.usuario_id, mensaje_id)
    if m is None:
        abort(404)
    db.registrar_lectura_correo_equipo(g.usuario_id, mensaje_id)
    return render_template(
        "correo_equipo_mensaje.html", m=m, notas=db.listar_notas_internas_correo(g.usuario_id, mensaje_id),
        companeros=db.listar_companeros_tenant(g.usuario_id),
        historial=db.historial_correo_equipo(g.usuario_id, mensaje_id),
        max_compartidos=db.MAX_COMPARTIDOS_POR_MENSAJE,
    )


@correo_bp.route("/<int:mensaje_id>/equipo/asignar", methods=["POST"])
@login_required
def equipo_asignar(mensaje_id: int):
    try:
        destino = int(request.form.get("usuario_id") or 0) or None
    except ValueError:
        abort(404)
    if not db.asignar_correo(g.usuario_id, mensaje_id, destino):
        abort(404)
    if destino:
        _avisar_correo(g.usuario_id, destino, mensaje_id, "Correo asignado", "te ha asignado un correo")
    return redirect(request.referrer or url_for("correo.equipo", vista="enviados"))


@correo_bp.route("/<int:mensaje_id>/equipo/compartir", methods=["POST"])
@login_required
def equipo_compartir(mensaje_id: int):
    try:
        otro = int(request.form.get("usuario_id", ""))
    except ValueError:
        abort(404)
    if not db.compartir_correo(g.usuario_id, mensaje_id, otro):
        if db.rol_en_correo(g.usuario_id, mensaje_id) == "dueno" and len(db.estado_correo_equipo(mensaje_id)["compartidos"]) >= db.MAX_COMPARTIDOS_POR_MENSAJE:
            abort(400, description=_("Un correo se puede compartir con un máximo de %(n)s personas.", n=db.MAX_COMPARTIDOS_POR_MENSAJE))
        abort(404)
    _avisar_correo(g.usuario_id, otro, mensaje_id, "Correo compartido", "ha compartido contigo un correo")
    return redirect(request.referrer or url_for("correo.equipo", vista="enviados"))


@correo_bp.route("/<int:mensaje_id>/equipo/quitar", methods=["POST"])
@login_required
def equipo_quitar(mensaje_id: int):
    try:
        otro = int(request.form.get("usuario_id", ""))
    except ValueError:
        abort(404)
    if not db.dejar_de_compartir_correo(g.usuario_id, mensaje_id, otro):
        abort(404)
    if otro == g.usuario_id and db.rol_en_correo(g.usuario_id, mensaje_id) is None:
        return redirect(url_for("correo.equipo", vista="compartidos"))
    return redirect(request.referrer or url_for("correo.equipo", vista="enviados"))


@correo_bp.route("/equipo/<int:mensaje_id>/estado", methods=["POST"])
@login_required
def equipo_estado(mensaje_id: int):
    if not db.cambiar_estado_correo_equipo(g.usuario_id, mensaje_id, request.form.get("estado", "")):
        abort(404)
    return redirect(url_for("correo.equipo_mensaje", mensaje_id=mensaje_id))


@correo_bp.route("/equipo/<int:mensaje_id>/notas", methods=["POST"])
@login_required
def equipo_nota(mensaje_id: int):
    if db.rol_en_correo(g.usuario_id, mensaje_id) is None:
        abort(404)
    nueva = db.anadir_nota_interna_correo(g.usuario_id, mensaje_id, request.form.get("texto", ""))
    if nueva:
        # Avisa al resto de implicados (dueño, asignado y compartidos).
        implicados = {db.estado_correo_equipo(mensaje_id)["asignado_a"], *[c["usuario_id"] for c in db.estado_correo_equipo(mensaje_id)["compartidos"]]}
        m = db.obtener_correo_equipo(g.usuario_id, mensaje_id)
        implicados.add(m["dueno_id"])
        for u in implicados - {None, g.usuario_id}:
            _avisar_correo(g.usuario_id, u, mensaje_id, "Nota interna en un correo", "ha escrito una nota interna en")
    return redirect(url_for("correo.equipo_mensaje", mensaje_id=mensaje_id) + "#notas")


@correo_bp.route("/equipo/<int:mensaje_id>/notas/<int:nota_id>/eliminar", methods=["POST"])
@login_required
def equipo_nota_eliminar(mensaje_id: int, nota_id: int):
    if not db.eliminar_nota_interna_correo(g.usuario_id, mensaje_id, nota_id):
        abort(404)
    return redirect(url_for("correo.equipo_mensaje", mensaje_id=mensaje_id) + "#notas")


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
    respuesta = Response(adjunto["contenido"], mimetype=adjunto["tipo_mime"])
    respuesta.headers.set("Content-Disposition", disposicion, filename=adjunto["nombre_archivo"])
    return respuesta


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
    correo.asignar_categoria(g.usuario_id, mensaje_id, categoria_id)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"], mensaje_id=mensaje_id,
    ))


@correo_bp.route("/<int:mensaje_id>/cliente-fiscal", methods=["POST"])
@login_required
def asignar_cliente_fiscal(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    if g.tenant_id is not None:
        cliente_fiscal_id = request.form.get("cliente_fiscal_id", type=int)
        correo.asignar_cliente_fiscal(g.tenant_id, mensaje_id, cliente_fiscal_id)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"], mensaje_id=mensaje_id,
    ))


@correo_bp.route("/ajustes/vincular-clientes", methods=["POST"])
@login_required
def vincular_clientes():
    """Enlaza los correos antiguos con el cliente fiscal cuyo email es el remitente."""
    n = correo.vincular_correos_a_clientes(g.usuario_id) if g.tenant_id is not None else 0
    return redirect(url_for("correo.ajustes", vinculados=n))


@correo_bp.route("/<int:mensaje_id>/adjunto/<int:adjunto_id>/guardar-vencimiento", methods=["POST"])
@login_required
def guardar_adjunto_en_vencimiento(mensaje_id: int, adjunto_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    vencimiento_id = request.form.get("vencimiento_id", type=int)
    aviso = None
    try:
        if vencimiento_id is None:
            raise correo.ErrorCorreo("Elige un vencimiento.")
        correo.guardar_adjunto_en_vencimiento(
            g.usuario_id, mensaje_id, adjunto_id, vencimiento_id, visible_cliente=request.form.get("visible_cliente") == "1",
        )
        aviso = _("Adjunto guardado en el vencimiento.")
    except correo.ErrorCorreo as e:
        aviso = str(e)
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"], mensaje_id=mensaje_id, aviso=aviso,
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
    borrador_id = request.args.get("borrador_id", type=int)
    if borrador_id is not None:
        borrador = db.obtener_borrador_correo(g.usuario_id, borrador_id)
        if borrador is None:
            abort(404)
        return _render_redactar(
            cuenta_id=borrador["cuenta_id"], destinatarios=borrador["destinatarios"] or "",
            cc=borrador["cc"] or "", bcc=borrador["bcc"] or "", asunto=borrador["asunto"] or "",
            cuerpo_html=borrador["cuerpo_html"] or "", en_respuesta_a=borrador["en_respuesta_a"],
            titulo=_("Editar borrador"), borrador_id=borrador_id,
        )
    cuenta_id = request.args.get("cuenta_id", type=int)
    if cuenta_id is None:
        cuentas_con_smtp = [c for c in db.listar_cuentas_correo(g.usuario_id) if c["smtp_host"]]
        cuenta_id = cuentas_con_smtp[0]["id"] if cuentas_con_smtp else None
    cuerpo_html = correo.preparar_cuerpo_inicial(g.usuario_id, cuenta_id, es_respuesta=False) if cuenta_id else ""
    return _render_redactar(cuenta_id=cuenta_id, cuerpo_html=cuerpo_html)


def _cita_de(mensaje) -> str:
    original_html = correo.sanear_html_externo(mensaje["cuerpo_html"]) if mensaje["cuerpo_html"] else correo.texto_a_html(mensaje["cuerpo_texto"] or "")
    return (
        f"<p>{correo.texto_a_html(mensaje['remitente'] or '')} escribió:</p>"
        f'<blockquote style="border-left:2px solid #ccc;margin:0 0 0 8px;padding-left:12px;color:#555;">{original_html}</blockquote>'
    )


@correo_bp.route("/<int:mensaje_id>/responder")
@login_required
def responder(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("re:"):
        asunto = f"Re: {asunto}"
    cuerpo_html = correo.preparar_cuerpo_inicial(
        g.usuario_id, mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=_cita_de(mensaje),
    )
    return _render_redactar(
        cuenta_id=mensaje["cuenta_id"], destinatarios=mensaje["remitente"] or "",
        asunto=asunto, cuerpo_html=cuerpo_html, en_respuesta_a=mensaje["message_id"], titulo=_("Responder"),
    )


@correo_bp.route("/<int:mensaje_id>/responder-a-todos")
@login_required
def responder_a_todos(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    cuenta = db.obtener_cuenta_correo(g.usuario_id, mensaje["cuenta_id"])
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("re:"):
        asunto = f"Re: {asunto}"
    original_html = correo.sanear_html_externo(mensaje["cuerpo_html"]) if mensaje["cuerpo_html"] else correo.texto_a_html(mensaje["cuerpo_texto"] or "")
    cita = (
        f"<p>{correo.texto_a_html(mensaje['remitente'] or '')} escribió:</p>"
        f'<blockquote style="border-left:2px solid #ccc;margin:0 0 0 8px;padding-left:12px;color:#555;">{original_html}</blockquote>'
    )
    cuerpo_html = correo.preparar_cuerpo_inicial(g.usuario_id, mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=cita)
    destinatarios = correo.destinatarios_responder_a_todos(mensaje, cuenta["usuario"] if cuenta else None)
    return _render_redactar(
        cuenta_id=mensaje["cuenta_id"], destinatarios=destinatarios,
        asunto=asunto, cuerpo_html=cuerpo_html, en_respuesta_a=mensaje["message_id"], titulo=_("Responder a todos"),
    )


@correo_bp.route("/<int:mensaje_id>/reenviar")
@login_required
def reenviar(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("fwd:"):
        asunto = f"Fwd: {asunto}"
    original_html = correo.sanear_html_externo(mensaje["cuerpo_html"]) if mensaje["cuerpo_html"] else correo.texto_a_html(mensaje["cuerpo_texto"] or "")
    cita = (
        "<p>---------- Mensaje reenviado ----------</p>"
        f"<p>De: {correo.texto_a_html(mensaje['remitente'] or '')}<br>"
        f"Asunto: {correo.texto_a_html(mensaje['asunto'] or '')}</p>"
        f"<blockquote style=\"border-left:2px solid #ccc;margin:0 0 0 8px;padding-left:12px;color:#555;\">{original_html}</blockquote>"
    )
    cuerpo_html = correo.preparar_cuerpo_inicial(g.usuario_id, mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=cita)
    return _render_redactar(cuenta_id=mensaje["cuenta_id"], asunto=asunto, cuerpo_html=cuerpo_html, titulo=_("Reenviar"))


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
    borrador_id = request.form.get("borrador_id", type=int)
    adjuntos = [
        {"nombre": f.filename, "tipo": f.mimetype or "application/octet-stream", "bytes": f.read()}
        for f in request.files.getlist("adjuntos") if f.filename
    ]
    if borrador_id is not None:  # adjuntos que ya traía el borrador (envío deshecho o fallido) y se siguen queriendo
        ids_mantener = [i for i in request.form.getlist("mantener_adjuntos") if i.isdigit()]
        adjuntos = db.adjuntos_borrador_para_enviar(g.usuario_id, borrador_id, [int(i) for i in ids_mantener]) + adjuntos
    programado = request.form.get("programar") == "1"
    deshacer = db.obtener_preferencias_correo(g.usuario_id)["deshacer_segundos"]
    try:
        enviar_en = None
        if programado:
            try:
                momento = datetime.strptime((request.form.get("programar_para") or "").strip(), "%Y-%m-%dT%H:%M")
            except ValueError:
                raise correo.ErrorCorreo(_("Elige la fecha y la hora del envío programado.")) from None
            if momento <= datetime.now() + timedelta(minutes=1):
                raise correo.ErrorCorreo(_("La hora del envío programado tiene que ser futura."))
            enviar_en = momento.isoformat(timespec="seconds")
        elif deshacer > 0:
            enviar_en = (datetime.now() + timedelta(seconds=deshacer)).isoformat(timespec="seconds")
        if enviar_en is not None:
            envio_id = correo.encolar_envio(
                g.usuario_id, cuenta_id, destinatarios, asunto, cuerpo_html, cc=cc, bcc=bcc,
                en_respuesta_a=en_respuesta_a, adjuntos=adjuntos, enviar_en=enviar_en, programado=programado,
            )
            if borrador_id is not None:
                db.eliminar_borrador_correo(g.usuario_id, borrador_id)
            return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id, envio_id=envio_id))
        correo.construir_y_enviar(
            g.usuario_id,
            cuenta_id, destinatarios, asunto, cuerpo_html, cc=cc, bcc=bcc,
            en_respuesta_a=en_respuesta_a, adjuntos=adjuntos,
        )
    except correo.ErrorCorreo as e:
        return _render_redactar(
            cuenta_id=cuenta_id, destinatarios=destinatarios, cc=cc, bcc=bcc, asunto=asunto,
            cuerpo_html=cuerpo_html, en_respuesta_a=en_respuesta_a, error=str(e), borrador_id=borrador_id,
        )
    if borrador_id is not None:
        db.eliminar_borrador_correo(g.usuario_id, borrador_id)
    return redirect(url_for("correo.bandeja", cuenta_id=cuenta_id))


@correo_bp.route("/envios/<int:envio_id>/deshacer", methods=["POST"])
@login_required
def deshacer_envio(envio_id: int):
    """Deshacer un envío en cuenta atrás o cancelar uno programado: el
    correo vuelve al editor como borrador."""
    envio = db.obtener_envio_correo(g.usuario_id, envio_id)
    if envio is None:
        abort(404)
    if db.cancelar_envio_correo(g.usuario_id, envio_id):
        borrador_id = correo.borrador_desde_envio(envio)
        db.cerrar_envio_correo(envio_id, "cancelado", borrar_adjuntos=True)
        return redirect(url_for("correo.redactar", borrador_id=borrador_id))
    return redirect(url_for(
        "correo.bandeja", cuenta_id=envio["cuenta_id"],
        aviso=_("Ya no se puede deshacer: el correo ya se ha enviado."),
    ))


@correo_bp.route("/programados")
@login_required
def programados():
    return render_template("correo_programados.html", envios=db.listar_envios_programados(g.usuario_id))


# --- Borradores -------------------------------------------------------------

@correo_bp.route("/borradores")
@login_required
def borradores():
    return render_template("correo_borradores.html", borradores=db.listar_borradores_correo(g.usuario_id))


@correo_bp.route("/borradores/guardar", methods=["POST"])
@login_required
def guardar_borrador():
    borrador_id = db.guardar_borrador_correo(
        g.usuario_id,
        request.form.get("borrador_id", type=int),
        cuenta_id=request.form.get("cuenta_id", type=int),
        destinatarios=request.form.get("destinatarios", ""),
        cc=request.form.get("cc", ""),
        bcc=request.form.get("bcc", ""),
        asunto=request.form.get("asunto", ""),
        cuerpo_html=request.form.get("cuerpo_html", ""),
        en_respuesta_a=request.form.get("en_respuesta_a") or None,
    )
    return jsonify({"ok": True, "borrador_id": borrador_id})


@correo_bp.route("/borradores/<int:borrador_id>/eliminar", methods=["POST"])
@login_required
def eliminar_borrador(borrador_id: int):
    db.eliminar_borrador_correo(g.usuario_id, borrador_id)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True})
    return redirect(url_for("correo.borradores"))


# --- Del correo a la acción: tarea, nota e IA bajo demanda ----------------------

def _volver_a_mensaje(mensaje, aviso: str):
    return redirect(url_for(
        "correo.bandeja", cuenta_id=mensaje["cuenta_id"], carpeta=mensaje["carpeta"],
        mensaje_id=mensaje["id"], aviso=aviso,
    ))


def _asunto_de(mensaje) -> str:
    return (mensaje["asunto"] or _("(sin asunto)")).strip()[:200]


@correo_bp.route("/<int:mensaje_id>/crear-tarea", methods=["POST"])
@login_required
def crear_tarea_desde_correo(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    vence = (request.form.get("vence") or "").strip() or None
    if vence:
        try:
            datetime.strptime(vence, "%Y-%m-%d")
        except ValueError:
            vence = None
    db.crear_tarea_outlook(
        g.usuario_id, _asunto_de(mensaje), cuerpo=_("Correo de {remitente}").format(remitente=mensaje["remitente"] or ""),
        fecha_vencimiento=vence, cliente_fiscal_id=mensaje["cliente_fiscal_id"], mensaje_correo_id=mensaje_id,
    )
    return _volver_a_mensaje(mensaje, _("Tarea creada."))


@correo_bp.route("/<int:mensaje_id>/guardar-nota", methods=["POST"])
@login_required
def guardar_nota_desde_correo(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    cuerpo = (mensaje["cuerpo_texto"] or "").strip()
    if not cuerpo and mensaje["cuerpo_html"]:
        cuerpo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", mensaje["cuerpo_html"])).strip()
    texto = _("De: {remitente}").format(remitente=mensaje["remitente"] or "") + "\n\n" + cuerpo[:2000]
    db.crear_nota(
        g.usuario_id, texto, titulo=_asunto_de(mensaje)[:120],
        cliente_fiscal_id=mensaje["cliente_fiscal_id"], mensaje_correo_id=mensaje_id,
    )
    return _volver_a_mensaje(mensaje, _("Nota guardada."))


@correo_bp.route("/<int:mensaje_id>/ia/<accion>", methods=["POST"])
@login_required
def ia_sobre_correo(mensaje_id: int, accion: str):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    if accion not in correo_ia.ACCIONES:
        abort(404)
    try:
        return jsonify({"ok": True, **correo_ia.ejecutar(g.usuario_id, accion, mensaje, str(get_locale() or "es")[:2])})
    except ia_asistente.ErrorIA as e:
        return jsonify({"ok": False, "error": str(e)}), 502


@correo_bp.route("/<int:mensaje_id>/ia-borrador", methods=["POST"])
@login_required
def ia_borrador_respuesta(mensaje_id: int):
    """Genera la respuesta con IA y la deja como borrador (texto de la IA
    arriba, luego firma y cita) para revisarla y enviarla desde el editor."""
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    texto = (request.form.get("texto") or "").strip()
    if not texto:
        abort(400)
    asunto = mensaje["asunto"] or ""
    if not asunto.lower().startswith("re:"):
        asunto = f"Re: {asunto}"
    cuerpo_html = correo.texto_a_html(texto) + correo.preparar_cuerpo_inicial(
        g.usuario_id, mensaje["cuenta_id"], es_respuesta=True, contenido_tras_firma=_cita_de(mensaje),
    )
    borrador_id = db.guardar_borrador_correo(
        g.usuario_id, None, cuenta_id=mensaje["cuenta_id"], destinatarios=mensaje["remitente"] or "",
        cc="", bcc="", asunto=asunto, cuerpo_html=cuerpo_html, en_respuesta_a=mensaje["message_id"],
    )
    return redirect(url_for("correo.redactar", borrador_id=borrador_id))


@correo_bp.route("/<int:mensaje_id>/tareas-ia", methods=["POST"])
@login_required
def crear_tareas_marcadas(mensaje_id: int):
    mensaje = _mensaje_de_usuario_o_404(mensaje_id)
    creadas = 0
    for asunto in request.form.getlist("tarea")[:correo_ia.MAX_TAREAS]:
        asunto = " ".join(asunto.split())[:correo_ia.MAX_LONGITUD_TAREA]
        if asunto:
            db.crear_tarea_outlook(
                g.usuario_id, asunto, cliente_fiscal_id=mensaje["cliente_fiscal_id"], mensaje_correo_id=mensaje_id,
            )
            creadas += 1
    return _volver_a_mensaje(mensaje, _("{n} tareas creadas.").format(n=creadas))


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
        reglas_avanzadas=db.listar_reglas_correo(g.usuario_id),
        clientes_fiscales=db.listar_clientes_fiscales(g.tenant_id) if g.tenant_id is not None else [],
        plantillas=db.listar_plantillas_correo(g.usuario_id),
        variables_plantilla=correo.VARIABLES_PLANTILLA,
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
        deshacer_segundos=request.form.get("deshacer_segundos", type=int),
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


@correo_bp.route("/plantillas/<int:plantilla_id>.json")
@login_required
def plantilla_json(plantilla_id: int):
    plantilla = correo.obtener_plantilla(g.usuario_id, plantilla_id)
    if plantilla is None:
        abort(404)
    cliente_id = request.args.get("cliente_fiscal_id", type=int)
    if cliente_id is None:
        cliente_id = _cliente_del_mensaje_respondido(request.args.get("en_respuesta_a"))
    valores = correo.contexto_plantilla(g.usuario_id, cliente_id)
    asunto, faltan_asunto = correo.rellenar_plantilla(plantilla["asunto"], valores)
    cuerpo, faltan_cuerpo = correo.rellenar_plantilla(plantilla["cuerpo"], valores, html=True)
    return jsonify({"asunto": asunto, "cuerpo": cuerpo, "sin_resolver": sorted(set(faltan_asunto + faltan_cuerpo))})


@correo_bp.route("/ajustes/plantillas", methods=["POST"])
@login_required
def crear_plantilla():
    try:
        correo.crear_plantilla(
            g.usuario_id, request.form.get("nombre", ""), request.form.get("asunto"),
            request.form.get("cuerpo", ""),
        )
    except correo.ErrorCorreo as e:
        return _render_ajustes(error=str(e))
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/plantillas/<int:plantilla_id>/eliminar", methods=["POST"])
@login_required
def eliminar_plantilla(plantilla_id: int):
    correo.eliminar_plantilla(g.usuario_id, plantilla_id)
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


@correo_bp.route("/ajustes/reglas-avanzadas", methods=["POST"])
@login_required
def crear_regla_avanzada():
    try:
        db.crear_regla_correo(
            g.usuario_id, request.form.get("remitente_patron"), request.form.get("asunto_patron"),
            categoria_id=request.form.get("categoria_id", type=int),
            marcar_leido=request.form.get("marcar_leido") == "on",
            destacar=request.form.get("destacar") == "on",
            cliente_fiscal_id=request.form.get("cliente_fiscal_id", type=int),
        )
    except ValueError as e:
        return _render_ajustes(error=str(e))
    return redirect(url_for("correo.ajustes"))


@correo_bp.route("/ajustes/reglas-avanzadas/<int:regla_id>/eliminar", methods=["POST"])
@login_required
def eliminar_regla_avanzada(regla_id: int):
    db.eliminar_regla_correo(g.usuario_id, regla_id)
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
