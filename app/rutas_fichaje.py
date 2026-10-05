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


@fichaje_bp.app_template_filter("horas_hm")
def _horas_hm(segundos):
    return fichaje_export.formato_horas(segundos)


@fichaje_bp.context_processor
def _inyectar_tipos_fichaje():
    return {"tipos_fichaje": dict(TIPOS_FICHAJE)}


# --- Panel del trabajador --------------------------------------------------

def _geolocalizacion_activa() -> bool:
    if not g.tenant_id:
        return False
    tenant = db.obtener_tenant(g.tenant_id)
    return bool(tenant and tenant["fichaje_geolocalizacion"])


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
        ultimo_evento=db.ultimo_fichaje(g.usuario_id),
        hoy=db.listar_fichajes(g.usuario_id, desde=hoy, hasta=hoy),
        semana=fichaje_export.resumen_semana(g.tenant_id, g.usuario_id),
        error=request.args.get("error"),
        geolocalizacion_activa=_geolocalizacion_activa(),
    )


@fichaje_bp.route("/marcar", methods=["POST"])
@login_required
def marcar():
    tipo = request.form.get("tipo", "")
    if tipo not in dict(TIPOS_FICHAJE):
        abort(400)
    # Geolocalización (Fase G3): solo se guarda si el tenant la tiene
    # activada (backoffice) -- si no, se ignora aunque el navegador la
    # mande, ni el propio formulario debería pedirla (ver
    # fichaje_panel.html), pero el servidor no se fía del cliente para
    # algo con implicaciones de RGPD.
    latitud = longitud = None
    tenant = db.obtener_tenant(g.tenant_id) if g.tenant_id else None
    if tenant and tenant["fichaje_geolocalizacion"]:
        latitud = request.form.get("latitud", type=float)
        longitud = request.form.get("longitud", type=float)
    try:
        db.fichar(g.usuario_id, g.tenant_id, tipo, origen="web", latitud=latitud, longitud=longitud)
    except ValueError as e:
        return redirect(url_for("fichaje.panel", error=str(e)))
    return redirect(url_for("fichaje.panel"))


@fichaje_bp.route("/historial")
@login_required
def historial():
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    fichajes = db.listar_fichajes(g.usuario_id, desde, hasta)
    # Agrupado por día con totales (reusa fichaje_export.filas_diarias(),
    # la misma agregación que ya usan los exportables CSV/PDF) -- antes
    # el historial era una tabla plana de eventos sueltos sin resumen de
    # horas trabajadas por jornada, obligando a hacer cálculo mental.
    por_dia_fecha: dict[str, dict] = {
        fila["fecha"]: fila for fila in fichaje_export.filas_diarias(g.tenant_id, desde, hasta, g.usuario_id)
    }
    por_dia: dict[str, list] = {}
    for f in fichajes:
        por_dia.setdefault(f["marca_tiempo"][:10], []).append(f)
    # fichajes viene ordenado por marca_tiempo DESCENDENTE (db.listar_fichajes)
    # -- dentro de cada día se invierte para leerlo en orden cronológico
    # normal (entrada arriba, salida abajo), el orden DESC solo tiene
    # sentido entre días, no dentro de uno.
    for eventos_dia in por_dia.values():
        eventos_dia.reverse()
    dias_ordenados = sorted(por_dia, reverse=True)
    return render_template(
        "fichaje_historial.html",
        desde=desde or "", hasta=hasta or "",
        fichajes=fichajes, dias_ordenados=dias_ordenados, por_dia=por_dia, por_dia_resumen=por_dia_fecha,
        semana=fichaje_export.resumen_semana(g.tenant_id, g.usuario_id),
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
        semana_segundos=fichaje_export.segundos_por_usuario_semana(tenant_id) if tenant_id else {},
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
    # El navegador manda "datetime-local" (YYYY-MM-DDTHH:MM, sin segundos) --
    # se normaliza a la misma granularidad de segundos que db.now_iso() porque
    # db.fichar() compara marca_tiempo como string ISO, no como datetime.
    marca_tiempo_raw = request.form.get("marca_tiempo", "")
    try:
        marca_tiempo = datetime.strptime(marca_tiempo_raw, "%Y-%m-%dT%H:%M").isoformat(timespec="seconds")
    except ValueError:
        return redirect(url_for(
            "fichaje.admin_detalle", usuario_id=usuario_id,
            error="Indica la fecha y hora real del fichaje que se corrige.", **volver,
        ))
    try:
        db.fichar(
            usuario_id, trabajador["tenant_id"], tipo, origen="correccion_admin",
            creado_por=g.usuario_id, corrige_a=corrige_a, nota=nota, marca_tiempo=marca_tiempo,
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


@fichaje_bp.route("/admin/exportar.json")
@login_required
def admin_exportar_json():
    """Export interoperable (Fase G3): detalle CRUDO por evento, con el
    hash de cada fila -- a diferencia de .csv/.pdf (agregado diario para
    lectura humana), esto es lo que se pueda necesitar dar a una futura
    interfaz del Ministerio de Trabajo (o a Inspección directamente) sin
    tener que rehacer nada cuando publiquen su especificación oficial."""
    tenant_id = _tenant_id_admin_actual()
    if not _puede_administrar(tenant_id):
        abort(403)
    if tenant_id is None:
        abort(400)
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    usuario_id = request.args.get("usuario_id", type=int)
    contenido = fichaje_export.a_json(tenant_id, desde, hasta, usuario_id)
    return Response(
        contenido, mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=fichajes.json"},
    )


@fichaje_bp.route("/admin/verificar-integridad")
@login_required
def admin_verificar_integridad():
    """Comprueba la cadena de hashes de TODA la tabla fichajes (no solo
    de este tenant -- ver db.verificar_integridad_fichajes) y muestra si
    está íntegra o en qué fila se rompió. Accesible a cualquier
    admin/gestor de fichajes (no revela contenido de otros tenants)."""
    if not (g.es_admin or g.gestor_fichajes):
        abort(403)
    tenant_id = _tenant_id_admin_actual()
    return render_template(
        "fichaje_integridad.html",
        resultado=db.verificar_integridad_fichajes(),
        tenant_id=tenant_id,
    )
