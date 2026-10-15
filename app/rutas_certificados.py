"""Pantallas de «Certificados» (inventario de certificados digitales X.509 del despacho): ver app/certificados.py. Solo para custodios y supervisores, y solo si el despacho tiene
el módulo de Gestoría. Nunca se sube ni se pide una clave privada: solo material público (PEM/DER)."""
import base64

from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from flask_babel import lazy_gettext as _l

from datetime import date, timedelta

from . import certificados as ce
from . import db, verticales
from .auth import login_required

certificados_bp = Blueprint("certificados", __name__, url_prefix="/certificados")

TEMPORAL = {"vigente": _l("Vigente"), "caducado": _l("Caducado"), "todavia_no_vigente": _l("Todavía no vigente"), "desconocido": _l("Sin fechas")}
CADENA = {"no_comprobada": _l("No comprobada"), "valida": _l("Válida"), "invalida": _l("Inválida"), "indeterminada": _l("Indeterminada")}
REVOCACION = {"no_comprobada": _l("No comprobada"), "no_revocado_en_comprobacion": _l("No revocado (en la última comprobación)"), "revocado": _l("Revocado"), "indeterminada": _l("Indeterminada")}
CLAVE = {"no_declarada": _l("Sin declarar"), "declarada_en_medio_autorizado": _l("Declarada en un medio autorizado"), "no_disponible": _l("No disponible")}
OPERATIVO = {"inventariado": _l("Inventariado"), "autorizado": _l("Autorizado"), "suspendido": _l("Suspendido"), "sustituido": _l("Sustituido"), "archivado": _l("Archivado")}
FASES_TEXTO = {"sin_iniciar": _l("Sin iniciar"), "en_gestion": _l("En gestión"), "pendiente_titular": _l("Pendiente del titular"), "obtenido": _l("Obtenido"), "validado": _l("Validado"),
               "implantado": _l("Implantado"), "cerrado": _l("Cerrado"), "cancelada": _l("Cancelada")}
SERVICIOS_TEXTO = {"acceso_buzon": _l("Acceso a un buzón de notificaciones"), "firma": _l("Firma"), "presentacion": _l("Presentación de impuestos"), "otro": _l("Otro")}
TITULAR = {"persona_fisica": _l("Persona física"), "persona_juridica": _l("Persona jurídica"), "representante": _l("Representante")}
RIESGO = {"cobertura_desconocida": _l("Cobertura desconocida"), "caduca_antes": _l("Caduca antes del vencimiento"), "sin_alternativa": _l("Sin alternativa autorizada")}


@certificados_bp.before_request
def _solo_con_gestoria_y_permiso():
    if g.get("usuario_id") is None:
        return                                   # sin sesión: login_required se ocupa
    if g.get("tenant_id") is None:
        abort(403)
    if not verticales.esta_activo(g.tenant_id, "gestoria"):
        abort(404)
    if not ce.puede_gestionar(g.usuario_id, g.tenant_id):
        abort(403)


@certificados_bp.app_context_processor
def _inyectar():
    # Sin consultas: los dos permisos ya viajan en `g` desde el principio de la petición (el menú se pinta en todas las pantallas).
    return {"puede_certificados": lambda: bool(g.get("usuario_id") and g.get("tenant_id") and (g.get("supervisor_tenant") or g.get("custodio_certificados")))}


def _tipos_texto() -> dict:
    return {k: v["nombre"] for k, v in ce.TIPOS_CERTIFICADO.items()}


def _ctx_textos() -> dict:
    return {"t_tipos": _tipos_texto(), "tipos_cert": ce.TIPOS_CERTIFICADO, "t_temporal": TEMPORAL, "t_cadena": CADENA, "t_revocacion": REVOCACION, "t_clave": CLAVE, "t_operativo": OPERATIVO, "t_fases": FASES_TEXTO, "t_servicios": SERVICIOS_TEXTO,
            "t_titular": TITULAR, "t_riesgo": RIESGO}


def _volver(cid: int | None = None, **kw):
    return redirect(url_for("certificados.detalle", certificado_id=cid, **kw) if cid else url_for("certificados.lista", **kw))


@certificados_bp.route("/")
@login_required
def lista():
    a = request.args
    q, temporal, operativo, plazo = a.get("q", ""), a.get("temporal") or None, a.get("operativo") or None, a.get("plazo") or None
    cliente_id = a.get("cliente_id", type=int)
    certificados = ce.listar(g.tenant_id, q=q or None, temporal=temporal, operativo=operativo, plazo=plazo, cliente_fiscal_id=cliente_id)
    return render_template(
        "certificados.html", certificados=certificados, resumen=ce.resumen(g.tenant_id), riesgos=ce.riesgos(g.tenant_id), q=q, temporal=temporal, operativo=operativo, plazo=plazo, cliente_id=cliente_id,
        clientes=db.listar_clientes_fiscales(g.tenant_id), equipo=ce.custodios(g.tenant_id), es_supervisor=bool(db.es_supervisor_tenant(g.usuario_id)), cfg=ce.config(g.tenant_id),
        error=request.args.get("error"), aviso=request.args.get("aviso"), **_ctx_textos())


@certificados_bp.route("/nuevo", methods=["POST"])
@login_required
def nuevo():
    """El alta de siempre: sin archivo. Cliente (o titular), tipo y caducidad (o emisión); lo demás es opcional."""
    f = request.form
    av = f.get("avisar_cliente", "")
    try:
        r = ce.alta_rapida(g.tenant_id, g.usuario_id, tipo=f.get("tipo", "otro"), caduca=f.get("caduca"), emitido=f.get("emitido"), cliente_fiscal_id=f.get("cliente_fiscal_id", type=int) or None,
                           titular=f.get("titular"), nif=f.get("nif"), serie=f.get("serie"), custodio_id=f.get("custodio_id", type=int) or None, ubicacion=f.get("ubicacion"), notas=f.get("notas"),
                           avisar_cliente=None if av == "" else av == "1")
    except ValueError as e:
        return _volver(error=str(e))
    return _volver(r["id"], aviso="creado" if r["nuevo"] else "ya-estaba")


@certificados_bp.route("/<int:certificado_id>/editar", methods=["POST"])
@login_required
def editar(certificado_id: int):
    f = request.form
    c = ce.obtener(g.tenant_id, certificado_id)
    if c is None:
        abort(404)
    campos = dict(nif=f.get("nif", ""), cliente_fiscal_id=f.get("cliente_fiscal_id", type=int) or None, custodio_id=f.get("custodio_id", type=int) or None, ubicacion=f.get("ubicacion", ""),
                  notas=f.get("notas", ""))
    if "avisar_cliente" in f:
        campos["avisar_cliente"] = None if f.get("avisar_cliente") == "" else f.get("avisar_cliente") == "1"
    if not c["verificado"]:                                          # apuntado a mano: también se corrigen titular, tipo, fechas y serie
        campos.update(titular=f.get("titular", ""), tipo=f.get("tipo", "otro"), caduca=f.get("caduca"), emitido=f.get("emitido", ""), serie=f.get("serie", ""))
    return _accion(certificado_id, ce.editar, certificado_id, **campos)


@certificados_bp.route("/<int:certificado_id>/renovado", methods=["POST"])
@login_required
def renovado(certificado_id: int):
    f = request.form
    try:
        r = ce.renovado(g.tenant_id, g.usuario_id, certificado_id, f.get("nueva_caducidad"), emitido=f.get("emitido"), serie=f.get("serie"), funciona="funciona" in f)
    except ValueError as e:
        return _volver(certificado_id, error=str(e))
    return _volver(r["id"], aviso="renovado")


@certificados_bp.route("/<int:certificado_id>/avisar", methods=["POST"])
@login_required
def avisar_ahora(certificado_id: int):
    return _accion(certificado_id, ce.enviar_aviso_ahora, certificado_id, aviso="aviso-enviado")


@certificados_bp.route("/avisos", methods=["GET", "POST"])
@login_required
def avisos():
    """Cómo informa el despacho a sus clientes de la caducidad de su certificado (solo la dirección lo cambia)."""
    from . import notificaciones_email
    directivo = bool(db.es_supervisor_tenant(g.usuario_id) or g.get("es_admin"))
    error = None
    if request.method == "POST":
        if not directivo:
            abort(403)
        f = request.form
        try:
            ce.guardar_config(g.tenant_id, g.usuario_id, avisar_cliente="avisar_cliente" in f, mostrar_en_portal="mostrar_en_portal" in f, dias_antes=f.get("dias_antes", ""), dias_despues=f.get("dias_despues", ""),
                              asunto=f.get("asunto", ""), cuerpo=f.get("cuerpo", ""), instrucciones=f.get("instrucciones", ""))
        except ValueError as e:
            error = str(e)
        else:
            return redirect(url_for("certificados.avisos", aviso="guardado"))
    cfg = ce.config(g.tenant_id)
    return render_template("certificados_avisos.html", cfg=cfg, directivo=directivo, error=error or request.args.get("error"), aviso=request.args.get("aviso"), marcas=ce.MARCAS_PLANTILLA,
                           vista_previa=ce.vista_previa(g.tenant_id, cfg), smtp=notificaciones_email.configurado(), max_antes=ce.MAX_AVISOS_ANTES, max_despues=ce.MAX_AVISOS_DESPUES,
                           sin_correo=sum(1 for c in ce.listar(g.tenant_id) if c["cliente_titular_id"] and not (c.get("cliente_email") or "").strip()), **_ctx_textos())


@certificados_bp.route("/avisos/prueba", methods=["POST"])
@login_required
def avisos_prueba():
    """Te manda a ti, a tu correo, el aviso tal como lo recibiría un cliente."""
    from . import notificaciones_email, portal_recordatorios
    u = db.obtener_usuario(g.usuario_id)
    if not (u and u["email"]) or not notificaciones_email.configurado():
        return redirect(url_for("certificados.avisos", error="El correo saliente no está configurado o tu cuenta no tiene correo."))
    cfg, gestoria, idioma, destino = ce.config(g.tenant_id), ce._gestoria(g.tenant_id), db.idioma_usuario(g.usuario_id), u["email"]      # antes de entrar en el contexto de idioma: `g` es otro dentro
    try:
        with portal_recordatorios._en_idioma(idioma):
            notificaciones_email.enviar_aviso_certificado(destino, "Marta Puig", str(ce.TIPOS_CERTIFICADO["fnmt_persona_fisica"]["nombre"]), (date.today() + timedelta(days=30)).isoformat(), 30,
                                                          portal_recordatorios.url_portal() if cfg["mostrar_en_portal"] else None, gestoria, cfg["instrucciones"],
                                                          plantilla=(cfg["asunto"], cfg["cuerpo"]) if cfg["asunto"] and cfg["cuerpo"] else None)
    except Exception as e:  # noqa: BLE001
        return redirect(url_for("certificados.avisos", error=f"No se ha podido enviar: {e}"))
    return redirect(url_for("certificados.avisos", aviso="prueba"))


def _archivo_subido():
    f = request.files.get("archivo")
    if f is None or not f.filename:
        return None
    return f.read(ce.MAX_BYTES + 1)


@certificados_bp.route("/importar", methods=["POST"])
@login_required
def importar():
    datos = _archivo_subido()
    if datos is None and request.form.get("contenido_b64"):
        try:
            datos = base64.b64decode(request.form["contenido_b64"], validate=True)
        except ValueError:
            datos = None
    if datos is None:
        return _volver(error="Elige un archivo de certificado público (.cer, .crt o .pem).")
    try:
        r = ce.importar(g.tenant_id, g.usuario_id, datos, huella=request.form.get("huella") or None, ubicacion_externa=request.form.get("ubicacion"), notas=request.form.get("notas"),
                        custodio_id=request.form.get("custodio_id", type=int))
    except ce.EleccionRequerida as e:
        return render_template("certificados_elegir.html", candidatos=e.candidatos, contenido_b64=base64.b64encode(datos).decode(), ubicacion=request.form.get("ubicacion", ""),
                               notas=request.form.get("notas", ""), **_ctx_textos())
    except ValueError as e:
        return _volver(error=str(e))
    return _volver(r["id"], aviso="importado" if r["nuevo"] else "ya-estaba")


@certificados_bp.route("/alta-manual", methods=["POST"])
@login_required
def alta_manual():
    f = request.form
    try:
        r = ce.alta_manual(g.tenant_id, g.usuario_id, sujeto=f.get("sujeto", ""), emisor=f.get("emisor", ""), numero_serie=f.get("numero_serie", ""), not_before=f.get("not_before"),
                           not_after=f.get("not_after", ""), evidencia=f.get("evidencia", ""), ubicacion_externa=f.get("ubicacion"))
    except ValueError as e:
        return _volver(error=str(e))
    return _volver(r["id"], aviso="importado" if r["nuevo"] else "ya-estaba")


@certificados_bp.route("/<int:certificado_id>")
@login_required
def detalle(certificado_id: int):
    c = ce.obtener(g.tenant_id, certificado_id)
    if c is None:
        abort(404)
    reno = ce.renovacion_activa(g.tenant_id, certificado_id)
    clientes = db.listar_clientes_fiscales(g.tenant_id)
    return render_template(
        "certificado_detalle.html", c=c, vinculos=ce.vinculos(g.tenant_id, certificado_id), renovacion=reno, renovaciones=ce.renovaciones(g.tenant_id, certificado_id),
        implantacion=ce.estado_implantacion(g.tenant_id, reno["id"]) if reno else [], eventos=ce.eventos(g.tenant_id, certificado_id), clientes=clientes, equipo=ce.custodios(g.tenant_id),
        paso_actual={"sin_iniciar": 0, "en_gestion": 1, "pendiente_titular": 1, "obtenido": 2, "validado": 3, "implantado": 4, "cerrado": 5}.get(reno["fase"], 0) if reno else 0,
        cfg=ce.config(g.tenant_id), avisos_cliente=ce.avisos_del_cliente(g.tenant_id, certificado_id), es_supervisor=bool(db.es_supervisor_tenant(g.usuario_id)),
        local_hasta=ce.hora_local(c["not_after"], g.tenant_id), local_desde=ce.hora_local(c["not_before"], g.tenant_id), anterior=ce.obtener(g.tenant_id, c["sustituye_a"]) if c["sustituye_a"] else None,
        sucesor=_sucesor(certificado_id), error=request.args.get("error"), aviso=request.args.get("aviso"), servicios=ce.SERVICIOS, **_ctx_textos())


def _sucesor(certificado_id: int):
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id FROM certificados WHERE tenant_id = ? AND sustituye_a = ? ORDER BY id DESC LIMIT 1", (g.tenant_id, certificado_id)).fetchone()
    finally:
        conn.close()
    return ce.obtener(g.tenant_id, f["id"]) if f else None


def _accion(certificado_id: int, funcion, *args, aviso: str = "hecho", **kw):
    try:
        funcion(g.tenant_id, g.usuario_id, *args, **kw)
    except ValueError as e:
        return _volver(certificado_id, error=str(e))
    return _volver(certificado_id, aviso=aviso)


@certificados_bp.route("/<int:certificado_id>/datos", methods=["POST"])
@login_required
def datos(certificado_id: int):
    f = request.form
    return _accion(certificado_id, ce.actualizar_datos, certificado_id, custodio_id=f.get("custodio_id", type=int) or None, nif_confirmado=f.get("nif_confirmado", ""), tipo_titular=f.get("tipo_titular") or None,
                   ubicacion_externa=f.get("ubicacion", ""), notas=f.get("notas", ""))


@certificados_bp.route("/<int:certificado_id>/estado", methods=["POST"])
@login_required
def estado(certificado_id: int):
    return _accion(certificado_id, ce.cambiar_estado_operativo, certificado_id, request.form.get("nuevo", ""), request.form.get("motivo"))


@certificados_bp.route("/<int:certificado_id>/evaluaciones", methods=["POST"])
@login_required
def evaluacion(certificado_id: int):
    return _accion(certificado_id, ce.registrar_evaluacion, certificado_id, request.form.get("dimension", ""), request.form.get("resultado", ""), detalle=request.form.get("detalle"))


@certificados_bp.route("/<int:certificado_id>/comprobar", methods=["POST"])
@login_required
def comprobar(certificado_id: int):
    """Comprueba la cadena y la revocación del certificado consultando lo que él mismo publica (OCSP, CRL, emisor)."""
    return _accion(certificado_id, ce.comprobar_ahora, certificado_id, aviso="comprobado")


@certificados_bp.route("/<int:certificado_id>/vinculos", methods=["POST"])
@login_required
def vincular(certificado_id: int):
    f = request.form
    try:
        ce.vincular(g.tenant_id, g.usuario_id, certificado_id, cliente_fiscal_id=f.get("cliente_fiscal_id", type=int) or None, servicio=f.get("servicio", ""), autorizacion=f.get("autorizacion", ""),
                    vigente_desde=f.get("desde") or None, vigente_hasta=f.get("hasta") or None)
    except ValueError as e:
        return _volver(certificado_id, error=str(e))
    return _volver(certificado_id, aviso="hecho")


@certificados_bp.route("/vinculos/<int:vinculo_id>/retirar", methods=["POST"])
@login_required
def retirar_vinculo(vinculo_id: int):
    cid = request.form.get("certificado_id", type=int)
    try:
        ce.retirar_vinculo(g.tenant_id, g.usuario_id, vinculo_id, request.form.get("motivo", ""))
    except ValueError as e:
        return _volver(cid, error=str(e))
    return _volver(cid, aviso="hecho")


@certificados_bp.route("/<int:certificado_id>/renovacion", methods=["POST"])
@login_required
def abrir_renovacion(certificado_id: int):
    return _accion(certificado_id, ce.abrir_renovacion, certificado_id, titular=request.form.get("titular"), notas=request.form.get("notas"))


@certificados_bp.route("/renovaciones/<int:renovacion_id>/avanzar", methods=["POST"])
@login_required
def avanzar(renovacion_id: int):
    cid = request.form.get("certificado_id", type=int)
    return _accion(cid, ce.avanzar_renovacion, renovacion_id, request.form.get("fase", ""), request.form.get("nota"), confirmar_sin_servicios="confirmar_sin_servicios" in request.form)


@certificados_bp.route("/renovaciones/<int:renovacion_id>/nuevo", methods=["POST"])
@login_required
def nuevo_certificado(renovacion_id: int):
    cid = request.form.get("certificado_id", type=int)
    datos = _archivo_subido()
    if datos is None:
        return _volver(cid, error="Elige el archivo del certificado nuevo (solo la parte pública).")
    try:
        r = ce.registrar_certificado_nuevo(g.tenant_id, g.usuario_id, renovacion_id, datos, huella=request.form.get("huella") or None)
    except ce.EleccionRequerida:
        return _volver(cid, error="El archivo trae varios certificados finales: sube un archivo con solo el certificado nuevo.")
    except ValueError as e:
        return _volver(cid, error=str(e))
    return redirect(url_for("certificados.detalle", certificado_id=cid, aviso="nuevo-recibido") + "#renovacion")


@certificados_bp.route("/renovaciones/<int:renovacion_id>/implantacion", methods=["POST"])
@login_required
def implantacion(renovacion_id: int):
    cid = request.form.get("certificado_id", type=int)
    return _accion(cid, ce.registrar_implantacion, renovacion_id, request.form.get("vinculo_id", type=int) or 0, request.form.get("resultado", ""), request.form.get("nota"))


@certificados_bp.route("/custodios", methods=["POST"])
@login_required
def custodio():
    try:
        ce.fijar_custodio_flag(g.tenant_id, g.usuario_id, request.form.get("usuario_id", type=int) or 0, request.form.get("valor") == "1")
    except ValueError as e:
        return _volver(error=str(e))
    return _volver(aviso="hecho")
