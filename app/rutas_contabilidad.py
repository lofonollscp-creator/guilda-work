"""Facturas para contabilizar y fichero de enlace de a3 (ver app/facturas_contables.py y app/enlace_a3.py)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, Response, abort, g, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import acceso, db, enlace_a3, enlace_a3_chequeo, importador_clientes, lectura_facturas, plan_cuentas, verticales
from . import facturas_contables as fc
from .auth import login_required

contabilidad_bp = Blueprint("contabilidad", __name__, url_prefix="/contabilidad")


@contabilidad_bp.before_request
def _solo_con_gestoria():
    """Es del módulo Contabilización de facturas: sin él no existe (404); y quien solo audita puede mirar, no cambiar."""
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, "contabilizacion"):
        abort(404)
    if request.method not in ("GET", "HEAD", "OPTIONS") and g.get("usuario_id") is not None and acceso.es_solo_auditor(g.tenant_id, g.usuario_id):
        abort(403)


@contabilidad_bp.app_context_processor
def _catalogos_de_plantilla():
    return {"operaciones_contables": fc.OPERACIONES, "regimenes": [(r, fc.TEXTO_REGIMEN[r]) for r in fc.REGIMENES]}


def _error() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _clientes() -> list:
    visibles = acceso.clientes_visibles(g.tenant_id, g.usuario_id)
    return [c for c in db.listar_clientes_fiscales(g.tenant_id) if visibles is None or c["id"] in visibles]


def _lineas_del_formulario() -> list[dict]:
    return [{c: request.form.get(f"{c}_{i}", "") for c in ("base", "pct_iva", "cuota_iva", "pct_recargo", "pct_retencion", "cuenta", "subtipo")} for i in range(fc.MAX_LINEAS)]


def _datos_del_formulario() -> dict:
    return {c: request.form.get(c, "") for c in ("tipo", "fecha", "fecha_operacion", "numero", "tercero_nombre", "tercero_nif", "tercero_cuenta", "concepto", "referencia", "suplidos", "notas", "abono", "rectifica_fecha", "rectifica_numero", "criterio_caja")}


def _adjunto_del_formulario(cliente_id: int | None) -> int | None:
    """El archivo subido con la factura (si lo hay), guardado en los documentos del cliente. `ValueError` si no vale."""
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename or cliente_id is None:
        return None
    return fc.adjuntar(g.tenant_id, cliente_id, g.usuario_id, archivo.filename, archivo.mimetype, archivo.read(fc.MAX_ADJUNTO_BYTES + 1))


def _trimestres() -> list[str]:
    hoy = date.today()
    res = []
    for anio in (hoy.year, hoy.year - 1):
        res += [f"{anio}-T{t}" for t in (4, 3, 2, 1)]
    return res


@contabilidad_bp.route("/")
@login_required
def lista():
    cliente_id = request.args.get("cliente_id", type=int)
    estado = request.args.get("estado") or None
    tipo = request.args.get("tipo") or None
    trimestre = request.args.get("trimestre") or None
    desde = hasta = None
    if trimestre:
        try:
            desde, hasta = fc.rango_del_trimestre(trimestre)
        except ValueError:
            trimestre = None
    facturas = fc.listar(g.tenant_id, g.usuario_id, cliente_fiscal_id=cliente_id, estado=estado, tipo=tipo, desde=desde, hasta=hasta)
    cfg = fc.configuracion(g.tenant_id, cliente_id) if cliente_id else None
    cierres = {}                                                       # {cliente_fiscal_id: {trimestre: cierre}} de los trimestres que salen en la lista
    for cid in {f["cliente_fiscal_id"] for f in facturas}:
        cierres[cid] = fc.periodos_cerrados(g.tenant_id, cid, {fc.trimestre_de(f["fecha"]) for f in facturas if f["cliente_fiscal_id"] == cid})
    for f in facturas:
        f["periodo_cerrado"] = cierres.get(f["cliente_fiscal_id"], {}).get(fc.trimestre_de(f["fecha"]))
    cierre = fc.periodos_cerrados(g.tenant_id, cliente_id, [trimestre]).get(trimestre) if cliente_id and trimestre else None
    return render_template("contabilidad_lista.html", cierre=cierre, facturas=facturas, clientes=_clientes(), cliente_id=cliente_id, estado=estado or "", tipo=tipo or "", trimestre=trimestre or "",
                           trimestres=_trimestres(), resumen=fc.resumen_por_estado(g.tenant_id, g.usuario_id, cliente_id), cfg=cfg, error=_error(), subnav=None,
                           por_leer=lectura_facturas.pendientes_de_leer(g.tenant_id, g.usuario_id, cliente_id), ia_lista=lectura_facturas.configurada(g.usuario_id), max_archivos=fc.MAX_ARCHIVOS_POR_SUBIDA)


@contabilidad_bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    cliente_id = request.values.get("cliente_id", type=int)
    if request.method == "POST":
        try:
            fid = fc.crear(g.tenant_id, g.usuario_id, cliente_id, _datos_del_formulario(), _lineas_del_formulario(), documento_id=_adjunto_del_formulario(cliente_id))
        except ValueError as e:
            return render_template("contabilidad_factura.html", f=None, datos=_datos_del_formulario(), lineas=_lineas_del_formulario(), cliente_id=cliente_id, clientes=_clientes(), error=str(e), cfg=None), 400
        return redirect(url_for("contabilidad.ver", factura_id=fid))
    datos = {"tipo": request.args.get("tipo") or "recibida", "fecha": date.today().isoformat()}
    return render_template("contabilidad_factura.html", f=None, datos=datos, lineas=[{"pct_iva": "21"}], cliente_id=cliente_id, clientes=_clientes(), error=_error(), cfg=None)


@contabilidad_bp.route("/<int:factura_id>", methods=["GET", "POST"])
@login_required
def ver(factura_id: int):
    f = fc.obtener(g.tenant_id, g.usuario_id, factura_id)
    if f is None:
        abort(404)
    cfg = fc.configuracion(g.tenant_id, f["cliente_fiscal_id"])
    if request.method == "POST":
        try:
            fc.actualizar(g.tenant_id, g.usuario_id, factura_id, _datos_del_formulario(), _lineas_del_formulario(), documento_id=_adjunto_del_formulario(f["cliente_fiscal_id"]))
        except ValueError as e:
            return render_template("contabilidad_factura.html", f=f, datos=_datos_del_formulario(), lineas=_lineas_del_formulario(), cliente_id=f["cliente_fiscal_id"], clientes=_clientes(),
                                   error=str(e), cfg=cfg), 400
        return redirect(url_for("contabilidad.ver", factura_id=factura_id))
    lineas = [{"base": f"{l['base_centimos'] / 100:.2f}".replace(".", ","), "pct_iva": f"{l['pct_iva'] / 100:g}", "cuota_iva": f"{l['cuota_iva'] / 100:.2f}".replace(".", ","),
               "pct_recargo": f"{l['pct_recargo'] / 100:g}" if l["pct_recargo"] else "", "pct_retencion": f"{l['pct_retencion'] / 100:g}" if l["pct_retencion"] else "",
               "cuenta": l["cuenta"] or "", "subtipo": l["subtipo"]} for l in f["lineas"]]
    datos = {k: f[k] for k in ("tipo", "fecha", "fecha_operacion", "numero", "tercero_nombre", "tercero_nif", "concepto", "referencia", "notas")}
    datos.update(rectifica_fecha=f["rectifica_fecha"] or "", rectifica_numero=f["rectifica_numero"] or "", criterio_caja="1" if f.get("criterio_caja") else "")
    datos.update(tercero_cuenta=f["tercero_cuenta"] or "", abono="1" if f["abono"] else "", suplidos=f"{f['suplidos_centimos'] / 100:.2f}".replace(".", ",") if f["suplidos_centimos"] else "")
    return render_template("contabilidad_factura.html", f=f, datos=datos, lineas=lineas, cliente_id=f["cliente_fiscal_id"], clientes=_clientes(), error=_error(), cfg=cfg,
                           cuenta_efectiva=fc.cuenta_efectiva(g.tenant_id, f, cfg), ia_lista=lectura_facturas.configurada(g.usuario_id), regla=fc.regla_del_tercero(g.tenant_id, f["cliente_fiscal_id"], f["tipo"], f["tercero_nif"]), periodo_cerrado=fc.periodos_cerrados(g.tenant_id, f["cliente_fiscal_id"], [f["trimestre"]]).get(f["trimestre"]),
                           cuenta_nueva=bool(cfg["subcuentas_auto"] and f["tercero_nif"] and not f["tercero_cuenta"] and not fc.cuenta_del_tercero(g.tenant_id, f["cliente_fiscal_id"], f["tipo"], f["tercero_nif"])))


@contabilidad_bp.route("/recordatorios", methods=["GET", "POST"])
@login_required
def recordatorios():
    """Escribe a los clientes que aún no han entregado sus facturas antes del cierre del trimestre. Solo se envía lo que se elige y se confirma aquí: nada sale solo."""
    trimestre = request.values.get("trimestre") or _trimestres()[0]
    try:
        fc.rango_del_trimestre(trimestre)
    except ValueError:
        trimestre = _trimestres()[0]
    error = resultado = None
    if request.method == "POST":
        if request.form.get("confirmo") != "1":
            error = _("Marca la casilla para confirmar que quieres escribir a estos clientes.")
        else:
            try:
                resultado = fc.recordar(g.tenant_id, g.usuario_id, request.form.getlist("cliente_id", type=int), trimestre, request.form.get("fecha_limite"),
                                        url_for("portal_cliente.entrar", _external=True))
            except ValueError as e:
                error = str(e)
    return render_template("contabilidad_recordatorios.html", trimestre=trimestre, trimestres=_trimestres(), clientes=fc.para_recordar(g.tenant_id, g.usuario_id, trimestre), error=error,
                           resultado=resultado, dias=fc.DIAS_ENTRE_RECORDATORIOS)


@contabilidad_bp.route("/subir", methods=["POST"])
@login_required
def subir():
    """Varias fotos o PDF de un cliente de una vez, sin rellenar nada: quedan «por leer»."""
    cliente_id = request.form.get("cliente_id", type=int)
    try:
        archivos = [(a.filename, a.mimetype, a.read(fc.MAX_ADJUNTO_BYTES + 1)) for a in request.files.getlist("archivos") if a and a.filename]
        fc.subir_archivos(g.tenant_id, g.usuario_id, cliente_id, request.form.get("tipo", ""), archivos)
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, error=str(e)[:300]))
    return redirect(url_for("contabilidad.lista", cliente_id=cliente_id))


@contabilidad_bp.route("/<int:factura_id>/leer", methods=["POST"])
@login_required
def leer(factura_id: int):
    """Lee con IA el archivo de la factura. Con `Accept: application/json` (lo usa «Leer todas») responde JSON; si no, vuelve a la factura."""
    quiere_json = request.accept_mimetypes.best == "application/json"
    try:
        avisos = lectura_facturas.leer(g.tenant_id, g.usuario_id, factura_id)
    except ValueError as e:
        if quiere_json:
            return jsonify(ok=False, error=str(e)[:300]), 200
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, error=str(e)[:300]))
    if quiere_json:
        return jsonify(ok=True, avisos=avisos)
    return redirect(url_for("contabilidad.ver", factura_id=factura_id))


@contabilidad_bp.route("/<int:factura_id>/estado", methods=["POST"])
@login_required
def estado(factura_id: int):
    try:
        fc.cambiar_estado(g.tenant_id, g.usuario_id, factura_id, request.form.get("estado", ""))
    except ValueError as e:
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, error=str(e)[:300]))
    return redirect(request.form.get("volver") or url_for("contabilidad.ver", factura_id=factura_id))


def _es_supervisor() -> bool:
    return bool(g.get("supervisor_tenant") or g.get("es_admin"))


@contabilidad_bp.route("/ajustes", methods=["GET", "POST"])
@login_required
def ajustes():
    """Centro de la conexión con a3: los valores por defecto del despacho, el código de empresa de cada cliente y el alta de muchos de una vez."""
    error = mensaje = None
    cfg = fc.configuracion_despacho(g.tenant_id)
    if request.method == "POST":
        accion = request.form.get("accion")
        try:
            if accion == "despacho":
                if not _es_supervisor():
                    abort(403)
                cfg = fc.guardar_configuracion_despacho(g.tenant_id, g.usuario_id, request.form)
                mensaje = _("Valores del despacho guardados. Los heredan los clientes que no tengan los suyos.")
            elif accion == "codigos":
                n = fc.guardar_codigos(g.tenant_id, g.usuario_id, {int(k[7:]): v for k, v in request.form.items() if k.startswith("codigo_") and k[7:].isdigit()})
                mensaje = _("Códigos de a3 guardados: %(n)s cambios.", n=n)
            elif accion == "texto":
                r = fc.codigos_desde_texto(g.tenant_id, g.usuario_id, request.form.get("texto", ""))
                mensaje = _("Códigos aplicados: %(n)s.", n=r["aplicados"])
                if r["no_encontrados"]:
                    mensaje += " " + _("NIF sin cliente: %(l)s.", l=", ".join(r["no_encontrados"][:10]))
                if r["invalidos"]:
                    mensaje += " " + _("No válidos: %(l)s.", l="; ".join(r["invalidos"][:10]))
        except ValueError as e:
            error = str(e)
            if accion == "despacho":
                cfg = {**cfg, **{k: request.form.get(k, "") for k in cfg}}
    clientes = fc.resumen_clientes(g.tenant_id, g.usuario_id)
    return render_template("contabilidad_ajustes.html", cfg=cfg, clientes=clientes, listos=sum(1 for c in clientes if c["a3_empresa"]), error=error, mensaje=mensaje, puede_despacho=_es_supervisor())


@contabilidad_bp.route("/cliente/<int:cliente_id>/plan", methods=["GET", "POST"])
@login_required
def plan(cliente_id: int):
    """Importar el plan de cuentas del cliente en a3 (proveedores y clientes) para usar las subcuentas que ya existen allí."""
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None or not acceso.puede_ver_cliente(g.tenant_id, g.usuario_id, cliente_id):
        abort(404)
    error = mensaje = None
    ident = request.values.get("importacion") or ""
    if request.method == "POST":
        accion = request.form.get("accion")
        try:
            if accion == "subir":
                archivo = request.files.get("archivo")
                if archivo is None or not archivo.filename:
                    raise ValueError(_("Elige el archivo exportado de a3."))
                ident = plan_cuentas.preparar(g.tenant_id, g.usuario_id, cliente_id, archivo.filename, archivo.read(importador_clientes.MAX_BYTES + 1))
                return redirect(url_for("contabilidad.plan", cliente_id=cliente_id, importacion=ident))
            if accion == "importar":
                datos = plan_cuentas.cargar(g.tenant_id, g.usuario_id, cliente_id, ident)
                if datos is None:
                    raise ValueError(_("La importación ha caducado: vuelve a subir el archivo."))
                r = plan_cuentas.importar(g.tenant_id, g.usuario_id, cliente_id, datos, request.form.getlist("nombre_ok", type=int))
                importador_clientes.descartar(ident)
                ident = ""
                mensaje = _("Plan importado: %(n)s subcuentas. Coinciden por NIF: %(nif)s; confirmadas por nombre: %(nom)s.", n=r["cuentas"], nif=r["por_nif"], nom=r["por_nombre"])
            elif accion == "borrar":
                plan_cuentas.borrar(g.tenant_id, g.usuario_id, cliente_id)
                mensaje = _("Plan borrado.")
        except (ValueError, importador_clientes.ErrorImportacion) as e:
            error = str(e)
    vista = None
    if ident:
        datos = plan_cuentas.cargar(g.tenant_id, g.usuario_id, cliente_id, ident)
        if datos is None:
            error = error or _("La importación ha caducado: vuelve a subir el archivo.")
            ident = ""
        else:
            vista = plan_cuentas.previsualizar(g.tenant_id, g.usuario_id, cliente_id, datos)
    return render_template("contabilidad_plan.html", cliente=cliente, resumen=plan_cuentas.resumen(g.tenant_id, g.usuario_id, cliente_id), vista=vista, ident=ident, error=error, mensaje=mensaje)


@contabilidad_bp.route("/cliente/<int:cliente_id>/reglas", methods=["GET", "POST"])
@login_required
def reglas(cliente_id: int):
    """Reglas por proveedor y cliente: lo que se rellena solo en sus facturas (cuenta, IVA, retención, tipo de operación, criterio de caja, concepto)."""
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None or not acceso.puede_ver_cliente(g.tenant_id, g.usuario_id, cliente_id):
        abort(404)
    error = mensaje = None
    nueva = {}
    if request.method == "POST":
        accion = request.form.get("accion")
        try:
            if accion == "guardar":
                n = 0
                for r in fc.listar_reglas(g.tenant_id, g.usuario_id, cliente_id):
                    p = f"r{r['id']}_"
                    if request.form.get(p + "borrar"):
                        n += fc.borrar_regla(g.tenant_id, g.usuario_id, cliente_id, r["id"])
                    elif p + "nif" in request.form:
                        fc.guardar_regla(g.tenant_id, g.usuario_id, cliente_id, r["tipo"], {c: request.form.get(p + c) for c in _CAMPOS_REGLA} | {"nif": r["nif"], "nombre": r["nombre"]})
                        n += 1
                mensaje = _("Reglas guardadas.")
            elif accion == "nueva":
                nueva = {c: request.form.get("n_" + c, "") for c in _CAMPOS_REGLA + ("nif", "nombre", "tipo")}
                fc.guardar_regla(g.tenant_id, g.usuario_id, cliente_id, nueva["tipo"], nueva)
                nueva = {}
                mensaje = _("Regla creada.")
            elif accion == "sugeridas":
                claves = [tuple(v.split("|", 1)) for v in request.form.getlist("sugerida") if "|" in v]
                mensaje = _("Reglas creadas: %(n)s.", n=fc.crear_reglas_sugeridas(g.tenant_id, g.usuario_id, cliente_id, claves))
        except ValueError as e:
            error = str(e)
    return render_template("contabilidad_reglas.html", cliente=cliente, reglas=fc.listar_reglas(g.tenant_id, g.usuario_id, cliente_id), sugerencias=fc.sugerencias_de_reglas(g.tenant_id, g.usuario_id, cliente_id),
                           nueva=nueva, error=error, mensaje=mensaje)


_CAMPOS_REGLA = ("cuenta_linea", "pct_iva", "pct_retencion", "subtipo", "criterio_caja", "concepto")


@contabilidad_bp.route("/cliente/<int:cliente_id>/copiar-configuracion", methods=["POST"])
@login_required
def copiar_configuracion(cliente_id: int):
    try:
        if request.form.get("origen") == "despacho":
            fc.restablecer_configuracion(g.tenant_id, g.usuario_id, cliente_id)
        else:
            fc.copiar_configuracion(g.tenant_id, g.usuario_id, request.form.get("origen", type=int) or 0, cliente_id)
    except ValueError as e:
        return redirect(url_for("contabilidad.configuracion", cliente_id=cliente_id, error=str(e)[:300]))
    return redirect(url_for("contabilidad.configuracion", cliente_id=cliente_id))


@contabilidad_bp.route("/cliente/<int:cliente_id>/configuracion", methods=["GET", "POST"])
@login_required
def configuracion(cliente_id: int):
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None or not acceso.puede_ver_cliente(g.tenant_id, g.usuario_id, cliente_id):
        abort(404)
    error = _error()
    cfg = fc.configuracion(g.tenant_id, cliente_id)
    if request.method == "POST":
        try:
            cfg = fc.guardar_configuracion(g.tenant_id, g.usuario_id, cliente_id, request.form)
            return redirect(url_for("contabilidad.lista", cliente_id=cliente_id))
        except ValueError as e:
            error = str(e)
            cfg = {**cfg, **{k: request.form.get(k, "") for k in cfg}}
    return render_template("contabilidad_config.html", cliente=cliente, cfg=cfg, error=error, terceros=fc.terceros_del_cliente(g.tenant_id, g.usuario_id, cliente_id),
                           otros=[c for c in fc.resumen_clientes(g.tenant_id, g.usuario_id) if c["id"] != cliente_id and c["a3_empresa"]])


@contabilidad_bp.route("/periodo", methods=["POST"])
@login_required
def periodo():
    """Cierra a mano un trimestre de un cliente, o lo reabre."""
    cliente_id = request.form.get("cliente_id", type=int)
    trimestre = request.form.get("trimestre") or ""
    try:
        if request.form.get("accion") == "reabrir":
            fc.reabrir_periodo(g.tenant_id, g.usuario_id, cliente_id, trimestre)
        else:
            fc.cerrar_periodo(g.tenant_id, g.usuario_id, cliente_id, trimestre)
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre, error=str(e)[:300]))
    return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre))


@contabilidad_bp.route("/exportar", methods=["POST"])
@login_required
def exportar():
    cliente_id = request.form.get("cliente_id", type=int)
    trimestre = request.form.get("trimestre") or None
    try:
        desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
        r = fc.exportar(g.tenant_id, g.usuario_id, cliente_id, desde=desde, hasta=hasta, confirmar_cerrado=request.form.get("confirmo_cerrado") == "1")
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre, error=str(e)[:300]))
    return _descarga(r["contenido"])


@contabilidad_bp.route("/comprobar", methods=["POST"])
@login_required
def comprobar():
    """Pre-chequeo de lo que saldría ahora para un cliente (y trimestre): no marca ni guarda nada."""
    cliente_id = request.form.get("cliente_id", type=int)
    trimestre = request.form.get("trimestre") or None
    try:
        desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
        informe = fc.comprobar_exportacion(g.tenant_id, g.usuario_id, cliente_id, desde=desde, hasta=hasta)
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre, error=str(e)[:300]))
    return render_template("contabilidad_chequeo.html", informe=informe, titulo=_("Pre-chequeo de la exportación"), cliente_id=cliente_id, trimestre=trimestre or "")


@contabilidad_bp.route("/lotes/<int:lote_id>/comprobar")
@login_required
def comprobar_lote(lote_id: int):
    informe = fc.comprobar_lote(g.tenant_id, g.usuario_id, lote_id)
    if informe is None:
        abort(404)
    return render_template("contabilidad_chequeo.html", informe=informe, titulo=_("Pre-chequeo de un fichero generado"), cliente_id=None, trimestre="")


@contabilidad_bp.route("/comprobar-fichero", methods=["GET", "POST"])
@login_required
def comprobar_fichero():
    """Pre-chequeo de cualquier SUENLACE.DAT que se suba (por ejemplo, uno hecho por otro programa)."""
    informe = error = None
    if request.method == "POST":
        archivo = request.files.get("archivo")
        contenido = archivo.read(2 * 1024 * 1024 + 1) if archivo is not None and archivo.filename else b""
        if not contenido:
            error = _("Elige un fichero SUENLACE.DAT.")
        elif len(contenido) > 2 * 1024 * 1024:
            error = _("El fichero es demasiado grande (máximo 2 MB).")
        else:
            informe = enlace_a3_chequeo.chequear(contenido, min(12, max(4, request.form.get("digitos", 8, type=int) or 8)))
            informe["cliente"] = archivo.filename[:100]
    return render_template("contabilidad_chequeo_fichero.html", informe=informe, error=error)


def _descarga(contenido: bytes) -> Response:
    resp = Response(contenido, mimetype="application/octet-stream")
    resp.headers.set("Content-Disposition", "attachment", filename=enlace_a3.NOMBRE_FICHERO)
    resp.headers.set("X-Content-Type-Options", "nosniff")
    resp.headers.set("Cache-Control", "no-store")
    return resp


@contabilidad_bp.route("/lotes")
@login_required
def lotes():
    return render_template("contabilidad_lotes.html", lotes=fc.listar_lotes(g.tenant_id, g.usuario_id), error=_error())


@contabilidad_bp.route("/lotes/<int:lote_id>/descargar")
@login_required
def descargar_lote(lote_id: int):
    contenido = fc.contenido_del_lote(g.tenant_id, g.usuario_id, lote_id)
    if contenido is None:
        abort(404)
    return _descarga(contenido)


from . import rutas_api_contabilidad  # noqa: E402,F401 -- registra las rutas de la API REST de este módulo en api_bp
