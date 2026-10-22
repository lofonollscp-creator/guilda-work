"""Pantallas del control fiscal (fase A): flujo de trabajo del despacho, oficinas y permisos, y auditoría. Ver app/obligaciones.py, app/acceso.py y app/auditoria.py."""
from datetime import date

from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from flask_babel import lazy_gettext as _l

from . import acceso, auditoria, avisos, control_expedientes, db, nucleo, obligaciones, panel_fiscal, traspasos, verticales
from .auth import login_required

control_fiscal_bp = Blueprint("control_fiscal", __name__, url_prefix="/fiscal")

ROLES_TEXTO = {"coordinador": _l("Coordinador de oficina"), "gestor": _l("Gestor"), "revisor_fiscal": _l("Revisor fiscal"), "auditor": _l("Auditor (solo lectura)")}
ALCANCE_TEXTO = {"organizacion": _l("Todo el despacho"), "oficina": _l("Una oficina"), "cliente": _l("Un cliente")}


@control_fiscal_bp.before_request
def _solo_con_gestoria():
    if g.get("usuario_id") is None:
        return
    if g.get("tenant_id") is None:
        abort(403)
    if not verticales.esta_activo(g.tenant_id, "gestoria"):
        abort(404)


@control_fiscal_bp.app_context_processor
def _inyectar():
    """Qué enlaces del menú Fiscal ve esta persona (sin consultas: los roles de dirección ya viajan en `g`)."""
    return {"ve_oficinas": lambda: bool(g.get("usuario_id") and g.get("tenant_id") and (g.get("supervisor_tenant") or g.get("es_admin"))),
            "ve_auditoria": lambda: bool(g.get("usuario_id") and g.get("tenant_id") and (g.get("supervisor_tenant") or g.get("es_admin")))}


def _volver(destino: str, **kw):
    return redirect(url_for(destino, **kw))


# --- Flujo de trabajo ------------------------------------------------------------------------------------------------------------------------
@control_fiscal_bp.route("/flujo", methods=["GET", "POST"])
@login_required
def flujo():
    if not acceso.es_directivo(g.usuario_id):
        abort(403)
    if request.method == "POST":
        try:
            obligaciones.guardar_config(g.tenant_id, g.usuario_id, flujo_estricto="flujo_estricto" in request.form, exigir_justificante="exigir_justificante" in request.form)
        except ValueError as e:
            return _volver("control_fiscal.flujo", error=str(e))
        return _volver("control_fiscal.flujo", aviso="guardado")
    return render_template("fiscal_flujo.html", cfg=obligaciones.config(g.tenant_id), error=request.args.get("error"), aviso=request.args.get("aviso"))


# --- Oficinas y permisos -----------------------------------------------------------------------------------------------------------------------
def _puede_ver_oficinas() -> bool:
    return bool(acceso.roles_de(g.tenant_id, g.usuario_id) & {"director", "coordinador"})


@control_fiscal_bp.route("/oficinas")
@login_required
def oficinas():
    if not _puede_ver_oficinas():
        abort(403)
    return render_template(
        "fiscal_oficinas.html", oficinas=acceso.listar_oficinas(g.tenant_id), clientes=db.listar_clientes_fiscales(g.tenant_id), membresias=acceso.membresias_del_despacho(g.tenant_id),
        equipo=[{"id": u, "nombre": db.nombre_mostrado_usuario(u) or db.obtener_usuario(u)["email"]} for u in db.usuarios_de_tenant(g.tenant_id)],
        concesiones=[dict(k) | {"cliente": c["nombre"]} for c in db.listar_clientes_fiscales(g.tenant_id) for k in acceso.concesiones_de(g.tenant_id, c["id"])],
        roles=ROLES_TEXTO, alcances=ALCANCE_TEXTO, es_directivo=acceso.es_directivo(g.usuario_id), error=request.args.get("error"), aviso=request.args.get("aviso"))


def _accion(destino_ok: str, funcion, *a, **kw):
    try:
        funcion(g.tenant_id, g.usuario_id, *a, **kw)
    except ValueError as e:
        return _volver("control_fiscal.oficinas", error=str(e))
    acceso.invalidar(g.tenant_id)
    return _volver("control_fiscal.oficinas", aviso=destino_ok)


@control_fiscal_bp.route("/oficinas", methods=["POST"])
@login_required
def crear_oficina():
    return _accion("hecho", acceso.crear_oficina, request.form.get("nombre", ""))


@control_fiscal_bp.route("/oficinas/<int:oficina_id>/archivar", methods=["POST"])
@login_required
def archivar_oficina(oficina_id: int):
    return _accion("hecho", acceso.archivar_oficina, oficina_id)


@control_fiscal_bp.route("/oficinas/cliente", methods=["POST"])
@login_required
def asignar_cliente():
    return _accion("hecho", acceso.asignar_cliente_a_oficina, request.form.get("cliente_id", type=int) or 0, request.form.get("oficina_id", type=int) or None)


@control_fiscal_bp.route("/oficinas/membresias", methods=["POST"])
@login_required
def dar_membresia():
    f = request.form
    alcance = f.get("alcance", "organizacion")
    return _accion("hecho", acceso.dar_membresia, f.get("usuario_id", type=int) or 0, f.get("rol", ""), alcance,
                   (f.get("oficina_id", type=int) if alcance == "oficina" else f.get("cliente_id", type=int) if alcance == "cliente" else None), f.get("hasta") or None)


@control_fiscal_bp.route("/oficinas/membresias/<int:membresia_id>/revocar", methods=["POST"])
@login_required
def revocar_membresia(membresia_id: int):
    return _accion("hecho", acceso.revocar_membresia, membresia_id)


@control_fiscal_bp.route("/oficinas/concesiones", methods=["POST"])
@login_required
def conceder():
    f = request.form
    return _accion("hecho", acceso.conceder_cliente, f.get("cliente_id", type=int) or 0, oficina_id=f.get("oficina_id", type=int) or None, para_usuario_id=f.get("usuario_id", type=int) or None,
                   nivel=f.get("nivel", "gestion"), hasta=f.get("hasta") or None)


@control_fiscal_bp.route("/oficinas/concesiones/<int:concesion_id>/revocar", methods=["POST"])
@login_required
def revocar_concesion(concesion_id: int):
    return _accion("hecho", acceso.revocar_concesion, concesion_id)


# --- Auditoría ------------------------------------------------------------------------------------------------------------------------------
@control_fiscal_bp.route("/auditoria")
@login_required
def auditoria_pantalla():
    if not (acceso.roles_de(g.tenant_id, g.usuario_id) & {"director", "auditor", "revisor_fiscal"}):
        abort(403)
    a = request.args
    eventos = auditoria.listar(g.tenant_id, entidad=a.get("entidad") or None, usuario_id=a.get("usuario_id", type=int), accion=a.get("accion") or None, desde=a.get("desde") or None,
                               hasta=a.get("hasta") or None, antes_de_id=a.get("antes_de_id", type=int), limite=100)
    return render_template("fiscal_auditoria.html", eventos=eventos, filtros=a, siguiente=eventos[-1]["id"] if len(eventos) == 100 else None,
                           equipo=[{"id": u, "nombre": db.nombre_mostrado_usuario(u) or db.obtener_usuario(u)["email"]} for u in db.usuarios_de_tenant(g.tenant_id)])


# --- Panel y traspasos (fase E) ----------------------------------------------------------------------------------------------------------------
def _equipo() -> list[dict]:
    return [{"id": u, "nombre": db.nombre_mostrado_usuario(u) or db.obtener_usuario(u)["email"]} for u in db.usuarios_de_tenant(g.tenant_id)]


@control_fiscal_bp.route("/panel")
@login_required
def panel():
    return render_template("fiscal_panel.html", p=panel_fiscal.construir(g.tenant_id, g.usuario_id), yo=g.usuario_id)


@control_fiscal_bp.route("/traspasos")
@login_required
def traspasos_pantalla():
    visibles = acceso.clientes_visibles(g.tenant_id, g.usuario_id)
    clientes = [c for c in db.listar_clientes_fiscales(g.tenant_id) if visibles is None or c["id"] in visibles]
    return render_template("fiscal_traspasos.html", traspasos=traspasos.listar(g.tenant_id, g.usuario_id), clientes=clientes, equipo=_equipo(), oficinas=acceso.listar_oficinas(g.tenant_id),
                           yo=g.usuario_id, es_directivo=acceso.es_directivo(g.usuario_id), cliente_id=request.args.get("cliente_id", type=int),
                           responsables={c["id"]: db.nombre_mostrado_usuario(c["responsable_id"]) for c in clientes if c["responsable_id"]},
                           error=request.args.get("error"), aviso=request.args.get("aviso"))


def _traspaso(destino_ok: str, funcion, *a, **kw):
    try:
        funcion(g.tenant_id, g.usuario_id, *a, **kw)
    except (ValueError, traspasos.ConflictoDeVersion) as e:
        return _volver("control_fiscal.traspasos_pantalla", error=str(e))
    return _volver("control_fiscal.traspasos_pantalla", aviso=destino_ok)


@control_fiscal_bp.route("/traspasos/nuevo", methods=["POST"])
@login_required
def traspaso_nuevo():
    f = request.form
    return _traspaso("propuesto", traspasos.proponer, f.get("cliente_id", type=int) or 0, f.get("a_usuario_id", type=int) or 0, a_oficina_id=f.get("a_oficina_id", type=int) or None, nota=f.get("nota"))


@control_fiscal_bp.route("/traspasos/<int:traspaso_id>/aceptar", methods=["POST"])
@login_required
def traspaso_aceptar(traspaso_id: int):
    return _traspaso("aceptado", traspasos.aceptar, traspaso_id, version=request.form.get("version", type=int))


@control_fiscal_bp.route("/traspasos/<int:traspaso_id>/rechazar", methods=["POST"])
@login_required
def traspaso_rechazar(traspaso_id: int):
    return _traspaso("rechazado", traspasos.rechazar, traspaso_id, request.form.get("motivo", ""), version=request.form.get("version", type=int))


@control_fiscal_bp.route("/traspasos/<int:traspaso_id>/cancelar", methods=["POST"])
@login_required
def traspaso_cancelar(traspaso_id: int):
    return _traspaso("cancelado", traspasos.cancelar, traspaso_id, version=request.form.get("version", type=int))


@control_fiscal_bp.route("/clientes/<int:cliente_id>/responsable", methods=["POST"])
@login_required
def cliente_responsable(cliente_id: int):
    return _traspaso("hecho", traspasos.asignar_responsable, cliente_id, request.form.get("responsable_id", type=int) or None)


# --- Avisos con acuse y escalado (motor de avisos v2) -----------------------------------------------------------------------------------------
@control_fiscal_bp.route("/avisos", methods=["GET", "POST"])
@login_required
def avisos_pantalla():
    directivo = acceso.es_directivo(g.usuario_id)
    if request.method == "POST":
        if not directivo:
            abort(403)
        f = request.form
        try:
            avisos.guardar_config(g.tenant_id, g.usuario_id, activo="activo" in f, dias_antes=f.get("dias_antes", ""), escalar_horas_urgente=f.get("escalar_horas_urgente"),
                                  escalar_horas_atencion=f.get("escalar_horas_atencion"), reenviar_horas=f.get("reenviar_horas"), max_reenvios=f.get("max_reenvios"), dias_certificados=f.get("dias_certificados") or None)
        except ValueError as e:
            return _volver("control_fiscal.avisos_pantalla", error=str(e))
        return _volver("control_fiscal.avisos_pantalla", aviso="hecho")
    estado = request.args.get("estado", "abierta")
    estado = estado if estado in avisos.ESTADOS else "abierta"
    mios = request.args.get("mios") == "1"
    return render_template("fiscal_avisos.html", lista=avisos.listar(g.tenant_id, g.usuario_id, estado=estado, mios=mios), estado=estado, mios=mios, cfg=avisos.config(g.tenant_id),
                           metricas=avisos.metricas(g.tenant_id) if directivo else None, es_directivo=directivo, error=request.args.get("error"), aviso=request.args.get("aviso"))


@control_fiscal_bp.route("/avisos/<int:alerta_id>/acusar", methods=["POST"])
@login_required
def avisos_acusar(alerta_id: int):
    try:
        avisos.acusar(g.tenant_id, g.usuario_id, alerta_id, request.form.get("nota"))
    except ValueError as e:
        return _volver("control_fiscal.avisos_pantalla", error=str(e))
    return _volver("control_fiscal.avisos_pantalla", aviso="acusado")


# --- Expedientes unificados (RF-13) -----------------------------------------------------------------------------------------------------------
def _a_expediente(expediente_id: int, error: str | None = None):
    return redirect(url_for("expedientes.ficha", expediente_id=expediente_id, **({"error": error[:200]} if error else {})))


@control_fiscal_bp.route("/expedientes")
@login_required
def expedientes_lista():
    estado = request.args.get("estado") or None
    todos = request.args.get("todos") == "1"
    clientes = nucleo.listar_clientes(g.tenant_id, limite=500)[0]
    return render_template("fiscal_expedientes.html", lista=control_expedientes.listar(g.tenant_id, g.usuario_id, estado=estado, solo_abiertos=not todos), tipos=control_expedientes.TIPOS, estados=control_expedientes.ESTADOS,
                           estado=estado, todos=todos, clientes=clientes, equipo=_equipo(), hoy=date.today().isoformat(), error=request.args.get("error"),
                           solo_lectura=acceso.es_solo_auditor(g.tenant_id, g.usuario_id))


@control_fiscal_bp.route("/expedientes/nuevo", methods=["POST"])
@login_required
def expediente_nuevo():
    f = request.form
    try:
        nuevo = control_expedientes.crear(g.tenant_id, g.usuario_id, f.get("cliente_id", type=int) or 0, f.get("tipo", ""), f.get("titulo", ""), prioridad=f.get("prioridad") or "normal",
                                          fecha_objetivo=f.get("fecha_objetivo") or None, revisor_id=f.get("revisor_id", type=int) or None, descripcion=f.get("descripcion"))
    except ValueError as e:
        return redirect(url_for("control_fiscal.expedientes_lista", error=str(e)[:200]))
    return _a_expediente(nuevo)


@control_fiscal_bp.route("/expedientes/obligacion/<int:vencimiento_id>/abrir", methods=["POST"])
@login_required
def expediente_de_obligacion(vencimiento_id: int):
    try:
        r = control_expedientes.abrir_desde_obligacion(g.tenant_id, g.usuario_id, vencimiento_id)
    except ValueError as e:
        return redirect(url_for("fiscal.editar_vencimiento", vencimiento_id=vencimiento_id, error=str(e)[:200]))
    return _a_expediente(r["id"])


@control_fiscal_bp.route("/expedientes/certificado/<int:certificado_id>/abrir", methods=["POST"])
@login_required
def expediente_de_certificado(certificado_id: int):
    try:
        r = control_expedientes.abrir_desde_certificado(g.tenant_id, g.usuario_id, certificado_id)
    except ValueError as e:
        return redirect(url_for("certificados.detalle", certificado_id=certificado_id, error=str(e)[:200]))
    return _a_expediente(r["id"])


def _en_expediente(expediente_id: int, funcion, *a, **kw):
    try:
        funcion(g.tenant_id, g.usuario_id, *a, **kw)
    except ValueError as e:
        return _a_expediente(expediente_id, str(e))
    return _a_expediente(expediente_id)


@control_fiscal_bp.route("/expedientes/<int:expediente_id>/control", methods=["POST"])
@login_required
def expediente_control(expediente_id: int):
    f = request.form
    return _en_expediente(expediente_id, control_expedientes.editar_control, expediente_id, revisor_id=f.get("revisor_id", type=int) or None, prioridad=f.get("prioridad") or "normal",
                          fecha_objetivo=f.get("fecha_objetivo") or None, **({"oficina_id": f.get("oficina_id", type=int) or None} if "oficina_id" in f else {}))


@control_fiscal_bp.route("/expedientes/<int:expediente_id>/lista", methods=["POST"])
@login_required
def expediente_punto_nuevo(expediente_id: int):
    f = request.form
    return _en_expediente(expediente_id, control_expedientes.anadir_punto, expediente_id, f.get("texto", ""), obligatorio=bool(f.get("obligatorio")), asignado_id=f.get("asignado_id", type=int) or None,
                          fecha_limite=f.get("fecha_limite") or None)


def _expediente_del_punto(punto_id: int) -> int:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT c.expediente_id FROM expediente_checklist c JOIN expedientes x ON x.id = c.expediente_id WHERE c.id = ? AND x.tenant_id = ?", (punto_id, g.tenant_id)).fetchone()
    finally:
        conn.close()
    if f is None:
        abort(404)
    return f["expediente_id"]


@control_fiscal_bp.route("/expedientes/lista/<int:punto_id>/hecho", methods=["POST"])
@login_required
def expediente_punto_hecho(punto_id: int):
    exp = _expediente_del_punto(punto_id)
    return _en_expediente(exp, control_expedientes.marcar_punto, punto_id, not request.form.get("reabrir"), request.form.get("nota"))


@control_fiscal_bp.route("/expedientes/lista/<int:punto_id>/quitar", methods=["POST"])
@login_required
def expediente_punto_quitar(punto_id: int):
    exp = _expediente_del_punto(punto_id)
    return _en_expediente(exp, control_expedientes.eliminar_punto, punto_id)


@control_fiscal_bp.route("/expedientes/<int:expediente_id>/documentos/<int:documento_id>/version", methods=["POST"])
@login_required
def expediente_documento_version(expediente_id: int, documento_id: int):
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return _a_expediente(expediente_id, "Elige un archivo.")
    return _en_expediente(expediente_id, control_expedientes.subir_version, documento_id, archivo.filename, archivo.mimetype, archivo.read(db.MAX_DOCUMENTO_CLIENTE_BYTES + 1))


@control_fiscal_bp.route("/expedientes/<int:expediente_id>/documentos/<int:documento_id>/conservacion", methods=["POST"])
@login_required
def expediente_documento_conservacion(expediente_id: int, documento_id: int):
    return _en_expediente(expediente_id, control_expedientes.fijar_conservacion, documento_id, request.form.get("hasta") or None)
