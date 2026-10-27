"""Prorrata general en el 303: porcentaje provisional del perfil (redondeado a la unidad superior) y regularización en el último periodo (casilla 44) con el porcentaje definitivo del año."""
from datetime import date

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from app.fiscal_modelos import motor_303, motor_390
from tests.escenarios_303 import compra, venta

NIF = "A12345674"


def test_el_porcentaje_se_redondea_a_la_unidad_superior():
    assert motor_303.porcentaje_de_prorrata(7234) == 73 and motor_303.porcentaje_de_prorrata(7300) == 73 and motor_303.porcentaje_de_prorrata(10000) == 100 and motor_303.porcentaje_de_prorrata(1) == 1


def test_con_prorrata_se_deduce_el_porcentaje_de_la_cuota_y_la_base_va_entera():
    r = motor_303.calcular([venta(10000), compra(10000)], ejercicio=2026, periodo="2T", prorrata_general=7234)
    assert r.calculable, r.bloqueos
    assert r.casillas["28"] == 10000 and r.casillas["29"] == 1533 and r.casillas["45"] == 1533 and r.casillas["46"] == 2100 - 1533
    # sin prorrata, todo
    assert motor_303.calcular([venta(10000), compra(10000)], ejercicio=2026, periodo="2T").casillas["29"] == 2100


def test_prorrata_con_deduccion_parcial_se_bloquea():
    r = motor_303.calcular([compra(10000, cuota_deducible=1000)], ejercicio=2026, periodo="2T", prorrata_general=8000)
    assert not r.calculable and any("deducción parcial" in b for b in r.bloqueos)


def _anio():
    from tests.escenarios_303 import venta as v
    return [v(100000, fecha=date(2026, 2, 3)), v(50000, 0, 0, numero="2", fecha=date(2026, 3, 3), calificacion="S1", exenta="E1"), compra(100000, fecha=date(2026, 5, 12))]


def test_el_ultimo_periodo_regulariza_con_el_porcentaje_definitivo_del_ano():
    ap = _anio()
    # volumen 150.000, sin derecho 50.000 -> 66,67 % -> 67 %; provisional 80 %
    c2 = motor_303.calcular(ap, ejercicio=2026, periodo="2T", prorrata_general=8000)
    assert c2.casillas["29"] == 16800 and "44" not in c2.casillas
    c4 = motor_303.calcular(ap, ejercicio=2026, periodo="4T", prorrata_general=8000)
    assert c4.calculable, c4.bloqueos
    assert c4.casillas["44"] == 14070 - 16800 and c4.casillas["45"] == c4.casillas["44"]
    assert any("definitiva 67 %" in a for a in c4.avisos)
    # sin perfil de prorrata no hay regularización
    assert "44" not in motor_303.calcular(ap, ejercicio=2026, periodo="4T").casillas


def test_el_390_con_prorrata_general_se_bloquea():
    r = motor_390.calcular(_anio(), ejercicio=2026, prorrata_general=8000)
    assert not r.calculable and any("prorrata" in b for b in r.bloqueos)


def _despacho(nombre, **perfil):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    u = db.crear_usuario_vinculado_a_kratos(f"{clave}@ejemplo.com", f"k-{clave}"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif=NIF)
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad", **perfil}, vigente_desde="2026-01-01")
    return t, u, c


def test_el_perfil_decide_entre_prorrata_general_y_especial():
    t, u, c = _despacho("Despacho prorrata a", prorrata_centesimas=8000)
    p = fp.perfil_en(t, c, "2026-05-01")
    ajustes, _ = fn._perfil_a_flags(p, "2T")
    assert ajustes["prorrata"] is False and ajustes["prorrata_general"] == 8000
    t, u, c = _despacho("Despacho prorrata b", prorrata_centesimas=8000, prorrata_especial=1)
    ajustes, _ = fn._perfil_a_flags(fp.perfil_en(t, c, "2026-05-01"), "2T")
    assert ajustes["prorrata"] is True and ajustes["prorrata_general"] is None


def test_declaracion_con_prorrata_y_fichero_salvo_exonerado_del_390():
    t, u, c = _despacho("Despacho prorrata c", prorrata_centesimas=8000)
    for a in (venta(10000), compra(10000)):
        fn.aprobar_apunte(t, u, c, a)
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")["id"])
    assert dec["bloqueos"] == [] and dec["casillas"]["29"] == 1680 and dec["casillas"]["71"] == 2100 - 1680
    fn.revisar_declaracion(t, u, dec["id"])
    assert fn.exportar_declaracion(t, u, dec["id"])["estado"] == "exportada"
    t, u, c = _despacho("Despacho prorrata d", prorrata_centesimas=8000, exonerado_390=1)
    for a in (venta(10000, fecha=date(2026, 10, 3)), compra(10000, fecha=date(2026, 10, 5))):
        fn.aprobar_apunte(t, u, c, a)
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="4T")["id"])
    assert dec["bloqueos"] == [], dec["bloqueos"]
    fn.revisar_declaracion(t, u, dec["id"])
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.exportar_declaracion(t, u, dec["id"])
    assert e.value.codigo == "no_soportado"


def test_una_cuota_excluida_del_todo_no_se_prorratea():
    r = motor_303.calcular([compra(10000, cuota_deducible=0)], ejercicio=2026, periodo="2T", prorrata_general=8000)
    assert r.calculable and "29" not in r.casillas
