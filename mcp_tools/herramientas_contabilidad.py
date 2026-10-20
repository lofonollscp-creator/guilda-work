"""Herramientas MCP (y del asistente de IA) de «Facturas para contabilizar»: consultar las facturas anotadas, anotar una, revisarla, leerla con IA, comprobar lo que saldría y generar el SUENLACE.DAT para a3.
La lógica está en app/consultas_contabilidad.py, que comparte con la API REST: solo el despacho propio, solo si el módulo está activo, solo los clientes que la persona puede ver y, quien solo audita,
únicamente puede consultar. Los importes van en euros."""
from __future__ import annotations

import mcp_tools as _mt


def _ctx_conta() -> tuple[int, int]:
    return _mt._tenant_id_actual(), _mt._uid()


def _conta():
    from app import consultas_contabilidad
    return consultas_contabilidad


def contabilidad_listar_facturas(cliente_fiscal_id: int | None = None, estado: str | None = None, tipo: str | None = None, trimestre: str | None = None, limite: int = 50) -> list[dict]:
    """Las facturas anotadas para contabilizar, las más recientes primero. `estado`: pendiente, revisada, exportada o descartada. `tipo`: emitida o recibida. `trimestre`: «2026-T3»."""
    return _mt._conta().listar_facturas(*_mt._ctx_conta(), cliente_fiscal_id, estado, tipo, trimestre, limite)


def contabilidad_ver_factura(factura_id: int) -> dict:
    """Una factura entera: datos, líneas de IVA, subcuenta del tercero, lo que impide darla por revisada y si su periodo está cerrado."""
    return _mt._conta().ver_factura(*_mt._ctx_conta(), factura_id)


def contabilidad_resumen() -> dict:
    """Qué espera en Facturas para contabilizar, cliente por cliente: por revisar, por leer con IA (solo el archivo) y revisadas listas para exportar."""
    return _mt._conta().resumen(*_mt._ctx_conta())


def contabilidad_comprobar_exportacion(cliente_fiscal_id: int, trimestre: str | None = None) -> dict:
    """Pre-chequeo de lo que saldría ahora en el SUENLACE.DAT de un cliente (y trimestre): errores y avisos con el número de registro, periodos cerrados y subcuentas nuevas. No marca ni guarda nada."""
    return _mt._conta().comprobar_exportacion(*_mt._ctx_conta(), cliente_fiscal_id, trimestre)


def contabilidad_anotar_factura(cliente_fiscal_id: int, tipo: str, fecha: str, numero: str, tercero_nombre: str, lineas: list[dict], tercero_nif: str | None = None, concepto: str | None = None,
                                abono: bool = False, rectifica_numero: str | None = None, rectifica_fecha: str | None = None, tercero_cuenta: str | None = None, notas: str | None = None) -> dict:
    """Anota una factura de un cliente de la gestoría (queda pendiente de revisar). `tipo`: emitida o recibida; `fecha` AAAA-MM-DD. `lineas`: una por tipo de IVA, cada una con `base` (importe sin IVA,
    «1.234,56») y `pct_iva` (21); opcionales `cuota_iva`, `pct_recargo`, `pct_retencion`, `cuenta` y `subtipo` (tipo de operación). Lo que dejes en blanco lo rellenan el régimen del cliente y la regla del
    proveedor. Un abono necesita `rectifica_numero` y `rectifica_fecha`."""
    datos = {"cliente_fiscal_id": cliente_fiscal_id, "tipo": tipo, "fecha": fecha, "numero": numero, "tercero_nombre": tercero_nombre, "tercero_nif": tercero_nif, "concepto": concepto,
             "abono": "1" if abono else "", "rectifica_numero": rectifica_numero, "rectifica_fecha": rectifica_fecha, "tercero_cuenta": tercero_cuenta, "notas": notas, "lineas": lineas}
    return _mt._conta().anotar_factura(*_mt._ctx_conta(), datos)


def contabilidad_cambiar_estado_factura(factura_id: int, estado: str) -> dict:
    """Da una factura por revisada (`revisada`, solo si no tiene problemas), la reabre (`pendiente`) o la saca del circuito (`descartada`)."""
    return _mt._conta().cambiar_estado(*_mt._ctx_conta(), factura_id, estado)


def contabilidad_leer_factura_con_ia(factura_id: int) -> dict:
    """Lee con IA la foto o el PDF adjunto de una factura y rellena sus datos; queda pendiente de revisar y con los avisos de la lectura. Gasta una consulta de tu modelo de OpenRouter, que debe tener visión."""
    return _mt._conta().leer_con_ia(*_mt._ctx_conta(), factura_id)


def contabilidad_exportar(cliente_fiscal_id: int, trimestre: str | None = None) -> dict:
    """Genera el SUENLACE.DAT para a3 con las facturas revisadas del cliente (y trimestre) y las marca como exportadas. Lo pasa antes por el pre-chequeo y no exporta periodos cerrados (eso se confirma en la
    web). Devuelve el número de lote; el fichero se descarga en Contabilización › Ficheros generados o por la API."""
    return _mt._conta().exportar(*_mt._ctx_conta(), cliente_fiscal_id, trimestre)
