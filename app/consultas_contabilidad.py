"""Consultas y acciones de «Facturas para contabilizar» que comparten la API REST (app/rutas_api_contabilidad.py) y las herramientas MCP y del asistente de IA (mcp_tools/herramientas_contabilidad.py).
Mismas reglas que la web: el despacho propio, el módulo `contabilizacion` activo, solo los clientes que la persona puede ver, y quien solo audita puede mirar pero no cambiar. Los importes salen en euros
con dos decimales además de en céntimos. Los `ValueError` llevan un mensaje legible y los de «no existe» o «no está activo» se tratan como 404."""
from __future__ import annotations

from . import acceso, cobro_contabilidad, facturas_contables as fc, lectura_facturas, verticales


def _exigir_modulo(tenant_id: int) -> None:
    if not verticales.esta_activo(tenant_id, "contabilizacion"):
        raise ValueError("El módulo Contabilización de facturas no está activo en este despacho.")


def _exigir_escritura(tenant_id: int, usuario_id: int) -> None:
    _exigir_modulo(tenant_id)
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ValueError("Tu perfil solo permite consultar: no puedes cambiar facturas.")


def _euros(centimos: int | None) -> float | None:
    return None if centimos is None else round(centimos / 100, 2)


def _resumen(f: dict) -> dict:
    return {"id": f["id"], "cliente_fiscal_id": f["cliente_fiscal_id"], "cliente": f.get("cliente_nombre"), "tipo": f["tipo"], "abono": bool(f["abono"]), "fecha": f["fecha"], "trimestre": fc.trimestre_de(f["fecha"]),
            "numero": f["numero"], "tercero": f["tercero_nombre"], "nif": f["tercero_nif"], "total": _euros(f["total_centimos"]), "estado": f["estado"], "origen": f["origen"], "lectura": f.get("lectura"),
            "tiene_archivo": bool(f.get("documento_id"))}


def listar_facturas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None, estado: str | None = None, tipo: str | None = None, trimestre: str | None = None, limite: int = 50) -> list[dict]:
    """Las facturas anotadas (las más recientes primero), con su estado y su procedencia."""
    _exigir_modulo(tenant_id)
    if estado and estado not in fc.ESTADOS:
        raise ValueError("`estado` debe ser pendiente, revisada, exportada o descartada.")
    if tipo and tipo not in fc.TIPOS:
        raise ValueError("`tipo` debe ser emitida o recibida.")
    desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
    filas = fc.listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, estado=estado or None, tipo=tipo or None, desde=desde, hasta=hasta, limite=max(1, min(int(limite or 50), 200)))
    return [_resumen(f) for f in filas]


def ver_factura(tenant_id: int, usuario_id: int, factura_id: int) -> dict:
    """Una factura entera: datos, líneas de IVA, lo que impide darla por revisada y si su periodo está cerrado."""
    _exigir_modulo(tenant_id)
    f = fc.obtener(tenant_id, usuario_id, int(factura_id))
    if f is None:
        raise ValueError("No existe esa factura.")
    cerrado = fc.periodos_cerrados(tenant_id, f["cliente_fiscal_id"], [f["trimestre"]]).get(f["trimestre"])
    return {**_resumen(f), "fecha_operacion": f["fecha_operacion"], "concepto": f["concepto"], "referencia": f["referencia"], "subcuenta_tercero": fc.cuenta_efectiva(tenant_id, f),
            "rectifica_numero": f["rectifica_numero"], "rectifica_fecha": f["rectifica_fecha"], "criterio_caja": bool(f.get("criterio_caja")), "suplidos": _euros(f["suplidos_centimos"]), "notas": f["notas"],
            "lectura_error": f.get("lectura_error"), "problemas": f["problemas"], "periodo_cerrado": cerrado["detalle"] if cerrado else None,
            "lineas": [{"base": _euros(l["base_centimos"]), "pct_iva": l["pct_iva"] / 100, "cuota_iva": _euros(l["cuota_iva"]), "pct_recargo": l["pct_recargo"] / 100, "cuota_recargo": _euros(l["cuota_recargo"]),
                        "pct_retencion": l["pct_retencion"] / 100, "cuota_retencion": _euros(l["cuota_retencion"]), "cuenta": l["cuenta"], "tipo_operacion": l["subtipo"]} for l in f["lineas"]]}


def resumen(tenant_id: int, usuario_id: int) -> dict:
    """Lo que espera en el módulo, cliente por cliente: facturas por revisar, por leer con IA y revisadas listas para exportar."""
    _exigir_modulo(tenant_id)
    clientes = sorted(fc.pendientes_por_cliente(tenant_id, usuario_id), key=lambda c: (-(c["pendientes"] or 0), c["nombre"].lower()))
    uso = cobro_contabilidad.consumo(tenant_id)
    plan = None if uso["tarifa"] is None else {"mes": uso["mes"], "unidad": uso["unidad"], "usadas": uso["unidades"], "incluidas": uso["incluidas"], "de_mas": uso["extra"],
                                               "precio_por_factura_de_mas": _euros(uso["precio_extra_centimos"]), "limite": uso["limite_duro"], "restantes": uso["restantes"]}
    return {"plan": plan, "por_revisar": sum(c["pendientes"] or 0 for c in clientes), "por_leer": sum(c["por_leer"] or 0 for c in clientes), "para_exportar": sum(c["revisadas"] or 0 for c in clientes),
            "clientes": [{"cliente_fiscal_id": c["cliente_fiscal_id"], "cliente": c["nombre"], "por_revisar": c["pendientes"] or 0, "por_leer": c["por_leer"] or 0, "para_exportar": c["revisadas"] or 0,
                          "del_portal": c["del_portal"] or 0, "mas_antigua": (c["antigua"] or "")[:10] or None} for c in clientes]}


def comprobar_exportacion(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str | None = None) -> dict:
    """El pre-chequeo de lo que saldría ahora para un cliente (y trimestre): errores y avisos con el número de registro, periodos cerrados y subcuentas nuevas. No marca ni guarda nada."""
    _exigir_modulo(tenant_id)
    desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
    i = fc.comprobar_exportacion(tenant_id, usuario_id, int(cliente_fiscal_id), desde=desde, hasta=hasta)
    return {"cliente": i["cliente"], "ok": i["ok"], "facturas": i["facturas"], "registros": i["registros"], "total": i["totales"]["total"], "errores": i["errores"], "avisos": i["avisos"],
            "periodos_cerrados": i["periodos_cerrados"], "subcuentas_nuevas": i["subcuentas_nuevas"]}


def anotar_factura(tenant_id: int, usuario_id: int, datos: dict) -> dict:
    """Anota una factura (queda pendiente de revisar). `datos`: cliente_fiscal_id, tipo, fecha, numero, tercero_nombre, tercero_nif y lineas [{base, pct_iva, ...}] más los opcionales de la web."""
    _exigir_escritura(tenant_id, usuario_id)
    datos = dict(datos)
    cliente_id = int(datos.pop("cliente_fiscal_id", 0) or 0)
    lineas = datos.pop("lineas", None)
    if not isinstance(lineas, list) or not lineas:
        raise ValueError("Indica al menos una línea con la base imponible (`lineas`).")
    fid = fc.crear(tenant_id, usuario_id, cliente_id, datos, [l for l in lineas if isinstance(l, dict)])
    return ver_factura(tenant_id, usuario_id, fid)


def cambiar_estado(tenant_id: int, usuario_id: int, factura_id: int, estado: str) -> dict:
    """Pasa una factura a revisada, la reabre (pendiente) o la descarta."""
    _exigir_escritura(tenant_id, usuario_id)
    if ver_factura(tenant_id, usuario_id, factura_id) is None:
        raise ValueError("No existe esa factura.")
    fc.cambiar_estado(tenant_id, usuario_id, int(factura_id), estado)
    return ver_factura(tenant_id, usuario_id, factura_id)


def leer_con_ia(tenant_id: int, usuario_id: int, factura_id: int) -> dict:
    """Lee con IA el archivo de la factura y rellena sus datos (queda pendiente: hay que revisarla). Usa el modelo y la clave de OpenRouter de quien lo pide."""
    _exigir_escritura(tenant_id, usuario_id)
    avisos = lectura_facturas.leer(tenant_id, usuario_id, int(factura_id))
    return {**ver_factura(tenant_id, usuario_id, factura_id), "avisos_de_la_lectura": avisos}


def exportar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str | None = None) -> dict:
    """Genera el SUENLACE.DAT con las facturas revisadas del cliente (y trimestre), las marca como exportadas y guarda el fichero como lote. Pasa antes por el pre-chequeo y no exporta periodos cerrados:
    eso hay que confirmarlo en la web."""
    _exigir_escritura(tenant_id, usuario_id)
    desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
    r = fc.exportar(tenant_id, usuario_id, int(cliente_fiscal_id), desde=desde, hasta=hasta)
    return {"lote": r["lote"], "cliente": r["cliente"], "facturas": r["n_facturas"], "registros": r["n_registros"], "avisos": [a["mensaje"] for a in r["avisos"]]}


def fichero_del_lote(tenant_id: int, usuario_id: int, lote_id: int) -> bytes:
    _exigir_modulo(tenant_id)
    contenido = fc.contenido_del_lote(tenant_id, usuario_id, int(lote_id))
    if contenido is None:
        raise ValueError("No existe ese fichero.")
    return contenido
