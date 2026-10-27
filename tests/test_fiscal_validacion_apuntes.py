"""Validación de apuntes (app/fiscal_modelos/validacion_apuntes.py): las reglas que el simulador de la AEAT aplicó al importar libros. Los casos «rechazados» son los reales
(los mensajes de la AEAT están en docs/fiscal-vias-aeat.md §4e); los escenarios que la AEAT ACEPTÓ no deben dar ningún error."""
from datetime import date as d

import pytest

from app.fiscal_modelos import validacion_apuntes as v
from tests.escenarios_303 import ESCENARIOS, compra, venta

HOY = d(2026, 10, 25)
TITULAR = "A12345674"
FR_OK = dict(contraparte_nif="FR40303265045", contraparte_nif_tipo="02", contraparte_pais="FR")


def _codigos(apuntes, **kw):
    return {x.codigo for x in v.errores(v.validar(apuntes, hoy=HOY, nif_titular=TITULAR, **kw))}


@pytest.mark.parametrize("nombre", sorted(ESCENARIOS))
def test_lo_que_la_aeat_acepto_no_da_errores(nombre):
    apuntes, _, _ = ESCENARIOS[nombre]
    assert v.errores(v.validar(apuntes, hoy=HOY, nif_titular=TITULAR)) == []


def test_fechas_futuras():
    assert _codigos([venta(100, fecha=d(2026, 11, 3))]) == {"fecha_futura"}
    assert _codigos([compra(100, fecha=d(2026, 9, 1), fecha_recepcion=d(2026, 12, 1))]) == {"fecha_futura"}
    assert _codigos([compra(100, fecha=d(2026, 9, 5), fecha_recepcion=d(2026, 9, 1))]) == {"recepcion_anterior"}


def test_tipos_de_iva_no_vigentes_salvo_rectificativas():
    assert _codigos([venta(10000, 0)]) == {"tipo_iva_no_vigente"}
    assert _codigos([venta(10000, 500)]) == {"tipo_iva_no_vigente"}
    assert _codigos([venta(-10000, 0, tipo_factura="R1")]) == set()


def test_inversion_del_sujeto_pasivo_y_s2():
    assert _codigos([venta(5000, 2100, calificacion="S2")]) == {"s2_con_iva"}
    assert _codigos([compra(15000, isp=True, total=17000)]) == {"total_distinto_base"}
    assert _codigos([compra(15000, isp=True)]) == set()


def test_nif_iva_intracomunitario():
    malo = dict(FR_OK, contraparte_nif="FR12345678901")
    assert _codigos([compra(20000, clave="09", **malo)]) == {"nif_iva_invalido"}                    # la AEAT lo rechazó («NIF-IVA no válido»)
    assert _codigos([compra(20000, clave="09", **FR_OK)]) == set()
    assert _codigos([compra(20000, clave="09")]) == {"aib_sin_nif_iva"}
    assert _codigos([venta(4000, 0, 0, calificacion="", exenta="E5")]) == {"e5_sin_nif_iva"}
    assert _codigos([venta(4000, 0, 0, calificacion="", exenta="E5", **FR_OK)]) == set()
    assert _codigos([venta(4000, 0, 0, calificacion="", exenta="E5", contraparte_nif="XX1", contraparte_nif_tipo="02", contraparte_pais="XX")]) == {"nif_iva_invalido"}


def test_dua():
    assert _codigos([compra(30000, tipo_factura="F5", numero="DUA1")]) == {"dua_expedidor", "dua_no_espanol"}
    assert _codigos([compra(30000, tipo_factura="F5", numero="26ES00123456789012", contraparte_nif=TITULAR)]) == set()


def test_deduccion_diferida():
    assert _codigos([compra(100, deducible_periodo_posterior=True)]) == {"sin_periodo_deduccion"}
    assert _codigos([compra(100, fecha=d(2026, 5, 12), deducible_periodo_posterior=True, periodo_deduccion=(2026, "2T"))]) == {"deduccion_no_posterior"}
    assert _codigos([compra(100, fecha=d(2026, 5, 12), deducible_periodo_posterior=True, periodo_deduccion=(2026, "3T"))]) == set()


def test_la_cuota_repercutida_es_exactamente_base_por_tipo():
    assert _codigos([venta(10000, cuota=999)]) == {"cuota_no_cuadra"}                      # la AEAT: «igual a (base imponible x tipo IVA)»
    assert _codigos([venta(10000, 2100, cuota=2100, total=12100)]) == set()
    assert _codigos([venta(12100, 2100, cuota=2100, total=14000)]) == {"cuota_no_cuadra", "total_no_cuadra"}
    assert _codigos([venta(10000, 2100, total=9000)]) == {"total_no_cuadra"}
    assert _codigos([venta(3333, 2100, cuota=700)]) == set() and _codigos([venta(-3333, 2100, cuota=-700, tipo_factura="R1")]) == set()


def test_avisos_no_bloquean():
    ap = [venta(10000), venta(10000, numero="1")]
    p = v.validar(ap, hoy=HOY, nif_titular=TITULAR)
    assert {x.codigo for x in p} == {"posible_duplicado", "nif_digito"} and v.errores(p) == []          # el NIF de los escenarios es inventado: su dígito de control no cuadra (solo avisa)


def test_preparar_borrador_de_un_paso():
    from app.fiscal_modelos import preparar_303 as p
    ap, ej, per = ESCENARIOS["basico"]
    b = p.preparar(ap, ejercicio=ej, periodo=per, nif=TITULAR, nombre="EMPRESA DE PRUEBA SL", hoy=HOY)
    assert b.listo_para_revisar and b.fichero.startswith(b"<T303020262T0000>") and b.resultado.casillas["71"] == 1050
    malo = p.preparar([venta(10000, 0)], ejercicio=2026, periodo="2T", nif=TITULAR, nombre="X", hoy=HOY)          # dato erróneo: sin fichero
    assert not malo.listo_para_revisar and malo.fichero is None and "errores en los datos" in malo.motivo_sin_fichero
    bloqueado = p.preparar(ap, ejercicio=ej, periodo=per, nif=TITULAR, nombre="X", hoy=HOY, prorrata=True)
    assert bloqueado.fichero is None and "bloqueado" in bloqueado.motivo_sin_fichero
    ultimo = p.preparar([venta(10000, fecha=d(2026, 10, 5))], ejercicio=2026, periodo="4T", nif=TITULAR, nombre="X", hoy=HOY)
    assert ultimo.fichero is not None and ultimo.fichero.startswith(b"<T303020264T0000>")


def test_digito_de_control_del_nif_espanol():
    ok = ["A12345674", "12345678Z", "X1234567L", "00000000T"]
    mal = ["A12345675", "12345678A", "B87654321", "X1234567A"]
    assert all(v.nif_espanol_valido(n) is True for n in ok)
    assert all(v.nif_espanol_valido(n) is False for n in mal)
    assert v.nif_espanol_valido("FR40303265045") is None and v.nif_espanol_valido("") is None
    assert v.nif_espanol_valido("a-1234567-4") is True
