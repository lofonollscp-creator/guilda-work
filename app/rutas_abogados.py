"""Pantallas del módulo Gabinete de abogados (app/abogados.py): panel, ajustes, conflictos, agenda de vistas, minutas y las acciones sobre cada asunto, más la
página pública de solo lectura que se enseña al cliente con su enlace. Todo el módulo desaparece (404) si el despacho no lo tiene activo."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import abogados, almacen_documentos, nucleo, verticales
from .auth import limiter, login_required

abogados_bp = Blueprint("abogados", __name__, url_prefix="/abogados")
asunto_bp = Blueprint("asunto_publico", __name__, url_prefix="/asunto")


@abogados_bp.before_request
def _solo_con_el_modulo():
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, abogados.ID):
        abort(404)


def _sup() -> bool:
    return bool(g.get("supervisor_tenant") or g.get("es_admin"))


def _err() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _volver(expediente_id: int, error: str | None = None):
    return redirect(url_for("expedientes.ficha", expediente_id=expediente_id, **({"error": error[:300]} if error else {})) + "#panel-abogados")


def _entero(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ejecutar(expediente_id: int, f):
    try:
        f()
    except ValueError as e:
        return _volver(expediente_id, str(e))
    return _volver(expediente_id)


# =============================================================================== Panel y ajustes
@abogados_bp.route("/")
@login_required
def panel():
    t, u, s = g.tenant_id, g.usuario_id, _sup()
    hoy = date.today()
    plazos = [p for p in nucleo.listar_plazos(t, u, s, estado="abiertos", hasta=(hoy + timedelta(days=21)).isoformat()) if p["expediente_tipo"] in abogados.TIPOS]
    asuntos, total = nucleo.listar_expedientes(t, u, s, solo_abiertos=True, limite=500)
    asuntos = [a for a in asuntos if a["tipo"] in abogados.TIPOS]
    return render_template(
        "abogados_panel.html", plazos=plazos, asuntos=asuntos[:10], n_asuntos=len(asuntos), vistas=abogados.listar_vistas(t, u, s, desde=datetime.now().isoformat(timespec="minutes"), estado="prevista", limite=8),
        provision_baja=abogados.expedientes_con_provision_baja(t, u, s), minutas_borrador=abogados.listar_minutas(t, u, s, estado="borrador", limite=10),
        minutas_emitidas=abogados.listar_minutas(t, u, s, estado="emitida", limite=10), error=_err(), subnav="abogados",
    )


@abogados_bp.route("/ajustes", methods=["GET", "POST"])
@login_required
def ajustes():
    t = g.tenant_id
    error = _err()
    if request.method == "POST":
        if not _sup():
            abort(403)
        f = request.form
        try:
            abogados.guardar_ajustes(t, serie=f.get("serie", ""), iva_pct=f.get("iva_pct"), irpf_pct=f.get("irpf_pct"), bloque_minutos=f.get("bloque_minutos"),
                                     provision_minima_centimos=abogados._importe(f.get("provision_minima") or "0"), plantilla_encargo=f.get("plantilla_encargo"))
        except ValueError as e:
            return redirect(url_for("abogados.ajustes", error=str(e)[:300]))
        return redirect(url_for("abogados.ajustes", guardado=1))
    return render_template("abogados_ajustes.html", a=abogados.obtener_ajustes(t), puede_editar=_sup(), error=error, guardado=request.args.get("guardado"), subnav="abogados")


# =============================================================================== Conflictos y agenda
@abogados_bp.route("/conflictos")
@login_required
def conflictos():
    nombre, nif, como = (request.args.get("nombre") or "").strip(), (request.args.get("nif") or "").strip(), request.args.get("como") if request.args.get("como") in ("cliente", "contraparte") else "cliente"
    hallazgos = abogados.revisar_conflictos(g.tenant_id, g.usuario_id, nombre, nif, como, _sup()) if (nombre or nif) else None
    return render_template("abogados_conflictos.html", hallazgos=hallazgos, nombre=nombre, nif=nif, como=como, roles=dict(abogados.ROLES_PARTE), subnav="abogados")


@abogados_bp.route("/vistas")
@login_required
def vistas():
    desde = request.args.get("desde") or date.today().isoformat()
    hasta = request.args.get("hasta") or None
    lista = abogados.listar_vistas(g.tenant_id, g.usuario_id, _sup(), desde=desde, hasta=hasta)
    return render_template("abogados_vistas.html", vistas=lista, desde=desde, hasta=hasta or "", tipos=dict(abogados.TIPOS_VISTA), subnav="abogados")


@abogados_bp.route("/vistas.ics")
@login_required
def vistas_ics():
    lista = abogados.listar_vistas(g.tenant_id, g.usuario_id, _sup(), desde=datetime.now().isoformat(timespec="minutes"), estado="prevista", limite=500)
    return Response(abogados.vistas_a_ics(lista), mimetype="text/calendar; charset=utf-8", headers={"Content-Disposition": "attachment; filename=senalamientos.ics"})


# =============================================================================== Minutas
@abogados_bp.route("/minutas")
@login_required
def minutas():
    estado = request.args.get("estado") if request.args.get("estado") in ("borrador", "emitida", "pagada", "anulada") else None
    return render_template("abogados_minutas.html", minutas=abogados.listar_minutas(g.tenant_id, g.usuario_id, _sup(), estado=estado), estado=estado or "", subnav="abogados")


def _minuta_o_404(minuta_id: int):
    m, lineas = abogados.obtener_minuta(g.tenant_id, minuta_id)
    if m is None or (m["expediente_id"] and nucleo.obtener_expediente(g.tenant_id, m["expediente_id"], g.usuario_id, _sup()) is None):
        abort(404)
    return m, lineas


@abogados_bp.route("/minutas/<int:minuta_id>")
@login_required
def minuta(minuta_id: int):
    m, lineas = _minuta_o_404(minuta_id)
    return render_template("abogados_minuta.html", m=m, lineas=lineas, error=_err(), subnav="abogados")


@abogados_bp.route("/minutas/<int:minuta_id>.pdf")
@login_required
def minuta_pdf(minuta_id: int):
    m, _l = _minuta_o_404(minuta_id)
    nombre = (m["numero"] or f"borrador-{m['id']}").replace("/", "-")
    return Response(abogados.minuta_a_pdf(g.tenant_id, minuta_id), mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename=minuta_{nombre}.pdf"})


def _accion_minuta(minuta_id: int, f):
    _minuta_o_404(minuta_id)
    try:
        f()
    except ValueError as e:
        return redirect(url_for("abogados.minuta", minuta_id=minuta_id, error=str(e)[:300]))
    return redirect(url_for("abogados.minuta", minuta_id=minuta_id))


@abogados_bp.route("/minutas/<int:minuta_id>/lineas", methods=["POST"])
@login_required
def minuta_linea(minuta_id: int):
    f = request.form
    return _accion_minuta(minuta_id, lambda: abogados.anadir_linea_minuta(g.tenant_id, minuta_id, f.get("concepto", ""), f.get("importe", ""), f.get("tipo", "honorarios")))


@abogados_bp.route("/minutas/<int:minuta_id>/lineas/<int:linea_id>/eliminar", methods=["POST"])
@login_required
def minuta_quitar_linea(minuta_id: int, linea_id: int):
    return _accion_minuta(minuta_id, lambda: abogados.quitar_linea_minuta(g.tenant_id, minuta_id, linea_id))


@abogados_bp.route("/minutas/<int:minuta_id>/impuestos", methods=["POST"])
@login_required
def minuta_impuestos(minuta_id: int):
    f = request.form
    return _accion_minuta(minuta_id, lambda: abogados.fijar_impuestos_minuta(g.tenant_id, minuta_id, f.get("iva_pct"), f.get("irpf_pct"), f.get("notas")))


@abogados_bp.route("/minutas/<int:minuta_id>/emitir", methods=["POST"])
@login_required
def minuta_emitir(minuta_id: int):
    return _accion_minuta(minuta_id, lambda: abogados.emitir_minuta(g.tenant_id, g.usuario_id, minuta_id, bool(request.form.get("cargar_a_provision"))))


@abogados_bp.route("/minutas/<int:minuta_id>/estado", methods=["POST"])
@login_required
def minuta_estado(minuta_id: int):
    return _accion_minuta(minuta_id, lambda: abogados.cambiar_estado_minuta(g.tenant_id, g.usuario_id, minuta_id, request.form.get("estado", "")))


@abogados_bp.route("/minutas/<int:minuta_id>/eliminar", methods=["POST"])
@login_required
def minuta_eliminar(minuta_id: int):
    m, _l = _minuta_o_404(minuta_id)
    try:
        abogados.eliminar_borrador(g.tenant_id, minuta_id)
    except ValueError as e:
        return redirect(url_for("abogados.minuta", minuta_id=minuta_id, error=str(e)[:300]))
    return redirect(url_for("abogados.minutas"))


# =============================================================================== Acciones sobre un asunto
@abogados_bp.route("/expedientes/<int:expediente_id>/datos", methods=["POST"])
@login_required
def datos(expediente_id: int):
    campos = {c: request.form.get(c) for c in (*abogados.CAMPOS_PROCEDIMIENTO, "cuantia") if c in request.form}
    return _ejecutar(expediente_id, lambda: abogados.fijar_datos(g.tenant_id, g.usuario_id, expediente_id, _sup(), **campos))


@abogados_bp.route("/expedientes/<int:expediente_id>/partes", methods=["POST"])
@login_required
def parte(expediente_id: int):
    f = request.form
    try:
        abogados.anadir_parte(g.tenant_id, g.usuario_id, expediente_id, f.get("rol", ""), f.get("nombre", ""), f.get("nif"), f.get("notas"), _sup())
    except ValueError as e:
        return _volver(expediente_id, str(e))
    como = "contraparte" if f.get("rol") in abogados.ROLES_CONTRARIOS else "cliente"      # qué va a ser para nosotros quien se acaba de añadir
    if f.get("rol") == "cliente" or f.get("rol") in abogados.ROLES_CONTRARIOS:
        if abogados.revisar_conflictos(g.tenant_id, g.usuario_id, f.get("nombre", ""), f.get("nif"), como, _sup(), excluir_expediente=expediente_id):
            url = url_for("abogados.conflictos", nombre=f.get("nombre", ""), nif=f.get("nif") or None, como=como)
            return redirect(url)           # hay coincidencias: se enseñan antes de seguir
    return _volver(expediente_id)


@abogados_bp.route("/expedientes/<int:expediente_id>/partes/<int:parte_id>/eliminar", methods=["POST"])
@login_required
def parte_eliminar(expediente_id: int, parte_id: int):
    return _ejecutar(expediente_id, lambda: abogados.eliminar_parte(g.tenant_id, g.usuario_id, expediente_id, parte_id, _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/vistas", methods=["POST"])
@login_required
def vista_nueva(expediente_id: int):
    f = request.form
    return _ejecutar(expediente_id, lambda: abogados.crear_vista(g.tenant_id, g.usuario_id, expediente_id, f.get("fecha_hora", ""), f.get("tipo", "vista"), f.get("lugar"), f.get("notas"), _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/vistas/<int:vista_id>/estado", methods=["POST"])
@login_required
def vista_estado(expediente_id: int, vista_id: int):
    return _ejecutar(expediente_id, lambda: abogados.cambiar_estado_vista(g.tenant_id, g.usuario_id, vista_id, request.form.get("estado", ""), _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/vistas/<int:vista_id>/eliminar", methods=["POST"])
@login_required
def vista_eliminar(expediente_id: int, vista_id: int):
    return _ejecutar(expediente_id, lambda: abogados.eliminar_vista(g.tenant_id, g.usuario_id, vista_id, _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/notificacion", methods=["GET", "POST"])
@login_required
def notificacion(expediente_id: int):
    x = nucleo.obtener_expediente(g.tenant_id, expediente_id, g.usuario_id, _sup())
    if x is None or x["tipo"] not in abogados.TIPOS:
        abort(404)
    f = request.values
    error, calculo = None, None
    if request.method == "POST":
        try:
            abogados.registrar_notificacion(g.tenant_id, g.usuario_id, expediente_id, f.get("resolucion", ""), f.get("fecha_notificacion", ""), int(f.get("plazo") or 0), f.get("unidad", "habiles"),
                                            titulo=f.get("titulo"), critico=bool(f.get("critico")), crear_tarea=bool(f.get("crear_tarea")), supervisor=_sup())
        except (ValueError, TypeError) as e:
            error = str(e)
        else:
            return _volver(expediente_id)
    if f.get("fecha_notificacion") and f.get("plazo"):
        try:
            calculo = abogados.calcular_plazo(g.tenant_id, f.get("fecha_notificacion"), int(f.get("plazo")), f.get("unidad", "habiles"))
        except (ValueError, TypeError) as e:
            error = error or str(e)
    return render_template("abogados_notificacion.html", x=x, f=f, calculo=calculo, error=error or _err(), resoluciones=abogados.RESOLUCIONES, tipicos=abogados.PLAZOS_TIPICOS, hoy=date.today().isoformat(), subnav="abogados")


@abogados_bp.route("/expedientes/<int:expediente_id>/fondos", methods=["POST"])
@login_required
def fondo(expediente_id: int):
    f = request.form
    return _ejecutar(expediente_id, lambda: abogados.registrar_movimiento(g.tenant_id, g.usuario_id, expediente_id, f.get("tipo", ""), f.get("importe", ""), f.get("concepto", ""), f.get("fecha") or None, _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/minutas", methods=["POST"])
@login_required
def minuta_nueva(expediente_id: int):
    try:
        mid = abogados.crear_borrador_de_minuta(g.tenant_id, g.usuario_id, expediente_id, _sup(), desde=request.form.get("desde") or None, hasta=request.form.get("hasta") or None)
    except ValueError as e:
        return _volver(expediente_id, str(e))
    return redirect(url_for("abogados.minuta", minuta_id=mid))


@abogados_bp.route("/expedientes/<int:expediente_id>/hoja-de-encargo", methods=["POST"])
@login_required
def hoja_encargo(expediente_id: int):
    return _ejecutar(expediente_id, lambda: abogados.generar_hoja_de_encargo(g.tenant_id, g.usuario_id, expediente_id, _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/firma/<int:documento_id>", methods=["POST"])
@login_required
def firma(expediente_id: int, documento_id: int):
    f = request.form
    return _ejecutar(expediente_id, lambda: abogados.enviar_a_firma(g.tenant_id, g.usuario_id, documento_id, f.get("email", ""), f.get("nombre", ""), _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/documentos/<int:documento_id>/compartir", methods=["POST"])
@login_required
def compartir(expediente_id: int, documento_id: int):
    return _ejecutar(expediente_id, lambda: abogados.compartir_documento(g.tenant_id, g.usuario_id, expediente_id, documento_id, bool(request.form.get("compartido")), _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/mensajes", methods=["POST"])
@login_required
def mensaje_responder(expediente_id: int):
    from . import mensajes_enlace
    return _ejecutar(expediente_id, lambda: mensajes_enlace.responder(abogados.ID, g.tenant_id, g.usuario_id, expediente_id, request.form.get("texto", ""), _sup()))


@abogados_bp.route("/expedientes/<int:expediente_id>/enlaces", methods=["POST"])
@login_required
def enlace_nuevo(expediente_id: int):
    try:
        token = abogados.crear_enlace(g.tenant_id, g.usuario_id, expediente_id, request.form.get("dias", 30, type=int), _sup(), permite_mensajes=bool(request.form.get("permite_mensajes")))
    except ValueError as e:
        return _volver(expediente_id, str(e))
    x = nucleo.obtener_expediente(g.tenant_id, expediente_id, g.usuario_id, _sup())
    resp = Response(render_template("abogados_enlace_creado.html", x=x, url=url_for("asunto_publico.ver", token=token, _external=True), subnav="abogados"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@abogados_bp.route("/expedientes/<int:expediente_id>/enlaces/<int:enlace_id>/revocar", methods=["POST"])
@login_required
def enlace_revocar(expediente_id: int, enlace_id: int):
    return _ejecutar(expediente_id, lambda: abogados.revocar_enlace(g.tenant_id, g.usuario_id, expediente_id, enlace_id, _sup()))


# =============================================================================== Página pública del cliente (solo lectura)
def _sin_rastro(resp: Response) -> Response:
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@asunto_bp.route("/<token>")
@limiter.limit("60/minute")
def ver(token: str):
    datos = abogados.datos_publicos(token)
    if datos is None:
        return _sin_rastro(Response(render_template("asunto_publico_caducado.html"), status=404))
    return _sin_rastro(Response(render_template("asunto_publico.html", d=datos, token=token, llano=abogados.ESTADO_EN_LLANO)))


@asunto_bp.route("/<token>/mensajes", methods=["POST"])
@limiter.limit("20/hour")
def mensaje_enviar(token: str):
    from . import mensajes_enlace
    try:
        mensajes_enlace.enviar_externo(abogados.ID, token, request.form.get("nombre"), request.form.get("texto", ""))
    except ValueError as e:
        datos = abogados.datos_publicos(token)
        if datos is None:
            return _sin_rastro(Response(render_template("asunto_publico_caducado.html"), status=404))
        return _sin_rastro(Response(render_template("asunto_publico.html", d=datos, token=token, llano=abogados.ESTADO_EN_LLANO, error_mensaje=str(e)), status=400))
    return _sin_rastro(redirect(url_for("asunto_publico.ver", token=token) + "#mensajes"))


@asunto_bp.route("/<token>/documentos/<int:documento_id>")
@limiter.limit("60/minute")
def documento(token: str, documento_id: int):
    d = abogados.documento_publico(token, documento_id)
    if d is None:
        abort(404)
    nombre = d["nombre_archivo"].replace('"', "")
    return _sin_rastro(Response(d["contenido"], mimetype=d["tipo_mime"], headers={"Content-Disposition": f'attachment; filename="{nombre}"', "X-Content-Type-Options": "nosniff"}))
