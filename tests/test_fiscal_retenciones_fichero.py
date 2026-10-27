"""Ficheros de los modelos 111 y 115 con los diseños de registro oficiales de la AEAT: coherencia del diseño, correspondencia casilla-campo y lectura de vuelta de lo generado."""
from datetime import date

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from app.fiscal_modelos import disenos_oficiales as d, fichero_retenciones as fr, motor_retenciones as mr
from tests.escenarios_303 import compra

NIF = "A12345674"


def _calc(modelo, retenciones, periodo="2T", a_deducir=0):
    return mr.calcular(retenciones, modelo=modelo, ejercicio=2026, periodo=periodo, a_deducir=a_deducir)


@pytest.mark.parametrize("modelo, total", [("111", 1000), ("115", 500)])
def test_los_disenos_oficiales_son_coherentes(modelo, total):
    diseno = fr.cargar_diseno(modelo)
    assert d.comprobar(diseno) == []
    assert diseno["paginas"][1]["total_posiciones"] == total


def test_cada_casilla_va_al_campo_que_dice_el_diseno():
    for modelo, esperadas in fr.DESCRIPCION_ESPERADA.items():
        diseno = fr.cargar_diseno(modelo)
        por_n = {c["n"]: c["descripcion"] for c in diseno["paginas"][1]["campos"]}
        for casilla, texto in esperadas.items():
            n = fr._campo_111(casilla) if modelo == "111" else fr.CAMPO_115[casilla]
            assert texto in por_n[n], (modelo, casilla, n, por_n[n])


def test_fichero_111_con_actividades_y_trabajo():
    ret = [mr.Retencion("111", "G", 100000, 15000, "12345678Z"), mr.Retencion("111", "G", 50000, 7500, "B87654321"), mr.Retencion("111", "A", 200000, 20000, "87654321X")]
    r = _calc("111", ret, a_deducir=1000)
    assert r.calculable, r.bloqueos
    datos = fr.generar(r, nif=NIF, nombre="Empresa de prueba SL")
    assert datos.startswith(b"<T11102026" + b"2T0000><AUX>") and datos.endswith(b"</T111020262T0000>")
    assert len(datos) == 328 + 1000 + len("</T111020262T0000>")
    c = fr.leer_campos("111", datos)
    assert c[1] == "<T" and c[2] == "111" and c[3] == "01" and c[4] == "000>" and c[6] == "I" and c[7].strip() == NIF and c[8].strip() == "EMPRESA DE PRUEBA SL" and c[10] == "2026" and c[11] == "2T"
    assert int(c[18]) == 2 and int(c[19]) == 150000 and int(c[20]) == 22500           # actividades económicas: 2 perceptores, 1.500,00 € de percepciones, 225,00 € de retenciones
    assert int(c[12]) == 1 and int(c[13]) == 200000 and int(c[14]) == 20000           # trabajo
    assert int(c[39]) == 42500 and int(c[40]) == 1000 and int(c[41]) == 41500 and c[48] == "</T11101000>"
    assert c[42] == " " and c[43].strip() == ""                                      # no es complementaria


def test_fichero_115_y_resultado_cero():
    r = _calc("115", [mr.Retencion("115", "", 60000, 11400, "B11111111")])
    c = fr.leer_campos("115", fr.generar(r, nif=NIF, nombre="Empresa SL"))
    assert c[6] == "I" and int(c[12]) == 1 and int(c[13]) == 60000 and int(c[14]) == 11400 and int(c[16]) == 11400 and c[22] == "</T11501000>"
    cero = _calc("115", [mr.Retencion("115", "", 60000, 11400, "B11111111")], a_deducir=11400)
    assert fr.leer_campos("115", fr.generar(cero, nif=NIF, nombre="Empresa SL"))[6] == "N"


def test_un_calculo_bloqueado_no_genera_fichero():
    r = _calc("111", [mr.Retencion("111", "Z", 1000, 150, "A")])
    with pytest.raises(fr.FicheroNoGenerable):
        fr.generar(r, nif=NIF, nombre="X")


def _despacho(nombre="Despacho retenciones"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos("retfichero@ejemplo.com", "k-retfichero"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif=NIF)
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    return t, u, c


def test_descarga_desde_el_nucleo_con_auditoria_y_sin_retenciones():
    t, u, c = _despacho()
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.descargar_fichero_retenciones(t, u, c, "111", 2026, "2T")
    assert e.value.codigo == "sin_datos"
    fn.aprobar_apunte(t, u, c, compra(100000, 2100, numero="P-1"), retencion={"modelo": "111", "clave": "G", "base": 100000, "pct": 1500})
    datos, nombre = fn.descargar_fichero_retenciones(t, u, c, "111", 2026, "2T")
    assert nombre == "2026_2T_111_prueba.txt" and int(fr.leer_campos("111", datos)[20]) == 15000
    with pytest.raises(fn.ErrorFiscal):
        fn.descargar_fichero_retenciones(t, u, c, "115", 2026, "2T")                  # no hay del 115
    with pytest.raises(fn.ErrorFiscal):
        fn.descargar_fichero_retenciones(t, u, c, "190", 2026, "2T")
