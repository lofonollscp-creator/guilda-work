"""Portal de cliente: acceso mínimo, sin cuenta, para que un CLIENTE de la
gestoría (no un empleado) consulte el estado de sus vencimientos fiscales
y suba un documento -- vía enlace mágico por email, no contraseña.

El "principal" de este blueprint es session["cliente_fiscal_id"], un
concepto completamente distinto de g.usuario_id (empleado autenticado vía
Kratos/sesión de escritorio, ver app/main.py:_resolver_usuario_actual).
Este before_request NO toca esa función ni g.usuario_id -- son dos
sistemas de sesión independientes que conviven en la misma cookie de
Flask sin pisarse (claves de session distintas).

v1 deliberadamente NO incluye: auto-registro (el acceso es opt-in, un
empleado pone el email desde /fiscal/clientes/<id>/editar), mensajería
cliente<->gestoría, ni contraseña (solo enlace mágico)."""
import json
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from flask import Blueprint, Response, abort, g, redirect, render_template, request, session, url_for
from flask_babel import gettext as _, get_locale

from . import antivirus, auditoria, captcha, db, notificaciones, tareas_trabajo, verticales
from . import ayuda, portal_buzon, portal_busqueda, portal_conversaciones, portal_cuestionarios, portal_datos, portal_novedades, portal_calendario, portal_citas, portal_extracto, portal_firmas_honorarios, portal_lectura_previa, portal_personas, portal_peticiones, portal_seguridad, portal_valoraciones, portal_plazos, portal_push, portal_situacion, portal_estado, portal_informe_anual, portal_glosario, portal_primeros_pasos, portal_subida_rapida, portal_vista_previa, qr, cierre_trimestre, conformidad_declaracion, portal_carpeta, portal_firma, portal_pagos, facturas_contables, justificantes, facturas_portal, portal_inicio
from .auth import limiter
from . import notificaciones_email
from .notificaciones_email import ErrorNotificacionesEmail, enviar_enlace_portal

portal_bp = Blueprint("portal_cliente", __name__, url_prefix="/portal")

_MINUTOS_COOLDOWN_ENVIO = 2
MAX_ARCHIVOS_POR_SUBIDA = 10


DIAS_SESION_RECORDADA = 30
# Con el perfil «consulta» solo se mira: estas son las únicas acciones que se permiten (sus propias preferencias y salir).
_ACCIONES_DE_CONSULTA = {"portal_cliente.salir", "portal_cliente.cerrar_sesion_remota", "portal_cliente.cerrar_otras_sesiones", "portal_cliente.segundo_factor_iniciar", "portal_cliente.segundo_factor_confirmar", "portal_cliente.segundo_factor_quitar", "portal_cliente.cambiar_titular", "portal_cliente.guardar_preferencias", "portal_cliente.push_suscribir", "portal_cliente.push_baja", "portal_cliente.bienvenida_vista"}
# Lo que solo hace el perfil «completo»: decidir en nombre del cliente y gestionar a quién más se deja entrar.
_SOLO_PERFIL_COMPLETO = {"portal_cliente.conformidad", "portal_cliente.pagar_vencimiento", "portal_cliente.firma_vencimiento", "portal_cliente.anadir_contacto", "portal_cliente.cambiar_perfil_contacto", "portal_cliente.quitar_contacto",
                         "portal_cliente.renovar_enlace_subida"}


def _cerrar_sesion_del_portal(tenant_id: int | None = None) -> None:
    portal_seguridad.cerrar_esta(tenant_id if tenant_id is not None else g.get("portal_tenant_id"), session.get("portal_sid"))
    for clave in ("cliente_fiscal_id", "portal_email", "portal_hasta", "portal_sid"):
        session.pop(clave, None)


@portal_bp.before_request
def _resolver_cliente_actual():
    g.vista_previa = portal_vista_previa.activa(session)               # el equipo mirando el portal de un cliente: solo lectura
    g.cliente_fiscal_id = session.get("cliente_fiscal_id")
    g.portal_email = session.get("portal_email")
    g.portal_rol = "completo"
    g.portal_tenant_id = None
    if g.cliente_fiscal_id and not g.vista_previa:
        cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
        rol = portal_personas.rol_de(cliente, g.portal_email) if cliente is not None else None
        caducada = bool(session.get("portal_hasta")) and session["portal_hasta"] < datetime.now().isoformat(timespec="seconds")
        valida = portal_seguridad.sesion_valida(cliente["tenant_id"], session.get("portal_sid")) if rol is not None and not caducada else None
        if rol is None or caducada or valida is False:
            _cerrar_sesion_del_portal(cliente["tenant_id"] if cliente is not None else None)                          # la ficha ya no existe, la persona perdió el acceso, la sesión recordada caducó o la cerraron desde otro dispositivo
            g.cliente_fiscal_id = None
        else:
            g.portal_rol, g.portal_tenant_id = rol, cliente["tenant_id"]
            if valida is None:                                   # una sesión de antes de existir el registro: se anota ahora, sin avisar de nada
                session["portal_sid"] = portal_seguridad.abrir_sesion(cliente, g.portal_email or cliente["email"], request.headers.get("User-Agent"), request.remote_addr)[0]
    if g.vista_previa and request.method not in ("GET", "HEAD", "OPTIONS") and request.endpoint != "portal_cliente.salir":
        abort(403)
    if g.portal_rol == "consulta" and request.method not in ("GET", "HEAD", "OPTIONS") and request.endpoint not in _ACCIONES_DE_CONSULTA:
        return _sin_permiso()
    if g.portal_rol != "completo" and request.endpoint in _SOLO_PERFIL_COMPLETO:
        return _sin_permiso()


def _sin_permiso():
    return render_template("portal_sin_permiso.html", portal_seccion="inicio"), 403


@portal_bp.after_request
def _auditar_lo_que_hace_el_cliente(respuesta):
    """Cada cosa que una persona hace en el portal (un POST que sale bien) queda en la auditoría con quién fue: el titular o uno de sus contactos."""
    try:
        if (request.method == "POST" and g.get("cliente_fiscal_id") and g.get("portal_tenant_id") and not g.get("vista_previa") and respuesta.status_code < 400
                and request.endpoint not in ("portal_cliente.salir", "portal_cliente.entrar", "portal_cliente.comprobar_archivos")):
            auditoria.registrar(g.portal_tenant_id, None, "portal.accion", "cliente_fiscal", g.cliente_fiscal_id, {"quien": g.portal_email or "titular", "pantalla": (request.endpoint or "").split(".")[-1]})
    except Exception:  # noqa: BLE001 -- la auditoría nunca debe romper la respuesta
        pass
    return respuesta


@portal_bp.context_processor
def _menu_del_portal():
    """La barra de secciones de todas las pantallas del portal: Inicio · Facturas (si el despacho las contabiliza) · Impuestos. La insignia de Facturas cuenta las que hay que corregir."""
    if not g.get("cliente_fiscal_id"):
        return {}
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        return {}
    con_facturas = verticales.esta_activo(cliente["tenant_id"], "contabilizacion")
    email = g.get("portal_email") or cliente["email"]
    otras = [c for c in portal_personas.clientes_de(email) if c["id"] != cliente["id"]] if not g.get("vista_previa") else []
    return {"vista_previa": g.get("vista_previa"), "portal_cliente": cliente, "portal_facturas": con_facturas, "portal_insignia_facturas": facturas_portal.para_el_inicio(cliente["id"])["para_corregir"] if con_facturas else 0,
            "portal_insignia_mensajes": portal_buzon.sin_leer_total(cliente), "portal_insignia_avisos": 0 if g.get("vista_previa") else portal_novedades.sin_leer(cliente, g.get("portal_email") or cliente["email"] or ""), "portal_rol": g.get("portal_rol", "completo"), "portal_otros_clientes": otras, "portal_puede_decidir": g.get("portal_rol", "completo") == "completo",
            "portal_puede_subir": g.get("portal_rol", "completo") != "consulta" and not g.get("vista_previa"),
            "glosario_modelo": portal_glosario.por_modelo, "portal_ayuda_url": ayuda.url_de(request.endpoint, str(get_locale() or "es")[:2])[0]}


def cliente_login_required(vista):
    from functools import wraps

    @wraps(vista)
    def decorada(*args, **kwargs):
        if not g.cliente_fiscal_id:
            return redirect(url_for("portal_cliente.entrar"))
        return vista(*args, **kwargs)
    return decorada


@portal_bp.route("/solicitar-acceso", methods=["GET", "POST"])
@limiter.limit("10/hour")
def solicitar_acceso():
    """Cola de solicitudes para quien NO tiene ficha previa en
    clientes_fiscales (v1 es opt-in, un empleado pone el email desde
    /fiscal/clientes/<id>/editar) -- a diferencia de /entrar (que no
    revela si un email existe), este SÍ es un formulario público visible
    sin autenticar detrás de él, así que lleva ALTCHA desde el principio
    (mismo captcha.py que /login tras varios fallos)."""
    enviado = False
    error = None
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        email = (request.form.get("email") or "").strip()
        if not nombre or not email or "@" not in email:
            error = _("Faltan datos: nombre y email son obligatorios.")
        elif not captcha.verificar_solucion(request.form.get("altcha")):
            error = _("No se ha podido comprobar el captcha. Resuélvelo de nuevo.")
        else:
            db.crear_solicitud_acceso_portal(
                nombre, email, nif=request.form.get("nif"), mensaje=request.form.get("mensaje"),
            )
            enviado = True
    return render_template("portal_solicitar_acceso.html", enviado=enviado, error=error)


def destino_seguro(valor: str | None) -> str | None:
    """La pantalla del portal a la que llevar al cliente tras entrar: solo rutas propias del portal (nunca otra web), sin saltos de línea ni `//`."""
    v = (valor or "").strip()
    if not v.startswith("/portal/") or v.startswith("/portal/entrar") or v.startswith("/portal/salir") or len(v) > 200:
        return None
    if "//" in v or "\\" in v or any(ord(c) < 32 for c in v) or ":" in v.split("?")[0]:
        return None
    return v


def _ficha_pedida(email: str):
    """La ficha a la que llevar a esa persona al entrar: la que pide el enlace (`c`) si es suya; si no, la primera de las suyas."""
    suyas = portal_personas.clientes_de(email)
    pedida = request.values.get("c", type=int)
    return next((c for c in suyas if c["id"] == pedida), suyas[0] if suyas else None)


@portal_bp.route("/entrar", methods=["GET", "POST"])
@limiter.limit("10/hour")
def entrar():
    siguiente = destino_seguro(request.values.get("siguiente"))
    if request.method == "GET" and siguiente and g.cliente_fiscal_id:
        pedida = request.args.get("c", type=int)
        if pedida and pedida != g.cliente_fiscal_id:                  # el enlace es de otra de sus sociedades: se cambia a ella si es suya
            email = g.get("portal_email") or (db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id) or {"email": ""})["email"]
            if any(c["id"] == pedida for c in portal_personas.clientes_de(email)):
                session["cliente_fiscal_id"] = pedida
        return redirect(siguiente)
    if request.method == "POST":
        email = portal_personas.limpio(request.form.get("email"))
        if email and "@" in email:
            cliente = _ficha_pedida(email)
            if cliente is not None:
                ultimo_envio = db.ultimo_acceso_solicitado_a(email)
                # Cooldown por email (no solo el rate-limit por IP de arriba):
                # sin esto, alguien con la IP de otro (o varias IPs) podría
                # seguir mandando enlaces a un email ajeno sin parar.
                if not (ultimo_envio and datetime.fromisoformat(ultimo_envio) > datetime.now() - timedelta(minutes=_MINUTOS_COOLDOWN_ENVIO)):
                    token = db.crear_acceso_cliente_fiscal(cliente["id"], request.remote_addr, email=email)
                    enlace = url_for("portal_cliente.entrar_con_token", token=token, siguiente=siguiente, c=request.form.get("c", type=int) or None, r="1" if request.form.get("recordar") else None, _external=True)
                    try:
                        enviar_enlace_portal(email, enlace, tenant_id=cliente["tenant_id"])
                    except ErrorNotificacionesEmail:
                        pass
        # Mismo mensaje exista o no el email -- no confirmar si un email
        # concreto está asociado a algún cliente.
        return render_template("portal_entrar.html", enviado=True)
    return render_template("portal_entrar.html", enviado=False, siguiente=siguiente, ficha=request.args.get("c", type=int))


@portal_bp.route("/entrar/<token>")
def entrar_con_token(token: str):
    acceso = db.consumir_acceso_portal(token)
    if acceso is None:
        return render_template("portal_entrar.html", enviado=False, enlace_invalido=True)
    cliente_fiscal_id, email = acceso
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    email = portal_personas.limpio(email) or (portal_personas.limpio(cliente["email"]) if cliente is not None else "")
    suyas = {c["id"] for c in portal_personas.clientes_de(email)}
    if cliente is None or cliente_fiscal_id not in suyas:                  # le quitaron el acceso entre pedir el enlace y abrirlo
        return render_template("portal_entrar.html", enviado=False, enlace_invalido=True)
    pedida = request.args.get("c", type=int)
    elegida = pedida if pedida in suyas else cliente_fiscal_id
    entrada = db.obtener_cliente_fiscal_por_id(elegida)
    destino = destino_seguro(request.args.get("siguiente"))
    if portal_seguridad.activo(entrada, email):                            # con segundo factor, la entrada no se completa hasta dar el código
        session["portal_2fa"] = {"c": elegida, "email": email, "r": request.args.get("r") == "1", "siguiente": destino, "hasta": (datetime.now() + timedelta(minutes=10)).isoformat(timespec="seconds")}
        return redirect(url_for("portal_cliente.verificacion"))
    return _completar_entrada(elegida, email, request.args.get("r") == "1", destino)


def _completar_entrada(cliente_id: int, email: str, recordar: bool, destino: str | None):
    """Abre la sesión del portal (cookie + registro), avisa si es un dispositivo nuevo y lleva a donde pidió."""
    entrada = db.obtener_cliente_fiscal_por_id(cliente_id)
    session.pop("portal_2fa", None)
    session["cliente_fiscal_id"] = cliente_id
    session["portal_email"] = email
    if recordar:                                                           # «mantener la sesión en este dispositivo»
        session.permanent = True
        session["portal_hasta"] = (datetime.now() + timedelta(days=DIAS_SESION_RECORDADA)).isoformat(timespec="seconds")
    else:
        session.pop("portal_hasta", None)
    session["portal_sid"], nuevo = portal_seguridad.abrir_sesion(entrada, email, request.headers.get("User-Agent"), request.remote_addr)
    portal_personas.registrar_acceso(entrada, email)
    auditoria.registrar(entrada["tenant_id"], None, "portal.entrada", "cliente_fiscal", entrada["id"], {"quien": email, "recordada": recordar, "dispositivo": portal_seguridad.dispositivo_de(request.headers.get("User-Agent")), "nuevo": nuevo})
    if nuevo:
        try:
            notificaciones_email.enviar_aviso_dispositivo_nuevo(email, portal_seguridad.dispositivo_de(request.headers.get("User-Agent")), datetime.now().strftime("%d/%m/%Y %H:%M"),
                                                                url_for("portal_cliente.cuenta", _external=True) + "#seguridad", tenant_id=entrada["tenant_id"])
        except ErrorNotificacionesEmail:
            pass
    return redirect(destino or url_for("portal_cliente.dashboard"))


@portal_bp.route("/verificacion", methods=["GET", "POST"])
@limiter.limit("10/hour", methods=["POST"])
def verificacion():
    """El segundo paso de la entrada para quien tiene activado el segundo factor: el código de su aplicación (o uno de recuperación)."""
    pendiente = session.get("portal_2fa")
    if not pendiente or pendiente.get("hasta", "") < datetime.now().isoformat(timespec="seconds"):
        session.pop("portal_2fa", None)
        return redirect(url_for("portal_cliente.entrar"))
    cliente = db.obtener_cliente_fiscal_por_id(pendiente["c"])
    if cliente is None or portal_personas.rol_de(cliente, pendiente["email"]) is None:
        session.pop("portal_2fa", None)
        return redirect(url_for("portal_cliente.entrar"))
    error = None
    if request.method == "POST":
        if portal_seguridad.verificar(cliente, pendiente["email"], request.form.get("codigo", "")):
            return _completar_entrada(pendiente["c"], pendiente["email"], pendiente["r"], pendiente.get("siguiente"))
        error = _("El código no es correcto.")
        auditoria.registrar(cliente["tenant_id"], None, "portal.segundo_factor_fallido", "cliente_fiscal", cliente["id"], {"quien": pendiente["email"]})
    return render_template("portal_verificacion.html", error=error), (401 if error else 200)


@portal_bp.route("/salir", methods=["POST"])
def salir():
    if g.get("vista_previa"):
        portal_vista_previa.salir(session)
        return redirect(url_for("fiscal.clientes"))
    _cerrar_sesion_del_portal()
    return redirect(url_for("portal_cliente.entrar"))


@portal_bp.route("/cambiar-titular", methods=["POST"])
@cliente_login_required
def cambiar_titular():
    """Pasa a otra de las fichas a las que da acceso el mismo email (varias sociedades). Se comprueba contra la base, no contra la sesión."""
    actual = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    email = g.get("portal_email") or (actual["email"] if actual is not None else "")
    elegida = request.form.get("cliente_id", type=int)
    if any(c["id"] == elegida for c in portal_personas.clientes_de(email)):
        session["cliente_fiscal_id"] = elegida
    return redirect(url_for("portal_cliente.dashboard"))


@portal_bp.route("/")
@cliente_login_required
def dashboard():
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        _cerrar_sesion_del_portal()
        return redirect(url_for("portal_cliente.entrar"))
    d = portal_inicio.datos(cliente, g.portal_rol)
    from . import certificados
    cfg_cert = certificados.config(cliente["tenant_id"])
    bienvenida = not g.get("vista_previa") and not portal_personas.bienvenida_vista(cliente, g.get("portal_email"))
    primeros = portal_primeros_pasos.pasos(cliente, d["con_facturas"], g.portal_rol != "consulta", g.portal_rol != "consulta") if bienvenida else []
    resumen_primeros = portal_primeros_pasos.resumen(primeros)
    return render_template(
        "portal_dashboard.html", cliente=cliente, vencimientos=d["vencimientos"], certificados=d["certificados"], tipos_certificado=certificados.TIPOS_CERTIFICADO,
        instrucciones_certificado=cfg_cert["instrucciones"], ayuda_enviada=request.args.get("ayuda"), portal_seccion="inicio",
        para_hacer=d["para_hacer"], presentados=d["presentados"], proximo_pendiente=d["proximo_pendiente"], trabajo_en_curso=portal_estado.enriquecer(d["trabajo"], cliente["tenant_id"]),
        plazos=portal_plazos.proximos(cliente, d["vencimientos"], g.portal_rol),
        aviso=(request.args.get("aviso") or "")[:200] or None, max_caracteres=tareas_trabajo.MAX_CARACTERES_COMENTARIO,
        bienvenida=bienvenida and not resumen_primeros["completo"], primeros_pasos=primeros, primeros_resumen=resumen_primeros,
    )


@portal_bp.route("/glosario")
@cliente_login_required
def glosario():
    """Qué es cada modelo fiscal y cada palabra rara, en lenguaje llano; con buscador."""
    q = (request.args.get("q") or "")[:60]
    return render_template("portal_glosario.html", cliente=db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id), q=q, g_datos=portal_glosario.todo(q), portal_seccion="inicio")


@portal_bp.route("/impuestos")
@cliente_login_required
def impuestos():
    """Todos sus modelos por año, con el estado de cada uno y el acceso a sus documentos y mensajes."""
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        _cerrar_sesion_del_portal()
        return redirect(url_for("portal_cliente.entrar"))
    vencimientos = db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"], sin_internos=True)
    # Agrupados por año, el más reciente primero, para que un cliente con varios años de histórico no vea todo mezclado; dentro de cada año se mantiene el orden por fecha límite.
    por_anio: dict[str, list] = {}
    for v in vencimientos:
        por_anio.setdefault(v["fecha_limite"][:4], []).append(v)
    return render_template("portal_impuestos.html", situacion=portal_situacion.calcular(cliente), cobros=portal_pagos.cobros(cliente, vencimientos), firmas={v["id"] for v in portal_firma.pendientes(vencimientos)}, pago=request.args.get("pago"),
                           error=(request.args.get("error") or "")[:200] or None, cliente=cliente, por_anio=por_anio, anios_ordenados=sorted(por_anio, reverse=True), vencimientos=vencimientos, portal_seccion="impuestos",
                           sin_leer={m["vencimiento_id"]: m["n"] for m in db.mensajes_sin_leer_para_cliente(cliente["id"])})


@portal_bp.route("/certificados/<int:certificado_id>/ayuda", methods=["POST"])
@cliente_login_required
def ayuda_certificado(certificado_id: int):
    """El cliente pide ayuda a su gestoría para renovar SU certificado digital (solo de los que su gestoría le enseña)."""
    from . import certificados
    if not certificados.pedir_ayuda(g.cliente_fiscal_id, certificado_id):
        abort(404)
    return redirect(url_for("portal_cliente.dashboard", ayuda="1"))


from .vencimientos_fiscales import MODELOS_INTERNOS  # noqa: E402


def _vencimiento_del_cliente_actual(vencimiento_id: int):
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        abort(404)
    vencimiento = db.obtener_vencimiento_fiscal(cliente["tenant_id"], vencimiento_id)
    if vencimiento is None or vencimiento["cliente_fiscal_id"] != cliente["id"] or vencimiento["modelo"] in MODELOS_INTERNOS:
        abort(404)
    return vencimiento


@portal_bp.route("/vencimientos/<int:vencimiento_id>/documentos", methods=["GET", "POST"])
@cliente_login_required
def documentos_vencimiento(vencimiento_id: int):
    vencimiento = _vencimiento_del_cliente_actual(vencimiento_id)
    cliente_actual = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    error = None
    resultados = []
    if request.method == "POST":
        archivos = [f for f in request.files.getlist("documento") if f and f.filename]
        if len(archivos) > MAX_ARCHIVOS_POR_SUBIDA:
            error = _("Puedes subir hasta %(n)s archivos a la vez.", n=MAX_ARCHIVOS_POR_SUBIDA)
        for f in ([] if error else archivos):
            # Igual que rutas_api.py/rutas_ia.py: se lee como mucho
            # LIMITE+1 bytes, no el fichero entero, para no comprobar el
            # tamaño DESPUÉS de haberlo cargado todo a memoria.
            contenido = f.read(db.TAMANO_MAXIMO_DOCUMENTO_VENCIMIENTO + 1)
            if f.mimetype not in db.MIME_PERMITIDOS_DOCUMENTO_VENCIMIENTO or len(contenido) > db.TAMANO_MAXIMO_DOCUMENTO_VENCIMIENTO:
                resultados.append({"nombre": f.filename, "ok": False,
                                   "mensaje": _("Archivo no válido: solo imágenes o PDF, hasta 8MB.")})
            else:
                try:
                    antivirus.exigir_limpio(f.filename, contenido, cliente_actual["tenant_id"], cliente_actual["id"])
                    db.subir_documento_vencimiento(vencimiento_id, f.filename, f.mimetype, contenido)
                    resultados.append({"nombre": f.filename, "ok": True, "mensaje": _("Subido.")})
                except antivirus.ArchivoRechazado as e:
                    mensaje = (_("El archivo no se ha podido aceptar: nuestro antivirus ha detectado en él algo peligroso. Revisa tu equipo antes de volver a enviarlo.") if e.codigo == "virus"
                               else _("Ahora mismo no podemos comprobar el archivo con el antivirus. Inténtalo de nuevo dentro de unos minutos."))
                    resultados.append({"nombre": f.filename, "ok": False, "mensaje": mensaje})
                except ValueError:
                    resultados.append({"nombre": f.filename, "ok": False, "mensaje": _("Archivo no válido: solo imágenes o PDF, hasta 8MB.")})
        if archivos and not error and all(r["ok"] for r in resultados):
            return redirect(url_for("portal_cliente.documentos_vencimiento", vencimiento_id=vencimiento_id))
    return render_template(
        "portal_vencimiento_documentos.html",
        vencimiento=vencimiento, portal_seccion="impuestos", documentos=db.listar_documentos_vencimiento(vencimiento_id, excluir_origenes=db.ORIGENES_INTERNOS_DOCUMENTO_VENCIMIENTO), error=error,
        resultados=resultados,
    )


@portal_bp.route("/vencimientos/<int:vencimiento_id>/documentos/<int:documento_id>")
@cliente_login_required
def descargar_documento(vencimiento_id: int, documento_id: int):
    """El cliente descarga cualquier documento de SU vencimiento: lo que subió
    él, el justificante oficial y la constancia de presentación."""
    _vencimiento_del_cliente_actual(vencimiento_id)
    documento = db.obtener_documento_vencimiento(documento_id)
    if (
        documento is None or documento["vencimiento_id"] != vencimiento_id
        or documento["origen"] in db.ORIGENES_INTERNOS_DOCUMENTO_VENCIMIENTO  # adjuntos internos guardados desde el correo
    ):
        abort(404)
    try:
        contenido = db.contenido_documento_vencimiento(documento)
    except Exception:  # noqa: BLE001 -- almacenamiento externo caído
        abort(503)
    respuesta = Response(contenido, mimetype=documento["tipo_mime"])
    respuesta.headers.set("Content-Disposition", "attachment", filename=documento["nombre_archivo"])
    respuesta.headers.set("X-Content-Type-Options", "nosniff")
    return respuesta


@portal_bp.route("/vencimientos/<int:vencimiento_id>/mensajes", methods=["GET", "POST"])
@cliente_login_required
def mensajes_vencimiento(vencimiento_id: int):
    vencimiento = _vencimiento_del_cliente_actual(vencimiento_id)
    if request.method == "POST":
        texto = (request.form.get("texto") or "").strip()
        if texto:
            db.crear_mensaje_vencimiento(vencimiento_id, "cliente", texto)
            # Avisa al empleado asignado -- mismo patrón que el recordatorio
            # de vencimientos (app/main.py) y el correo nuevo (app/correo.py):
            # notificaciones.crear_y_enviar (app/notificaciones.py) registra
            # el aviso en el centro de notificaciones Y manda el push, nunca
            # lanza; si no hay usuario_id asignado simplemente no se
            # notifica a nadie (v2 no tiene "avisar a todo el tenant" todavía).
            if vencimiento["usuario_id"] and db.notificacion_tipo_activa(
                vencimiento["usuario_id"], "portal_mensaje_nuevo"
            ):
                notificaciones.crear_y_enviar(
                    vencimiento["usuario_id"], "portal_mensaje_nuevo", _("Nuevo mensaje del cliente"), texto[:100],
                    url=f"/fiscal/vencimientos/{vencimiento_id}/editar",
                    datos={"tipo": "portal_mensaje_nuevo", "vencimiento_id": vencimiento_id},
                )
        return redirect(url_for("portal_cliente.mensajes_vencimiento", vencimiento_id=vencimiento_id))
    if not g.get("vista_previa"):
        db.marcar_mensajes_leidos(vencimiento_id, "cliente")
    return render_template(
        "portal_vencimiento_mensajes.html",
        vencimiento=vencimiento, portal_seccion="impuestos", mensajes=db.listar_mensajes_vencimiento(vencimiento_id),
    )


# --- Tareas que el despacho enseña al cliente: comentarios --------------------------------------------------------------------------------------------------------

@portal_bp.route("/tareas/<int:tarea_id>/comentarios", methods=["POST"])
@cliente_login_required
@limiter.limit("30/hour", methods=["POST"])
def comentar_tarea(tarea_id: int):
    """El cliente escribe en una tarea que se le enseña y en la que el despacho le deja comentar (ver app/tareas_trabajo.py). Cualquier otra cosa es un 404: ni se confirma que la tarea exista."""
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        _cerrar_sesion_del_portal()
        return redirect(url_for("portal_cliente.entrar"))
    try:
        archivos = [(a.filename, a.read(tareas_trabajo.MAX_ADJUNTO_CLIENTE_BYTES + 1)) for a in request.files.getlist("archivos")[:tareas_trabajo.MAX_ADJUNTOS_POR_COMENTARIO + 1] if a and a.filename]
        nuevo = tareas_trabajo.comentar_como_cliente(cliente["tenant_id"], cliente["id"], tarea_id, request.form.get("texto", ""), archivos)
    except tareas_trabajo.ComentarioInvalido as e:
        if e.codigo == "no_encontrada":
            abort(404)
        return redirect(url_for("portal_cliente.dashboard", aviso=_(str(e)), _anchor=f"tarea-{tarea_id}"))
    for destino in nuevo["destinatarios"]:
        if db.notificacion_tipo_activa(destino, "portal_comentario_tarea"):
            notificaciones.crear_y_enviar(destino, "portal_comentario_tarea", _("Comentario de un cliente en una tarea"), f"{cliente['nombre']}: {nuevo['tarea']['asunto']}"[:100],
                                          url=f"/tareas/{tarea_id}#cliente", datos={"tipo": "portal_comentario_tarea", "tarea_id": tarea_id})
        tareas_trabajo.avisar_por_correo_comentario_cliente(destino, tarea_id, nuevo["tarea"]["asunto"], cliente["nombre"], cliente["tenant_id"], url_for("tareas.ver", tarea_id=tarea_id, _external=True) + "#cliente")
    return redirect(url_for("portal_cliente.dashboard", _anchor=f"tarea-{tarea_id}"))


@portal_bp.route("/tareas/adjuntos/<int:adjunto_id>")
@cliente_login_required
def descargar_adjunto_de_tarea(adjunto_id: int):
    """El cliente descarga un archivo que él mismo envió en un comentario. Siempre como descarga y sin ejecutar nada; lo ajeno, oculto o de una tarea que ya no se le enseña es un 404."""
    from .rutas_api_tareas_trabajo import respuesta_de_adjunto
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        abort(404)
    return respuesta_de_adjunto(tareas_trabajo.leer_adjunto_de_cliente_para_cliente(cliente["tenant_id"], cliente["id"], adjunto_id))


# --- Facturas: el cliente las anota (y adjunta la foto o el PDF) para que el despacho las contabilice ---------------------------------------------------------

def _cliente_con_facturas():
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None or not verticales.esta_activo(cliente["tenant_id"], "contabilizacion"):
        abort(404)
    return cliente


@portal_bp.route("/facturas", methods=["GET", "POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def facturas():
    cliente = _cliente_con_facturas()
    error, datos, anotada = None, {"tipo": request.args.get("tipo") or "recibida", "pct_iva": "21"}, request.args.get("anotada") == "1"
    destino = facturas_portal.trimestre_actual()                   # lo que se sube sin fecha entra con la de hoy
    if request.method == "POST" and request.form.get("modo") == "archivos":
        try:
            archivos = [(a.filename, a.mimetype, a.read(facturas_contables.MAX_ADJUNTO_BYTES + 1)) for a in request.files.getlist("archivos") if a and a.filename]
            if request.form.get("misma_factura") == "1":
                archivos = facturas_contables.unir_paginas(archivos)
            subidas = facturas_contables.subir_desde_portal(cliente["id"], request.form.get("tipo", ""), archivos)
            return redirect(url_for("portal_cliente.facturas", anotada=1, trimestre=destino, repetidas=subidas.repetidas or None))
        except ValueError as e:
            error = _(str(e))
    elif request.method == "POST":
        datos = {c: request.form.get(c, "") for c in ("tipo", "fecha", "numero", "tercero_nombre", "tercero_nif", "total", "pct_iva", "complicada")}
        archivo = request.files.get("archivo")
        adjunto = (archivo.filename, archivo.mimetype, archivo.read(facturas_contables.MAX_ADJUNTO_BYTES + 1)) if archivo is not None and archivo.filename else None
        try:
            facturas_contables.crear_desde_portal(cliente["id"], datos, adjunto)
            return redirect(url_for("portal_cliente.facturas", anotada=1, trimestre=facturas_contables.trimestre_de(datos["fecha"])))
        except ValueError as e:
            error = str(e)
    error = error or (request.args.get("error") or "")[:200] or None
    return render_template("portal_facturas.html", cliente=cliente, lectura_previa=g.portal_rol != "consulta" and not g.get("vista_previa") and portal_lectura_previa.disponible(cliente), tablero=facturas_portal.tablero(cliente["id"], request.args.get("trimestre")), etiqueta=facturas_portal.etiqueta_trimestre,
                           datos=datos, error=error, anotada=anotada, atendida=request.args.get("atendida"), con_informe=verticales.esta_activo(cliente["tenant_id"], "fiscal"), justificantes_pendientes=len(justificantes.pendientes_del_cliente(cliente["id"])), repetidas=request.args.get("repetidas", type=int) or 0, sin_leer={m["factura_id"] for m in facturas_portal.sin_leer_para_cliente(cliente["id"])}, cerrados=facturas_portal.trimestres_cerrados(cliente["id"]), portal_seccion="facturas", textos=facturas_contables.TEXTO_ESTADO_PORTAL,
                           max_archivos=facturas_contables.MAX_ARCHIVOS_POR_SUBIDA)


@portal_bp.route("/facturas/<int:factura_id>/reenviar", methods=["POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def reenviar_factura(factura_id: int):
    """El cliente sube de nuevo una factura que su gestoría le devolvió."""
    cliente = _cliente_con_facturas()
    trimestre = request.form.get("trimestre") or None
    try:
        archivos = [(a.filename, a.mimetype, a.read(facturas_contables.MAX_ADJUNTO_BYTES + 1)) for a in request.files.getlist("archivos") if a and a.filename]
        facturas_portal.reenviar(cliente["id"], factura_id, archivos)
    except ValueError as e:
        return redirect(url_for("portal_cliente.facturas", trimestre=trimestre, error=_(str(e))[:200]) + f"#factura-{factura_id}")
    return redirect(url_for("portal_cliente.facturas", trimestre=trimestre, atendida="reenviada"))


@portal_bp.route("/facturas/<int:factura_id>/entendido", methods=["POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def factura_entendida(factura_id: int):
    """El cliente da por leído el motivo de una factura devuelta y no reenvía nada."""
    cliente = _cliente_con_facturas()
    try:
        facturas_portal.dar_por_vista(cliente["id"], factura_id)
    except ValueError as e:
        return redirect(url_for("portal_cliente.facturas", trimestre=request.form.get("trimestre") or None, error=_(str(e))[:200]))
    return redirect(url_for("portal_cliente.facturas", trimestre=request.form.get("trimestre") or None, atendida="vista"))


@portal_bp.route("/facturas/comprobar", methods=["POST"])
@cliente_login_required
@limiter.limit("120/hour")
def comprobar_archivos():
    """Antes de subir: de las huellas SHA-256 de los archivos elegidos, cuáles ya están enviados (la página avisa; no se bloquea nada)."""
    cliente = _cliente_con_facturas()
    huellas = (request.get_json(silent=True) or {}).get("huellas")
    return {"repetidas": facturas_portal.archivos_ya_enviados(cliente["id"], huellas if isinstance(huellas, list) else [])}


@portal_bp.route("/facturas/leer-previa", methods=["POST"])
@cliente_login_required
@limiter.limit("60/hour")
def leer_previa():
    """Lo que la IA lee de la foto o el PDF que el cliente acaba de elegir, antes de enviarlo (solo si el despacho lo ha activado). No guarda nada."""
    cliente = _cliente_con_facturas()
    if g.get("vista_previa") or g.portal_rol == "consulta" or not portal_lectura_previa.disponible(cliente):
        return {"disponible": False}, 404
    archivo = request.files.get("archivo")
    if archivo is None:
        return {"error": _("Falta el archivo.")}, 400
    datos = archivo.read(portal_lectura_previa.MAX_BYTES + 1)
    try:
        return {"disponible": True, "lectura": portal_lectura_previa.leer(cliente, datos, (archivo.mimetype or "").lower())}
    except ValueError as e:
        return {"disponible": True, "error": _(str(e))}, 422


@portal_bp.route("/facturas/informe.pdf")
@cliente_login_required
def informe_trimestre():
    """El informe del trimestre (el que prepara Guilda Fiscal), solo para despachos que lo usan."""
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        abort(404)
    try:
        pdf = cierre_trimestre.informe_pdf(cliente["tenant_id"], cliente["id"], request.args.get("trimestre", ""))
    except ValueError:
        abort(404)
    if pdf is None:
        abort(404)
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="informe-{request.args.get("trimestre", "")}.pdf"', "X-Content-Type-Options": "nosniff"})


@portal_bp.route("/facturas/<int:factura_id>")
@cliente_login_required
def factura(factura_id: int):
    """Una factura del cliente con su estado, el motivo si se la devolvieron y la conversación con su gestoría."""
    cliente = _cliente_con_facturas()
    f = facturas_portal.detalle_del_cliente(cliente["id"], factura_id)
    if f is None:
        abort(404)
    if not g.get("vista_previa"):
        facturas_portal.marcar_leidos(cliente["tenant_id"], factura_id, "cliente")
    return render_template("portal_factura.html", cliente=cliente, f=f, mensajes=facturas_portal.mensajes(cliente["tenant_id"], factura_id), portal_seccion="facturas",
                           textos=facturas_contables.TEXTO_ESTADO_PORTAL, etiqueta=facturas_portal.etiqueta_trimestre, max_mensaje=facturas_portal.MAX_MENSAJE,
                           error=(request.args.get("error") or "")[:200] or None)


@portal_bp.route("/facturas/<int:factura_id>/mensajes", methods=["POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def mensaje_de_factura(factura_id: int):
    cliente = _cliente_con_facturas()
    try:
        facturas_portal.escribir_como_cliente(cliente["id"], factura_id, request.form.get("texto", ""))
    except ValueError as e:
        if facturas_portal.detalle_del_cliente(cliente["id"], factura_id) is None:
            abort(404)
        return redirect(url_for("portal_cliente.factura", factura_id=factura_id, error=_(str(e))[:200]) + "#mensajes")
    return redirect(url_for("portal_cliente.factura", factura_id=factura_id) + "#mensajes")


# --- Revisar el modelo antes de presentarlo (conformidad del cliente) -----------------------------------------------------------------------------------

def _cliente_con_fiscal():
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None or not verticales.esta_activo(cliente["tenant_id"], "fiscal"):
        abort(404)
    return cliente


@portal_bp.route("/declaraciones/<int:declaracion_id>")
@cliente_login_required
def declaracion(declaracion_id: int):
    """El modelo 303 que la gestoría ha pedido revisar: resultado, cuotas y facturas que lo componen, y los botones «De acuerdo» / «Hay un error»."""
    cliente = _cliente_con_fiscal()
    v = conformidad_declaracion.ver_para_cliente(cliente["id"], declaracion_id)
    if v is None:
        abort(404)
    from .fiscal_resumen_pdf import frase_resultado
    d = v["declaracion"]
    return render_template("portal_declaracion.html", cliente=cliente, v=v, d=d, frase=frase_resultado(d["tipo_declaracion"], d["resultado_centimos"]), portal_seccion="impuestos",
                           con_facturas=verticales.esta_activo(cliente["tenant_id"], "contabilizacion"), pendiente=v["conformidad"]["respuesta"] is None and d["estado"] in conformidad_declaracion.ESTADOS_PEDIBLES,
                           max_comentario=conformidad_declaracion.MAX_COMENTARIO, error=(request.args.get("error") or "")[:200] or None, respondida=request.args.get("respondida"))


@portal_bp.route("/declaraciones/<int:declaracion_id>/conformidad", methods=["POST"])
@cliente_login_required
@limiter.limit("30/hour", methods=["POST"])
def conformidad(declaracion_id: int):
    cliente = _cliente_con_fiscal()
    if conformidad_declaracion.ver_para_cliente(cliente["id"], declaracion_id) is None:
        abort(404)
    resultado = request.form.get("resultado", "")
    try:
        conformidad_declaracion.responder(cliente["id"], declaracion_id, resultado, request.form.get("comentario", ""))
    except ValueError as e:
        return redirect(url_for("portal_cliente.declaracion", declaracion_id=declaracion_id, error=_(str(e))[:200]))
    return redirect(url_for("portal_cliente.declaracion", declaracion_id=declaracion_id, respondida=resultado))


# --- Movimientos del banco que el despacho no sabe explicar y tiquets ---------------------------------------------------------------------------------------

def _archivos_del_formulario(nombre: str = "archivos") -> list[tuple[str, str | None, bytes]]:
    return [(a.filename, a.mimetype, a.read(facturas_contables.MAX_ADJUNTO_BYTES + 1)) for a in request.files.getlist(nombre) if a and a.filename]


@portal_bp.route("/justificantes")
@cliente_login_required
def justificantes_cliente():
    """Los movimientos del banco por los que su gestoría pregunta, con lo que puede contestar, y el formulario para anotar un tiquet."""
    cliente = _cliente_con_facturas()
    todos = justificantes.del_cliente(cliente["id"])
    return render_template("portal_justificantes.html", cliente=cliente, pendientes=[j for j in todos if j["estado"] == "pendiente"], contestados=[j for j in todos if j["estado"] != "pendiente"], portal_seccion="facturas",
                           hoy=date.today().isoformat(), max_comentario=justificantes.MAX_COMENTARIO, max_archivos=facturas_contables.MAX_ARCHIVOS_POR_SUBIDA, contestado=request.args.get("contestado"),
                           error=(request.args.get("error") or "")[:200] or None)


@portal_bp.route("/extracto")
@cliente_login_required
def extracto():
    """Cargar el extracto del banco y ver qué pagos no tienen factura ni tiquet: todo se hace en el navegador, el extracto no se envía."""
    cliente = _cliente_con_facturas()
    return render_template("portal_extracto.html", cliente=cliente, portal_seccion="facturas", puede_anotar=g.portal_rol != "consulta" and not g.get("vista_previa"))


@portal_bp.route("/extracto/datos.json")
@cliente_login_required
@limiter.limit("60/hour")
def extracto_datos():
    """Lo mínimo para comparar un extracto en el navegador: fecha e importe de las facturas del cliente y de los tiquets que ya anotó."""
    cliente = _cliente_con_facturas()
    respuesta = Response(json.dumps(portal_extracto.datos(cliente)), mimetype="application/json")
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@portal_bp.route("/justificantes/<int:justificante_id>", methods=["POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def contestar_justificante(justificante_id: int):
    cliente = _cliente_con_facturas()
    accion = request.form.get("accion", "")
    try:
        justificantes.responder(cliente["id"], justificante_id, accion, request.form.get("comentario", ""), _archivos_del_formulario())
    except ValueError as e:
        return redirect(url_for("portal_cliente.justificantes_cliente", error=_(str(e))[:200]) + f"#justificante-{justificante_id}")
    return redirect(url_for("portal_cliente.justificantes_cliente", contestado=accion))


@portal_bp.route("/justificantes/tiquet", methods=["POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def anotar_tiquet():
    cliente = _cliente_con_facturas()
    archivos = _archivos_del_formulario("archivo")
    try:
        justificantes.anotar_tiquet(cliente["id"], request.form.get("fecha", ""), request.form.get("importe", ""), request.form.get("concepto", ""), archivos[0] if archivos else None)
    except ValueError as e:
        return redirect(url_for("portal_cliente.justificantes_cliente", error=_(str(e))[:200]) + "#tiquet")
    return redirect(url_for("portal_cliente.justificantes_cliente", contestado="tiquet_anotado"))


# --- Firmar un documento y pagar los honorarios de un modelo -------------------------------------------------------------------------------------------------

def _vencimiento_firma_o_404(vencimiento_id: int):
    return _vencimiento_del_cliente_actual(vencimiento_id)


@portal_bp.route("/vencimientos/<int:vencimiento_id>/firma")
@cliente_login_required
def firma_vencimiento(vencimiento_id: int):
    """El documento que la gestoría ha enviado a firmar para este modelo, con el botón que lleva directo a la página de firma."""
    vencimiento = _vencimiento_firma_o_404(vencimiento_id)
    if not vencimiento["documenso_documento_id"]:
        abort(404)
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    firma = portal_firma.consultar(cliente, vencimiento) if not vencimiento["documenso_firmado_en"] else {"estado": "firmado", "enlace": None}
    return render_template("portal_firma.html", cliente=cliente, vencimiento=vencimiento, firma=firma, portal_seccion="impuestos")


@portal_bp.route("/vencimientos/<int:vencimiento_id>/pagar", methods=["POST"])
@cliente_login_required
@limiter.limit("30/hour", methods=["POST"])
def pagar_vencimiento(vencimiento_id: int):
    """Abre el pago con tarjeta de los honorarios confirmados de este modelo (en la página segura de Stripe)."""
    _vencimiento_del_cliente_actual(vencimiento_id)
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    try:
        url = portal_pagos.crear_pago(cliente, vencimiento_id, url_for("portal_cliente.impuestos", pago="ok", _external=True), url_for("portal_cliente.impuestos", pago="cancelado", _external=True))
    except ValueError as e:
        return redirect(url_for("portal_cliente.impuestos", error=_(str(e))[:200]) + f"#vencimiento-{vencimiento_id}")
    return redirect(url, code=303)


@portal_bp.route("/firmas")
@cliente_login_required
def firmas():
    """Los documentos que tiene por firmar y los que ya firmó."""
    cliente = _cliente_actual_o_salir()
    return render_template("portal_firmas.html", cliente=cliente, f=portal_firmas_honorarios.firmas(cliente), portal_seccion="impuestos", puede_decidir=g.portal_rol == "completo" and not g.get("vista_previa"))


@portal_bp.route("/honorarios")
@cliente_login_required
def honorarios_cliente():
    """Los honorarios de su gestoría: lo pendiente de pagar y lo pagado, con el recibo de cada pago."""
    cliente = _cliente_actual_o_salir()
    return render_template("portal_honorarios.html", cliente=cliente, h=portal_firmas_honorarios.honorarios(cliente) if cliente["portal_honorarios"] else None, portal_seccion="impuestos",
                           puede_decidir=g.portal_rol == "completo" and not g.get("vista_previa"))


@portal_bp.route("/honorarios/<int:vencimiento_id>/recibo.pdf")
@cliente_login_required
def recibo_honorarios(vencimiento_id: int):
    cliente = _cliente_actual_o_salir()
    pdf = portal_firmas_honorarios.recibo_pdf(cliente, vencimiento_id) if cliente["portal_honorarios"] else None
    if pdf is None:
        abort(404)
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="recibo-{vencimiento_id}.pdf"', "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


# --- La carpeta del año -----------------------------------------------------------------------------------------------------------------------------------------

@portal_bp.route("/carpeta")
@cliente_login_required
def carpeta():
    """Justificantes, constancias, informes trimestrales y resúmenes de modelos presentados de un año, con un ZIP para descargarlo todo."""
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        _cerrar_sesion_del_portal()
        return redirect(url_for("portal_cliente.entrar"))
    anios = portal_carpeta.anios_disponibles(cliente)
    anio = request.args.get("anio", type=int)
    if anio not in anios:
        anio = anios[0] if anios else date.today().year
    return render_template("portal_carpeta.html", cliente=cliente, anios=anios, c=portal_carpeta.contenido(cliente, anio), anio=anio, portal_seccion="carpeta")


@portal_bp.route("/carpeta/<int:anio>.zip")
@cliente_login_required
def carpeta_zip(anio: int):
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None or anio not in portal_carpeta.anios_disponibles(cliente):
        abort(404)
    return Response(portal_carpeta.zip_del_anio(cliente, anio), mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="carpeta-{anio}.zip"', "X-Content-Type-Options": "nosniff"})


@portal_bp.route("/carpeta/informe-<int:anio>.pdf")
@cliente_login_required
def carpeta_informe(anio: int):
    """El informe del año: lo presentado, lo firmado, los honorarios y lo que el cliente envió, en un PDF."""
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None or anio not in portal_carpeta.anios_disponibles(cliente):
        abort(404)
    return Response(portal_informe_anual.generar(cliente, anio), mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="informe-{anio}.pdf"', "X-Content-Type-Options": "nosniff"})


@portal_bp.route("/carpeta/resumen/<int:declaracion_id>.pdf")
@cliente_login_required
def carpeta_resumen(declaracion_id: int):
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    pdf = portal_carpeta.pdf_resumen(cliente, declaracion_id) if cliente is not None else None
    if pdf is None:
        abort(404)
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="resumen-303-{declaracion_id}.pdf"', "X-Content-Type-Options": "nosniff"})


# --- El buzón único -------------------------------------------------------------------------------------------------------------------------------------------

@portal_bp.route("/mensajes")
@cliente_login_required
def mensajes():
    """Todas las conversaciones con la gestoría en una lista: sobre un modelo, sobre una factura o sobre un trabajo en curso."""
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        _cerrar_sesion_del_portal()
        return redirect(url_for("portal_cliente.entrar"))
    return render_template("portal_mensajes.html", cliente=cliente, conversaciones=portal_buzon.conversaciones(cliente), portal_seccion="mensajes", con_facturas=verticales.esta_activo(cliente["tenant_id"], "contabilizacion"))


# --- Mi cuenta: avisos, personas con acceso, móvil ----------------------------------------------------------------------------------------------------------

def _base_publica() -> str:
    import os
    return (os.environ.get("GUILDA_URL_PUBLICA", "").strip() or request.host_url).rstrip("/")


def _cliente_actual_o_salir():
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        abort(404)
    return cliente


@portal_bp.route("/cuenta")
@cliente_login_required
def cuenta():
    """Lo que cada persona ajusta de su acceso: qué avisos recibe, quién más puede entrar, el móvil (subir facturas, avisos, instalar) y su sesión."""
    cliente = _cliente_actual_o_salir()
    yo = g.get("portal_email") or portal_personas.limpio(cliente["email"])
    previa = bool(g.get("vista_previa"))
    subida = None
    if portal_subida_rapida.activa_para(cliente) and g.portal_rol != "consulta" and not previa:
        enlace = portal_subida_rapida.url(cliente, _base_publica())
        subida = {"url": enlace, "qr": qr.svg(enlace, _("Código QR para subir facturas desde el móvil")), "correo": portal_subida_rapida.direccion_de(cliente)}
    agenda = None
    if not previa and g.portal_rol != "consulta":
        ruta = url_for("portal_cliente.calendario", cliente_id=cliente["id"], token=portal_calendario.token_de(cliente))
        base = _base_publica()
        agenda = {"https": f"{base.rstrip('/')}{ruta}", "webcal": "webcal://" + f"{base.rstrip('/')}{ruta}".split("://", 1)[-1]}
    seguridad = None
    if not previa:
        sid = session.get("portal_sid")
        seguridad = {"sesiones": portal_seguridad.listar(cliente, yo, sid), "segundo_factor": portal_seguridad.activo(cliente, yo), "codigos": portal_seguridad.codigos_restantes(cliente, yo)}
        pendiente = portal_seguridad.secreto_pendiente(cliente, yo)
        if pendiente and not seguridad["segundo_factor"]:
            uri = portal_seguridad.uri_totp(yo, pendiente)
            seguridad["alta"] = {"secreto": pendiente, "qr": qr.svg(uri, _("Código QR para añadir la cuenta a tu aplicación de autenticación"))}
    return render_template("portal_cuenta.html", cliente=cliente, yo=yo, seguridad=seguridad, agenda=agenda, codigos_nuevos=session.pop("portal_codigos_nuevos", None), avisos=portal_personas.avisos_de(cliente, yo), niveles=portal_personas.NIVELES_AVISO, personas=portal_personas.listar(cliente), roles=portal_personas.ROLES,
                           puede_gestionar=g.portal_rol == "completo" and not previa, subida=subida, push_disponible=portal_push.disponible() and not previa, push_activo=portal_push.tiene(cliente, yo) if not previa else 0,
                           portal_seccion="cuenta", guardado=request.args.get("guardado"), error=(request.args.get("error") or "")[:200] or None, max_contactos=portal_personas.MAX_CONTACTOS)


def _yo(cliente) -> str:
    return g.get("portal_email") or portal_personas.limpio(cliente["email"])


@portal_bp.route("/sesiones/<int:sesion_id>/cerrar", methods=["POST"])
@cliente_login_required
def cerrar_sesion_remota(sesion_id: int):
    cliente = _cliente_actual_o_salir()
    if portal_seguridad.cerrar(cliente, _yo(cliente), sesion_id):
        auditoria.registrar(cliente["tenant_id"], None, "portal.sesion_cerrada", "cliente_fiscal", cliente["id"], {"quien": _yo(cliente)})
    return redirect(url_for("portal_cliente.cuenta", guardado="sesion") + "#seguridad")


@portal_bp.route("/sesiones/cerrar-otras", methods=["POST"])
@cliente_login_required
def cerrar_otras_sesiones():
    cliente = _cliente_actual_o_salir()
    n = portal_seguridad.cerrar_otras(cliente, _yo(cliente), session.get("portal_sid"))
    auditoria.registrar(cliente["tenant_id"], None, "portal.sesiones_cerradas", "cliente_fiscal", cliente["id"], {"quien": _yo(cliente), "cuantas": n})
    return redirect(url_for("portal_cliente.cuenta", guardado="sesiones") + "#seguridad")


@portal_bp.route("/segundo-factor/iniciar", methods=["POST"])
@cliente_login_required
def segundo_factor_iniciar():
    cliente = _cliente_actual_o_salir()
    try:
        portal_seguridad.iniciar_alta(cliente, _yo(cliente))
    except ValueError as e:
        return redirect(url_for("portal_cliente.cuenta", error=_(str(e))[:200]) + "#seguridad")
    return redirect(url_for("portal_cliente.cuenta") + "#seguridad")


@portal_bp.route("/segundo-factor/confirmar", methods=["POST"])
@cliente_login_required
@limiter.limit("20/hour", methods=["POST"])
def segundo_factor_confirmar():
    cliente = _cliente_actual_o_salir()
    try:
        codigos = portal_seguridad.confirmar_alta(cliente, _yo(cliente), request.form.get("codigo", ""))
    except ValueError as e:
        return redirect(url_for("portal_cliente.cuenta", error=_(str(e))[:200]) + "#seguridad")
    auditoria.registrar(cliente["tenant_id"], None, "portal.segundo_factor_activado", "cliente_fiscal", cliente["id"], {"quien": _yo(cliente)})
    session["portal_codigos_nuevos"] = codigos
    return redirect(url_for("portal_cliente.cuenta", guardado="segundo-factor") + "#seguridad")


@portal_bp.route("/segundo-factor/quitar", methods=["POST"])
@cliente_login_required
@limiter.limit("20/hour", methods=["POST"])
def segundo_factor_quitar():
    cliente = _cliente_actual_o_salir()
    if not portal_seguridad.desactivar(cliente, _yo(cliente), request.form.get("codigo", "")):
        return redirect(url_for("portal_cliente.cuenta", error=_("El código no es correcto.")) + "#seguridad")
    auditoria.registrar(cliente["tenant_id"], None, "portal.segundo_factor_quitado", "cliente_fiscal", cliente["id"], {"quien": _yo(cliente)})
    return redirect(url_for("portal_cliente.cuenta", guardado="segundo-factor-quitado") + "#seguridad")


@portal_bp.route("/calendario/<int:cliente_id>/<token>.ics")
@limiter.limit("240/hour")
def calendario(cliente_id: int, token: str):
    """El calendario de plazos del cliente para su agenda. Sin sesión: lo abre la aplicación de calendario con el enlace secreto de Mi cuenta."""
    cliente = portal_calendario.cliente_por_token(token, cliente_id)
    if cliente is None:
        abort(404)
    return Response(portal_calendario.contenido(cliente), mimetype="text/calendar", headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff",
                                                                                              "Content-Disposition": 'inline; filename="plazos.ics"'})


@portal_bp.route("/valorar", methods=["POST"])
@cliente_login_required
@limiter.limit("30/hour", methods=["POST"])
def valorar():
    """«¿Qué tal ha ido?»: la valoración de un trámite ya resuelto. Una nota baja avisa a quien lleva al cliente."""
    cliente = _cliente_actual_o_salir()
    tipo, referencia = request.form.get("tipo", ""), request.form.get("referencia", "")
    destino = url_for("portal_cliente.peticion", peticion_id=int(referencia)) if tipo == "peticion" and referencia.isdigit() else url_for("portal_cliente.dashboard")
    try:
        baja = portal_valoraciones.valorar(cliente, g.portal_email or cliente["email"], tipo, referencia, request.form.get("puntos"), request.form.get("comentario", ""))
    except ValueError as e:
        return redirect(destino + "?" + urlencode({"error": _(str(e))[:200]}))
    if baja:
        facturas_contables.avisar_al_equipo(cliente, _("%(cliente)s ha valorado con nota baja un trámite", cliente=cliente["nombre"]), _("Conviene hablar con el cliente: ha puntuado %(n)s o menos sobre 5.", n=portal_valoraciones.NOTA_BAJA),
                                           url_for("fiscal.portal_actividad"), {"valoracion": tipo})
    return redirect(destino + "?valorado=1")


@portal_bp.route("/citas", methods=["GET", "POST"])
@cliente_login_required
@limiter.limit("20/hour", methods=["POST"])
def citas():
    """Pedir una llamada, una videollamada o una visita a la gestoría, y ver las citas pedidas y confirmadas."""
    cliente = _cliente_actual_o_salir()
    error = None
    if request.method == "POST":
        try:
            cid = portal_citas.solicitar(cliente, g.portal_email or cliente["email"], request.form.get("canal", ""), request.form.get("motivo", ""), request.form.get("preferencias", ""))
            auditoria.registrar(cliente["tenant_id"], None, "portal.cita_pedida", "portal_cita", cid, {"quien": g.portal_email or "titular", "canal": request.form.get("canal", "")})
            facturas_contables.avisar_al_equipo(cliente, _("%(cliente)s pide una cita", cliente=cliente["nombre"]), request.form.get("motivo", "")[:100], url_for("fiscal.citas_portal"), {"cita": cid})
            return redirect(url_for("portal_cliente.citas", pedida=1))
        except ValueError as e:
            error = _(str(e))
    return render_template("portal_citas.html", cliente=cliente, lista=portal_citas.listar(cliente), canales=portal_citas.CANALES, error=error, pedida=request.args.get("pedida"), portal_seccion="inicio",
                           puede_pedir=g.portal_rol != "consulta" and not g.get("vista_previa"), hoy=datetime.now().isoformat(timespec="minutes"))


@portal_bp.route("/citas/<int:cita_id>/cancelar", methods=["POST"])
@cliente_login_required
def cancelar_cita(cita_id: int):
    cliente = _cliente_actual_o_salir()
    if portal_citas.cancelar(cliente, g.portal_email or cliente["email"], cita_id):
        auditoria.registrar(cliente["tenant_id"], None, "portal.cita_cancelada", "portal_cita", cita_id, {"quien": g.portal_email or "titular"})
    return redirect(url_for("portal_cliente.citas"))


@portal_bp.route("/peticiones")
@cliente_login_required
def peticiones():
    """Lo que la gestoría le ha pedido al cliente, con su fecha límite y lo que ya ha enviado."""
    cliente = _cliente_actual_o_salir()
    return render_template("portal_peticiones.html", cliente=cliente, lista=portal_peticiones.listar(cliente), portal_seccion="inicio", puede_subir=g.portal_rol != "consulta" and not g.get("vista_previa"))


@portal_bp.route("/peticiones/<int:peticion_id>", methods=["GET", "POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def peticion(peticion_id: int):
    cliente = _cliente_actual_o_salir()
    p = portal_peticiones.obtener(cliente, peticion_id)
    if p is None:
        abort(404)
    error = None
    if request.method == "POST":
        ficheros = [(f.filename or "archivo", (f.mimetype or "").lower(), f.read(portal_peticiones.MAX_BYTES + 1)) for f in request.files.getlist("archivos") if f and f.filename]
        try:
            n = portal_peticiones.subir(cliente, peticion_id, ficheros, g.portal_email or "titular")
            auditoria.registrar(cliente["tenant_id"], None, "portal.peticion_enviada", "portal_peticion", peticion_id, {"quien": g.portal_email or "titular", "archivos": n})
            portal_peticiones_avisar_equipo(cliente, p, n)
            return redirect(url_for("portal_cliente.peticion", peticion_id=peticion_id, enviado=n))
        except ValueError as e:
            error = _(str(e))
    puede_valorar = p["estado"] == "revisada" and g.portal_rol != "consulta" and not g.get("vista_previa") and not portal_valoraciones.ya_valorada(cliente, g.portal_email or cliente["email"], "peticion", peticion_id)
    return render_template("portal_peticion.html", cliente=cliente, p=p, puede_valorar=puede_valorar, valorado=request.args.get("valorado"), error_valoracion=(request.args.get("error") or "")[:200] or None, archivos=portal_peticiones.archivos(cliente, peticion_id), error=error, enviado=request.args.get("enviado", type=int),
                           puede_subir=g.portal_rol != "consulta" and not g.get("vista_previa") and p["estado"] in ("pendiente", "enviada"), max_archivos=portal_peticiones.MAX_ARCHIVOS, portal_seccion="inicio")


def _adjuntos_de_conversacion() -> list[tuple[str, str, bytes]]:
    return [(f.filename or "archivo", (f.mimetype or "").lower(), f.read(portal_conversaciones.MAX_BYTES + 1)) for f in request.files.getlist("archivos")[:portal_conversaciones.MAX_ADJUNTOS + 1] if f and f.filename]


def _puede_escribir() -> bool:
    return g.portal_rol != "consulta" and not g.get("vista_previa")


def _conversacion_avisar_equipo(cliente, cid: int, asunto: str, texto: str, nueva: bool) -> None:
    """Cuando el cliente escribe (o abre un hilo), lo sabe quien lleva al cliente."""
    titulo = _("%(cliente)s te ha escrito: %(asunto)s", cliente=cliente["nombre"], asunto=asunto[:80]) if nueva else _("%(cliente)s ha contestado: %(asunto)s", cliente=cliente["nombre"], asunto=asunto[:80])
    facturas_contables.avisar_al_equipo(cliente, titulo, texto, url_for("fiscal.editar_cliente", cliente_id=cliente["id"]) + f"#conversacion-{cid}", {"conversacion": cid})


@portal_bp.route("/cuestionarios")
@cliente_login_required
def cuestionarios():
    cliente = _cliente_actual_o_salir()
    return render_template("portal_cuestionarios.html", cliente=cliente, lista=portal_cuestionarios.listar(cliente), portal_seccion="inicio")


@portal_bp.route("/cuestionarios/<int:cuestionario_id>", methods=["GET", "POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def cuestionario(cuestionario_id: int):
    cliente = _cliente_actual_o_salir()
    c = portal_cuestionarios.obtener(cliente, cuestionario_id)
    if c is None:
        abort(404)
    error = None
    puede = _puede_escribir() and c["estado"] == "pendiente"
    if request.method == "POST":
        if not puede:
            abort(403)
        try:
            if portal_cuestionarios.responder(cliente, cuestionario_id, request.form, g.portal_email or cliente["email"] or ""):
                auditoria.registrar(cliente["tenant_id"], None, "portal.cuestionario_respondido", "portal_cuestionario", cuestionario_id, {"quien": g.portal_email or "titular"})
                facturas_contables.avisar_al_equipo(cliente, _("%(cliente)s ha contestado: %(titulo)s", cliente=cliente["nombre"], titulo=c["titulo"][:80]), _("Cuestionario contestado, pendiente de revisar."),
                                                    url_for("fiscal.editar_cliente", cliente_id=cliente["id"]) + f"#cuestionario-{cuestionario_id}", {"cuestionario": cuestionario_id})
                return redirect(url_for("portal_cliente.cuestionario", cuestionario_id=cuestionario_id, enviado=1))
            error = _("Este cuestionario ya no admite respuestas.")
        except ValueError as e:
            error = _(str(e))
    return render_template("portal_cuestionario.html", cliente=cliente, c=c, puede=puede, error=error, enviado=request.args.get("enviado"), valores=request.form if request.method == "POST" else {}, portal_seccion="inicio")


@portal_bp.route("/mis-datos", methods=["POST"])
@cliente_login_required
@limiter.limit("3/hour")
def descargar_mis_datos():
    """Una copia de los datos de este cliente en un ZIP (solo el titular o quien tiene acceso completo; nunca desde la vista previa del despacho)."""
    cliente = _cliente_actual_o_salir()
    if g.get("vista_previa") or g.portal_rol != "completo":
        abort(403)
    contenido = portal_datos.zip_de_mis_datos(cliente, g.portal_email or cliente["email"] or "")
    auditoria.registrar(cliente["tenant_id"], None, "portal.datos_descargados", "cliente_fiscal", cliente["id"], {"quien": g.portal_email or "titular", "bytes": len(contenido)})
    r = Response(contenido, mimetype="application/zip")
    r.headers.set("Content-Disposition", "attachment", filename="mis-datos.zip")
    r.headers.set("X-Content-Type-Options", "nosniff")
    r.headers.set("Cache-Control", "no-store")
    return r


@portal_bp.route("/pedir-supresion", methods=["POST"])
@cliente_login_required
@limiter.limit("3/day")
def pedir_supresion():
    """El cliente pide la supresión de sus datos: se abre una conversación con su gestoría (que es quien responde de ellos) y se avisa al equipo."""
    cliente = _cliente_actual_o_salir()
    if g.get("vista_previa") or g.portal_rol != "completo" or request.form.get("confirmo") != "1":
        abort(403)
    email = g.portal_email or cliente["email"] or ""
    try:
        cid = portal_datos.pedir_supresion(cliente, email)
    except ValueError as e:
        return redirect(url_for("portal_cliente.cuenta", error=_(str(e))[:200]) + "#tus-datos")
    auditoria.registrar(cliente["tenant_id"], None, "portal.supresion_solicitada", "cliente_fiscal", cliente["id"], {"quien": email, "conversacion": cid})
    _conversacion_avisar_equipo(cliente, cid, _("Solicitud de supresión de mis datos (RGPD)"), _("Solicitud de supresión de datos"), True)
    return redirect(url_for("portal_cliente.conversacion", conversacion_id=cid, enviado=1))


@portal_bp.route("/avisos")
@cliente_login_required
def avisos():
    """El centro de avisos: todo lo que ha pasado para esta persona, lo nuevo primero y marcado. Al abrirlo, lo que se ve pasa a leído."""
    cliente = _cliente_actual_o_salir()
    email = g.get("portal_email") or cliente["email"] or ""
    lista = portal_novedades.listar(cliente, email)
    if not g.get("vista_previa"):
        portal_novedades.marcar_leidas(cliente, email)
    persona = next((p for p in portal_personas.listar(cliente) if p["email"] == email.lower()), None)
    return render_template("portal_avisos.html", cliente=cliente, avisos=lista, avisos_correo=(persona or {}).get("avisos"), portal_seccion="avisos")


@portal_bp.route("/conversaciones/nueva", methods=["GET", "POST"])
@cliente_login_required
@limiter.limit("20/hour", methods=["POST"])
def conversacion_nueva():
    """Abre una conversación con la gestoría sobre cualquier cosa (o sobre una petición de documentos, con `?peticion=`)."""
    cliente = _cliente_actual_o_salir()
    if not _puede_escribir():
        abort(403)
    peticion_id = request.values.get("peticion", type=int)
    p = portal_peticiones.obtener(cliente, peticion_id) if peticion_id else None
    if peticion_id and p is None:
        abort(404)
    error = None
    asunto = request.form.get("asunto", "") if request.method == "POST" else (_("Sobre: %(titulo)s", titulo=p["titulo"]) if p else "")
    texto = request.form.get("texto", "")
    if request.method == "POST":
        try:
            cid = portal_conversaciones.iniciar(cliente, asunto, texto, "cliente", g.portal_email or cliente["email"] or "", peticion_id=p["id"] if p else None, archivos=_adjuntos_de_conversacion())
            auditoria.registrar(cliente["tenant_id"], None, "portal.conversacion_abierta", "portal_conversacion", cid, {"quien": g.portal_email or "titular"})
            _conversacion_avisar_equipo(cliente, cid, asunto, texto, True)
            return redirect(url_for("portal_cliente.conversacion", conversacion_id=cid, enviado=1))
        except ValueError as e:
            error = _(str(e))
    return render_template("portal_conversacion_nueva.html", cliente=cliente, asunto=asunto, texto=texto, error=error, peticion=p, max_asunto=portal_conversaciones.MAX_ASUNTO, max_texto=portal_conversaciones.MAX_TEXTO,
                           portal_seccion="mensajes")


@portal_bp.route("/conversaciones/<int:conversacion_id>", methods=["GET", "POST"])
@cliente_login_required
@limiter.limit("60/hour", methods=["POST"])
def conversacion(conversacion_id: int):
    cliente = _cliente_actual_o_salir()
    c = portal_conversaciones.obtener(cliente, conversacion_id)
    if c is None:
        abort(404)
    error = None
    if request.method == "POST":
        if not _puede_escribir():
            abort(403)
        texto = request.form.get("texto", "")
        try:
            portal_conversaciones.responder(cliente, conversacion_id, texto, "cliente", g.portal_email or cliente["email"] or "", archivos=_adjuntos_de_conversacion())
            auditoria.registrar(cliente["tenant_id"], None, "portal.conversacion_respuesta", "portal_conversacion", conversacion_id, {"quien": g.portal_email or "titular"})
            _conversacion_avisar_equipo(cliente, conversacion_id, c["asunto"], texto, False)
            return redirect(url_for("portal_cliente.conversacion", conversacion_id=conversacion_id, enviado=1) + "#ultimo")
        except ValueError as e:
            error = _(str(e))
    if not g.get("vista_previa"):
        portal_conversaciones.marcar_leida(cliente, conversacion_id, "cliente")
        c = portal_conversaciones.obtener(cliente, conversacion_id)
    peticion = portal_peticiones.obtener(cliente, c["peticion_id"]) if c["peticion_id"] else None
    return render_template("portal_conversacion.html", cliente=cliente, c=c, peticion=peticion, error=error, enviado=request.args.get("enviado"), puede_escribir=_puede_escribir(),
                           max_texto=portal_conversaciones.MAX_TEXTO, portal_seccion="mensajes")


def portal_peticiones_avisar_equipo(cliente, p: dict, n: int) -> None:
    """Cuando el cliente envía lo pedido, lo sabe quien lleva al cliente."""
    facturas_contables.avisar_al_equipo(cliente, _("%(cliente)s ha enviado lo que le pedías", cliente=cliente["nombre"]), _("«%(titulo)s»: %(n)s archivo(s) por revisar.", titulo=p["titulo"], n=n),
                                       url_for("fiscal.editar_cliente", cliente_id=cliente["id"]) + "#peticiones", {"peticion": p["id"]})


@portal_bp.route("/conversaciones/<int:conversacion_id>/adjunto/<int:documento_id>")
@cliente_login_required
def adjunto_de_conversacion(conversacion_id: int, documento_id: int):
    """Descarga un archivo adjunto a un mensaje de una conversación del propio cliente (nunca de otra)."""
    cliente = _cliente_actual_o_salir()
    try:
        doc = portal_conversaciones.adjunto_de(cliente, conversacion_id, documento_id)
    except Exception:  # noqa: BLE001 -- despacho cifrado y bloqueado
        abort(503)
    if doc is None:
        abort(404)
    respuesta = Response(bytes(doc["contenido"]), mimetype=doc["tipo_mime"])
    respuesta.headers.set("Content-Disposition", "attachment", filename=doc["nombre_archivo"])
    respuesta.headers.set("X-Content-Type-Options", "nosniff")
    return respuesta


@portal_bp.route("/preferencias", methods=["POST"])
@cliente_login_required
def guardar_preferencias():
    cliente = _cliente_actual_o_salir()
    try:
        portal_personas.fijar_avisos(cliente, g.get("portal_email"), request.form.get("avisos", ""))
    except ValueError as e:
        return redirect(url_for("portal_cliente.cuenta", error=_(str(e))[:200]))
    return redirect(url_for("portal_cliente.cuenta", guardado="avisos"))


@portal_bp.route("/preferencias/<token>", methods=["GET", "POST"])
@limiter.limit("60/hour")
def preferencias_por_enlace(token: str):
    """El enlace del pie de cada correo: cambiar cuánto avisamos a esta persona sin tener que entrar al portal. El enlace va firmado y solo sirve para eso."""
    leido = portal_personas.leer_token_preferencias(token)
    if leido is None:
        return render_template("portal_preferencias.html", invalido=True), 404
    cliente, email = leido
    guardado = False
    if request.method == "POST":
        try:
            portal_personas.fijar_avisos(cliente, email, request.form.get("avisos", ""))
            guardado = True
        except ValueError:
            pass
    return render_template("portal_preferencias.html", invalido=False, cliente=cliente, email=email, avisos=portal_personas.avisos_de(cliente, email), niveles=portal_personas.NIVELES_AVISO, guardado=guardado)


@portal_bp.route("/contactos", methods=["POST"])
@cliente_login_required
@limiter.limit("30/hour", methods=["POST"])
def anadir_contacto():
    cliente = _cliente_actual_o_salir()
    try:
        portal_personas.anadir(cliente, request.form.get("email", ""), request.form.get("nombre", ""), request.form.get("rol", ""))
    except ValueError as e:
        return redirect(url_for("portal_cliente.cuenta", error=_(str(e))[:200]) + "#personas")
    return redirect(url_for("portal_cliente.cuenta", guardado="persona") + "#personas")


@portal_bp.route("/contactos/<int:contacto_id>/perfil", methods=["POST"])
@cliente_login_required
def cambiar_perfil_contacto(contacto_id: int):
    cliente = _cliente_actual_o_salir()
    try:
        portal_personas.cambiar_rol(cliente, contacto_id, request.form.get("rol", ""))
    except ValueError as e:
        return redirect(url_for("portal_cliente.cuenta", error=_(str(e))[:200]) + "#personas")
    return redirect(url_for("portal_cliente.cuenta", guardado="persona") + "#personas")


@portal_bp.route("/contactos/<int:contacto_id>/quitar", methods=["POST"])
@cliente_login_required
def quitar_contacto(contacto_id: int):
    cliente = _cliente_actual_o_salir()
    try:
        portal_personas.quitar(cliente, contacto_id)
    except ValueError as e:
        return redirect(url_for("portal_cliente.cuenta", error=_(str(e))[:200]) + "#personas")
    return redirect(url_for("portal_cliente.cuenta", guardado="quitada") + "#personas")


@portal_bp.route("/bienvenida", methods=["POST"])
@cliente_login_required
def bienvenida_vista():
    portal_personas.marcar_bienvenida(_cliente_actual_o_salir(), g.get("portal_email"))
    return redirect(url_for("portal_cliente.dashboard"))


# --- Avisos en el móvil (Web Push) --------------------------------------------------------------------------------------------------------------------------

@portal_bp.route("/push/clave")
@cliente_login_required
def push_clave():
    from . import push
    return {"clave": push.VAPID_PUBLICA if portal_push.disponible() else ""}


@portal_bp.route("/push/suscribir", methods=["POST"])
@cliente_login_required
@limiter.limit("30/hour", methods=["POST"])
def push_suscribir():
    try:
        portal_push.suscribir(_cliente_actual_o_salir(), g.get("portal_email"), request.get_json(silent=True) or {})
    except ValueError as e:
        return {"error": _(str(e))}, 400
    return {"ok": True}


@portal_bp.route("/push/baja", methods=["POST"])
@cliente_login_required
def push_baja():
    portal_push.dar_de_baja(_cliente_actual_o_salir(), str((request.get_json(silent=True) or {}).get("endpoint") or ""))
    return {"ok": True}


# --- Subir facturas desde el móvil con un enlace (sin entrar) -------------------------------------------------------------------------------------------------

@portal_bp.route("/subida/<token>", methods=["GET", "POST"])
@limiter.limit("60/hour")
def subida_rapida(token: str):
    """La página a la que lleva el código QR: elegir o fotografiar facturas y tiquets y enviarlos. El enlace es un secreto del cliente que solo sirve para subir (no se ve nada de su portal)."""
    cliente = portal_subida_rapida.cliente_por_token(token)
    if cliente is None or not portal_subida_rapida.activa_para(cliente):
        abort(404)
    error = enviadas = None
    if request.method == "POST":
        try:
            archivos = [(a.filename, a.mimetype, a.read(facturas_contables.MAX_ADJUNTO_BYTES + 1)) for a in request.files.getlist("archivos")[:facturas_contables.MAX_ARCHIVOS_POR_SUBIDA + 1] if a and a.filename]
            if len(archivos) > facturas_contables.MAX_ARCHIVOS_POR_SUBIDA:
                raise ValueError(_("Puedes enviar hasta %(n)s archivos a la vez.", n=facturas_contables.MAX_ARCHIVOS_POR_SUBIDA))
            if not archivos:
                raise ValueError(_("Elige al menos una foto o un PDF."))
            if request.form.get("misma_factura") == "1":
                archivos = facturas_contables.unir_paginas(archivos)
            subidas = facturas_contables.subir_desde_portal(cliente["id"], "emitida" if request.form.get("tipo") == "emitida" else "recibida", archivos, nota="Subida desde el móvil con el enlace rápido, pendiente de leer.")
            auditoria.registrar(cliente["tenant_id"], None, "portal.subida_rapida", "cliente_fiscal", cliente["id"], {"archivos": len(subidas)})
            enviadas = len(subidas)
        except ValueError as e:
            error = _(str(e))
    return render_template("portal_subida_rapida.html", cliente=cliente, token=token, error=error, enviadas=enviadas, max_archivos=facturas_contables.MAX_ARCHIVOS_POR_SUBIDA)


@portal_bp.route("/subida/renovar", methods=["POST"])
@cliente_login_required
@limiter.limit("10/hour", methods=["POST"])
def renovar_enlace_subida():
    portal_subida_rapida.renovar(_cliente_actual_o_salir())
    return redirect(url_for("portal_cliente.cuenta", guardado="enlace") + "#movil")


# --- Buscar ------------------------------------------------------------------------------------------------------------------------------------------------------------

@portal_bp.route("/buscar")
@cliente_login_required
def buscar():
    cliente = _cliente_actual_o_salir()
    return render_template("portal_buscar.html", cliente=cliente, r=portal_busqueda.buscar(cliente, request.args.get("q", "")), portal_seccion="buscar")


# --- Instalar el portal como una app --------------------------------------------------------------------------------------------------------------------------

@portal_bp.route("/manifest.webmanifest")
def manifiesto():
    """El portal instalable en el móvil: arranca en su portada y no se sale de /portal/."""
    import json
    cuerpo = {"name": "Guilda Work", "short_name": "Mi gestoría", "description": _("Tu portal de cliente: lo que tienes que hacer, tus facturas e impuestos y tus mensajes."), "start_url": "/portal/", "scope": "/portal/", "display": "standalone",
              "background_color": "#f5f6f8", "theme_color": "#f5f6f8", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"}, {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                                                                                {"src": "/static/pwa/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
    return Response(json.dumps(cuerpo, ensure_ascii=False), mimetype="application/manifest+json")
