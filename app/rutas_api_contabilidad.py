"""API REST de «Facturas para contabilizar» (área de token `contabilidad`): consultar, anotar, revisar, leer con IA, comprobar y exportar el fichero SUENLACE.DAT para a3. Mismas reglas que la web
(app/consultas_contabilidad.py): despacho propio, módulo activo, solo los clientes que la persona ve y, quien solo audita, únicamente consulta."""
from __future__ import annotations

from flask import Response, g, request

from . import consultas_contabilidad as cc
from . import enlace_a3
from .auth import token_required
from .rutas_api import _body, _err, _exigir_tenant_api, _ok, api_bp


def _consulta(funcion, *args, **kw):
    """Ejecuta una consulta de `consultas_contabilidad` con el despacho y la persona del token; los `ValueError` salen como 404 (no existe, módulo inactivo) o 400."""
    error = _exigir_tenant_api()
    if error:
        return error
    try:
        return _ok(funcion(g.tenant_id, g.usuario_id, *args, **kw))
    except ValueError as e:
        texto = str(e)
        if texto.startswith("No existe") or "no está activo" in texto or "no encontrado" in texto.lower():
            return _err(texto, 404, "no_encontrado")
        return _err(texto, 400, "peticion_invalida")


@api_bp.route("/contabilidad/facturas", methods=["GET"])
@token_required
def listar_facturas_contables_api():
    """Facturas anotadas (las más recientes primero). Filtros: `cliente_fiscal_id`, `estado` (pendiente, revisada, exportada, descartada), `tipo` (emitida, recibida), `trimestre` (2026-T3) y `limite` (50, máximo 200)."""
    return _consulta(cc.listar_facturas, request.args.get("cliente_fiscal_id", type=int), request.args.get("estado") or None, request.args.get("tipo") or None,
                     request.args.get("trimestre") or None, request.args.get("limite", 50, type=int))


@api_bp.route("/contabilidad/facturas/<int:factura_id>", methods=["GET"])
@token_required
def ver_factura_contable_api(factura_id: int):
    """Una factura entera: datos, líneas de IVA (importes en euros), subcuenta del tercero, lo que impide revisarla y si su periodo está cerrado."""
    return _consulta(cc.ver_factura, factura_id)


@api_bp.route("/contabilidad/facturas", methods=["POST"])
@token_required
def anotar_factura_contable_api():
    """Anota una factura (queda pendiente de revisar). Cuerpo: `cliente_fiscal_id`, `tipo`, `fecha`, `numero`, `tercero_nombre`, `tercero_nif`, `lineas` (`[{base, pct_iva, ...}]`) y, opcionales, `concepto`,
    `abono`, `rectifica_numero`, `rectifica_fecha`, `tercero_cuenta`, `notas`. Lo que se deje en blanco lo rellenan el régimen del cliente y la regla del proveedor."""
    d = _body()
    datos = {"cliente_fiscal_id": d.get("cliente_fiscal_id"), "tipo": d.get("tipo"), "fecha": d.get("fecha"), "fecha_operacion": d.get("fecha_operacion"), "numero": d.get("numero"),
             "tercero_nombre": d.get("tercero_nombre"), "tercero_nif": d.get("tercero_nif"), "tercero_cuenta": d.get("tercero_cuenta"), "concepto": d.get("concepto"), "referencia": d.get("referencia"),
             "abono": d.get("abono"), "rectifica_numero": d.get("rectifica_numero"), "rectifica_fecha": d.get("rectifica_fecha"), "suplidos": d.get("suplidos"), "notas": d.get("notas"),
             "criterio_caja": d.get("criterio_caja"), "lineas": d.get("lineas")}
    resultado = _consulta(cc.anotar_factura, {k: v for k, v in datos.items() if v is not None})
    if isinstance(resultado, tuple) and resultado[1] == 200:       # creada: 201
        return resultado[0], 201
    return resultado


@api_bp.route("/contabilidad/facturas/<int:factura_id>/estado", methods=["POST"])
@token_required
def estado_factura_contable_api(factura_id: int):
    """Cambia el estado: `revisada` (solo si no tiene problemas), `pendiente` (reabrir) o `descartada`. Cuerpo: `estado`."""
    d = _body()
    return _consulta(cc.cambiar_estado, factura_id, str(d.get("estado") or ""))


@api_bp.route("/contabilidad/facturas/<int:factura_id>/leer", methods=["POST"])
@token_required
def leer_factura_contable_api(factura_id: int):
    """Lee con IA el archivo de la factura y rellena sus datos (queda pendiente de revisar). Usa el modelo y la clave de OpenRouter de la persona del token, que debe tener visión."""
    return _consulta(cc.leer_con_ia, factura_id)


@api_bp.route("/contabilidad/resumen", methods=["GET"])
@token_required
def resumen_contabilidad_api():
    """Qué espera, cliente por cliente: por revisar, por leer con IA y revisadas listas para exportar."""
    return _consulta(cc.resumen)


@api_bp.route("/contabilidad/clientes/<int:cliente_fiscal_id>/comprobar", methods=["GET"])
@token_required
def comprobar_exportacion_api(cliente_fiscal_id: int):
    """Pre-chequeo de lo que saldría ahora en el SUENLACE.DAT del cliente (`trimestre` opcional): errores y avisos con número de registro, periodos cerrados y subcuentas nuevas. No guarda nada."""
    return _consulta(cc.comprobar_exportacion, cliente_fiscal_id, request.args.get("trimestre") or None)


@api_bp.route("/contabilidad/clientes/<int:cliente_fiscal_id>/exportar", methods=["POST"])
@token_required
def exportar_contabilidad_api(cliente_fiscal_id: int):
    """Genera el SUENLACE.DAT con las facturas revisadas del cliente (`trimestre` opcional), las marca como exportadas y guarda el fichero como lote; se baja con `/contabilidad/lotes/<id>/fichero`.
    Pasa por el pre-chequeo y no exporta periodos cerrados (eso se confirma en la web)."""
    d = _body()
    return _consulta(cc.exportar, cliente_fiscal_id, str(d.get("trimestre") or "") or None)


@api_bp.route("/contabilidad/lotes/<int:lote_id>/fichero", methods=["GET"])
@token_required
def fichero_del_lote_api(lote_id: int):
    """El SUENLACE.DAT de un lote ya generado, como descarga (registros de 512 bytes)."""
    error = _exigir_tenant_api()
    if error:
        return error
    try:
        contenido = cc.fichero_del_lote(g.tenant_id, g.usuario_id, lote_id)
    except ValueError as e:
        return _err(str(e), 404, "no_encontrado")
    r = Response(contenido, mimetype="application/octet-stream")
    r.headers.set("Content-Disposition", "attachment", filename=enlace_a3.NOMBRE_FICHERO)
    r.headers.set("Cache-Control", "no-store")
    r.headers.set("X-Content-Type-Options", "nosniff")
    return r
