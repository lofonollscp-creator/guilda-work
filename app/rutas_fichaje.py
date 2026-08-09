"""Rutas de "Fichaje" (registro horario, art. 34.9 del Estatuto de los
Trabajadores / RD-ley 8/2019) — mismo esqueleto de Blueprint que
app/rutas_tiquets.py.

A diferencia de tiquets (tablero compartido), aquí cada trabajador ve y
ficha SOLO lo suyo — pero a diferencia de notas/tareas (privado incluso
entre compañeros), la administración del fichaje SÍ necesita ver a otros
usuarios del mismo tenant: quien tiene `usuarios.gestor_fichajes = 1`
administra el fichaje de su propio tenant (`g.tenant_id`), y el superadmin
global (`g.es_admin`) puede administrar el de cualquier tenant, eligiéndolo
por querystring (`?tenant_id=`).
"""
from datetime import datetime

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import lazy_gettext as _l

from . import db, fichaje_export
from .auth import login_required

fichaje_bp = Blueprint("fichaje", __name__, url_prefix="/fichaje")

TIPOS_FICHAJE = [
    ("entrada", _l("Entrada")),
    ("pausa_inicio", _l("Inicio de pausa")),
    ("pausa_fin", _l("Fin de pausa")),
    ("salida", _l("Salida")),
]


def _puede_administrar(tenant_id: int | None) -> bool:
    return g.es_admin or (g.gestor_fichajes and g.tenant_id is not None and g.tenant_id == tenant_id)


def _tenant_id_admin_actual() -> int | None:
    """De qué tenant está administrando el fichaje quien pide la página:
    el superadmin lo elige por querystring (puede ver cualquiera), un
    gestor de fichajes normal solo puede ver el suyo."""
    if g.es_admin:
        return request.args.get("tenant_id", type=int)
    return g.tenant_id


@fichaje_bp.context_processor
def _inyectar_tipos_fichaje():
    return {"tipos_fichaje": dict(TIPOS_FICHAJE)}


# --- Panel del trabajador --------------------------------------------------

@fichaje_bp.route("/")
@login_required
def panel():
    if not db.fichaje_datos_completos(g.usuario_id):
        return render_template("fichaje_panel.html", datos_incompletos=True, estado=None, hoy=[], error=None)
    hoy = datetime.now().strftime("%Y-%m-%d")
    return render_template(
        "fichaje_panel.html",
        datos_incompletos=False,
        estado=db.estado_actual_fichaje(g.usuario_id),
        hoy=db.listar_fichajes(g.usuario_id, desde=hoy, hasta=hoy),
        error=request.args.get("error"),
    )


@fichaje_bp.route("/marcar", methods=["POST"])
@login_required
def marcar():
    tipo = request.form.get("tipo", "")
    if tipo not in dict(TIPOS_FICHAJE):
        abort(400)
    try:
        db.fichar(g.usuario_id, g.tenant_id, tipo, origen="web")
    except ValueError as e:
        return redirect(url_for("fichaje.panel", error=str(e)))
    return redirect(url_for("fichaje.panel"))


@fichaje_bp.route("/historial")
@login_required
def historial():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    return render_template(
        "fichaje_historial.html",
        desde=desde or "", hasta=hasta or "",
        fichajes=db.listar_fichajes(g.usuario_id, desde, hasta),
    )


@fichaje_bp.route("/mis-datos", methods=["GET", "POST"])
@login_required
def mis_datos():
    if request.method == "POST":
        nombre_completo = request.form.get("nombre_completo", "").strip()
        dni_nie = request.form.get("dni_nie", "").strip()
        if not nombre_completo or not dni_nie:
            return render_template(
                "fichaje_datos.html", datos=db.obtener_fichaje_datos(g.usuario_id),
                error="Nombre completo y DNI/NIE son obligatorios: la normativa exige poder identificarte.",
            )
        jornada = request.form.get("jornada_semanal_horas", "").strip()
        db.guardar_fichaje_datos(
            g.usuario_id, nombre_completo, dni_nie,
            numero_afiliacion_ss=request.form.get("numero_afiliacion_ss", "").strip() or None,
            categoria_profesional=request.form.get("categoria_profesional", "").strip() or None,
            tipo_contrato=request.form.get("tipo_contrato", "").strip() or None,
            fecha_alta=request.form.get("fecha_alta") or None,
            jornada_semanal_horas=float(jornada) if jornada else None,
            convenio_colectivo=request.form.get("convenio_colectivo", "").strip() or None,
        )
        return redirect(url_for("fichaje.panel"))
    return render_template("fichaje_datos.html", datos=db.obtener_fichaje_datos(g.usuario_id), error=None)


# --- Administración (gestor del tenant o superadmin) -----------------------

@fichaje_bp.route("/admin")
@login_required
def admin_resumen():
    if not (g.es_admin or g.gestor_fichajes):
        abort(403)
    tenant_id = _tenant_id_admin_actual()
    if tenant_id is None and not g.es_admin:
        abort(403)  # gestor sin tenant asignado: no hay nada que administrar
    tenant = db.obtener_tenant(tenant_id) if tenant_id else None
    if tenant_id and tenant is None:
        abort(404)
    if not _puede_administrar(tenant_id):
        abort(403)
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    return render_template(
        "fichaje_admin.html",
        tenant=tenant, tenant_id=tenant_id,
        tenants=db.listar_tenants() if g.es_admin else None,
        desde=desde or "", hasta=hasta or "",
        resumen=db.resumen_fichajes_tenant(tenant_id, desde, hasta) if tenant_id else [],
    )


@fichaje_bp.route("/admin/<int:usuario_id>")
@login_required
def admin_detalle(usuario_id: int):
    trabajador = db.obtener_usuario(usuario_id)
    if trabajador is None:
        abort(404)
    if not _puede_administrar(trabajador["tenant_id"]):
        abort(403)
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    return render_template(
        "fichaje_admin_detalle.html",
        trabajador=trabajador, datos=db.obtener_fichaje_datos(usuario_id),
        fichajes=db.listar_fichajes(usuario_id, desde, hasta),
        desde=desde or "", hasta=hasta or "",
        error=request.args.get("error"),
    )


@fichaje_bp.route("/admin/<int:usuario_id>/corregir", methods=["POST"])
@login_required
def admin_corregir(usuario_id: int):
    """Corrección auditable de un olvido (p.ej. una salida que no se
    fichó) -- inserta un fichaje NUEVO que referencia al original vía
    `corrige_a`, nunca sobrescribe la fila existente (ver comentario en
    la tabla `fichajes` de db.py)."""
    trabajador = db.obtener_usuario(usuario_id)
    if trabajador is None:
        abort(404)
    if not _puede_administrar(trabajador["tenant_id"]):
        abort(403)
    tipo = request.form.get("tipo", "")
    corrige_a = request.form.get("corrige_a", type=int)
    nota = request.form.get("nota", "").strip() or None
    volver = {"desde": request.form.get("desde") or None, "hasta": request.form.get("hasta") or None}
    if tipo not in dict(TIPOS_FICHAJE):
        abort(400)
    try:
        db.fichar(
            usuario_id, trabajador["tenant_id"], tipo, origen="correccion_admin",
            creado_por=g.usuario_id, corrige_a=corrige_a, nota=nota,
        )
    except ValueError as e:
        return redirect(url_for("fichaje.admin_detalle", usuario_id=usuario_id, error=str(e), **volver))
    return redirect(url_for("fichaje.admin_detalle", usuario_id=usuario_id, **volver))


@fichaje_bp.route("/admin/exportar.csv")
@login_required
def admin_exportar_csv():
    tenant_id = _tenant_id_admin_actual()
    if not _puede_administrar(tenant_id):
        abort(403)
    if tenant_id is None:
        abort(400)  # el superadmin tiene que elegir un tenant antes de exportar
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    usuario_id = request.args.get("usuario_id", type=int)
    contenido = fichaje_export.a_csv(tenant_id, desde, hasta, usuario_id)
    return Response(
        contenido, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=fichajes.csv"},
    )


@fichaje_bp.route("/admin/exportar.pdf")
@login_required
def admin_exportar_pdf():
    tenant_id = _tenant_id_admin_actual()
    if not _puede_administrar(tenant_id):
        abort(403)
    if tenant_id is None:
        abort(400)  # el superadmin tiene que elegir un tenant antes de exportar
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    usuario_id = request.args.get("usuario_id", type=int)
    contenido = fichaje_export.a_pdf(tenant_id, desde, hasta, usuario_id)
    return Response(
        contenido, mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=fichajes.pdf"},
    )
