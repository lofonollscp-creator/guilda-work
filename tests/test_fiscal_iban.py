"""IBAN del 303: validación, página DID del fichero y obligatoriedad cuando la declaración sale a devolver o es una rectificativa con casilla 111 (Nota 3 del diseño oficial)."""
import json
from datetime import date

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from app.fiscal_modelos import exportador_303 as ex, fichero_303, iban, motor_303
from tests.escenarios_303 import ESCENARIOS, compra, venta

NIF = "A12345674"
CUENTA = "ES91 2100 0418 4502 0005 1332"
JUSTIFICANTE = "3030000000123"


def test_validacion_del_iban():
    assert iban.validar(CUENTA) == "ES9121000418450200051332" and iban.validar("de89 3704 0044 0532 0130 00") == "DE89370400440532013000"
    for malo, parte in (("ES9121000418450200051333", "control"), ("ES91210004184502000513", "tiene 22"), ("US64SVBKUS6S3300958879", "no está entre"), ("1234", "empezar por dos letras"), ("", "empezar")):
        with pytest.raises(iban.IbanNoValido, match=parte):
            iban.validar(malo)
    assert iban.marca_sepa(CUENTA) == "1" and iban.marca_sepa("DE89370400440532013000") == "2"


def _octubre():
    return [venta(1000, fecha=date(2026, 10, 5)), compra(50000, fecha=date(2026, 10, 6))]


def test_la_pagina_did_del_fichero_lleva_la_cuenta_y_la_marca_sepa():
    diseno = json.loads(ex.DISENO_303_2026.read_text())
    r = motor_303.calcular(_octubre(), ejercicio=2026, periodo="4T", destino_negativo="D")
    sin = fichero_303.generar(r, nif=NIF, nombre="Empresa SL")
    con = fichero_303.generar(r, nif=NIF, nombre="Empresa SL", iban=CUENTA)
    assert len(sin) == len(con)
    pagina = next(p for p in ex.descomponer(diseno, con)["paginas"] if p["hoja"] == "DP303DID")["campos"]
    assert pagina[6].strip() == "ES9121000418450200051332" and pagina[11] == "1"
    assert next(p for p in ex.descomponer(diseno, sin)["paginas"] if p["hoja"] == "DP303DID")["campos"][6].strip() == ""
    de = next(p for p in ex.descomponer(diseno, fichero_303.generar(r, nif=NIF, nombre="Empresa SL", iban="DE89370400440532013000"))["paginas"] if p["hoja"] == "DP303DID")["campos"]
    assert de[11] == "2"
    with pytest.raises(fichero_303.FicheroNoGenerable, match="IBAN"):
        fichero_303.generar(r, nif=NIF, nombre="Empresa SL", iban="ES9121000418450200051333")


def _despacho(nombre="Despacho iban"):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    u = db.crear_usuario_vinculado_a_kratos(f"{clave}@ejemplo.com", f"k-{clave}"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif=NIF)
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    return t, u, c


def _revisada(t, u, c, apuntes, destino="C", periodo="2T"):
    for a in apuntes:
        fn.aprobar_apunte(t, u, c, a)
    inst = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo=periodo)
    dec = fn.calcular_declaracion(t, u, inst["id"], destino_negativo=destino)
    return fn.revisar_declaracion(t, u, dec["id"])


def test_a_devolver_no_se_genera_el_fichero_sin_iban_y_con_iban_la_cuenta_va_en_el_fichero():
    t, u, c = _despacho()
    d = _revisada(t, u, c, _octubre(), destino="D", periodo="4T")
    assert d["tipo_declaracion"] == "D" and fn.necesita_iban(d)
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.exportar_declaracion(t, u, d["id"])
    assert e.value.codigo == "iban_necesario"
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.guardar_iban(t, u, d["id"], "ES9121000418450200051333")
    assert e.value.codigo == "invalido"
    assert fn.guardar_iban(t, u, d["id"], CUENTA)["iban"] == "ES9121000418450200051332"
    assert fn.iban_reciente(t, u, c) == "ES9121000418450200051332"
    exportada = fn.exportar_declaracion(t, u, d["id"])
    fichero, _ = fn.descargar_artefacto(t, u, exportada["id"], "303")
    pagina = next(p for p in ex.descomponer(json.loads(ex.DISENO_303_2026.read_text()), fichero)["paginas"] if p["hoja"] == "DP303DID")["campos"]
    assert pagina[6].strip() == "ES9121000418450200051332"
    with pytest.raises(fn.ErrorFiscal) as e:                                      # exportada: ya no cambia
        fn.guardar_iban(t, u, d["id"], "")
    assert e.value.codigo == "estado_invalido"


def test_un_resultado_a_compensar_no_necesita_iban_y_una_rectificativa_con_111_si():
    t, u, c = _despacho("Despacho iban 2")
    d = _revisada(t, u, c, [venta(1000), compra(50000)])
    assert d["tipo_declaracion"] == "C" and not fn.necesita_iban(d)
    fn.exportar_declaracion(t, u, d["id"])                                        # sin iban: compensar no lo pide
    t, u, c = _despacho("Despacho iban 3")
    for a in ESCENARIOS["basico"][0]:
        fn.aprobar_apunte(t, u, c, a)
    inst = fn.crear_instantanea(t, u, c, ejercicio=2026, periodo="2T")
    original = fn.calcular_declaracion(t, u, inst["id"]); fn.revisar_declaracion(t, u, original["id"]); fn.exportar_declaracion(t, u, original["id"]); fn.marcar_presentada(t, u, original["id"], JUSTIFICANTE)
    fn.aprobar_apunte(t, u, c, compra(40000, numero="P-9"))                       # el trimestre pasa a favor: la casilla 111 recoge los 10,50 € que constaban a ingresar
    rect = fn.rectificar_declaracion(t, u, original["id"], justificante=JUSTIFICANTE)
    assert rect["casillas"]["111"] == 1050 and rect["tipo_declaracion"] == "C" and fn.necesita_iban(rect)
    fn.revisar_declaracion(t, u, rect["id"])
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.exportar_declaracion(t, u, rect["id"])
    assert e.value.codigo == "iban_necesario" and "111" in str(e.value)
    fn.guardar_iban(t, u, rect["id"], CUENTA)
    assert fn.exportar_declaracion(t, u, rect["id"])["estado"] == "exportada"


def test_la_devolucion_solo_se_admite_en_el_ultimo_periodo():
    """Regla de la AEAT (error 30260 del simulador: «No se permite la devolución excepto en el último período»): en el resto se compensa."""
    for periodo, mes, ok in (("2T", 5, False), ("4T", 10, True), ("05", 5, False), ("12", 12, True)):
        r = motor_303.calcular([compra(5000, fecha=date(2026, mes, 3))], ejercicio=2026, periodo=periodo, destino_negativo="D")
        assert r.calculable is ok, (periodo, r.bloqueos)
        if not ok:
            assert "último periodo" in r.bloqueos[0]
    r = motor_303.calcular([compra(5000)], ejercicio=2026, periodo="2T", destino_negativo="C")
    assert r.calculable and r.tipo_declaracion == "C"
    # la rectificativa también
    r = motor_303.Resultado303(2026, "2T", casillas={"69": -3150, "71": -3150})
    motor_303.aplicar_rectificativa(r, {"69": 1050}, destino_negativo="D")
    assert not r.calculable and "último periodo" in r.bloqueos[0]
