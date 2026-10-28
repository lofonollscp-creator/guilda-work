"""Ficheros `.303` completos que se importan en el simulador de la AEAT (scripts/fiscal/grabar_ficheros_303.py): rectificativas, recargo, caja y prorrata. La devolución con IBAN no se puede probar todavía: el simulador solo la admite en el último periodo (4T/12), que aún no está abierto. Cada función devuelve nuestro fichero;
`tests/fixtures/aeat/ficheros_303/nuestro/<nombre>.303` guarda el que se probó y `.../aeat/<nombre>.303` el que el simulador exportó de vuelta tras importarlo y validarlo."""
from app.fiscal_modelos import fichero_303 as f
from app.fiscal_modelos import motor_303 as m
from tests.escenarios_303 import ESCENARIOS, _re, compra, d, venta

NIF, NOMBRE = "A12345674", "EMPRESA DE PRUEBA SL"
JUSTIFICANTE = "3030000000123"
IBAN_ES = "ES91 2100 0418 4502 0005 1332"
BASICO = ESCENARIOS["basico"][0]
NEGATIVO = ESCENARIOS["resultado_negativo"][0]


def _anio():
    return [venta(100000, fecha=d(2026, 2, 3)), venta(50000, 0, 0, numero="2", fecha=d(2026, 3, 3), exenta="E1"), compra(100000, fecha=d(2026, 5, 12))]


def _rectificativa(extra, **kw):
    r = m.calcular(BASICO + extra, ejercicio=2026, periodo="2T")
    m.aplicar_rectificativa(r, {"69": m.calcular(BASICO, ejercicio=2026, periodo="2T").casillas["69"]}, **kw)
    return r


def _g(r, **kw):
    return f.generar(r, nif=NIF, nombre=NOMBRE, **kw)


def _periodo(periodo, mes, **kw):
    ap = [venta(10000, fecha=d(2026, mes, 10)), compra(4000, fecha=d(2026, mes, 12))]
    return _g(m.calcular(ap, ejercicio=2026, periodo=periodo, **kw))


CASOS = {
    "rectificativa_a_ingresar": lambda: _g(_rectificativa([venta(10000, numero="2")]), justificante_anterior=JUSTIFICANTE),
    "rectificativa_111_con_iban": lambda: _g(_rectificativa([compra(40000, numero="P-9")]), justificante_anterior=JUSTIFICANTE, iban=IBAN_ES),
    "recargo": lambda: _g(m.calcular([_re(100000, 2100, 520), _re(10000, 400, 50, numero="2"), compra(20000)], ejercicio=2026, periodo="2T")),
    "caja": lambda: _g(m.calcular([venta(100000, clave="07", cobros=((d(2026, 5, 20), 30000), (d(2026, 8, 1), 50000))), venta(10000, numero="2")], ejercicio=2026, periodo="2T", criterio_caja=True), criterio_caja=True),
    "caja_destinataria": lambda: _g(m.calcular([venta(100000), compra(50000, clave="07", cobros=((d(2026, 6, 1), 30250),))], ejercicio=2026, periodo="2T", criterio_caja=True), criterio_caja=True),
    "prorrata_general": lambda: _g(m.calcular(_anio(), ejercicio=2026, periodo="2T", prorrata_general=8000)),
    "a_compensar": lambda: _g(m.calcular(NEGATIVO, ejercicio=2026, periodo="2T")),
    "trimestre_1t": lambda: _periodo("1T", 2),
    "trimestre_3t": lambda: _periodo("3T", 8),
    "mensual_01": lambda: _periodo("01", 1),
    "mensual_05": lambda: _periodo("05", 5),
}
