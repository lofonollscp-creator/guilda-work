"""Escenarios del cálculo del 303: los MISMOS apuntes se calculan con nuestro motor y se suben, como libro, al simulador de la AEAT; el resultado de la AEAT queda grabado en
`tests/fixtures/aeat/oraculo_libros/<nombre>.json` (scripts/fiscal/grabar_oraculo.py) y los tests comparan nuestro motor con él sin tocar la red."""
from datetime import date as d

from app.fiscal_modelos.apuntes import Apunte

E, R = "E", "R"


def venta(base, tipo=2100, cuota=None, fecha=d(2026, 5, 10), **kw):
    return Apunte(E, kw.pop("tipo_factura", "F1"), fecha, numero=kw.pop("numero", "1"), serie="A", base=base, tipo_iva=tipo, cuota=base * tipo // 10000 if cuota is None else cuota, **kw)


def compra(base, tipo=2100, cuota=None, fecha=d(2026, 5, 12), **kw):
    return Apunte(R, kw.pop("tipo_factura", "F1"), fecha, numero=kw.pop("numero", "P-1"), base=base, tipo_iva=tipo, cuota=base * tipo // 10000 if cuota is None else cuota,
                  **{"contraparte_nif": "B11111111", **kw})


ESCENARIOS = {
    "basico": ([venta(10000), compra(5000)], 2026, "2T"),
    "solo_ventas": ([venta(10000), venta(20000, numero="2")], 2026, "2T"),
    "tipos": ([venta(10000, 400), venta(10000, 1000, numero="2"), venta(10000, 2100, numero="3")], 2026, "2T"),
    "otros_trimestres": ([venta(10000), venta(7000, numero="2", fecha=d(2026, 2, 3)), venta(9000, numero="3", fecha=d(2026, 8, 3)), compra(3000), compra(4000, fecha=d(2026, 9, 3), numero="P-2")], 2026, "2T"),
    "fecha_operacion": ([venta(10000, fecha=d(2026, 7, 2), fecha_operacion=d(2026, 6, 30)), venta(5000, numero="2", fecha=d(2026, 4, 2), fecha_operacion=d(2026, 3, 30))], 2026, "2T"),
    "rectificativas": ([venta(10000), venta(-2000, numero="2", tipo_factura="R1"), venta(-1000, numero="3", tipo_factura="F1"), compra(5000), compra(-500, numero="P-2", tipo_factura="R1")], 2026, "2T"),
    "bien_inversion": ([venta(200000), compra(80000, bien_inversion=True), compra(1000, numero="P-2")], 2026, "2T"),
    "importacion": ([venta(10000), compra(30000, tipo_factura="F5", numero="26ES00123456789012", contraparte_nif="A12345674")], 2026, "2T"),
    "adquisicion_intracomunitaria": ([venta(10000), compra(20000, clave="09", contraparte_nif="FR40303265045", contraparte_nif_tipo="02", contraparte_pais="FR")], 2026, "2T"),
    "inversion_sujeto_pasivo": ([venta(10000), compra(15000, isp=True)], 2026, "2T"),
    "exentas_y_no_sujetas": ([venta(10000), venta(4000, 0, 0, numero="2", calificacion="", exenta="E5", contraparte_nif="FR40303265045", contraparte_nif_tipo="02", contraparte_pais="FR"),
                              venta(6000, 0, 0, numero="3", calificacion="", exenta="E2", clave="02", contraparte_nif="US123", contraparte_nif_tipo="04", contraparte_pais="US"),
                              venta(2500, 0, 0, numero="4", calificacion="N2", contraparte_nif="B87654321")], 2026, "2T"),
    "venta_con_isp": ([venta(10000), venta(12000, 0, 0, numero="2", calificacion="S2")], 2026, "2T"),
    "recepcion_posterior": ([venta(10000), compra(5000, fecha=d(2026, 3, 20), fecha_recepcion=d(2026, 4, 10)), compra(2000, numero="P-2", fecha=d(2026, 6, 28), fecha_recepcion=d(2026, 7, 3))], 2026, "2T"),
    "deduccion_diferida": ([venta(10000), compra(6000, deducible_periodo_posterior=True, periodo_deduccion=(2026, "3T")),
                           compra(3000, numero="P-2", fecha=d(2026, 2, 1), deducible_periodo_posterior=True, periodo_deduccion=(2026, "2T"))], 2026, "2T"),
    "resultado_negativo": ([venta(1000), compra(50000)], 2026, "2T"),
    "cuota_con_decimales": ([venta(3333, 2100, cuota=700), venta(3333, 1000, numero="2", cuota=333), compra(1234, 2100, cuota=259)], 2026, "2T"),
    # --- más casos reales de despacho
    "simplificadas_y_resumen": ([venta(10000, 2100, cuota=2100, tipo_factura="F2", numero="10", contraparte_nif="", contraparte_nombre="VENTAS A CONSUMIDOR FINAL", total=12100),
                                 venta(5000, 1000, tipo_factura="F4", numero="11", contraparte_nif="", contraparte_nombre="VENTAS A CONSUMIDOR FINAL"), compra(2000, tipo_factura="F6", numero="P-9")], 2026, "2T"),
    "rectificativa_de_adquisicion_intracomunitaria": ([venta(10000), compra(20000, clave="09", numero="P-1", **dict(contraparte_nif="FR40303265045", contraparte_nif_tipo="02", contraparte_pais="FR")),
                                                       compra(-5000, clave="09", numero="P-2", tipo_factura="R1", **dict(contraparte_nif="FR40303265045", contraparte_nif_tipo="02", contraparte_pais="FR"))], 2026, "2T"),
    "rectificativa_de_inversion_sujeto_pasivo": ([venta(10000), compra(15000, isp=True), compra(-3000, isp=True, numero="P-2", tipo_factura="R1")], 2026, "2T"),
    "abono_recibido_y_emitido_en_otro_periodo": ([venta(10000), venta(-4000, numero="2", tipo_factura="R2", fecha=d(2026, 5, 20)), compra(8000, fecha=d(2026, 2, 2)), compra(-8000, numero="P-2", tipo_factura="R1", fecha=d(2026, 6, 2))], 2026, "2T"),
    # --- alquileres (Guilda Fiscal Alquileres)
    "alquiler_local_comercial": ([venta(100000, clave="12", inmueble_situacion="1", inmueble_referencia="9872023VH5797S0001WX"),
                                  compra(30000, clave="12", numero="A-7", inmueble_situacion="1", inmueble_referencia="9872023VH5797S0001WX"), compra(4500, numero="REP-1")], 2026, "2T"),
    "alquiler_vivienda_exento": ([venta(80000, 0, 0, clave="13", calificacion="", exenta="E1", inmueble_situacion="1", inmueble_referencia="9872023VH5797S0001WX"), venta(10000, numero="2"),
                                  compra(2500, numero="P-1")], 2026, "2T"),
    "alquiler_turistico_al_10": ([venta(45000, 1000, numero="1"), venta(30000, 1000, numero="2", fecha=d(2026, 6, 3)), compra(9000, numero="LIMP-1"), compra(12000, 1000, numero="SUM-1")], 2026, "2T"),
}


# --- Regímenes especiales: se calculan con kwargs del motor y el simulador necesita contestar a la identificación (criterio de caja, etc.).
# nombre -> (apuntes, ejercicio, periodo, kwargs de motor_303.calcular, respuestas de «Identificación»)
CAJA = {"acogido al régimen especial del criterio de Caja": "SI"}


def _re(base, tipo, rec, **kw):
    return venta(base, tipo, recargo_pct=rec, recargo_cuota=(base * rec + 5000) // 10000, **kw)


ESCENARIOS_ESPECIALES = {
    "recargo_21": ([_re(100000, 2100, 520), compra(20000)], 2026, "2T", {}, {}),
    "recargo_varios_tipos": ([_re(10000, 400, 50), _re(20000, 1000, 140, numero="2"), _re(30000, 2100, 520, numero="3")], 2026, "2T", {}, {}),
    "recargo_con_abono": ([_re(100000, 2100, 520), venta(-10000, 2100, numero="9", tipo_factura="R1", recargo_pct=520, recargo_cuota=-520)], 2026, "2T", {}, {}),
    "caja_cobro_total_en_el_periodo": ([venta(100000, clave="07", cobros=((d(2026, 5, 20), 121000),)), compra(5000)], 2026, "2T", {"criterio_caja": True}, CAJA),
    "caja_cobro_parcial": ([venta(100000, clave="07", cobros=((d(2026, 5, 20), 30000), (d(2026, 8, 1), 50000)))], 2026, "2T", {"criterio_caja": True}, CAJA),
    "caja_cobro_en_periodo_posterior": ([venta(100000, clave="07", fecha=d(2026, 2, 10), cobros=((d(2026, 5, 20), 60500),))], 2026, "2T", {"criterio_caja": True}, CAJA),
    "caja_sin_cobros": ([venta(100000, clave="07"), venta(10000, numero="2")], 2026, "2T", {"criterio_caja": True}, CAJA),
    "caja_compra_pagada": ([venta(100000), compra(50000, clave="07", cobros=((d(2026, 6, 1), 30250),))], 2026, "2T", {"criterio_caja": True}, CAJA),
}
