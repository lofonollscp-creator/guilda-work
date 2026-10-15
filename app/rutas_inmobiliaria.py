"""Pantallas del módulo Inmobiliaria (app/inmobiliaria.py): panel, tablero de captación, inmuebles, demandas con cruces, agenda de visitas, ajustes y exportación para portales, más la
página pública de solo lectura del propietario. Todo el módulo desaparece (404) si la agencia no lo tiene activo. Las acciones sobre un inmueble se hacen desde el panel de su operación."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, g, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import almacen_documentos, inmobiliaria, nucleo, verticales
from .auth import limiter, login_required

inmobiliaria_bp = Blueprint("inmobiliaria", __name__, url_prefix="/inmobiliaria")
propietario_bp = Blueprint("propietario_publico", __name__, url_prefix="/propietario")


@inmobiliaria_bp.before_request
def _solo_con_el_modulo():
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, inmobiliaria.ID):
        abort(404)


def _sup() -> bool:
    return bool(g.get("supervisor_tenant") or g.get("es_admin"))


def _err() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _entero(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _inmueble_o_404(inmueble_id: int):
    i, x = inmobiliaria.obtener_inmueble(g.tenant_id, g.usuario_id, inmueble_id, _sup())
    if i is None:
        abort(404)
    return i, x


def _volver(inmueble_id: int, error: str | None = None):
    i, x = _inmueble_o_404(inmueble_id)
    return redirect(url_for("expedientes.ficha", expediente_id=x["id"], **({"error": error[:300]} if error else {})) + "#panel-inmobiliaria")


def _ejecutar(inmueble_id: int, f):
    _inmueble_o_404(inmueble_id)
    try:
        f()
    except ValueError as e:
        return _volver(inmueble_id, str(e))
    return _volver(inmueble_id)


# =============================================================================== Panel, tablero y listados
@inmobiliaria_bp.route("/")
@login_required
def panel():
    r = inmobiliaria.resumen(g.tenant_id, g.usuario_id, _sup())
    return render_template("inmobiliaria_panel.html", r=r, estados=inmobiliaria.ESTADOS_OPERACION, error=_err(), seccion="panel", mapa=inmobiliaria.mapa_url)


@inmobiliaria_bp.route("/tablero")
@login_required
def tablero():
    operacion = request.args.get("operacion") if request.args.get("operacion") in inmobiliaria.OPERACIONES else None
    inmuebles = inmobiliaria.listar_inmuebles(g.tenant_id, g.usuario_id, _sup(), operacion=operacion, limite=1000)
    columnas = {e.id: [] for e in inmobiliaria.ESTADOS_OPERACION}
    for i in inmuebles:
        columnas.setdefault(i["estado"], []).append(i)
    return render_template("inmobiliaria_tablero.html", columnas=columnas, estados=inmobiliaria.ESTADOS_OPERACION, operacion=operacion or "", error=_err(), seccion="tablero")


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/fase", methods=["POST"])
@login_required
def fase(inmueble_id: int):
    i, x = _inmueble_o_404(inmueble_id)
    try:
        nucleo.cambiar_estado_expediente(g.tenant_id, g.usuario_id, x["id"], request.form.get("estado", ""), _sup())
    except ValueError as e:
        return redirect(url_for("inmobiliaria.tablero", error=str(e)[:300]))
    return redirect(url_for("inmobiliaria.tablero", operacion=request.form.get("operacion") or None))


@inmobiliaria_bp.route("/inmuebles")
@login_required
def inmuebles():
    f = {"operacion": request.args.get("operacion") or None, "estado": request.args.get("estado") or None, "municipio": request.args.get("municipio") or None, "q": request.args.get("q") or None,
         "precio_max": request.args.get("precio_max") or None, "solo_activos": request.args.get("activos", "1") == "1"}
    try:
        lista = inmobiliaria.listar_inmuebles(g.tenant_id, g.usuario_id, _sup(), **f)
        error = _err()
    except ValueError as e:
        lista, error = [], str(e)
    return render_template("inmobiliaria_inmuebles.html", inmuebles=lista, f=f, estados=inmobiliaria.ESTADOS_OPERACION, error=error, seccion="inmuebles")


@inmobiliaria_bp.route("/inmuebles/nuevo", methods=["GET", "POST"])
@login_required
def inmueble_nuevo():
    t = g.tenant_id
    datos = {k: (request.form.get(k) or "").strip() for k in ("propietario_id", "operacion", "direccion", "tipo", "municipio", "codigo_postal", "ref_catastral", "superficie_m2", "habitaciones", "banos",
                                                               "planta", "certificado_energetico", "precio", "descripcion", "copropietarios")}
    error = _err()
    if request.method == "POST":
        try:
            if _entero(datos["propietario_id"]) is None:
                raise ValueError(_("Elige el propietario."))
            iid, xid = inmobiliaria.crear_inmueble(t, g.usuario_id, int(datos["propietario_id"]), datos["operacion"], datos["direccion"], tipo=datos["tipo"] or "piso", municipio=datos["municipio"],
                                                   codigo_postal=datos["codigo_postal"], ref_catastral=datos["ref_catastral"], superficie_m2=datos["superficie_m2"], habitaciones=datos["habitaciones"],
                                                   banos=datos["banos"], planta=datos["planta"], certificado_energetico=datos["certificado_energetico"] or None, caracteristicas=request.form.getlist("caracteristicas"),
                                                   precio=datos["precio"], descripcion=datos["descripcion"], copropietarios=datos["copropietarios"])
            return redirect(url_for("expedientes.ficha", expediente_id=xid) + "#panel-inmobiliaria")
        except ValueError as e:
            error = str(e)
    return render_template("inmobiliaria_inmueble_nuevo.html", datos=datos, marcadas=request.form.getlist("caracteristicas"), propietarios=nucleo.listar_clientes(t, limite=500)[0], tipos=inmobiliaria.TIPOS_INMUEBLE,
                           caracteristicas=inmobiliaria.CARACTERISTICAS, certificados=inmobiliaria.CERTIFICADOS, error=error, seccion="inmuebles"), (400 if request.method == "POST" and error else 200)


# =============================================================================== Acciones sobre un inmueble (desde el panel de su operación)
@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/datos", methods=["POST"])
@login_required
def datos(inmueble_id: int):
    f = request.form
    campos = {k: f.get(k) for k in ("referencia", "tipo", "direccion", "municipio", "codigo_postal", "ref_catastral", "superficie_m2", "habitaciones", "banos", "planta", "certificado_energetico", "descripcion", "copropietarios") if k in f}
    campos["caracteristicas"] = f.getlist("caracteristicas")
    return _ejecutar(inmueble_id, lambda: inmobiliaria.editar_inmueble(g.tenant_id, g.usuario_id, inmueble_id, _sup(), **campos))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/precio", methods=["POST"])
@login_required
def precio(inmueble_id: int):
    return _ejecutar(inmueble_id, lambda: inmobiliaria.cambiar_precio(g.tenant_id, g.usuario_id, inmueble_id, request.form.get("precio", ""), request.form.get("motivo"), _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/fotos", methods=["POST"])
@login_required
def fotos_subir(inmueble_id: int):
    _inmueble_o_404(inmueble_id)
    archivos = [f for f in request.files.getlist("foto") if f and f.filename]
    if not archivos:
        return _volver(inmueble_id, _("Elige al menos una foto."))
    errores = []
    for f in archivos[:15]:
        try:
            inmobiliaria.subir_foto(g.tenant_id, g.usuario_id, inmueble_id, f.filename, f.read(12 * 1024 * 1024), _sup())
        except ValueError as e:
            errores.append(f"{f.filename}: {e}")
    return _volver(inmueble_id, " ".join(errores) or None)


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/fotos/<int:documento_id>")
@login_required
def foto(inmueble_id: int, documento_id: int):
    i, x = _inmueble_o_404(inmueble_id)
    d = almacen_documentos.leer(g.tenant_id, g.usuario_id, documento_id)
    if d is None or d["expediente_id"] != x["id"] or d["categoria"] != "Foto":
        abort(404)
    return Response(d["contenido"], mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/fotos/<int:documento_id>/eliminar", methods=["POST"])
@login_required
def foto_eliminar(inmueble_id: int, documento_id: int):
    i, x = _inmueble_o_404(inmueble_id)
    d = almacen_documentos.leer(g.tenant_id, g.usuario_id, documento_id)
    if d is not None and d["expediente_id"] == x["id"] and d["categoria"] == "Foto":
        almacen_documentos.eliminar(g.tenant_id, g.usuario_id, documento_id)
    return _volver(inmueble_id)


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/visitas", methods=["POST"])
@login_required
def visita_nueva(inmueble_id: int):
    f = request.form
    return _ejecutar(inmueble_id, lambda: inmobiliaria.crear_visita(g.tenant_id, g.usuario_id, inmueble_id, f.get("fecha_hora", ""), demanda_id=_entero(f.get("demanda_id")), visitante=f.get("visitante"),
                                                                    agente_id=_entero(f.get("agente_id")), supervisor=_sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/visitas/<int:visita_id>/resultado", methods=["POST"])
@login_required
def visita_resultado(inmueble_id: int, visita_id: int):
    f = request.form
    return _ejecutar(inmueble_id, lambda: inmobiliaria.registrar_resultado_visita(g.tenant_id, g.usuario_id, visita_id, f.get("estado", ""), f.get("valoracion") or None, f.get("interes") or None, f.get("comentario"), _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/visitas/<int:visita_id>/eliminar", methods=["POST"])
@login_required
def visita_eliminar(inmueble_id: int, visita_id: int):
    return _ejecutar(inmueble_id, lambda: inmobiliaria.eliminar_visita(g.tenant_id, g.usuario_id, visita_id, _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/ofertas", methods=["POST"])
@login_required
def oferta_nueva(inmueble_id: int):
    f = request.form
    return _ejecutar(inmueble_id, lambda: inmobiliaria.registrar_oferta(g.tenant_id, g.usuario_id, inmueble_id, f.get("importe", ""), demanda_id=_entero(f.get("demanda_id")), oferente=f.get("oferente"),
                                                                        notas=f.get("notas"), supervisor=_sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/ofertas/<int:oferta_id>/estado", methods=["POST"])
@login_required
def oferta_estado(inmueble_id: int, oferta_id: int):
    return _ejecutar(inmueble_id, lambda: inmobiliaria.cambiar_estado_oferta(g.tenant_id, g.usuario_id, oferta_id, request.form.get("estado", ""), _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/contratos", methods=["POST"])
@login_required
def contrato_nuevo(inmueble_id: int):
    f = request.form
    return _ejecutar(inmueble_id, lambda: inmobiliaria.generar_contrato(g.tenant_id, g.usuario_id, inmueble_id, f.get("tipo", ""), parte_nombre=f.get("parte_nombre", ""), parte_nif=f.get("parte_nif"),
                                                                        precio=f.get("precio") or None, arras=f.get("arras") or None, renta=f.get("renta") or None, fianza=f.get("fianza") or None,
                                                                        duracion=f.get("duracion"), comision=f.get("comision"), supervisor=_sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/contratos/<int:contrato_id>/firma", methods=["POST"])
@login_required
def contrato_firma(inmueble_id: int, contrato_id: int):
    f = request.form
    return _ejecutar(inmueble_id, lambda: inmobiliaria.enviar_contrato_a_firma(g.tenant_id, g.usuario_id, contrato_id, f.get("email", ""), f.get("nombre", ""), _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/contratos/<int:contrato_id>/firmado", methods=["POST"])
@login_required
def contrato_firmado(inmueble_id: int, contrato_id: int):
    return _ejecutar(inmueble_id, lambda: inmobiliaria.marcar_contrato_firmado(g.tenant_id, g.usuario_id, contrato_id, _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/contratos/<int:contrato_id>/documento")
@login_required
def contrato_documento(inmueble_id: int, contrato_id: int):
    i, x = _inmueble_o_404(inmueble_id)
    c = next((c for c in inmobiliaria.listar_contratos(g.tenant_id, g.usuario_id, inmueble_id, _sup()) if c["id"] == contrato_id), None)
    d = almacen_documentos.leer(g.tenant_id, g.usuario_id, c["documento_id"]) if c else None
    if d is None:
        abort(404)
    return Response(d["contenido"], mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{d["nombre_archivo"].replace(chr(34), "")}"', "X-Content-Type-Options": "nosniff"})


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/comision", methods=["POST"])
@login_required
def comision(inmueble_id: int):
    f = request.form
    try:
        reparto = [(int(a), int(p)) for a, p in zip(f.getlist("agente_id"), f.getlist("agente_pct")) if a and p not in ("", None)]
    except ValueError:
        return _volver(inmueble_id, _("El reparto no es válido."))
    return _ejecutar(inmueble_id, lambda: inmobiliaria.guardar_comision(g.tenant_id, g.usuario_id, inmueble_id, f.get("base", ""), f.get("pct_bp", ""), f.get("minimo") or "0", f.get("iva_pct", ""), reparto, _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/comision/estado", methods=["POST"])
@login_required
def comision_estado(inmueble_id: int):
    return _ejecutar(inmueble_id, lambda: inmobiliaria.cambiar_estado_comision(g.tenant_id, g.usuario_id, inmueble_id, request.form.get("estado", ""), _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/documentos/<int:documento_id>/compartir", methods=["POST"])
@login_required
def compartir(inmueble_id: int, documento_id: int):
    i, x = _inmueble_o_404(inmueble_id)
    from . import abogados

    try:
        abogados.compartir_documento_de_expediente(g.tenant_id, g.usuario_id, x["id"], documento_id, bool(request.form.get("compartido")))
    except ValueError as e:
        return _volver(inmueble_id, str(e))
    return _volver(inmueble_id)


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/mensajes", methods=["POST"])
@login_required
def mensaje_responder(inmueble_id: int):
    from . import mensajes_enlace
    i, x = _inmueble_o_404(inmueble_id)
    return _ejecutar(inmueble_id, lambda: mensajes_enlace.responder(inmobiliaria.ID, g.tenant_id, g.usuario_id, x["id"], request.form.get("texto", ""), _sup()))


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/enlaces", methods=["POST"])
@login_required
def enlace_nuevo(inmueble_id: int):
    i, x = _inmueble_o_404(inmueble_id)
    try:
        token = inmobiliaria.crear_enlace(g.tenant_id, g.usuario_id, inmueble_id, request.form.get("dias", 30, type=int), _sup(), permite_mensajes=bool(request.form.get("permite_mensajes")))
    except ValueError as e:
        return _volver(inmueble_id, str(e))
    resp = Response(render_template("inmobiliaria_enlace_creado.html", i=i, x=x, url=url_for("propietario_publico.ver", token=token, _external=True), seccion="inmuebles"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/enlaces/<int:enlace_id>/revocar", methods=["POST"])
@login_required
def enlace_revocar(inmueble_id: int, enlace_id: int):
    from . import enlaces_publicos

    i, x = _inmueble_o_404(inmueble_id)
    enlaces_publicos.revocar(inmobiliaria.ID, g.tenant_id, x["id"], enlace_id)
    return _volver(inmueble_id)


@inmobiliaria_bp.route("/inmuebles/<int:inmueble_id>/informe.pdf")
@login_required
def informe(inmueble_id: int):
    i, x = _inmueble_o_404(inmueble_id)
    hoy = date.today()
    desde = request.args.get("desde") or hoy.replace(day=1).isoformat()
    hasta = request.args.get("hasta") or hoy.isoformat()
    try:
        pdf = inmobiliaria.informe_a_pdf(g.tenant_id, inmueble_id, nucleo._fecha_iso(desde), nucleo._fecha_iso(hasta))
    except ValueError as e:
        return _volver(inmueble_id, str(e))
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=informe_propietario.pdf"})


# =============================================================================== Demandas
@inmobiliaria_bp.route("/demandas")
@login_required
def demandas():
    estado = request.args.get("estado", "activa")
    estado = estado if estado in dict(inmobiliaria.ESTADOS_DEMANDA) else None
    return render_template("inmobiliaria_demandas.html", demandas=inmobiliaria.listar_demandas(g.tenant_id, estado=estado, operacion=request.args.get("operacion")), estado=estado or "",
                           operacion=request.args.get("operacion") or "", estados=dict(inmobiliaria.ESTADOS_DEMANDA), tipos=dict(inmobiliaria.TIPOS_INMUEBLE), error=_err(), seccion="demandas")


@inmobiliaria_bp.route("/demandas/nueva", methods=["GET", "POST"])
@login_required
def demanda_nueva():
    t = g.tenant_id
    f = request.form
    error = _err()
    if request.method == "POST":
        try:
            if _entero(f.get("cliente_id")) is None:
                raise ValueError(_("Elige el cliente."))
            did = inmobiliaria.crear_demanda(t, g.usuario_id, int(f["cliente_id"]), f.get("operacion", ""), tipos=f.getlist("tipos"), municipios=f.get("municipios"), presupuesto_min=f.get("presupuesto_min") or None,
                                             presupuesto_max=f.get("presupuesto_max") or None, superficie_min=f.get("superficie_min"), habitaciones_min=f.get("habitaciones_min"), banos_min=f.get("banos_min"),
                                             requisitos=f.getlist("requisitos"), notas=f.get("notas"), agente_id=_entero(f.get("agente_id")))
            return redirect(url_for("inmobiliaria.demanda", demanda_id=did))
        except ValueError as e:
            error = str(e)
    return render_template("inmobiliaria_demanda_nueva.html", datos=f, clientes=nucleo.listar_clientes(t, limite=500)[0], tipos=inmobiliaria.TIPOS_INMUEBLE, caracteristicas=inmobiliaria.CARACTERISTICAS,
                           equipo=nucleo.equipo(t), cliente_id=_entero(request.values.get("cliente_id")), error=error, seccion="demandas"), (400 if request.method == "POST" and error else 200)


@inmobiliaria_bp.route("/demandas/<int:demanda_id>")
@login_required
def demanda(demanda_id: int):
    d = inmobiliaria.obtener_demanda(g.tenant_id, demanda_id)
    if d is None:
        abort(404)
    return render_template("inmobiliaria_demanda.html", d=d, cruces=inmobiliaria.cruces_para_demanda(g.tenant_id, g.usuario_id, demanda_id, _sup(), minimo=int(request.args.get("minimo", 40) or 40)),
                           estados=inmobiliaria.ESTADOS_DEMANDA, tipos=dict(inmobiliaria.TIPOS_INMUEBLE), caracteristicas=dict(inmobiliaria.CARACTERISTICAS), error=_err(), seccion="demandas",
                           visitas=[v for v in inmobiliaria.listar_visitas(g.tenant_id, g.usuario_id, _sup()) if v["demanda_id"] == demanda_id])


@inmobiliaria_bp.route("/demandas/<int:demanda_id>/estado", methods=["POST"])
@login_required
def demanda_estado(demanda_id: int):
    try:
        inmobiliaria.cambiar_estado_demanda(g.tenant_id, demanda_id, request.form.get("estado", ""))
    except ValueError as e:
        return redirect(url_for("inmobiliaria.demanda", demanda_id=demanda_id, error=str(e)[:300]))
    return redirect(url_for("inmobiliaria.demanda", demanda_id=demanda_id))


@inmobiliaria_bp.route("/demandas/<int:demanda_id>/visita", methods=["POST"])
@login_required
def demanda_visita(demanda_id: int):
    try:
        inmobiliaria.crear_visita(g.tenant_id, g.usuario_id, _entero(request.form.get("inmueble_id")) or 0, request.form.get("fecha_hora", ""), demanda_id=demanda_id, supervisor=_sup())
    except ValueError as e:
        return redirect(url_for("inmobiliaria.demanda", demanda_id=demanda_id, error=str(e)[:300]))
    return redirect(url_for("inmobiliaria.demanda", demanda_id=demanda_id))


# =============================================================================== Agenda, ajustes y publicación
@inmobiliaria_bp.route("/visitas")
@login_required
def visitas():
    desde = request.args.get("desde") or date.today().isoformat()
    hasta = request.args.get("hasta") or (date.fromisoformat(desde) + timedelta(days=7)).isoformat()
    try:
        lista = inmobiliaria.listar_visitas(g.tenant_id, g.usuario_id, _sup(), desde=desde, hasta=hasta, agente_id=_entero(request.args.get("agente_id")))
        error = _err()
    except ValueError as e:
        lista, error = [], str(e)
    dias: dict[str, list] = {}
    for v in lista:
        dias.setdefault(v["fecha_hora"][:10], []).append(v)
    return render_template("inmobiliaria_visitas.html", dias=dias, desde=desde, hasta=hasta, estados=dict(inmobiliaria.ESTADOS_VISITA), equipo=nucleo.equipo(g.tenant_id), agente_id=_entero(request.args.get("agente_id")),
                           mapa=inmobiliaria.mapa_url, error=error, seccion="visitas")


@inmobiliaria_bp.route("/ajustes", methods=["GET", "POST"])
@login_required
def ajustes():
    t = g.tenant_id
    if request.method == "POST":
        if not _sup():
            abort(403)
        f = request.form
        try:
            inmobiliaria.guardar_ajustes(t, iva_pct=f.get("iva_pct"), comision_venta_pct=f.get("comision_venta_pct", ""), comision_alquiler_meses=f.get("comision_alquiler_meses", ""),
                                         minimo_centimos=nucleo.importe_a_centimos(f.get("minimo") or "0"), plantillas={k: f.get(f"plantilla_{k}", "") for k in inmobiliaria.CAMPOS_PLANTILLA})
        except ValueError as e:
            return redirect(url_for("inmobiliaria.ajustes", error=str(e)[:300]))
        return redirect(url_for("inmobiliaria.ajustes", guardado=1))
    return render_template("inmobiliaria_ajustes.html", a=inmobiliaria.obtener_ajustes(t), tipos_contrato=inmobiliaria.TIPOS_CONTRATO, puede_editar=_sup(), error=_err(), guardado=request.args.get("guardado"), seccion="ajustes")


@inmobiliaria_bp.route("/feed.json")
@login_required
def feed_json():
    return Response(json.dumps(inmobiliaria.feed_publicacion(g.tenant_id, g.usuario_id, _sup()), ensure_ascii=False, indent=1), mimetype="application/json", headers={"Content-Disposition": "attachment; filename=inmuebles.json"})


@inmobiliaria_bp.route("/feed.csv")
@login_required
def feed_csv():
    return Response(inmobiliaria.feed_a_csv(inmobiliaria.feed_publicacion(g.tenant_id, g.usuario_id, _sup())), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=inmuebles.csv"})


# =============================================================================== Página pública del propietario (solo lectura)
def _sin_rastro(resp: Response) -> Response:
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@propietario_bp.route("/<token>")
@limiter.limit("60/minute")
def ver(token: str):
    d = inmobiliaria.datos_propietario(token)
    if d is None:
        return _sin_rastro(Response(render_template("asunto_publico_caducado.html"), status=404))
    return _sin_rastro(Response(render_template("propietario_publico.html", d=d, token=token, llano=inmobiliaria.ESTADO_EN_LLANO, estados_oferta=dict(inmobiliaria.ESTADOS_OFERTA))))


@propietario_bp.route("/<token>/mensajes", methods=["POST"])
@limiter.limit("20/hour")
def mensaje_enviar(token: str):
    from . import mensajes_enlace
    try:
        mensajes_enlace.enviar_externo(inmobiliaria.ID, token, request.form.get("nombre"), request.form.get("texto", ""))
    except ValueError as e:
        d = inmobiliaria.datos_propietario(token)
        if d is None:
            return _sin_rastro(Response(render_template("asunto_publico_caducado.html"), status=404))
        return _sin_rastro(Response(render_template("propietario_publico.html", d=d, token=token, llano=inmobiliaria.ESTADO_EN_LLANO, estados_oferta=dict(inmobiliaria.ESTADOS_OFERTA), error_mensaje=str(e)), status=400))
    return _sin_rastro(redirect(url_for("propietario_publico.ver", token=token) + "#mensajes"))


@propietario_bp.route("/<token>/informe.pdf")
@limiter.limit("20/minute")
def informe_pdf(token: str):
    pdf = inmobiliaria.informe_publico_pdf(token)
    if pdf is None:
        abort(404)
    return _sin_rastro(Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=informe_propietario.pdf"}))


@propietario_bp.route("/<token>/documentos/<int:documento_id>")
@limiter.limit("60/minute")
def documento(token: str, documento_id: int):
    d = inmobiliaria.documento_publico(token, documento_id)
    if d is None:
        abort(404)
    nombre = d["nombre_archivo"].replace('"', "")
    return _sin_rastro(Response(d["contenido"], mimetype=d["tipo_mime"], headers={"Content-Disposition": f'attachment; filename="{nombre}"', "X-Content-Type-Options": "nosniff"}))
