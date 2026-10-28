"""Anotar que un 303 se presentó fuera de Guilda Work: el justificante de 13 cifras, el CSV, la referencia antigua libre y el justificante añadido después, que además sirve para rectificar."""
from datetime import date

import pytest

from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from tests.escenarios_303 import ESCENARIOS, venta

NIF = "A12345674"
J1, J2 = "3030000000123", "3030000000456"


def _despacho(nombre="Despacho presentacion"):
    t = db.crear_tenant(nombre)
    clave = nombre.replace(" ", "").lower()
    u = db.crear_usuario_vinculado_a_kratos(f"{clave}@ejemplo.com", f"k-{clave}"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif=NIF)
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    for a in ESCENARIOS["basico"][0]:
        fn.aprobar_apunte(t, u, c, a)
    return t, u, c


def _exportada(t, u, c, periodo="2T"):
    dec = fn.calcular_declaracion(t, u, fn.crear_instantanea(t, u, c, ejercicio=2026, periodo=periodo)["id"])
    fn.revisar_declaracion(t, u, dec["id"])
    return fn.exportar_declaracion(t, u, dec["id"])


def test_el_justificante_tiene_13_cifras_y_el_csv_se_guarda_aparte():
    t, u, c = _despacho()
    dec = _exportada(t, u, c)
    for malo in ("123", "30300000001AB", "30300000001234"):
        with pytest.raises(fn.ErrorFiscal):
            fn.marcar_presentada(t, u, dec["id"], justificante=malo)
    with pytest.raises(fn.ErrorFiscal):
        fn.marcar_presentada(t, u, dec["id"], justificante=J1, csv="corto")
    assert fn.obtener_declaracion(t, u, dec["id"])["estado"] == "exportada"                  # nada se anotó a medias
    hecha = fn.marcar_presentada(t, u, dec["id"], justificante=J1, csv="abcd 1234 efgh 5678")
    assert hecha["estado"] == "presentada" and hecha["referencia_presentacion"] == f"justificante {J1} · CSV ABCD1234EFGH5678" and fn.justificante_de(hecha) == J1


def test_la_referencia_libre_antigua_se_conserva_y_un_justificante_no_se_repite():
    t, u, c = _despacho("Despacho presentacion 2")
    dec = _exportada(t, u, c)
    assert fn.marcar_presentada(t, u, dec["id"], "CSV ABC123")["referencia_presentacion"] == "CSV ABC123"
    assert fn.justificante_de(fn.obtener_declaracion(t, u, dec["id"])) is None
    fn.aprobar_apunte(t, u, c, venta(5000, 2100, numero="9", fecha=date(2026, 8, 10)))
    otra = _exportada(t, u, c, "3T")
    fn.anotar_justificante(t, u, dec["id"], justificante=J1)
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.marcar_presentada(t, u, otra["id"], justificante=J1)
    assert "ya está anotado" in str(e.value)
    assert fn.marcar_presentada(t, u, otra["id"], justificante=J2)["referencia_presentacion"] == f"justificante {J2}"


def test_anotar_el_justificante_despues_permite_rectificar_sin_teclearlo():
    t, u, c = _despacho("Despacho presentacion 3")
    dec = _exportada(t, u, c)
    fn.marcar_presentada(t, u, dec["id"], "CSV ABC123")
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.rectificar_declaracion(t, u, dec["id"], justificante="")
    assert e.value.codigo == "invalido"
    hecha = fn.anotar_justificante(t, u, dec["id"], justificante=J1, csv="ABCDEF1234567890")
    assert hecha["referencia_presentacion"] == f"justificante {J1} · CSV ABCDEF1234567890"
    fn.aprobar_apunte(t, u, c, venta(10000, 2100, numero="2", fecha=date(2026, 5, 20)))
    rect = fn.rectificar_declaracion(t, u, dec["id"], justificante="")                       # usa el anotado
    assert rect["justificante_anterior"] == J1
    # completar solo el CSV conserva el justificante
    assert J1 in fn.anotar_justificante(t, u, dec["id"], csv="ZZZZZZZZ99999999")["referencia_presentacion"]


def test_solo_se_anota_el_justificante_de_una_presentada_y_con_algo_que_anotar():
    t, u, c = _despacho("Despacho presentacion 4")
    dec = _exportada(t, u, c)
    with pytest.raises(fn.ErrorFiscal) as e:
        fn.anotar_justificante(t, u, dec["id"], justificante=J1)
    assert e.value.codigo == "estado_invalido"
    fn.marcar_presentada(t, u, dec["id"], justificante=J1)
    with pytest.raises(fn.ErrorFiscal):
        fn.anotar_justificante(t, u, dec["id"])
