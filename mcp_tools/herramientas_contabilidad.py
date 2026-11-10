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


def contabilidad_listar_facturas(cliente_fiscal_id: int | None = None, estado: str | None = None, tipo: str | None = None, trimestre: str | None = None, limite: int = 50, desde_indice: int = 0) -> list[dict]:
    """Las facturas anotadas para contabilizar, las más recientes primero. `estado`: pendiente, revisada, exportada o descartada. `tipo`: emitida o recibida. `trimestre`: «2026-T3». Hasta 200 por llamada:
    para las siguientes, `desde_indice` (cuántas saltarse)."""
    return _mt._conta().listar_facturas(*_mt._ctx_conta(), cliente_fiscal_id, estado, tipo, trimestre, limite, desde_indice)


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
                                abono: bool = False, rectifica_numero: str | None = None, rectifica_fecha: str | None = None, tercero_cuenta: str | None = None, notas: str | None = None,
                                datos_a3: dict | None = None) -> dict:
    """Anota una factura de un cliente de la gestoría (queda pendiente de revisar). `tipo`: emitida o recibida; `fecha` AAAA-MM-DD. `lineas`: una por tipo de IVA, cada una con `base` (importe sin IVA,
    «1.234,56») y `pct_iva` (21); opcionales `cuota_iva`, `pct_recargo`, `pct_retencion`, `cuenta` y `subtipo` (tipo de operación). Lo que dejes en blanco lo rellenan el régimen del cliente y la regla del
    proveedor. Un abono necesita `rectifica_numero` y `rectifica_fecha`. En una línea, `impreso` fija el impreso de a3 (si no, el que toca). `datos_a3`, solo en casos especiales: `bien_inversion`, `dua` (importaciones),
    `clave_340` (1 ticket, 3 agencias de viajes), `nif_representante`, `autofactura`, `metalico` y `inmuebles` («total» o un importe del 347)."""
    datos = {"cliente_fiscal_id": cliente_fiscal_id, "tipo": tipo, "fecha": fecha, "numero": numero, "tercero_nombre": tercero_nombre, "tercero_nif": tercero_nif, "concepto": concepto,
             "abono": "1" if abono else "", "rectifica_numero": rectifica_numero, "rectifica_fecha": rectifica_fecha, "tercero_cuenta": tercero_cuenta, "notas": notas, "lineas": lineas, "datos_a3": datos_a3}
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


def contabilidad_revisar_seguras(cliente_fiscal_id: int | None = None, umbral: int | None = None, simular: bool = False) -> dict:
    """Da por revisadas de golpe las facturas que devuelve `contabilidad_revisables_en_lote` (opcionalmente de un solo cliente). Devuelve cuántas se revisaron y cuántas se omitieron. No enseña reglas al sistema.
    Con `simular` no cambia nada: dice cuáles se revisarían."""
    return _mt._conta().revisar_seguras(*_mt._ctx_conta(), cliente_fiscal_id, umbral, simular)


def contabilidad_mapa_de_cuentas(cliente_fiscal_id: int) -> dict:
    """Qué subcuenta de a3 se usará con cada proveedor y cliente de un cliente de la gestoría y de dónde sale: recordada, del plan de a3 importado, nueva (se numera al exportar) o genérica (todo cae en una sola)."""
    return _mt._conta().mapa_de_cuentas(*_mt._ctx_conta(), cliente_fiscal_id)


def contabilidad_fijar_cuenta_tercero(cliente_fiscal_id: int, tipo_tercero: str, nif: str, cuenta: str) -> dict:
    """Fija a mano la subcuenta de a3 de un proveedor o cliente (por su NIF) para las próximas exportaciones. `tipo_tercero`: proveedor o cliente. Las facturas ya exportadas no cambian."""
    return _mt._conta().fijar_cuenta_tercero(*_mt._ctx_conta(), cliente_fiscal_id, tipo_tercero, nif, cuenta)


def contabilidad_calidad_lectura(desde: str | None = None, cliente_fiscal_id: int | None = None) -> dict:
    """Cómo acierta la lectura de facturas: por fuente (XML, texto, imagen), por tipo de documento y por campo, con las facturas dadas por buenas sin correcciones y el coste. `desde`: AAAA-MM-DD (por defecto, el día 1 del mes)."""
    return _mt._conta().calidad_lectura(*_mt._ctx_conta(), desde, cliente_fiscal_id)


def contabilidad_comprobar_retorno_a3(cliente_fiscal_id: int, contenido: str | None = None, contenido_base64: str | None = None, nombre: str = "", columnas: dict | None = None, fila_de_titulos: int = 1) -> dict:
    """Cruza un listado que devuelve a3 (CSV en `contenido`, o CSV/Excel en `contenido_base64` con su `nombre`) con las facturas exportadas del cliente: cuáles coinciden, cuáles tienen importes distintos, cuáles faltan en a3
    y cuáles sobran, las que parecen la misma con otro número y el cuadre del IVA por trimestre. Si no se reconocen las columnas por su título, indícalas con `columnas` (letras, por ejemplo {"numero": "C", "fecha": "B", "total": "D"}) y `fila_de_titulos` (0 si no hay). SOLO INFORMA: no guarda nada. Para confirmar las que coinciden usa `contabilidad_confirmar_retorno_a3`."""
    return _mt._conta().cruzar_retorno_a3(*_mt._ctx_conta(), cliente_fiscal_id, contenido, contenido_base64, nombre, confirmar=False, columnas=columnas, fila_de_titulos=fila_de_titulos)


def contabilidad_confirmar_retorno_a3(cliente_fiscal_id: int, contenido: str | None = None, contenido_base64: str | None = None, nombre: str = "", columnas: dict | None = None, fila_de_titulos: int = 1) -> dict:
    """Igual que `contabilidad_comprobar_retorno_a3`, pero además anota como «confirmadas en a3» las facturas exportadas que coinciden exactamente con el listado."""
    return _mt._conta().cruzar_retorno_a3(*_mt._ctx_conta(), cliente_fiscal_id, contenido, contenido_base64, nombre, confirmar=True, columnas=columnas, fila_de_titulos=fila_de_titulos)


def contabilidad_panel_cierre(trimestre: str | None = None) -> dict:
    """Qué falta para cerrar un trimestre («2026-T3»; por defecto el que se está cerrando), cliente por cliente: facturas por leer, por revisar, listas para exportar y sin confirmar en a3, si está cerrado,
    y el plazo de presentación con los días que quedan. Los clientes que más les falta van primero."""
    return _mt._conta().panel_del_cierre(*_mt._ctx_conta(), trimestre)


def contabilidad_mensajes_factura(factura_id: int) -> dict:
    """La conversación con el cliente sobre una factura: lo que le escribió el despacho y lo que ha contestado él desde su portal, de la más antigua a la más reciente."""
    return _mt._conta().mensajes_de_la_factura(*_mt._ctx_conta(), factura_id)


def contabilidad_preguntar_al_cliente(factura_id: int, texto: str) -> dict:
    """Escribe al cliente un mensaje sobre una factura suya (hasta 1000 caracteres): lo verá en su portal. Es un mensaje a una persona de fuera del despacho: redáctalo claro y amable y di qué factura es (número y
    proveedor). Antes mira `contabilidad_avisos_factura` y `contabilidad_mensajes_factura` para preguntar solo lo que falta."""
    return _mt._conta().preguntar_al_cliente(*_mt._ctx_conta(), factura_id, texto)


def contabilidad_cierre_cliente(cliente_fiscal_id: int, trimestre: str | None = None) -> dict:
    """El estado de cierre de un trimestre («2026-T3»; por defecto el que se está cerrando) de un cliente: cada punto de la lista de cierre (por leer, por revisar, mensajes sin leer del cliente, duplicadas, sin
    exportar, justificantes del banco…) con su estado (ok, pendiente o aviso) y cuántas facturas afecta, el plazo de presentación y las exportadas aún sin confirmar en a3. Úsala para redactar un resumen del cierre."""
    return _mt._conta().cierre_del_cliente(*_mt._ctx_conta(), cliente_fiscal_id, trimestre)


def contabilidad_cuadre_303(cliente_fiscal_id: int, trimestre: str | None = None) -> dict:
    """Cuadra el IVA de las facturas (revisadas o exportadas, solo operaciones interiores) con las casillas 27 (cuota devengada) y 45 (total a deducir) del modelo 303 simulado en Guilda Fiscal, de un cliente y un
    trimestre («2026-T3»; por defecto el que se está cerrando). Una diferencia suele ser una factura que no llegó a Guilda Fiscal. Si no hay 303 calculable, `disponible` es false y `motivo` dice por qué."""
    return _mt._conta().cuadre_con_303(*_mt._ctx_conta(), cliente_fiscal_id, trimestre)


def contabilidad_mover_factura(factura_id: int, cliente_destino_id: int) -> dict:
    """Pasa una factura PENDIENTE a otro cliente del despacho, con su archivo (se subió o se leyó en el cliente equivocado). Quita las cuentas escritas a mano, que eran las del plan del otro cliente."""
    return _mt._conta().mover_factura(*_mt._ctx_conta(), factura_id, cliente_destino_id)


def contabilidad_historial_factura(factura_id: int) -> dict:
    """Lo que ha pasado con una factura: anotada, leída, editada (con lo que cambió), revisada, exportada con su fichero, confirmada en a3, movida o descartada, quién y cuándo."""
    return _mt._conta().historial_factura(*_mt._ctx_conta(), factura_id)


def contabilidad_listar_ficheros(cliente_fiscal_id: int | None = None, limite: int = 50, desde_indice: int = 0) -> list[dict]:
    """Los ficheros SUENLACE.DAT generados, los más recientes primero: facturas, registros, cuántas confirmó a3 y el estado anotado (importado o rechazado, con su motivo)."""
    return _mt._conta().listar_ficheros(*_mt._ctx_conta(), cliente_fiscal_id, limite, desde_indice)


def contabilidad_fijar_estado_fichero(lote_id: int, estado: str = "", motivo: str = "") -> dict:
    """Anota lo que pasó al importar un fichero en a3: `importado`, `rechazado` (con el `motivo` que dio a3) o vacío para quitarlo. Es una nota: no cambia las facturas."""
    return _mt._conta().fijar_estado_fichero(*_mt._ctx_conta(), lote_id, estado, motivo)


def contabilidad_listar_reglas(cliente_fiscal_id: int) -> list[dict]:
    """Las reglas de proveedor y de cliente de un cliente de la gestoría: cuenta, IVA, retención, tipo de operación y concepto que se rellenan solos en sus facturas."""
    return _mt._conta().listar_reglas(*_mt._ctx_conta(), cliente_fiscal_id)


def contabilidad_guardar_regla(cliente_fiscal_id: int, tipo: str, nif: str, nombre: str | None = None, cuenta: str | None = None, pct_iva: float | None = None, pct_retencion: float | None = None,
                               tipo_operacion: str | None = None, criterio_caja: bool = False, concepto: str | None = None, iva_deducible: float | None = None) -> dict:
    """Crea o cambia la regla de un proveedor (`tipo` proveedor) o de un cliente (`tipo` cliente) por su NIF: la cuenta de gasto o ingreso, el IVA y la retención en tanto por ciento, el tipo de operación y el concepto
    que se rellenan solos en las facturas que se anoten o lean después. `iva_deducible` (solo proveedores, en %; por ejemplo 50 en un vehículo) parte cada línea en la parte deducible y la que no. Una regla escrita
    a mano nunca se pisa al aprender."""
    return _mt._conta().guardar_regla(*_mt._ctx_conta(), cliente_fiscal_id, tipo, nif, nombre, cuenta, pct_iva, pct_retencion, tipo_operacion, criterio_caja, concepto, iva_deducible)


def contabilidad_configuracion_a3(cliente_fiscal_id: int) -> dict:
    """La configuración de a3 de un cliente: código de empresa, dígitos de las subcuentas, formato del fichero (512 con SII o 256 clásico), cuentas por defecto, régimen de IVA y subcuentas automáticas."""
    return _mt._conta().configuracion_a3(*_mt._ctx_conta(), cliente_fiscal_id)


def contabilidad_subir_factura(cliente_fiscal_id: int, tipo: str, nombre_archivo: str, contenido_base64: str, tipo_mime: str | None = None) -> dict:
    """Sube la foto (JPG, PNG) o el PDF de una factura de un cliente de la gestoría (hasta 8 MB, en base64): queda pendiente de leer, y se lee con `contabilidad_leer_factura_con_ia`. `tipo`: emitida o recibida."""
    return _mt._conta().subir_factura(*_mt._ctx_conta(), cliente_fiscal_id, tipo, nombre_archivo, contenido_base64, tipo_mime)


def contabilidad_facturas_periodicas_que_faltan(cliente_fiscal_id: int) -> dict:
    """Proveedores de los que un cliente recibe factura casi todos los meses (la luz, el alquiler, un seguro) y de los que este mes aún no hay: suele ser algo que el cliente no ha mandado. Vacío antes del día 10."""
    return _mt._conta().facturas_periodicas_que_faltan(*_mt._ctx_conta(), cliente_fiscal_id)


def contabilidad_factura_desde_adjunto(adjunto_id: int, cliente_fiscal_id: int, tipo: str) -> dict:
    """Convierte en factura de un cliente de la gestoría la foto (JPG, PNG) o el PDF que la persona subió al chat (clip del asistente): queda pendiente de leer, y se lee con `contabilidad_leer_factura_con_ia`.
    `tipo`: emitida o recibida. Pregunta de qué cliente es si no te lo han dicho."""
    return _mt._conta().factura_desde_adjunto(*_mt._ctx_conta(), adjunto_id, cliente_fiscal_id, tipo)


def contabilidad_terceros_duplicados(cliente_fiscal_id: int) -> dict:
    """Los proveedores y clientes de un cliente de la gestoría que aparecen duplicados: el mismo NIF con nombres distintos y el mismo nombre con NIF distintos (casi siempre un NIF mal leído). Acaban en subcuentas repetidas en a3."""
    return _mt._conta().terceros_duplicados_de(*_mt._ctx_conta(), cliente_fiscal_id)


def contabilidad_unificar_tercero(cliente_fiscal_id: int, tipo: str, nif: str, nombre: str) -> dict:
    """Pone un nombre único a un NIF en las facturas pendientes o revisadas de un cliente (las ya exportadas no se tocan). `tipo`: recibida (proveedores) o emitida (clientes)."""
    return _mt._conta().unificar_tercero(*_mt._ctx_conta(), cliente_fiscal_id, tipo, nif, nombre)


def contabilidad_corregir_nif_tercero(cliente_fiscal_id: int, tipo: str, nif_mal: str, nif_bien: str) -> dict:
    """Cambia un NIF mal leído por el correcto en las facturas pendientes o revisadas de un cliente (las ya exportadas no se tocan). `tipo`: recibida (proveedores) o emitida (clientes)."""
    return _mt._conta().corregir_nif_tercero(*_mt._ctx_conta(), cliente_fiscal_id, tipo, nif_mal, nif_bien)


def contabilidad_facturas_para_asiento_de_pago(cliente_fiscal_id: int) -> list[dict]:
    """Las facturas ya exportadas de un cliente de la gestoría cuyo asiento de cobro (emitidas) o pago (recibidas) aún no ha salido en un fichero para a3, las más antiguas primero."""
    return _mt._conta().facturas_para_asiento_de_pago(*_mt._ctx_conta(), cliente_fiscal_id)


def contabilidad_generar_asientos_de_pago(cliente_fiscal_id: int, pagos: list[dict], repetir: bool = False) -> dict:
    """Genera el fichero de asientos de cobro y pago para a3 (solo clientes con el formato de 256 posiciones). `pagos`: una por factura exportada, con `factura_id` y, opcionalmente, `fecha` (AAAA-MM-DD; hoy por
    defecto), `importe` en euros (el total por defecto, para un pago parcial) y `cuenta_tesoreria`. Pago a un proveedor: Debe el proveedor, Haber el banco; cobro: Debe el banco, Haber el cliente. Marca las facturas
    para no repetirlas salvo con `repetir`. Devuelve el número de fichero (se baja en Ficheros generados)."""
    return _mt._conta().generar_asientos_de_pago(*_mt._ctx_conta(), cliente_fiscal_id, pagos, repetir)
