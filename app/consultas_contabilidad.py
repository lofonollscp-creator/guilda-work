"""Consultas y acciones de «Facturas para contabilizar» que comparten la API REST (app/rutas_api_contabilidad.py) y las herramientas MCP y del asistente de IA (mcp_tools/herramientas_contabilidad.py).
Mismas reglas que la web: el despacho propio, el módulo `contabilizacion` activo, solo los clientes que la persona puede ver, y quien solo audita puede mirar pero no cambiar. Los importes salen en euros
con dos decimales además de en céntimos. Los `ValueError` llevan un mensaje legible y los de «no existe» o «no está activo» se tratan como 404."""
from __future__ import annotations

import base64
import binascii

from . import acceso, cierre_trimestre, cobro_contabilidad, cuadre_303, facturas_contables as fc, facturas_portal, lectura_calidad, lectura_facturas, panel_cierre, retorno_a3, verticales


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
            "tiene_archivo": bool(f.get("documento_id")), "lectura_fuente": f.get("lectura_fuente"), "lectura_confianza": f.get("lectura_confianza"), "revision_auto": bool(f.get("revision_auto"))}


def listar_facturas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None, estado: str | None = None, tipo: str | None = None, trimestre: str | None = None, limite: int = 50,
                    desde_indice: int = 0) -> list[dict]:
    """Las facturas anotadas (las más recientes primero), con su estado y su procedencia."""
    _exigir_modulo(tenant_id)
    if estado and estado not in fc.ESTADOS:
        raise ValueError("`estado` debe ser pendiente, revisada, exportada o descartada.")
    if tipo and tipo not in fc.TIPOS:
        raise ValueError("`tipo` debe ser emitida o recibida.")
    desde, hasta = fc.rango_del_trimestre(trimestre) if trimestre else (None, None)
    limite, salto = max(1, min(int(limite or 50), 200)), max(0, int(desde_indice or 0))
    filas = fc.listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, estado=estado or None, tipo=tipo or None, desde=desde, hasta=hasta, limite=min(limite + salto, 2000))
    return [_resumen(f) for f in filas[salto:salto + limite]]


def ver_factura(tenant_id: int, usuario_id: int, factura_id: int) -> dict:
    """Una factura entera: datos, líneas de IVA, lo que impide darla por revisada y si su periodo está cerrado."""
    _exigir_modulo(tenant_id)
    f = fc.obtener(tenant_id, usuario_id, int(factura_id))
    if f is None:
        raise ValueError("No existe esa factura.")
    cerrado = fc.periodos_cerrados(tenant_id, f["cliente_fiscal_id"], [f["trimestre"]]).get(f["trimestre"])
    return {**_resumen(f), "fecha_operacion": f["fecha_operacion"], "concepto": f["concepto"], "referencia": f["referencia"], "subcuenta_tercero": fc.cuenta_efectiva(tenant_id, f),
            "rectifica_numero": f["rectifica_numero"], "rectifica_fecha": f["rectifica_fecha"], "criterio_caja": bool(f.get("criterio_caja")), "suplidos": _euros(f["suplidos_centimos"]), "notas": f["notas"], "datos_a3": f.get("a3") or {},
            "lectura_error": f.get("lectura_error"), "problemas": f["problemas"], "periodo_cerrado": cerrado["detalle"] if cerrado else None,
            "lineas": [{"base": _euros(l["base_centimos"]), "pct_iva": l["pct_iva"] / 100, "cuota_iva": _euros(l["cuota_iva"]), "pct_recargo": l["pct_recargo"] / 100, "cuota_recargo": _euros(l["cuota_recargo"]),
                        "pct_retencion": l["pct_retencion"] / 100, "cuota_retencion": _euros(l["cuota_retencion"]), "cuenta": l["cuenta"], "tipo_operacion": l["subtipo"], "impreso": fc.impreso_de_linea(f["tipo"], l)} for l in f["lineas"]]}


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


def subir_archivos(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, archivos: list[tuple[str, str | None, bytes]]) -> dict:
    """Sube de 1 a 10 fotos o PDF de facturas de un cliente sin teclear nada: quedan pendientes de leer (con IA o a mano). Devuelve los ids creados y cuántos archivos ya estaban enviados."""
    _exigir_escritura(tenant_id, usuario_id)
    if not archivos or len(archivos) > fc.MAX_ARCHIVOS_POR_SUBIDA:
        raise ValueError("Sube de 1 a 10 archivos de una vez (`archivos`).")
    ids = fc.subir_archivos(tenant_id, usuario_id, int(cliente_fiscal_id or 0), tipo, archivos)
    return {"ids": list(ids), "repetidas": getattr(ids, "repetidas", 0)}


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


# --- Controles, revisión en lote, mapa de cuentas y retorno de a3 ---------------------------------------------------------------------------------------

def avisos_factura(tenant_id: int, usuario_id: int, factura_id: int) -> dict:
    """Lo que conviene mirar de una factura aunque no impida revisarla (NIF dudoso, fechas raras, hueco de numeración…) y las facturas que pueden ser la misma: {avisos, duplicados}."""
    from . import facturas_control
    _exigir_modulo(tenant_id)
    f = fc.obtener(tenant_id, usuario_id, int(factura_id))
    if f is None:
        raise ValueError("No existe esa factura.")
    return {"factura_id": f["id"], "avisos": facturas_control.avisos(tenant_id, f), "duplicados": facturas_control.duplicados(tenant_id, f)}


def comprobar_vies(tenant_id: int, usuario_id: int, nif: str) -> dict:
    """Pregunta al VIES si un NIF-IVA de otro país de la UE está dado de alta: {valido: true|false|null, error}. `null` = el servicio no contestó."""
    from . import facturas_control
    _exigir_modulo(tenant_id)
    return facturas_control.comprobar_vies(nif)


def siguiente_pendiente(tenant_id: int, usuario_id: int, factura_id: int) -> dict:
    """La siguiente factura pendiente del mismo cliente tras la indicada (o de otro si ya no quedan): {factura_id: id|null}."""
    _exigir_modulo(tenant_id)
    return {"factura_id": fc.siguiente_pendiente(tenant_id, usuario_id, int(factura_id))}


def revisables_en_lote(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None, umbral: int | None = None) -> dict:
    """Las pendientes que se pueden dar por buenas de golpe (factura electrónica o lectura con confianza alta, sin problemas ni avisos). No cambia nada."""
    _exigir_modulo(tenant_id)
    umbral = int(umbral or fc.UMBRAL_REVISION_EN_LOTE)
    filas = fc.revisables_en_lote(tenant_id, usuario_id, cliente_fiscal_id or None, umbral)
    return {"umbral": umbral, "total": len(filas), "facturas": [_resumen(f) for f in filas[:200]]}


def revisar_seguras(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None, umbral: int | None = None, simular: bool = False) -> dict:
    """Da por revisadas de golpe las `revisables_en_lote`: {revisadas, omitidas}. No enseña reglas al sistema. Con `simular` no cambia nada: {simulacion: true, se_revisarian, facturas}."""
    if simular:
        _exigir_modulo(tenant_id)
        r = revisables_en_lote(tenant_id, usuario_id, cliente_fiscal_id, umbral)
        return {"simulacion": True, "se_revisarian": r["total"], "umbral": r["umbral"], "facturas": r["facturas"]}
    _exigir_escritura(tenant_id, usuario_id)
    return fc.revisar_en_lote(tenant_id, usuario_id, cliente_fiscal_id or None, int(umbral or fc.UMBRAL_REVISION_EN_LOTE))


def mapa_de_cuentas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> dict:
    """Qué subcuenta de a3 se usará con cada proveedor y cliente del cliente de la gestoría y de dónde sale (recordada, plan, nueva o genérica)."""
    _exigir_modulo(tenant_id)
    return fc.mapa_de_cuentas(tenant_id, usuario_id, int(cliente_fiscal_id))


def fijar_cuenta_tercero(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo_tercero: str, nif: str, cuenta: str) -> dict:
    """Fija a mano la subcuenta de un proveedor o cliente para las próximas exportaciones (las ya exportadas no cambian)."""
    _exigir_escritura(tenant_id, usuario_id)
    fc.fijar_cuenta_tercero(tenant_id, usuario_id, int(cliente_fiscal_id), tipo_tercero, nif, cuenta)
    return {"ok": True, "tipo_tercero": tipo_tercero, "nif": nif, "cuenta": cuenta}


def calidad_lectura(tenant_id: int, usuario_id: int, desde: str | None = None, cliente_fiscal_id: int | None = None) -> dict:
    """Cómo acierta la lectura de facturas (por fuente, por tipo de documento y por campo) y cuánto cuesta. Por defecto, desde el día 1 del mes."""
    _exigir_modulo(tenant_id)
    if cliente_fiscal_id and not acceso.puede_ver_cliente(tenant_id, usuario_id, int(cliente_fiscal_id)):
        raise ValueError("No tienes acceso a ese cliente.")
    return lectura_calidad.resumen(tenant_id, desde or None, int(cliente_fiscal_id) if cliente_fiscal_id else None)


def _bytes_del_listado(contenido: str | None, contenido_base64: str | None) -> bytes:
    if contenido_base64:
        try:
            return base64.b64decode(contenido_base64, validate=False)
        except (binascii.Error, ValueError):
            raise ValueError("`contenido_base64` no es base64 válido.") from None
    if contenido:
        return contenido.encode("utf-8")
    raise ValueError("Pasa el listado de a3 en `contenido` (texto CSV) o en `contenido_base64` (CSV o Excel).")


def cruzar_retorno_a3(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, contenido: str | None = None, contenido_base64: str | None = None, nombre: str = "", confirmar: bool = False,
                      columnas: dict | None = None, fila_de_titulos: int = 1) -> dict:
    """Cruza un listado de a3 con las facturas exportadas del cliente. Sin `confirmar` solo informa (no guarda nada); con `confirmar` anota como confirmadas las que coinciden exactamente. Si las columnas no
    se reconocen por su título, `columnas` ({"numero": "C", "fecha": "B", "total": "D"}, por letra) y `fila_de_titulos` (0 si no hay) dicen cuál es cuál."""
    if confirmar:
        _exigir_escritura(tenant_id, usuario_id)
    else:
        _exigir_modulo(tenant_id)
    mapa = retorno_a3.mapa_de_columnas(**{k: v for k, v in (columnas or {}).items() if k in retorno_a3.SINONIMOS})
    filas = retorno_a3.leer(_bytes_del_listado(contenido, contenido_base64), nombre or "", mapa, int(fila_de_titulos))
    return retorno_a3.cruzar(tenant_id, usuario_id, int(cliente_fiscal_id), filas, confirmar=bool(confirmar))


def panel_del_cierre(tenant_id: int, usuario_id: int, trimestre: str | None = None) -> dict:
    """Qué falta para cerrar un trimestre, cliente por cliente (por leer, por revisar, listas para exportar, sin confirmar en a3), con el plazo de presentación y los días que quedan."""
    _exigir_modulo(tenant_id)
    return panel_cierre.panel(tenant_id, usuario_id, trimestre or None)


def mensajes_de_la_factura(tenant_id: int, usuario_id: int, factura_id: int) -> dict:
    """La conversación con el cliente sobre una factura (lo que le escribió el despacho y lo que contestó él desde su portal): [{autor, texto, cuando, leido}], de la más antigua a la más reciente."""
    _exigir_modulo(tenant_id)
    if fc.obtener(tenant_id, usuario_id, int(factura_id)) is None:
        raise ValueError("No existe esa factura.")
    return {"factura_id": int(factura_id), "mensajes": [{"autor": "cliente" if m["autor"] == "cliente" else "despacho", "texto": m["texto"], "cuando": m["creado_en"], "leido": bool(m["leido_en"])}
                                                       for m in facturas_portal.mensajes(tenant_id, int(factura_id))]}


def preguntar_al_cliente(tenant_id: int, usuario_id: int, factura_id: int, texto: str) -> dict:
    """Escribe al cliente en una factura suya: lo verá en su portal."""
    _exigir_escritura(tenant_id, usuario_id)
    facturas_portal.escribir_como_despacho(tenant_id, usuario_id, int(factura_id), texto)
    return mensajes_de_la_factura(tenant_id, usuario_id, factura_id)


def cierre_del_cliente(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str | None = None) -> dict:
    """El estado de cierre de un trimestre de un cliente: la lista de puntos (por leer, por revisar, mensajes sin leer, duplicadas, sin exportar, justificantes…) con su estado, y lo que le falta frente a a3.
    Para redactar un resumen del cierre."""
    _exigir_modulo(tenant_id)
    trimestre = trimestre or panel_cierre.trimestre_anterior()
    c = cierre_trimestre.checklist(tenant_id, usuario_id, int(cliente_fiscal_id), trimestre)
    fila = next((x for x in panel_cierre.panel(tenant_id, usuario_id, trimestre)["clientes"] if x["cliente_fiscal_id"] == int(cliente_fiscal_id)), None)
    return {"trimestre": trimestre, "plazo": panel_cierre.plazo(trimestre).isoformat(), "facturas": c["total"], "listo_para_cerrar": c["listo"], "cerrado": bool(c["cierre"]),
            "puntos": [{"punto": p["clave"], "estado": p["estado"], "cuantos": p["cuantos"]} for p in c["puntos"]],
            "exportadas_sin_confirmar_en_a3": fila["sin_confirmar"] if fila and fila["usa_retorno"] else None}


def cuadre_con_303(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str | None = None) -> dict:
    """El IVA de las operaciones interiores de las facturas revisadas o exportadas frente a las casillas 27 y 45 del 303 simulado en Guilda Fiscal (en euros). `disponible` es false, con su `motivo`, si no hay 303
    con el que comparar."""
    _exigir_modulo(tenant_id)
    if not acceso.puede_ver_cliente(tenant_id, usuario_id, int(cliente_fiscal_id)):
        raise ValueError("No tienes acceso a ese cliente.")
    r = cuadre_303.cuadrar(tenant_id, usuario_id, int(cliente_fiscal_id), trimestre or panel_cierre.trimestre_anterior())
    euros = lambda d: {k: (_euros(v) if isinstance(v, int) else v) for k, v in d.items()}      # noqa: E731
    return {**r, "facturas": euros(r["facturas"]), **({"modelo_303": euros(r["modelo_303"]), "diferencia": euros(r["diferencia"])} if r["disponible"] else {})}


# --- Catálogo completo: mover, historial, ficheros, reglas, configuración y subida ------------------------------------------------------------------------

def mover_factura(tenant_id: int, usuario_id: int, factura_id: int, cliente_destino_id: int) -> dict:
    """Pasa una factura pendiente a otro cliente del despacho (con su archivo). Hay que volver a leerla después si era una factura leída con IA."""
    _exigir_escritura(tenant_id, usuario_id)
    fc.mover_a_cliente(tenant_id, usuario_id, int(factura_id), int(cliente_destino_id))
    return ver_factura(tenant_id, usuario_id, factura_id)


def historial_factura(tenant_id: int, usuario_id: int, factura_id: int) -> dict:
    """Lo que ha pasado con una factura, de lo más reciente a lo más antiguo: {cuando, quien, que, detalle}."""
    _exigir_modulo(tenant_id)
    if fc.obtener(tenant_id, usuario_id, int(factura_id)) is None:
        raise ValueError("No existe esa factura.")
    return {"factura_id": int(factura_id), "eventos": fc.historial(tenant_id, usuario_id, int(factura_id))}


def listar_ficheros(tenant_id: int, usuario_id: int, cliente_fiscal_id: int | None = None, limite: int = 50, desde_indice: int = 0) -> list[dict]:
    """Los ficheros SUENLACE.DAT generados (los más recientes primero), con cuántas facturas llevan, cuántas confirmó a3 y el estado que se anotó (importado o rechazado)."""
    _exigir_modulo(tenant_id)
    return [{"id": l["id"], "cliente_fiscal_id": l["cliente_fiscal_id"], "cliente": l["cliente_nombre"], "creado_en": l["creado_en"], "facturas": l["n_facturas"], "registros": l["n_registros"],
             "comprobado_en": l["comprobado_en"], "confirmadas_en_a3": l["n_confirmadas"], "estado_a3": l["estado_a3"], "motivo_a3": l["motivo_a3"]}
            for l in fc.listar_lotes(tenant_id, usuario_id, cliente_fiscal_id or None, min(max(1, min(int(limite or 50), 200)) + max(0, int(desde_indice or 0)), 400))][max(0, int(desde_indice or 0)):][:max(1, min(int(limite or 50), 200))]


def fijar_estado_fichero(tenant_id: int, usuario_id: int, lote_id: int, estado: str = "", motivo: str = "") -> dict:
    """Anota si a3 importó el fichero (`importado`) o lo rechazó (`rechazado`, con el motivo), o lo quita (vacío). Es una nota: no cambia las facturas."""
    _exigir_escritura(tenant_id, usuario_id)
    fc.fijar_estado_a3_del_lote(tenant_id, usuario_id, int(lote_id), estado or "", motivo or "")
    return next(l for l in listar_ficheros(tenant_id, usuario_id, None, 200) if l["id"] == int(lote_id))


def listar_reglas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> list[dict]:
    """Las reglas de proveedor y de cliente de un cliente de la gestoría: lo que se rellena solo en sus facturas (cuenta, IVA, retención, tipo de operación, concepto)."""
    _exigir_modulo(tenant_id)
    return [{"id": r["id"], "tipo": r["tipo"], "nif": r["nif"], "nombre": r["nombre"], "cuenta": r["cuenta_linea"], "pct_iva": None if r["pct_iva"] is None else r["pct_iva"] / 100,
             "pct_retencion": None if r["pct_retencion"] is None else r["pct_retencion"] / 100, "tipo_operacion": r["subtipo"], "criterio_caja": bool(r["criterio_caja"]), "concepto": r["concepto"],
             "aprendida": bool(r["aprendida"])} for r in fc.listar_reglas(tenant_id, usuario_id, int(cliente_fiscal_id))]


def guardar_regla(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, nif: str, nombre: str | None = None, cuenta: str | None = None, pct_iva=None, pct_retencion=None,
                  tipo_operacion: str | None = None, criterio_caja: bool = False, concepto: str | None = None) -> dict:
    """Crea o cambia la regla de un proveedor (`tipo` = proveedor) o de un cliente (`cliente`), identificado por su NIF. Vale para las facturas que se anoten o lean después."""
    _exigir_escritura(tenant_id, usuario_id)
    fc.guardar_regla(tenant_id, usuario_id, int(cliente_fiscal_id), tipo, {"nif": nif, "nombre": nombre, "cuenta_linea": cuenta, "pct_iva": None if pct_iva is None else str(pct_iva), "pct_retencion": None if pct_retencion is None else str(pct_retencion), "subtipo": tipo_operacion,
                                                                          "criterio_caja": "1" if criterio_caja else "", "concepto": concepto})
    return next(r for r in listar_reglas(tenant_id, usuario_id, cliente_fiscal_id) if r["tipo"] == tipo and r["nif"] == fc._nif(nif))


def configuracion_a3(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> dict:
    """La configuración de a3 de un cliente: código de empresa, dígitos, formato del fichero (512 o 256), cuentas por defecto, régimen de IVA y si usa subcuentas automáticas."""
    _exigir_modulo(tenant_id)
    if not acceso.puede_ver_cliente(tenant_id, usuario_id, int(cliente_fiscal_id)):
        raise ValueError("No tienes acceso a ese cliente.")
    c = fc.configuracion(tenant_id, int(cliente_fiscal_id))
    return {**{k: c[k] for k in ("a3_empresa", "digitos", "formato_enlace", "regimen_iva", "subcuentas_auto", *fc.CAMPOS_CUENTAS)}, "retencion_emitidas": c["retencion_emitidas"] / 100}


def subir_factura(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, nombre_archivo: str, contenido_base64: str, tipo_mime: str | None = None) -> dict:
    """Sube la foto o el PDF de una factura de un cliente: queda pendiente de leer (usa `contabilidad_leer_factura_con_ia`). Devuelve su id y si el archivo ya estaba subido."""
    _exigir_escritura(tenant_id, usuario_id)
    try:
        contenido = base64.b64decode(contenido_base64 or "", validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("`contenido_base64` no es base64 válido.") from None
    if not contenido:
        raise ValueError("El archivo está vacío.")
    mime = tipo_mime or ("application/pdf" if str(nombre_archivo).lower().endswith(".pdf") else "image/jpeg" if str(nombre_archivo).lower().endswith((".jpg", ".jpeg")) else "image/png" if str(nombre_archivo).lower().endswith(".png") else None)
    ids = fc.subir_archivos(tenant_id, usuario_id, int(cliente_fiscal_id), tipo, [(str(nombre_archivo)[:200], mime, contenido)])
    return {"factura_id": ids[0] if ids else None, "ya_estaba": bool(getattr(ids, "repetidas", 0)) and not ids}


def facturas_periodicas_que_faltan(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> dict:
    """Proveedores periódicos (factura en al menos 3 de los 6 meses anteriores, la última reciente) de los que este mes aún no hay factura. Solo las recibidas; vacío antes del día 10 de cada mes."""
    _exigir_modulo(tenant_id)
    fc._cliente(tenant_id, usuario_id, int(cliente_fiscal_id))
    from . import facturas_periodicas
    return {"cliente_fiscal_id": int(cliente_fiscal_id), "proveedores": [{"nif": x["nif"], "nombre": x["nombre"], "meses_con_factura": x["meses"], "ultima_factura_del_mes": x["ultima"]}
                                                                        for x in facturas_periodicas.que_faltan(tenant_id, int(cliente_fiscal_id))]}
