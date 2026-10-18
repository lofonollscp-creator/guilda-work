"""Facturas para contabilizar y fichero de enlace de a3 (ver app/facturas_contables.py y app/enlace_a3.py)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _

from . import acceso, db, enlace_a3, verticales
from . import facturas_contables as fc
from .auth import login_required

contabilidad_bp = Blueprint("contabilidad", __name__, url_prefix="/contabilidad")


@contabilidad_bp.before_request
def _solo_con_gestoria():
    """Es del módulo Gestoría: sin él no existe (404); y quien solo audita puede mirar, no cambiar."""
    if g.get("tenant_id") is None or not verticales.esta_activo(g.tenant_id, "gestoria"):
        abort(404)
    if request.method not in ("GET", "HEAD", "OPTIONS") and g.get("usuario_id") is not None and acceso.es_solo_auditor(g.tenant_id, g.usuario_id):
        abort(403)


def _error() -> str | None:
    return (request.args.get("error") or "")[:300] or None


def _clientes() -> list:
    visibles = acceso.clientes_visibles(g.tenant_id, g.usuario_id)
    return [c for c in db.listar_clientes_fiscales(g.tenant_id) if visibles is None or c["id"] in visibles]


def _lineas_del_formulario() -> list[dict]:
    return [{c: request.form.get(f"{c}_{i}", "") for c in ("base", "pct_iva", "cuota_iva", "pct_recargo", "pct_retencion", "cuenta", "subtipo")} for i in range(fc.MAX_LINEAS)]


def _datos_del_formulario() -> dict:
    return {c: request.form.get(c, "") for c in ("tipo", "fecha", "fecha_operacion", "numero", "tercero_nombre", "tercero_nif", "tercero_cuenta", "concepto", "referencia", "suplidos", "notas", "abono", "rectifica_fecha", "rectifica_numero")}


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
    return render_template("contabilidad_lista.html", facturas=facturas, clientes=_clientes(), cliente_id=cliente_id, estado=estado or "", tipo=tipo or "", trimestre=trimestre or "",
                           trimestres=_trimestres(), resumen=fc.resumen_por_estado(g.tenant_id, g.usuario_id, cliente_id), cfg=cfg, error=_error(), subnav=None)


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
    datos.update(rectifica_fecha=f["rectifica_fecha"] or "", rectifica_numero=f["rectifica_numero"] or "")
    datos.update(tercero_cuenta=f["tercero_cuenta"] or "", abono="1" if f["abono"] else "", suplidos=f"{f['suplidos_centimos'] / 100:.2f}".replace(".", ",") if f["suplidos_centimos"] else "")
    return render_template("contabilidad_factura.html", f=f, datos=datos, lineas=lineas, cliente_id=f["cliente_fiscal_id"], clientes=_clientes(), error=_error(), cfg=cfg,
                           cuenta_efectiva=fc.cuenta_efectiva(g.tenant_id, f, cfg))


@contabilidad_bp.route("/<int:factura_id>/estado", methods=["POST"])
@login_required
def estado(factura_id: int):
    try:
        fc.cambiar_estado(g.tenant_id, g.usuario_id, factura_id, request.form.get("estado", ""))
    except ValueError as e:
        return redirect(url_for("contabilidad.ver", factura_id=factura_id, error=str(e)[:300]))
    return redirect(request.form.get("volver") or url_for("contabilidad.ver", factura_id=factura_id))


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
    return render_template("contabilidad_config.html", cliente=cliente, cfg=cfg, error=error)


@contabilidad_bp.route("/exportar", methods=["POST"])
@login_required
def exportar():
    cliente_id = request.form.get("cliente_id", type=int)
    trimestre = request.form.get("trimestre") or None
    try:
        desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
        r = fc.exportar(g.tenant_id, g.usuario_id, cliente_id, desde=desde, hasta=hasta)
    except ValueError as e:
        return redirect(url_for("contabilidad.lista", cliente_id=cliente_id, trimestre=trimestre, error=str(e)[:300]))
    return _descarga(r["contenido"])


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
