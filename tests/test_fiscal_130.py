"""Modelo 130 (pago fraccionado del IRPF, estimación directa): casillas según las instrucciones oficiales, correspondencia con el diseño y fichero de prueba."""
from datetime import date

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from app.fiscal_modelos import disenos_oficiales as d, fichero_retenciones as fr, motor_130 as m
from tests.escenarios_303 import compra, venta

NIF = "12345678Z"


def _c(**kw):
    base = dict(ejercicio=2026, periodo="2T", ingresos=1000000, gastos=400000, retenciones=0)
    base.update(kw)
    return m.calcular(**base)


def test_el_pago_fraccionado_es_el_20_por_100_del_rendimiento_menos_lo_ya_pagado_y_las_retenciones():
    r = _c(pagos_previos=50000, retenciones=30000)
    c = r.casillas
    assert r.calculable and c["03"] == 600000 and c["04"] == 120000 and c["05"] == 50000 and c["06"] == 30000 and c["07"] == 40000
    assert c["12"] == 40000 and c["14"] == 40000 and c["17"] == c["19"] == 40000 and r.tipo_declaracion == "I"


def test_rendimiento_negativo_da_cero_en_la_04():
    r = _c(ingresos=100000, gastos=300000)
    assert r.casillas["03"] == -200000 and r.casillas.get("04", 0) == 0 and r.casillas["07"] == 0 and r.casillas["19"] == 0 and r.tipo_declaracion == "N"


def test_resultado_negativo_se_deduce_en_los_trimestres_1_a_3_y_en_el_4t_es_negativa():
    r = _c(pagos_previos=150000, retenciones=0)                    # 04 = 1.200 € ; 05 = 1.500 € -> 07 = -300 €
    assert r.casillas["07"] == -30000 and r.casillas["12"] == 0 and r.casillas["19"] == 0
    r = _c(ingresos=1000000, gastos=0, retenciones=300000)         # 04 = 2.000 €; retenciones 3.000 € -> 07 = -1.000 €
    assert r.casillas["07"] == -100000 and r.casillas["19"] == 0
    # un negativo en la 19 sale de la minoración? no: está limitada; el negativo llega por los resultados anteriores solo vía 15 (nunca supera la 14)
    r = _c(negativos_previos=999999)
    assert r.casillas["15"] == r.casillas["14"] and r.casillas["19"] == 0


def test_minoracion_por_rendimientos_bajos_del_ano_anterior():
    for anterior, esperado in ((None, 0), (800000, 10000), (900000, 10000), (900001, 7500), (1000000, 7500), (1050000, 5000), (1200000, 2500), (1200001, 0)):
        assert m.minoracion(anterior) == esperado
    r = _c(rendimiento_anterior=900000)
    assert r.casillas["13"] == 10000 and r.casillas["14"] == r.casillas["12"] - 10000
    # no puede dejar el trimestre en negativo por sí sola
    r = _c(ingresos=600000, gastos=100000, rendimiento_anterior=900000)
    assert r.casillas["12"] == 100000 and r.casillas["13"] == 10000 and r.casillas["14"] == 90000
    r = _c(ingresos=10000, gastos=9500, rendimiento_anterior=900000)
    assert r.casillas["14"] == 0 and r.casillas["13"] == r.casillas["12"] and any("limitado" in a for a in r.avisos)


def test_la_modalidad_simplificada_suma_el_5_por_100_con_tope_de_2000_euros():
    r = _c(simplificada=True)                                      # 6.000 € previos -> 5 % = 300 €
    assert r.casillas["02"] == 400000 + 30000 and r.casillas["03"] == 570000
    r = _c(ingresos=10000000, gastos=0, simplificada=True)
    assert r.casillas["02"] == 200000
    assert _c(ingresos=100, gastos=1000, simplificada=True).casillas["02"] == 1000                  # sin rendimiento positivo no hay difícil justificación


def test_importes_negativos_bloquean_en_vez_de_inventar():
    for kw in ({"ingresos": -1}, {"gastos": -1}, {"retenciones": -1}, {"pagos_previos": -1}, {"negativos_previos": -1}):
        assert not _c(**kw).calculable
    assert not _c(periodo="05").calculable


def test_el_diseno_oficial_del_130_es_coherente_y_cada_casilla_va_a_su_campo():
    diseno = fr.cargar_diseno("130")
    assert d.comprobar(diseno) == [] and diseno["paginas"][1]["total_posiciones"] == 600
    por_n = {c["n"]: c["descripcion"] for c in diseno["paginas"][1]["campos"]}
    for casilla, texto in fr.DESCRIPCION_ESPERADA["130"].items():
        assert texto in por_n[fr._campo_130(casilla)], (casilla, por_n[fr._campo_130(casilla)])


def test_el_fichero_se_lee_de_vuelta_con_el_diseno():
    r = _c(pagos_previos=50000, retenciones=30000)
    datos = fr.generar(r, nif=NIF, nombre="Autonomo Prueba")
    assert datos.startswith(b"<T13002026" + b"2T0000><AUX>") and datos.endswith(b"</T130020262T0000>") and len(datos) == 328 + 600 + len("</T130020262T0000>")
    c = fr.leer_campos("130", datos)
    assert c[1] == "<T" and c[2] == "130" and c[3] == "01" and c[6] == "I" and c[7].strip() == NIF and c[10] == "2026" and c[11] == "2T" and c[36] == "</T13001000>"
    assert int(c[12]) == 1000000 and int(c[13]) == 400000 and int(c[14]) == 600000 and int(c[15]) == 120000 and int(c[16]) == 50000 and int(c[17]) == 30000 and int(c[18]) == 40000
    assert int(c[30]) == 40000 and c[31] == " " and c[32].strip() == ""
    neg = fr.leer_campos("130", fr.generar(_c(ingresos=100000, gastos=300000), nif=NIF, nombre="X"))
    assert neg[14].startswith("N") and int(neg[14][1:]) == 200000                                      # el rendimiento negativo lleva la N de signo
    a_deducir = _c(negativos_previos=0, pagos_previos=0, retenciones=0, ingresos=0, gastos=0)
    assert fr.leer_campos("130", fr.generar(a_deducir, nif=NIF, nombre="X"))[6] == "N"


def _despacho(nombre="Despacho 130", forma="persona_fisica"):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    u = db.crear_usuario_vinculado_a_kratos(f"{clave}@ejemplo.com", f"k-{clave}"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Autonomo Prueba", nif=NIF)
    fp.guardar_perfil(t, u, c, {"forma_juridica": forma}, vigente_desde="2026-01-01")
    return t, u, c


def test_con_los_apuntes_del_titular_acumulados_y_en_cadena():
    t, u, c = _despacho()
    fn.aprobar_apunte(t, u, c, venta(1000000, 2100, numero="1", fecha=date(2026, 2, 10)))                 # 1T: 10.000 € de ingresos
    fn.aprobar_apunte(t, u, c, compra(400000, 2100, numero="P-1", fecha=date(2026, 3, 5)))                # 1T: 4.000 € de gasto
    fn.aprobar_apunte(t, u, c, venta(500000, 2100, numero="2", fecha=date(2026, 5, 10)))                  # 2T: +5.000 €
    fn.aprobar_apunte(t, u, c, compra(100000, 2100, numero="P-2", fecha=date(2026, 5, 11), cuota_deducible=0))   # 2T: +1.000 € y el IVA no deducido (210 €) también es gasto
    fn.aprobar_apunte(t, u, c, compra(900000, 2100, numero="P-3", fecha=date(2026, 5, 12), bien_inversion=True))  # no es gasto: se amortiza
    uno = fn.calculo_130(t, u, c, 2026, "1T")
    assert uno["resultado"].casillas["01"] == 1000000 and uno["resultado"].casillas["02"] == 400000 and uno["resultado"].casillas["04"] == 120000 and uno["resultado"].casillas["19"] == 120000
    dos = fn.calculo_130(t, u, c, 2026, "2T")
    r = dos["resultado"]
    assert r.casillas["01"] == 1500000 and r.casillas["02"] == 400000 + 100000 + 21000 and r.casillas["05"] == 120000 and dos["calculados_de_los_anteriores"]
    assert r.casillas["04"] == (1500000 - 521000) * 20 // 100 and any("bienes de inversión" in a for a in r.avisos) and any("trimestres anteriores" in a for a in r.avisos)
    ajustado = fn.calculo_130(t, u, c, 2026, "2T", otros_gastos=100000, pagos_previos=100000)
    assert ajustado["resultado"].casillas["02"] == 521000 + 100000 and ajustado["resultado"].casillas["05"] == 100000 and not ajustado["calculados_de_los_anteriores"]


def test_una_sociedad_no_presenta_el_130_y_la_descarga_exige_aprobar_y_queda_en_auditoria():
    t, u, c = _despacho("Despacho 130 b", forma="sociedad")
    assert not fn.calculo_130(t, u, c, 2026, "1T")["resultado"].calculable
    with pytest.raises(fn.ErrorFiscal):
        fn.descargar_fichero_130(t, u, c, 2026, "1T")
    t, u, c = _despacho("Despacho 130 c")
    fn.aprobar_apunte(t, u, c, venta(100000, 2100, numero="1", fecha=date(2026, 2, 10)))
    datos, nombre = fn.descargar_fichero_130(t, u, c, 2026, "1T")
    assert nombre == "2026_1T_130_prueba.txt" and int(fr.leer_campos("130", datos)[18]) == 20000
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT count(*) FROM auditoria_eventos WHERE accion = 'fiscal.130.descargar'").fetchone()[0] == 1
    finally:
        conn.close()
    with pytest.raises(fn.ErrorFiscal):
        fn.calculo_130(t, u, c, 2026, "5T")
