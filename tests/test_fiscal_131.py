"""Modelo 131 (IRPF, estimación objetiva): casillas según las instrucciones oficiales, correspondencia con el diseño, fichero de prueba y pantalla."""
from datetime import date
from decimal import Decimal

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from app.fiscal_modelos import disenos_oficiales as d, fichero_131 as f131, motor_131 as m
from tests.conftest import iniciar_sesion_de_prueba
from tests.escenarios_303 import venta

NIF = "12345678Z"
IBAN = "ES91 2100 0418 4502 0005 1332"


def _a(rendimiento=1000000, asalariados=0, **kw):
    return {"epigrafe": "6421", "rendimiento_neto": rendimiento, "asalariados": asalariados, **kw}


def _c(**kw):
    base = dict(ejercicio=2026, periodo="2T", actividades=[_a()])
    base.update(kw)
    return m.calcular(**base)


def test_el_porcentaje_del_apartado_i_depende_del_personal_asalariado():
    for unidades, esperado in ((0, 200), (Decimal("0.01"), 300), (1, 300), (Decimal("1.01"), 400), (7, 400)):
        assert m.porcentaje_del_apartado_i(unidades) == esperado
    r = _c(actividades=[_a(1000000, 0), _a(500000, 1), _a(500000, "2.5")])
    assert [f["resultado"] for f in r.filas] == [20000, 15000, 20000]
    assert r.casillas["01"] == 2000000 and r.casillas["02"] == 55000 and r.casillas["07"] == 55000


def test_porcentaje_superior_si_nunca_inferior_y_ceuta_por_cero_coma_cuatro():
    assert _c(actividades=[_a(1000000, 0, superior=500)]).casillas["02"] == 50000
    assert not _c(actividades=[_a(1000000, 0, superior=150)]).calculable                      # inferior al 2 %
    assert _c(actividades=[_a(1000000, 0, ceuta_melilla=True)]).casillas["02"] == 8000        # 0,8 %
    assert _c(actividades=[_a(1000000, 2, ceuta_melilla=True)]).casillas["02"] == 16000       # 4 % x 0,4
    assert not _c(actividades=[_a(1000000, 0, ceuta_melilla=True, superior=50)]).calculable   # superior al normal pero inferior al reducido... (0,5 < 0,8)
    assert _c(actividades=[_a(1000000, 0, ceuta_melilla=True, superior=100)]).casillas["02"] == 10000


def test_apartados_ii_y_iii_y_total():
    r = _c(actividades=[], ventas_ii=200000, ingresos_iii=100000, ingresos_iii_prioritarias=100000, ingresos_iii_ceuta=100000)
    c = r.casillas
    assert c["03"] == 200000 and c["04"] == 4000 and c["05"] == 300000 and c["06"] == 2000 + 1500 + 800 and c["07"] == 4000 + 4300 and "01" not in c
    assert any("prioritarias" in a for a in r.avisos)
    assert _c(actividades=[], ventas_ii=200000, ceuta_ii=True).casillas["04"] == 1600
    assert not _c(actividades=[], ingresos_iii=1, superior_iii=100).calculable


def test_retenciones_minoracion_y_negativos_de_la_casilla_15():
    r = _c(retenciones=5000, rendimiento_anterior=950000, negativos_previos=1000)       # 02 = 200 €; 09 = 75 €
    c = r.casillas
    assert c["07"] == 20000 and c["08"] == 5000 and c["09"] == 7500 and c["10"] == 7500 and c["11"] == 1000 and c["13"] == 6500 == c["15"] and r.tipo_declaracion == "I"
    assert r.detalle["tramo_minoracion"] == "2"
    for anterior, esperado in ((None, 0), (900000, 10000), (900001, 7500), (1100000, 5000), (1200000, 2500), (1200001, 0)):
        assert _c(rendimiento_anterior=anterior).casillas.get("09", 0) == esperado
    assert [m.tramo_de_minoracion(x) for x in (None, 100, 900000, 950000, 1100000, 1200000, 1300000)] == ["0", "1", "1", "2", "3", "4", "0"]
    # lo que se deduce de trimestres anteriores nunca pasa de la casilla 10
    assert _c(negativos_previos=999999).casillas["11"] == 20000 and _c(negativos_previos=999999).casillas["15"] == 0 and _c(negativos_previos=999999).tipo_declaracion == "N"


def test_resultado_negativo_se_deduce_de_1t_a_3t_y_en_4t_es_negativa():
    sin_pagar = _c(retenciones=30000)                                          # 07 = 200 €, 08 = 300 €
    assert sin_pagar.casillas["10"] == -10000 == sin_pagar.casillas["13"] == sin_pagar.casillas["15"] and "11" not in sin_pagar.casillas
    assert sin_pagar.tipo_declaracion == "B" and _c(periodo="4T", retenciones=30000).tipo_declaracion == "N"
    assert _c(actividades=[]).tipo_declaracion == "N" and any("ninguna actividad" in a for a in _c(actividades=[]).avisos)


def test_importes_negativos_y_epigrafes_invalidos_bloquean():
    for kw in ({"retenciones": -1}, {"ventas_ii": -1}, {"ingresos_iii": -1}, {"negativos_previos": -1}, {"periodo": "5T"}, {"periodo": "05"}):
        assert not _c(**kw).calculable
    assert not _c(actividades=[_a(-1)]).calculable and not _c(actividades=[_a() | {"epigrafe": "12345"}]).calculable
    assert not _c(actividades=[_a()] * 6).calculable


def test_el_diseno_oficial_del_131_y_cada_casilla_va_a_su_campo():
    diseno = f131.cargar_diseno()
    assert d.comprobar(diseno) == []
    por_n = {c["n"]: c["descripcion"] for c in diseno["paginas"][1]["campos"]}
    esperado = {"01": 33, "02": 34, "03": 41, "04": 42, "05": 52, "06": 53, "07": 54, "08": 55, "09": 58, "10": 59, "11": 60, "12": 63, "13": 64, "14": 65, "15": 66}
    for casilla, campo in esperado.items():
        assert por_n[campo].rstrip().endswith(f"[{casilla}]"), (casilla, por_n[campo])
    assert "Epígrafe IAE" in por_n[f131.FILAS_ACTIVIDAD[0][0]] and "Epígrafe IAE" in por_n[f131.FILAS_ACTIVIDAD[4][0]] and "Actividad 5" in por_n[f131.FILAS_ACTIVIDAD[4][0]]
    assert "Porcentaje aplicable" in por_n[f131.FILAS_ACTIVIDAD[4][2]] and "Resultado aplicación" in por_n[f131.FILAS_ACTIVIDAD[4][3]]
    assert "Ceuta" in por_n[f131.CEUTA_II] and "Volumen de ventas" in por_n[f131.VENTAS_II] and "Ingresos de explotaciones prioritarias" in por_n[f131.INGRESOS_III["prioritarias"]]
    assert "ejercicio anterior" in por_n[f131.TRAMO_MINORACION]


def test_el_fichero_se_lee_de_vuelta_con_el_diseno():
    r = _c(actividades=[_a(1000000, 0), _a(500000, "1.5", epigrafe="6591")], ventas_ii=200000, ingresos_iii=100000, ingresos_iii_prioritarias=100000, retenciones=5000, rendimiento_anterior=950000, negativos_previos=1000)
    datos = f131.generar(r, nif=NIF, nombre="Autonomo Prueba", iban=IBAN)
    assert datos.startswith(b"<T13102026" + b"2T0000><AUX>") and datos.endswith(b"</T131020262T0000>")
    c = f131.leer_campos(datos)
    assert c[6] == "I" and c[7].strip() == NIF and c[10] == "2026" and c[11] == "2T" and c[71] == "</T13101000>"
    assert c[13] == "6421" and int(c[14]) == 1000000 and int(c[15]) == 200 and int(c[16]) == 20000 and c[17] == "6591" and int(c[19]) == 400 and int(c[20]) == 20000
    assert int(c[33]) == 1500000 and int(c[34]) == 40000 and c[35] == "2" and int(c[36]) == 200000 and int(c[41]) == 200000 and int(c[42]) == 4000
    assert int(c[43]) == 100000 and int(c[44]) == 100000 and int(c[52]) == 200000 and int(c[53]) == 3500 and int(c[54]) == 47500 and int(c[55]) == 5000
    assert c[56] == "2" and int(c[58]) == 7500 and int(c[59]) == 35000 and int(c[60]) == 1000 and int(c[64]) == 34000 and int(c[66]) == 34000
    assert "ES9121000418450200051332" in datos.decode("iso-8859-15")
    sin_iban = f131.generar(r, nif=NIF, nombre="X")
    assert "</T131DID00>" not in sin_iban.decode("iso-8859-15")
    with pytest.raises(f131.FicheroNoGenerable):
        f131.generar(r, nif=NIF, nombre="X", iban="ES00 1234")
    with pytest.raises(f131.FicheroNoGenerable):
        f131.generar(_c(retenciones=-1), nif=NIF, nombre="X")
    negativo = f131.leer_campos(f131.generar(_c(retenciones=30000), nif=NIF, nombre="X"))
    assert negativo[6] == "B" and negativo[59].startswith("N") and int(negativo[59][1:]) == 10000 and negativo[66].startswith("N")


def _despacho(nombre="Despacho 131", forma="persona_fisica"):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    u = db.crear_usuario_vinculado_a_kratos(f"{clave}@ejemplo.com", f"k-{clave}"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Autonomo Prueba", nif=NIF)
    fp.guardar_perfil(t, u, c, {"forma_juridica": forma}, vigente_desde="2026-01-01")
    return t, u, c


def test_en_el_nucleo_las_retenciones_salen_del_trimestre_y_la_descarga_queda_en_auditoria():
    t, u, c = _despacho()
    fn.aprobar_apunte(t, u, c, venta(1000000, 2100, numero="1", fecha=date(2026, 2, 10)))
    fn.aprobar_apunte(t, u, c, venta(500000, 2100, numero="2", fecha=date(2026, 5, 10)))
    uno = fn.calculo_131(t, u, c, 2026, "1T", actividades=[_a()], retenciones_a_mano=1000)
    assert uno["sugerencias"]["ingresos"] == 1000000 and uno["resultado"].casillas["08"] == 1000
    dos = fn.calculo_131(t, u, c, 2026, "2T", actividades=[_a()])
    assert dos["sugerencias"]["ingresos"] == 500000 and dos["resultado"].casillas["02"] == 20000
    datos, nombre = fn.descargar_fichero_131(t, u, c, 2026, "2T", actividades=[_a()], iban=IBAN)
    assert nombre == "2026_2T_131_prueba.txt" and int(f131.leer_campos(datos)[34]) == 20000
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT count(*) FROM auditoria_eventos WHERE accion = 'fiscal.131.descargar'").fetchone()[0] == 1
    finally:
        conn.close()
    with pytest.raises(fn.ErrorFiscal):
        fn.calculo_131(t, u, c, 2026, "5T")
    with pytest.raises(fn.ErrorFiscal):
        fn.descargar_fichero_131(t, u, c, 2026, "2T", actividades=[_a(-1)])


def test_una_sociedad_no_presenta_el_131():
    t, u, c = _despacho("Despacho 131 b", forma="sociedad")
    assert not fn.calculo_131(t, u, c, 2026, "1T", actividades=[_a()])["resultado"].calculable
    with pytest.raises(fn.ErrorFiscal):
        fn.descargar_fichero_131(t, u, c, 2026, "1T", actividades=[_a()])


def test_modelo_131_desde_la_ficha(cliente):
    from app import verticales
    uid = iniciar_sesion_de_prueba(cliente, "m131web@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho m131web")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True); verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Autonomo Web", nif=NIF)
    fp.guardar_perfil(t, uid, c, {"forma_juridica": "persona_fisica"}, vigente_desde="2026-01-01")
    assert "Modelo 131 (IRPF, módulos)" in cliente.get(f"/guilda-fiscal/{c}?p_ejercicio=2026&p_periodo=1T").get_data(as_text=True)
    vacio = cliente.get(f"/guilda-fiscal/{c}/131?ejercicio=2026&periodo=1T").get_data(as_text=True)
    assert 'name="epigrafe_1"' in vacio and 'id="calculo-131"' not in vacio
    consulta = "ejercicio=2026&periodo=1T&epigrafe_1=6421&rendimiento_1=10000,00&asalariados_1=0&otras_retenciones=50,00"
    html = cliente.get(f"/guilda-fiscal/{c}/131?{consulta}").get_data(as_text=True)
    assert 'id="calculo-131"' in html and "150,00 €" in html and "Descargar el fichero de prueba del modelo 131" in html
    assert 'class="fiscal-resultado-cifra">150,00 €' in html and f"/guilda-fiscal/{c}/131?ejercicio=2026&amp;periodo=2T" in html
    r = cliente.get(f"/guilda-fiscal/{c}/131/fichero?{consulta}&iban=ES91+2100+0418+4502+0005+1332")
    assert r.status_code == 200 and "2026_1T_131_prueba.txt" in r.headers["Content-Disposition"] and int(f131.leer_campos(r.data)[59]) == 15000
    mal = cliente.get(f"/guilda-fiscal/{c}/131?ejercicio=2026&periodo=1T&epigrafe_1=6421&rendimiento_1=abc").get_data(as_text=True)
    assert 'id="calculo-131"' not in mal
    assert cliente.get(f"/guilda-fiscal/{c}/131/fichero?ejercicio=2026&periodo=9T").status_code == 404
