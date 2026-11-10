"""Controles previos de una factura (app/facturas_control.py): duplicados, NIF, numeración, fechas e intracomunitarias."""
from datetime import date

import pytest

from app import db, facturas_contables as fc, facturas_control as ctl
from tests.test_facturas_contables import LINEA, _datos, _despacho


@pytest.mark.parametrize("nif,esperado", [("12345678Z", True), ("12345678A", False), ("X1234567L", True), ("X1234567A", False), ("A58818501", True), ("A58818502", False), ("FR12345678901", None), ("", None)])
def test_nif_espanol(nif, esperado):
    assert ctl.nif_espanol_valido(nif) is esperado


def test_nif_ue_con_formato():
    assert ctl.nif_ue_con_formato("FR12345678901") is True and ctl.nif_ue_con_formato("DE123456789") is True
    assert ctl.nif_ue_con_formato("XX123") is False and ctl.nif_ue_con_formato("") is None


def test_vies_contesta_y_no_contesta():
    class R:
        def __init__(self, t): self.t = t
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.t.encode()
    assert ctl.comprobar_vies("FR12345678901", abrir=lambda *a, **k: R('{"valid": true, "name": "ACME SA", "address": "---"}')) == {"valido": True, "nombre": "ACME SA", "direccion": "", "error": ""}
    assert ctl.comprobar_vies("DE123456789", abrir=lambda *a, **k: R('{"valid": false}'))["valido"] is False

    def caido(*a, **k): raise OSError("sin red")
    assert ctl.comprobar_vies("DE123456789", abrir=caido)["valido"] is None
    assert ctl.comprobar_vies("12345678Z")["valido"] is None


def test_duplicados_por_numero_importe_y_sin_nif():
    t, u, c = _despacho()
    a = fc.crear(t, u, c, _datos(numero="F-9"), [LINEA])
    b = fc.crear(t, u, c, _datos(numero="f-9"), [LINEA])
    d = fc.crear(t, u, c, _datos(numero="F-10", fecha="2026-08-17"), [LINEA])
    assert [x["motivo"] for x in ctl.duplicados(t, fc.obtener(t, u, b)) if x["id"] == a] == ["mismo número"]
    assert [x["motivo"] for x in ctl.duplicados(t, fc.obtener(t, u, d)) if x["id"] == a] == ["mismo importe y fecha"]


def test_un_abono_no_es_duplicado_de_su_factura():
    t, u, c = _despacho()
    a = fc.crear(t, u, c, _datos(numero="F-5"), [LINEA])
    ab = fc.crear(t, u, c, _datos(numero="F-5", abono="1", rectifica_numero="F-5", rectifica_fecha="2026-08-15"), [LINEA])
    assert ctl.duplicados(t, fc.obtener(t, u, ab)) == [] and a


def test_revisar_una_copia_pide_confirmar():
    t, u, c = _despacho()
    a = fc.crear(t, u, c, _datos(numero="F-7"), [LINEA]); fc.cambiar_estado(t, u, a, "revisada")
    b = fc.crear(t, u, c, _datos(numero="F-7"), [LINEA])
    with pytest.raises(ValueError, match="repetida"):
        fc.cambiar_estado(t, u, b, "revisada")
    fc.cambiar_estado(t, u, b, "revisada", confirmar_duplicado=True)
    assert fc.obtener(t, u, b)["estado"] == "revisada"


def test_avisos_de_nif_fecha_total_y_propio():
    t, u, c = _despacho()
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(tercero_nif="12345678A", fecha="2020-01-01"), [LINEA]))
    texto = " ".join(ctl.avisos(t, f, hoy=date(2026, 8, 20)))
    assert "dígito de control" in texto and "más de 4 años" in texto
    propio = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="P-1", tercero_nif="B12345678"), [LINEA]))
    assert "del propio titular" in " ".join(ctl.avisos(t, propio, hoy=date(2026, 8, 20)))
    futura = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="P-2", fecha="2026-12-01"), [LINEA]))
    assert "futura" in " ".join(ctl.avisos(t, futura, hoy=date(2026, 8, 20)))


def test_aviso_de_hueco_en_la_numeracion_de_emitidas():
    t, u, c = _despacho()
    base = {"tipo": "emitida", "tercero_nombre": "Cliente A", "tercero_nif": "B87654321", "concepto": "Servicio"}
    fc.crear(t, u, c, {**base, "fecha": "2026-08-01", "numero": "2026-001"}, [LINEA])
    fc.crear(t, u, c, {**base, "fecha": "2026-08-02", "numero": "2026-002"}, [LINEA])
    f4 = fc.obtener(t, u, fc.crear(t, u, c, {**base, "fecha": "2026-08-04", "numero": "2026-004"}, [LINEA]))
    assert any("falta la factura 2026-003" in a for a in ctl.avisos(t, f4, hoy=date(2026, 8, 20)) if "numeración" in a)
    f3 = fc.obtener(t, u, fc.crear(t, u, c, {**base, "fecha": "2026-08-03", "numero": "2026-003"}, [LINEA]))
    assert not any("numeración" in a for a in ctl.avisos(t, fc.obtener(t, u, f4["id"]), hoy=date(2026, 8, 20)))
    assert not any("numeración" in a for a in ctl.avisos(t, f3, hoy=date(2026, 8, 20)))


def test_aviso_intracomunitaria_sin_nif_ue():
    t, u, c = _despacho()
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="I-1", tercero_nif="B87654321"), [{**LINEA, "pct_iva": "0", "subtipo": "03"}]))
    assert any("intracomunitaria" in a for a in ctl.avisos(t, f, hoy=date(2026, 8, 20)))
