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


def contabilidad_avisos_factura(factura_id: int) -> dict:
    """Lo que conviene mirar de una factura aunque no impida revisarla (NIF con el dígito de control mal, NIF igual al del titular, NIF-IVA sin formato, fecha futura o muy antigua, periodo cerrado, hueco en la numeración,
    total cero) y las facturas del mismo cliente que pueden ser la misma, con el motivo y si esa otra ya está revisada o exportada."""
    return _mt._conta().avisos_factura(*_mt._ctx_conta(), factura_id)


def contabilidad_comprobar_vies(nif: str) -> dict:
    """Comprueba en el VIES si un NIF-IVA de otro país de la UE (con su prefijo, por ejemplo FR12345678901) está dado de alta. `valido` es null si el servicio no contestó (no es un «no»)."""
    return _mt._conta().comprobar_vies(*_mt._ctx_conta(), nif)


def contabilidad_siguiente_pendiente(factura_id: int) -> dict:
    """La id de la siguiente factura pendiente de revisar del mismo cliente (o de otro si ya no quedan) tras la indicada; null si no hay más."""
    return _mt._conta().siguiente_pendiente(*_mt._ctx_conta(), factura_id)


def contabilidad_revisables_en_lote(cliente_fiscal_id: int | None = None, umbral: int | None = None) -> dict:
    """Las facturas pendientes que se pueden dar por buenas de golpe: de factura electrónica o leídas con IA con confianza igual o superior al `umbral` (90 por defecto), sin problemas ni avisos de control. No cambia nada."""
    return _mt._conta().revisables_en_lote(*_mt._ctx_conta(), cliente_fiscal_id, umbral)


def contabilidad_revisar_seguras(cliente_fiscal_id: int | None = None, umbral: int | None = None) -> dict:
    """Da por revisadas de golpe las facturas que devuelve `contabilidad_revisables_en_lote` (opcionalmente de un solo cliente). Devuelve cuántas se revisaron y cuántas se omitieron. No enseña reglas al sistema."""
    return _mt._conta().revisar_seguras(*_mt._ctx_conta(), cliente_fiscal_id, umbral)


def contabilidad_mapa_de_cuentas(cliente_fiscal_id: int) -> dict:
    """Qué subcuenta de a3 se usará con cada proveedor y cliente de un cliente de la gestoría y de dónde sale: recordada, del plan de a3 importado, nueva (se numera al exportar) o genérica (todo cae en una sola)."""
    return _mt._conta().mapa_de_cuentas(*_mt._ctx_conta(), cliente_fiscal_id)


def contabilidad_fijar_cuenta_tercero(cliente_fiscal_id: int, tipo_tercero: str, nif: str, cuenta: str) -> dict:
    """Fija a mano la subcuenta de a3 de un proveedor o cliente (por su NIF) para las próximas exportaciones. `tipo_tercero`: proveedor o cliente. Las facturas ya exportadas no cambian."""
    return _mt._conta().fijar_cuenta_tercero(*_mt._ctx_conta(), cliente_fiscal_id, tipo_tercero, nif, cuenta)


def contabilidad_calidad_lectura(desde: str | None = None, cliente_fiscal_id: int | None = None) -> dict:
    """Cómo acierta la lectura de facturas: por fuente (XML, texto, imagen), por tipo de documento y por campo, con las facturas dadas por buenas sin correcciones y el coste. `desde`: AAAA-MM-DD (por defecto, el día 1 del mes)."""
    return _mt._conta().calidad_lectura(*_mt._ctx_conta(), desde, cliente_fiscal_id)


def contabilidad_comprobar_retorno_a3(cliente_fiscal_id: int, contenido: str | None = None, contenido_base64: str | None = None, nombre: str = "") -> dict:
    """Cruza un listado que devuelve a3 (CSV en `contenido`, o CSV/Excel en `contenido_base64` con su `nombre`) con las facturas exportadas del cliente: cuáles coinciden, cuáles tienen importes distintos, cuáles faltan en a3
    y cuáles sobran, más el cuadre del IVA por trimestre. SOLO INFORMA: no guarda nada. Para confirmar las que coinciden usa `contabilidad_confirmar_retorno_a3`."""
    return _mt._conta().cruzar_retorno_a3(*_mt._ctx_conta(), cliente_fiscal_id, contenido, contenido_base64, nombre, confirmar=False)


def contabilidad_confirmar_retorno_a3(cliente_fiscal_id: int, contenido: str | None = None, contenido_base64: str | None = None, nombre: str = "") -> dict:
    """Igual que `contabilidad_comprobar_retorno_a3`, pero además anota como «confirmadas en a3» las facturas exportadas que coinciden exactamente con el listado."""
    return _mt._conta().cruzar_retorno_a3(*_mt._ctx_conta(), cliente_fiscal_id, contenido, contenido_base64, nombre, confirmar=True)


def contabilidad_panel_cierre(trimestre: str | None = None) -> dict:
    """Qué falta para cerrar un trimestre («2026-T3»; por defecto el que se está cerrando), cliente por cliente: facturas por leer, por revisar, listas para exportar y sin confirmar en a3, si está cerrado,
    y el plazo de presentación con los días que quedan. Los clientes que más les falta van primero."""
    return _mt._conta().panel_del_cierre(*_mt._ctx_conta(), trimestre)
