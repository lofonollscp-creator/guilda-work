"""Facturas para contabilizar y fichero de enlace de a3 (ver app/facturas_contables.py y app/enlace_a3.py)."""
from __future__ import annotations

import re
from datetime import date

from flask import Blueprint, Response, abort, g, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _, ngettext

from . import acceso, cobro_contabilidad, db, redireccion, enlace_a3, exportacion_generica, ia_comparador, ia_despacho, ia_trabajos, lectura_calidad, enlace_a3_chequeo, importador_clientes, lectura_facturas, plan_cuentas, verticales
from . import facturas_contables as fc
from . import cierre_trimestre, cola_contabilidad, cuadre_303, terceros_duplicados, facturas_control, panel_cierre, retorno_a3, facturas_portal, justificantes as justificantes_mod
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
    return {"operaciones_contables": fc.OPERACIONES, "regimenes": [(r, fc.TEXTO_REGIMEN[r]) for r in fc.REGIMENES], "impresos_comunes": fc.IMPRESOS_COMUNES}


def _error() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _clientes() -> list:
    visibles = acceso.clientes_visibles(g.tenant_id, g.usuario_id)
    return [c for c in db.listar_clientes_fiscales(g.tenant_id) if visibles is None or c["id"] in visibles]


def _lineas_del_formulario() -> list[dict]:
    return [{c: request.form.get(f"{c}_{i}", "") for c in ("base", "pct_iva", "cuota_iva", "pct_recargo", "pct_retencion", "cuenta", "subtipo", "impreso")} for i in range(fc.MAX_LINEAS)]


def _datos_del_formulario() -> dict:
    return {c: request.form.get(c, "") for c in ("tipo", "fecha", "fecha_operacion", "numero", "tercero_nombre", "tercero_nif", "tercero_cuenta", "concepto", "referencia", "suplidos", "notas", "abono", "rectifica_fecha", "rectifica_numero", "criterio_caja", *fc.DATOS_A3)}


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


def resumen_pendientes_hay(cliente_id: int | None) -> bool:
    return bool(fc.resumen_por_estado(g.tenant_id, g.usuario_id, cliente_id)["pendiente"])


@contabilidad_bp.route("/revisar-seguras", methods=["POST"])
@login_required
def revisar_seguras():
    """Da por revisadas de golpe las pendientes que se leyeron con seguridad y no tienen nada que mirar."""
    cliente_id = request.form.get("cliente_id", type=int)
    try:
        r = fc.revisar_en_lote(g.tenant_id, g.usuario_id, cliente_id, request.form.get("umbral", type=int) or fc.UMBRAL_REVISION_EN_LOTE)
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, error=_(str(e))[:300]))
    return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, estado="pendiente", orden="confianza", en_lote=r["revisadas"]))


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
    orden = "confianza" if request.args.get("orden") == "confianza" else None
    facturas = fc.listar(g.tenant_id, g.usuario_id, cliente_fiscal_id=cliente_id, estado=estado, tipo=tipo, desde=desde, hasta=hasta, orden=orden)
    cfg = fc.configuracion(g.tenant_id, cliente_id) if cliente_id else None
    por_cliente: dict = {}                                             # {cliente_fiscal_id: trimestres que salen en la lista}
    for f in facturas:
        por_cliente.setdefault(f["cliente_fiscal_id"], set()).add(fc.trimestre_de(f["fecha"]))
    cierres = fc.periodos_cerrados_de_varios(g.tenant_id, por_cliente)       # {cliente_fiscal_id: {trimestre: cierre}}
    for f in facturas:
        f["periodo_cerrado"] = cierres.get(f["cliente_fiscal_id"], {}).get(fc.trimestre_de(f["fecha"]))
    cierre = fc.periodos_cerrados(g.tenant_id, cliente_id, [trimestre]).get(trimestre) if cliente_id and trimestre else None
    uso_plan = cobro_contabilidad.consumo(g.tenant_id)
    ids = [f["id"] for f in facturas]
    en_lote = len(fc.revisables_en_lote(g.tenant_id, g.usuario_id, cliente_id)) if cliente_id and resumen_pendientes_hay(cliente_id) else 0
    return render_template("contabilidad_lista.html", orden=orden, en_lote=en_lote, umbral_lote=fc.UMBRAL_REVISION_EN_LOTE, duplicadas=fc.con_duplicado_entre(g.tenant_id, ids), con_mensaje=facturas_portal.con_mensajes_sin_leer_del_cliente(g.tenant_id, ids), uso_plan=uso_plan if uso_plan["tarifa"] else None, cierre=cierre, facturas=facturas, clientes=_clientes(), cliente_id=cliente_id, estado=estado or "", tipo=tipo or "", trimestre=trimestre or "",
                           trimestres=_trimestres(), resumen=fc.resumen_por_estado(g.tenant_id, g.usuario_id, cliente_id), cfg=cfg, error=_error(), subnav=None,
                           por_leer=lectura_facturas.pendientes_de_leer(g.tenant_id, g.usuario_id, cliente_id), ia_lista=lectura_facturas.configurada(g.usuario_id), max_archivos=fc.MAX_ARCHIVOS_POR_SUBIDA)


@contabilidad_bp.context_processor
def _fiscal_en_el_formulario():
    """Para la casilla «Incluir en Guilda Fiscal» del formulario de factura (funciones: solo cuestan algo si la plantilla las llama)."""
    def activo() -> bool:
        return bool(g.get("tenant_id") and verticales.esta_activo(g.tenant_id, "fiscal"))

    def marcada(f) -> bool:
        if request.method == "POST" and request.form.get("incluir_en_fiscal_presente"):
            return bool(request.form.get("incluir_en_fiscal"))
        return bool(int(f.get("incluir_en_fiscal", 1))) if f else True

    return {"fiscal_activo": activo, "fiscal_marcada": marcada}


def _elegir_fiscal(factura_id: int) -> None:
    """Si el formulario trae la casilla «Incluir en Guilda Fiscal» (solo con el módulo activo), guarda la elección de la persona."""
    if request.form.get("incluir_en_fiscal_presente"):
        fc.fijar_incluir_en_fiscal(g.tenant_id, g.usuario_id, factura_id, bool(request.form.get("incluir_en_fiscal")))


@contabilidad_bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    cliente_id = request.values.get("cliente_id", type=int)
    if request.method == "POST":
        try:
            fid = fc.crear(g.tenant_id, g.usuario_id, cliente_id, _datos_del_formulario(), _lineas_del_formulario(), documento_id=_adjunto_del_formulario(cliente_id))
            _elegir_fiscal(fid)
        except ValueError as e:
            return render_template("contabilidad_factura.html", f=None, datos=_datos_del_formulario(), lineas=_lineas_del_formulario(), cliente_id=cliente_id, clientes=_clientes(), error=_(str(e)), cfg=None), 400
        return redirect(url_for("contabilidad.ver", factura_id=fid))
    datos = {"tipo": request.args.get("tipo") or "recibida", "fecha": date.today().isoformat()}
    return render_template("contabilidad_factura.html", f=None, datos=datos, lineas=[{"pct_iva": "21"}], cliente_id=cliente_id, clientes=_clientes(), error=_error(), cfg=None)


@contabilidad_bp.route("/calidad")
@login_required
def calidad():
    """Cómo va la lectura de facturas: acierto por dato, de dónde sale cada lectura, qué proveedores se corrigen más y cuánto cuesta. Solo para la dirección del despacho."""
    if not ia_despacho.es_direccion(g.usuario_id):
        abort(403)
    desde = request.args.get("desde") or ""
    try:
        date.fromisoformat(desde)
    except ValueError:
        desde = date.today().replace(day=1).isoformat()
    return render_template("contabilidad_calidad.html", r=lectura_calidad.resumen(g.tenant_id, desde), desde=desde, etiquetas=lectura_calidad.ETIQUETAS,
                           tipos_documento=[("abono", _("Abonos y rectificativas")), ("sin_nif", _("Tiquets y recibos (sin NIF)")), ("emitida", _("Facturas emitidas")), ("recibida", _("Facturas recibidas")),
                                            ("portal", _("Subidas por el cliente")), ("despacho", _("Subidas por el despacho"))],
                           fuentes={"xml": _("Factura electrónica (XML)"), "texto": _("Texto del PDF"), "imagen": _("Imagen del documento"), "ocr": _("Texto reconocido en el servidor (OCR)")})


@contabilidad_bp.route("/comparar", methods=["GET", "POST"])
@login_required
def comparar():
    """Compara varios modelos de IA sobre facturas de este despacho que ya se revisaron: acierto por dato, tiempo y coste. Solo para la dirección."""
    if not ia_despacho.es_direccion(g.usuario_id):
        abort(403)
    error = None
    if request.method == "POST":
        try:
            lote, _n = ia_comparador.lanzar(g.tenant_id, g.usuario_id, request.form.get("n", 10, type=int), [int(i) for i in request.form.getlist("modelo") if i.isdigit()])
            return redirect(url_for("contabilidad.comparar", lote=lote))
        except ValueError as e:
            error = _(str(e))
    lote = (request.args.get("lote") or "")[:32]
    return render_template("contabilidad_comparar.html", modelos=ia_comparador.modelos_disponibles(g.usuario_id), muestra=len(ia_comparador.muestra_posible(g.tenant_id, g.usuario_id, ia_comparador.MUESTRA_MAXIMA)),
                           lote=lote, r=ia_comparador.resultado(g.tenant_id, lote) if lote else None, error=error, etiquetas=lectura_calidad.ETIQUETAS)


@contabilidad_bp.route("/comparar/<lote>.json")
@login_required
def comparar_estado(lote: str):
    if not ia_despacho.es_direccion(g.usuario_id):
        abort(403)
    return jsonify(ia_comparador.resultado(g.tenant_id, lote[:32]))


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
            _elegir_fiscal(factura_id)
        except ValueError as e:
            return render_template("contabilidad_factura.html", f=f, datos=_datos_del_formulario(), lineas=_lineas_del_formulario(), cliente_id=f["cliente_fiscal_id"], clientes=_clientes(),
                                   error=_(str(e)), cfg=cfg), 400
        return redirect(url_for("contabilidad.ver", factura_id=factura_id))
    lineas = [{"base": f"{l['base_centimos'] / 100:.2f}".replace(".", ","), "pct_iva": f"{l['pct_iva'] / 100:g}", "cuota_iva": f"{l['cuota_iva'] / 100:.2f}".replace(".", ","),
               "pct_recargo": f"{l['pct_recargo'] / 100:g}" if l["pct_recargo"] else "", "pct_retencion": f"{l['pct_retencion'] / 100:g}" if l["pct_retencion"] else "",
               "cuenta": l["cuenta"] or "", "subtipo": l["subtipo"], "impreso": l.get("impreso") or ""} for l in f["lineas"]]
    datos = {k: f[k] for k in ("tipo", "fecha", "fecha_operacion", "numero", "tercero_nombre", "tercero_nif", "concepto", "referencia", "notas")}
    a3 = f.get("a3") or {}
    datos.update(bien_inversion="1" if a3.get("bien_inversion") else "", dua=a3.get("dua", ""), clave_340=a3.get("clave_340", ""), nif_representante=a3.get("nif_representante", ""), autofactura=a3.get("autofactura", ""),
                 metalico="total" if a3.get("metalico") == "total" else (f"{a3['metalico'] / 100:.2f}".replace(".", ",") if a3.get("metalico") else ""),
                 inmuebles="total" if a3.get("inmuebles") == "total" else (f"{a3['inmuebles'] / 100:.2f}".replace(".", ",") if a3.get("inmuebles") else ""),
                 iban=a3.get("iban", ""), vencimiento=a3.get("vencimiento", ""), forma_pago=a3.get("forma_pago", ""))
    datos.update(rectifica_fecha=f["rectifica_fecha"] or "", rectifica_numero=f["rectifica_numero"] or "", criterio_caja="1" if f.get("criterio_caja") else "")
    datos.update(tercero_cuenta=f["tercero_cuenta"] or "", abono="1" if f["abono"] else "", suplidos=f"{f['suplidos_centimos'] / 100:.2f}".replace(".", ",") if f["suplidos_centimos"] else "")
    mensajes = facturas_portal.mensajes(g.tenant_id, factura_id)
    facturas_portal.marcar_leidos(g.tenant_id, factura_id, "empleado")
    return render_template("contabilidad_factura.html", f=f, datos=datos, lineas=lineas, cliente_id=f["cliente_fiscal_id"], clientes=_clientes(), error=_error(), cfg=cfg,
                           mensajes=mensajes, duplicados=fc.posibles_duplicados(g.tenant_id, g.usuario_id, factura_id), avisos_control=facturas_control.avisos(g.tenant_id, f), historial=fc.historial(g.tenant_id, g.usuario_id, factura_id),
                           cuenta_efectiva=fc.cuenta_efectiva(g.tenant_id, f, cfg), ia_lista=lectura_facturas.configurada(g.usuario_id), evidencia=lectura_facturas.evidencia_de(f) if f.get("lectura") in ("ia", "xml") else None, visor=_visor_de(f), visor_evidencias=_evidencias_para_el_visor(f), dudosos=lectura_facturas.campos_dudosos(lectura_facturas.evidencia_de(f), f["tipo"]) if f.get("lectura") == "ia" and f["estado"] == "pendiente" else [],
                           imagen_en_linea=False, regla=fc.regla_del_tercero(g.tenant_id, f["cliente_fiscal_id"], f["tipo"], f["tercero_nif"]), periodo_cerrado=fc.periodos_cerrados(g.tenant_id, f["cliente_fiscal_id"], [f["trimestre"]]).get(f["trimestre"]),
                           cuenta_nueva=bool(cfg["subcuentas_auto"] and f["tercero_nif"] and not f["tercero_cuenta"] and not fc.cuenta_del_tercero(g.tenant_id, f["cliente_fiscal_id"], f["tipo"], f["tercero_nif"])))


def _es_imagen(f: dict) -> bool:
    """¿El archivo adjunto de la factura es una imagen que se puede enseñar en línea? (se mira el tipo guardado, sin abrir el documento)"""
    from . import almacen_documentos
    datos = almacen_documentos.datos_de_cliente_fiscal(g.tenant_id, f["cliente_fiscal_id"], f["documento_id"])
    return bool(datos) and (datos.get("tipo_mime") or "").lower().split(";")[0] in IMAGENES_EN_LINEA


IMAGENES_EN_LINEA = ("image/png", "image/jpeg", "image/webp", "image/gif")
MIME_XML = ("application/xml", "text/xml")
LADO_PAGINA = 1500                                  # píxeles del lado mayor de cada página del visor: legible con zoom sin pesar de más


def _evidencias_para_el_visor(f: dict) -> dict:
    """{campo: {caja, coherente}} de las evidencias con recuadro, para que el visor las dibuje al pasar por cada campo."""
    e = lectura_facturas.evidencia_de(f) if f.get("lectura") in ("ia", "xml") else None
    return {c: {"caja": v["caja"], "coherente": v["coherente"]} for c, v in ((e or {}).get("campos") or {}).items() if v.get("caja")}


def _visor_de(f: dict) -> dict | None:
    """Lo que enseña el visor de la pantalla de revisión junto a los datos: `imagen` (una foto), `pdf` (sus páginas renderizadas), `xml` (factura electrónica: no hay imagen, se enseñan sus datos exactos) u
    `otro` (solo descarga). None si la factura no tiene archivo."""
    if not f.get("documento_id"):
        return None
    from . import almacen_documentos, facturas_estructuradas, pdf_facturas
    from .cifrado_despacho import DespachoBloqueado
    meta = almacen_documentos.datos_de_cliente_fiscal(g.tenant_id, f["cliente_fiscal_id"], f["documento_id"])
    if not meta:
        return None
    mime = (meta.get("tipo_mime") or "").lower().split(";")[0]
    visor = {"tipo": "otro", "mime": mime, "paginas": 1, "nombre": meta.get("nombre_archivo") or ""}
    if mime in IMAGENES_EN_LINEA:
        visor["tipo"] = "imagen"
    elif mime == "application/pdf" or mime in MIME_XML:
        try:
            doc = almacen_documentos.leer_de_cliente_fiscal(g.tenant_id, f["cliente_fiscal_id"], f["documento_id"], g.usuario_id)
        except DespachoBloqueado:
            return {**visor, "bloqueado": True}
        if doc is not None:
            contenido = bytes(doc["contenido"])
            if mime in MIME_XML:
                r = facturas_estructuradas.extraer(contenido, mime)
                visor.update(tipo="xml", datos=r["datos"] if r else None, formato=r["formato"] if r else None)
            else:
                n = pdf_facturas.numero_de_paginas(contenido)
                if n:
                    visor.update(tipo="pdf", paginas=min(n, pdf_facturas.MAX_PAGINAS))
    return visor


@contabilidad_bp.route("/<int:factura_id>/pagina/<int:numero>")
@login_required
def pagina(factura_id: int, numero: int):
    """Una página del PDF de la factura como imagen, para el visor de la pantalla de revisión (el navegador no tiene por qué tener visor de PDF, y así los recuadros de la IA encajan igual)."""
    from . import almacen_documentos, pdf_facturas
    from .cifrado_despacho import DespachoBloqueado
    f = fc.obtener(g.tenant_id, g.usuario_id, factura_id)
    if f is None or not f.get("documento_id") or not 1 <= numero <= pdf_facturas.MAX_PAGINAS:
        abort(404)
    try:
        doc = almacen_documentos.leer_de_cliente_fiscal(g.tenant_id, f["cliente_fiscal_id"], f["documento_id"], g.usuario_id)
    except DespachoBloqueado:
        abort(404)
    if doc is None or ((doc.get("tipo_mime") or "").lower().split(";")[0] != "application/pdf"):
        abort(404)
    png = pdf_facturas.pagina_a_imagen(bytes(doc["contenido"]), numero - 1, LADO_PAGINA)
    if png is None:
        abort(404)
    r = Response(png, mimetype="image/png")
    r.headers["Content-Disposition"] = "inline"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "private, max-age=120"
    r.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    return r


@contabilidad_bp.route("/<int:factura_id>/imagen")
@login_required
def imagen(factura_id: int):
    """La foto de la factura, en línea, para enseñar sobre ella de dónde sacó la IA cada dato. Solo imágenes (nunca PDF, SVG ni HTML); los PDF se abren con el enlace de descarga."""
    from . import almacen_documentos
    from .cifrado_despacho import DespachoBloqueado
    f = fc.obtener(g.tenant_id, g.usuario_id, factura_id)
    if f is None or not f.get("documento_id"):
        abort(404)
    try:
        doc = almacen_documentos.leer_de_cliente_fiscal(g.tenant_id, f["cliente_fiscal_id"], f["documento_id"], g.usuario_id)
    except DespachoBloqueado:
        abort(404)
    tipo = ((doc or {}).get("tipo_mime") or "").lower().split(";")[0]
    if doc is None or tipo not in IMAGENES_EN_LINEA:
        abort(404)
    r = Response(bytes(doc["contenido"]), mimetype=tipo)
    r.headers["Content-Disposition"] = "inline"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "private, no-store"
    r.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    return r


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
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, error=_(str(e))[:300]))
    return redirect(url_for("contabilidad.lista", cliente_id=cliente_id))


@contabilidad_bp.route("/leer-todas", methods=["POST"])
@login_required
def leer_todas():
    """Pone en la cola de fondo la lectura de todas las facturas por leer (de un cliente, o de todos los que ve la persona) y devuelve el lote para seguir el avance."""
    if not lectura_facturas.configurada(g.usuario_id):
        return jsonify({"ok": False, "error": _("Hace falta un modelo y una clave de IA, en Ajustes del Asistente IA.")}), 400
    lote, n = lectura_facturas.encolar_pendientes(g.tenant_id, g.usuario_id, request.form.get("cliente_id", type=int) or None)
    return jsonify({"ok": True, "lote": lote, "total": n})


@contabilidad_bp.route("/lectura/<lote>")
@login_required
def progreso_lectura(lote: str):
    """El avance de un lote de lecturas en segundo plano."""
    return jsonify(ia_trabajos.progreso(g.tenant_id, lote[:32]))


@contabilidad_bp.route("/<int:factura_id>/leer", methods=["POST"])
@login_required
def leer(factura_id: int):
    """Lee con IA el archivo de la factura. Con `Accept: application/json` (lo usa «Leer todas») responde JSON; si no, vuelve a la factura."""
    quiere_json = request.accept_mimetypes.best == "application/json"
    if not quiere_json and lectura_facturas.configurada(g.usuario_id):
        # Leer con IA puede tardar un minuto: no se hace dentro de la petición (retendría un hilo del servidor y la página se quedaría
        # parada). Va a la cola de fondo y la factura enseña el avance. Sin IA (XML) la lectura es instantánea y sigue siendo directa.
        f = fc.obtener(g.tenant_id, g.usuario_id, factura_id)
        if f is None:
            abort(404)
        lote = lectura_facturas.encolar_una(g.tenant_id, g.usuario_id, factura_id)
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, leyendo=lote))
    try:
        avisos = lectura_facturas.leer(g.tenant_id, g.usuario_id, factura_id)
    except ValueError as e:
        if quiere_json:
            return jsonify(ok=False, error=_(str(e))[:300]), 200
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, error=_(str(e))[:300]))
    if quiere_json:
        return jsonify(ok=True, avisos=avisos)
    return redirect(url_for("contabilidad.ver", factura_id=factura_id))


@contabilidad_bp.route("/<int:factura_id>/vies", methods=["POST"])
@login_required
def vies(factura_id: int):
    """Comprueba en el VIES europeo el NIF-IVA de la factura (solo consulta: no guarda nada)."""
    f = fc.obtener(g.tenant_id, g.usuario_id, factura_id)
    if f is None:
        abort(404)
    r = facturas_control.comprobar_vies(f.get("tercero_nif"))
    return jsonify(valido=r["valido"], error=r.get("error") or "")


@contabilidad_bp.route("/<int:factura_id>/estado", methods=["POST"])
@login_required
def estado(factura_id: int):
    try:
        fc.cambiar_estado(g.tenant_id, g.usuario_id, factura_id, request.form.get("estado", ""), confirmar_duplicado=bool(request.form.get("no_es_duplicado")))
    except ValueError as e:
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, error=_(str(e))[:300]))
    if request.form.get("siguiente"):
        siguiente = fc.siguiente_pendiente(g.tenant_id, g.usuario_id, factura_id, "confianza" if request.form.get("orden") == "confianza" else None)
        return redirect(url_for("contabilidad.ver", factura_id=siguiente) if siguiente else url_for("contabilidad.lista", estado="pendiente", todas_revisadas=1))
    return redirect(redireccion.destino_local(request.form.get("volver"), por_defecto=url_for("contabilidad.ver", factura_id=factura_id)))


@contabilidad_bp.route("/<int:factura_id>/mensajes", methods=["POST"])
@login_required
def mensaje(factura_id: int):
    """Escribe al cliente en una factura suya: lo verá en su portal."""
    try:
        facturas_portal.escribir_como_despacho(g.tenant_id, g.usuario_id, factura_id, request.form.get("texto", ""))
    except ValueError as e:
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, error=_(str(e))[:300]) + "#mensajes")
    return redirect(url_for("contabilidad.ver", factura_id=factura_id) + "#mensajes")


@contabilidad_bp.route("/<int:factura_id>/mover", methods=["POST"])
@login_required
def mover(factura_id: int):
    """Pasa la factura a otro cliente del despacho (se leyó o se subió en el equivocado)."""
    try:
        fc.mover_a_cliente(g.tenant_id, g.usuario_id, factura_id, request.form.get("cliente_destino", type=int) or 0)
    except ValueError as e:
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, error=_(str(e))[:300]))
    return redirect(url_for("contabilidad.ver", factura_id=factura_id, movida=1))


@contabilidad_bp.route("/<int:factura_id>/devolver", methods=["POST"])
@login_required
def devolver(factura_id: int):
    """Devuelve al cliente una factura que anotó él, con el motivo, para que la corrija o la vuelva a enviar desde su portal."""
    try:
        facturas_portal.devolver(g.tenant_id, g.usuario_id, factura_id, request.form.get("motivo", ""))
    except ValueError as e:
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, error=_(str(e))[:300]))
    return redirect(url_for("contabilidad.ver", factura_id=factura_id))


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


_CAMPOS_REGLA = ("cuenta_linea", "pct_iva", "pct_retencion", "pct_deducible", "subtipo", "criterio_caja", "concepto")


@contabilidad_bp.route("/cliente/<int:cliente_id>/copiar-configuracion", methods=["POST"])
@login_required
def copiar_configuracion(cliente_id: int):
    try:
        if request.form.get("origen") == "despacho":
            fc.restablecer_configuracion(g.tenant_id, g.usuario_id, cliente_id)
        else:
            fc.copiar_configuracion(g.tenant_id, g.usuario_id, request.form.get("origen", type=int) or 0, cliente_id)
    except ValueError as e:
        return redirect(url_for("contabilidad.configuracion", cliente_id=cliente_id, error=_(str(e))[:300]))
    return redirect(url_for("contabilidad.configuracion", cliente_id=cliente_id))


@contabilidad_bp.route("/cliente/<int:cliente_id>/cuentas", methods=["GET", "POST"])
@login_required
def cuentas(cliente_id: int):
    """El mapa de subcuentas de a3 de un cliente: qué cuenta va a cada proveedor y cliente, de dónde sale, y cambiarla a mano."""
    cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id)
    if cliente is None or not acceso.puede_ver_cliente(g.tenant_id, g.usuario_id, cliente_id):
        abort(404)
    error = mensaje = None
    if request.method == "POST":
        actuales = {(t["tipo"], t["nif"]): t["cuenta"] for t in fc.mapa_de_cuentas(g.tenant_id, g.usuario_id, cliente_id)["terceros"]}
        cambios = 0
        try:
            for clave, valor in request.form.items():
                if not clave.startswith("cuenta__") or not valor.strip():
                    continue
                _p, tipo, nif = clave.split("__", 2)
                if (tipo, nif) in actuales and actuales[(tipo, nif)] != re.sub(r"\D", "", valor):
                    fc.fijar_cuenta_tercero(g.tenant_id, g.usuario_id, cliente_id, tipo, nif, valor)
                    cambios += 1
            mensaje = _("Subcuentas guardadas: %(n)s cambios.", n=cambios)
        except ValueError as e:
            error = _(str(e))
    return render_template("contabilidad_cuentas.html", cliente=cliente, mapa=fc.mapa_de_cuentas(g.tenant_id, g.usuario_id, cliente_id), cfg=fc.configuracion(g.tenant_id, cliente_id), error=error or _error(), mensaje=mensaje, subnav=None)


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
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre, error=_(str(e))[:300]))
    return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre))


@contabilidad_bp.route("/cola")
@login_required
def cola():
    """Qué cliente atender primero: ordenados por los días que sobran hasta su próximo plazo una vez descontado lo que cuesta despachar lo pendiente."""
    return render_template("contabilidad_cola.html", filas=cola_contabilidad.cola(g.tenant_id, g.usuario_id), ritmo=cola_contabilidad.FACTURAS_POR_DIA, subnav=None)


@contabilidad_bp.route("/justificantes")
@login_required
def justificantes():
    """Movimientos del banco y tiquets que los clientes han explicado (o que aún están esperando su respuesta)."""
    cliente_id = request.args.get("cliente_id", type=int)
    estado = request.args.get("estado") or None
    return render_template("contabilidad_justificantes.html", filas=justificantes_mod.listar(g.tenant_id, g.usuario_id, cliente_fiscal_id=cliente_id, estado=estado), clientes=_clientes(), cliente_id=cliente_id,
                           estado=estado, pedidos=request.args.get("pedidos", type=int), repetidos=request.args.get("repetidos", type=int), avisado=request.args.get("avisado", type=int), error=_error(), subnav=None)


@contabilidad_bp.route("/justificantes/<int:justificante_id>/estado", methods=["POST"])
@login_required
def justificante_estado(justificante_id: int):
    try:
        justificantes_mod.cambiar_estado(g.tenant_id, g.usuario_id, justificante_id, request.form.get("estado", ""))
    except ValueError as e:
        return redirect(url_for("contabilidad.justificantes", cliente_id=request.form.get("cliente_id", type=int), error=_(str(e))[:300]))
    return redirect(url_for("contabilidad.justificantes", cliente_id=request.form.get("cliente_id", type=int), estado=request.form.get("filtro") or None))


@contabilidad_bp.route("/justificantes/<int:justificante_id>/archivo")
@login_required
def justificante_archivo(justificante_id: int):
    doc = justificantes_mod.documento_de(g.tenant_id, g.usuario_id, justificante_id)
    if doc is None:
        abort(404)
    nombre, tipo, contenido = doc
    return Response(contenido, mimetype=tipo, headers={"Content-Disposition": f'attachment; filename="{nombre.replace(chr(34), "")}"', "X-Content-Type-Options": "nosniff"})


@contabilidad_bp.route("/cierre", methods=["GET", "POST"])
@login_required
def cierre():
    """Cierre guiado de un trimestre de un cliente: lo que queda por hacer y el botón que lo cierra, avisa al cliente y le deja el informe en su portal."""
    cliente_id = request.values.get("cliente_id", type=int)
    trimestre = request.values.get("trimestre") or ""
    error, hecho = None, None
    try:
        if request.method == "POST":
            hecho = cierre_trimestre.cerrar(g.tenant_id, g.usuario_id, cliente_id, trimestre, forzar=bool(request.form.get("forzar")))
        c = cierre_trimestre.checklist(g.tenant_id, g.usuario_id, cliente_id, trimestre)
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, error=_(str(e))[:300])) if request.method == "GET" else \
            redirect(url_for("contabilidad.cierre", cliente_id=cliente_id, trimestre=trimestre, error=_(str(e))[:300]))
    cliente = next((x for x in _clientes() if x["id"] == cliente_id), None)
    return render_template("contabilidad_cierre.html", c=c, cliente=cliente, cliente_id=cliente_id, trimestre=trimestre, etiqueta=cierre_trimestre.etiqueta(trimestre), hecho=hecho, error=error or _error(),
                           con_fiscal=verticales.esta_activo(g.tenant_id, "fiscal"), subnav=None)


@contabilidad_bp.route("/exportar", methods=["POST"])
@login_required
def exportar():
    cliente_id = request.form.get("cliente_id", type=int)
    trimestre = request.form.get("trimestre") or None
    try:
        desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
        r = fc.exportar(g.tenant_id, g.usuario_id, cliente_id, desde=desde, hasta=hasta, confirmar_cerrado=request.form.get("confirmo_cerrado") == "1")
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre, error=_(str(e))[:300]))
    return _descarga(r["contenido"])


@contabilidad_bp.route("/exportar-otro-programa", methods=["POST"])
@login_required
def exportar_otro_programa():
    """Descarga las facturas revisadas de un cliente en CSV o Excel, para llevarlas a un programa que no es a3. No las marca como exportadas ni necesita la configuración de a3."""
    cliente_id = request.form.get("cliente_id", type=int)
    trimestre = request.form.get("trimestre") or None
    formato = request.form.get("formato", "csv")
    try:
        if formato not in ("csv", "xlsx"):
            raise ValueError("Elige CSV o Excel.")
        cliente = db.obtener_cliente_fiscal(g.tenant_id, cliente_id) if cliente_id else None
        if cliente is None:
            raise ValueError("Cliente no encontrado.")
        desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
        filas = exportacion_generica.filas(g.tenant_id, g.usuario_id, cliente_id, desde, hasta)
        if not filas:
            raise ValueError("No hay facturas revisadas que descargar en ese periodo.")
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre, error=_(str(e))[:300]))
    nombre = f"facturas-{(trimestre or 'todas').replace(' ', '')}"
    if formato == "xlsx":
        contenido, mime = exportacion_generica.a_xlsx(filas), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        contenido, mime = exportacion_generica.a_csv(filas), "text/csv; charset=utf-8"
    r = Response(contenido, mimetype=mime)
    r.headers.set("Content-Disposition", "attachment", filename=f"{nombre}.{formato}")
    r.headers.set("X-Content-Type-Options", "nosniff")
    r.headers.set("Cache-Control", "no-store")
    return r


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
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre, error=_(str(e))[:300]))
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


@contabilidad_bp.route("/pagos", methods=["GET", "POST"])
@login_required
def pagos():
    """Asientos de cobro y pago de las facturas ya exportadas: elige las facturas y la fecha y baja el fichero para a3 (formato clásico de 256)."""
    cliente_id = request.values.get("cliente_id", type=int)
    error = None
    if request.method == "POST":
        try:
            ids = request.form.getlist("factura", type=int)
            marcadas = [{"factura_id": i, "fecha": request.form.get(f"fecha_{i}") or request.form.get("fecha") or None} for i in ids]
            r = fc.asientos_de_pago(g.tenant_id, g.usuario_id, cliente_id or 0, marcadas, repetir=bool(request.form.get("repetir")))
            return _descarga(r["contenido"])
        except ValueError as e:
            error = _(str(e))
    facturas = fc.facturas_para_asiento_de_pago(g.tenant_id, g.usuario_id, cliente_id) if cliente_id else []
    cfg = fc.configuracion(g.tenant_id, cliente_id) if cliente_id else None
    return render_template("contabilidad_pagos.html", clientes=_clientes(), cliente_id=cliente_id, facturas=facturas, cfg=cfg, hoy=date.today().isoformat(), error=error or _error(), subnav=None)


@contabilidad_bp.route("/panel-cierre")
@login_required
def panel_del_cierre():
    """Qué falta para cerrar un trimestre, cliente por cliente: por leer, por revisar, listas para exportar y sin confirmar en a3, con los días que quedan para el plazo."""
    hoy = date.today()
    actual = panel_cierre.trimestre_actual(hoy)
    trimestres = [actual]
    for _i in range(5):
        a, t = int(trimestres[-1][:4]), int(trimestres[-1][-1])
        trimestres.append(f"{a - (t == 1)}-T{t - 1 or 4}")
    trimestre = request.args.get("trimestre") or panel_cierre.trimestre_anterior(hoy)
    error = None
    try:
        p = panel_cierre.panel(g.tenant_id, g.usuario_id, trimestre, hoy)
    except ValueError as e:
        p, error = None, _(str(e))
    return render_template("contabilidad_panel_cierre.html", p=p, trimestres=trimestres, trimestre=trimestre, etiqueta=cierre_trimestre.etiqueta, error=error or _error(), subnav=None)


@contabilidad_bp.route("/cliente/<int:cliente_id>/terceros", methods=["GET", "POST"])
@login_required
def terceros(cliente_id: int):
    """Proveedores y clientes duplicados de un cliente: el mismo NIF con nombres distintos y el mismo nombre con NIF distintos."""
    mensaje = error = None
    cliente = next((x for x in _clientes() if x["id"] == cliente_id), None)
    if cliente is None:
        abort(404)
    if request.method == "POST":
        try:
            if request.form.get("accion") == "nombre":
                n = terceros_duplicados.unificar_nombre(g.tenant_id, g.usuario_id, cliente_id, request.form.get("tipo", ""), request.form.get("nif", ""), request.form.get("nombre", ""))
                mensaje = ngettext("Se ha unificado el nombre en %(n)s factura.", "Se ha unificado el nombre en %(n)s facturas.", n, n=n)
            else:
                n = terceros_duplicados.corregir_nif(g.tenant_id, g.usuario_id, cliente_id, request.form.get("tipo", ""), request.form.get("nif_mal", ""), request.form.get("nif_bien", ""))
                mensaje = ngettext("Se ha corregido el NIF en %(n)s factura.", "Se ha corregido el NIF en %(n)s facturas.", n, n=n)
        except ValueError as e:
            error = _(str(e))
    return render_template("contabilidad_terceros.html", cliente=cliente, d=terceros_duplicados.encontrar(g.tenant_id, g.usuario_id, cliente_id), mensaje=mensaje, error=error or _error(), subnav=None)


@contabilidad_bp.route("/retorno", methods=["GET", "POST"])
@login_required
def retorno():
    """Sube el listado de facturas que devuelve a3 y comprueba cuáles de las exportadas están de verdad contabilizadas. Si no se reconocen las columnas por su título, se pueden indicar a mano."""
    cliente_id = request.values.get("cliente_id", type=int)
    informe = error = vista = None
    columnas = {c: request.form.get(f"col_{c}", "").strip() for c in retorno_a3.SINONIMOS}
    fila_titulos = request.form.get("fila_titulos", default=1, type=int)
    if request.method == "POST":
        archivo = request.files.get("archivo")
        contenido = b""
        try:
            if not cliente_id or archivo is None or not archivo.filename:
                raise ValueError("Elige el cliente y el archivo que devuelve a3.")
            contenido = archivo.read(retorno_a3.MAX_BYTES + 1)
            mapa = retorno_a3.mapa_de_columnas(**columnas)
            filas = retorno_a3.leer_de_cliente(g.tenant_id, cliente_id, contenido, archivo.filename, mapa, fila_titulos)
            informe = retorno_a3.cruzar(g.tenant_id, g.usuario_id, cliente_id, filas, confirmar=request.form.get("confirmar") == "1")
            informe["cuadre_303"] = [x for x in (cuadre_303.cuadrar(g.tenant_id, g.usuario_id, cliente_id, c["trimestre"]) for c in informe["cuadre"]) if x["disponible"]]
        except ValueError as e:
            error = _(str(e))
            if contenido:
                try:
                    vista = retorno_a3.vista_previa(contenido, archivo.filename)
                except ValueError:
                    vista = None
    return render_template("contabilidad_retorno.html", clientes=_clientes(), cliente_id=cliente_id, informe=informe, error=error or _error(), vista=vista, columnas=columnas, fila_titulos=fila_titulos,
                           campos_columnas=retorno_a3.SINONIMOS, subnav=None)


@contabilidad_bp.route("/lotes")
@login_required
def lotes():
    return render_template("contabilidad_lotes.html", lotes=fc.listar_lotes(g.tenant_id, g.usuario_id), error=_error())


@contabilidad_bp.route("/lotes/<int:lote_id>/estado", methods=["POST"])
@login_required
def estado_del_lote(lote_id: int):
    """Anota si a3 importó el fichero o lo rechazó (y por qué)."""
    try:
        fc.fijar_estado_a3_del_lote(g.tenant_id, g.usuario_id, lote_id, request.form.get("estado", ""), request.form.get("motivo", ""))
    except ValueError as e:
        return redirect(url_for("contabilidad.lotes", error=_(str(e))[:300]))
    return redirect(url_for("contabilidad.lotes"))


@contabilidad_bp.route("/lotes/<int:lote_id>/descargar")
@login_required
def descargar_lote(lote_id: int):
    contenido = fc.contenido_del_lote(g.tenant_id, g.usuario_id, lote_id)
    if contenido is None:
        abort(404)
    return _descarga(contenido)


from . import rutas_api_contabilidad  # noqa: E402,F401 -- registra las rutas de la API REST de este módulo en api_bp
