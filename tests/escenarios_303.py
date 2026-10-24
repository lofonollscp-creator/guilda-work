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
}
