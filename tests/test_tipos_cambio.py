"""Facturas en otra divisa: cambio del BCE y conversión a euros (app/tipos_cambio.py y su uso en la lectura)."""
from decimal import Decimal

import pytest

from app import lectura_facturas as lf, tipos_cambio as tc

CSV = "KEY,FREQ,CURRENCY,TIME_PERIOD,OBS_VALUE\nEXR.D.USD.EUR.SP00.A,D,USD,2026-02-26,1.2000\nEXR.D.USD.EUR.SP00.A,D,USD,2026-02-27,1.2500\n"


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    tc._cache.clear()
    monkeypatch.setattr(tc, "_descargar", lambda url: CSV)
    yield
    tc._cache.clear()


def test_el_cambio_es_el_del_dia_o_el_ultimo_anterior():
    assert tc.cambio("usd", "2026-02-27") == (Decimal("1.25"), "2026-02-27")
    assert tc.cambio("USD", "2026-03-01") == (Decimal("1.25"), "2026-02-27")             # domingo: vale el viernes
    assert tc.cambio("USD", "2026-02-20") is None                                         # antes de lo que devuelve el servicio
    assert tc.cambio("EUR", "2026-02-27") is None and tc.cambio("dolar", "2026-02-27") is None and tc.cambio("USD", "ayer") is None


def test_sin_respuesta_no_hay_cambio_y_no_se_queda_en_la_cache(monkeypatch):
    def falla(url):
        raise OSError("sin red")
    monkeypatch.setattr(tc, "_descargar", falla)
    assert tc.cambio("USD", "2026-02-27") is None
    monkeypatch.setattr(tc, "_descargar", lambda url: CSV)
    assert tc.cambio("USD", "2026-02-27") == (Decimal("1.25"), "2026-02-27")


def test_convertir_pasa_a_euros_y_lo_cuenta():
    datos = {"moneda": "USD", "fecha": "2026-02-27", "total": 1250, "suplidos": None, "lineas": [{"base": 1000, "pct_iva": 0, "cuota_iva": None}, {"base": "250,00", "pct_iva": 0}]}
    aviso = tc.convertir(datos)
    assert datos["moneda"] == "EUR" and datos["total"] == "1000.00" and [l["base"] for l in datos["lineas"]] == ["800.00", "200.00"] and datos["suplidos"] is None
    assert "1 EUR = 1.25 USD" in aviso and "1250 USD" in aviso and "2026-02-27" in aviso


def test_en_euros_o_sin_cambio_no_se_toca_nada(monkeypatch):
    datos = {"moneda": "EUR", "fecha": "2026-02-27", "total": 10, "lineas": [{"base": 10}]}
    assert tc.convertir(datos) is None and datos["total"] == 10
    monkeypatch.setattr(tc, "_descargar", lambda url: "")
    datos = {"moneda": "CHF", "fecha": "2026-02-27", "total": 10, "lineas": [{"base": 10}]}
    assert tc.convertir(datos) is None and datos["total"] == 10 and datos["moneda"] == "CHF"


def test_la_lectura_de_una_factura_en_dolares_sale_en_euros_y_cuadra():
    f = {"tipo": "recibida", "tercero_nombre": "X", "tercero_nif": "", "numero": "1", "fecha": "2026-02-27"}
    modelo = {"emisor_nif": "A58818501", "receptor_nif": "", "numero": "7", "fecha": "2026-02-27", "moneda": "USD", "total": 1250, "lineas": [{"base": 1250, "pct_iva": 0, "cuota_iva": 0}]}
    r = lf._procesar(modelo, f, "", "", None)
    assert r["lineas"][0]["base"] == "1000.00" and r["valores"]["total"] == "1000.00" and lf._cuadra(r["lineas"], "", r["valores"]["total"])
    assert any("pasado a euros" in a for a in r["avisos"]) and not any("Conviértelos" in a for a in r["avisos"])
    assert modelo["lineas"][0]["base"] == 1250 and modelo["moneda"] == "USD"                # lo que devolvió el modelo no se modifica


def test_si_el_bce_no_contesta_sigue_el_aviso_de_siempre(monkeypatch):
    monkeypatch.setattr(tc, "_descargar", lambda url: "")
    f = {"tipo": "recibida", "tercero_nombre": "X", "tercero_nif": "", "numero": "1", "fecha": "2026-02-27"}
    r = lf._procesar({"emisor_nif": "", "receptor_nif": "", "numero": "7", "fecha": "2026-02-27", "moneda": "USD", "total": 1250, "lineas": [{"base": 1250, "pct_iva": 0, "cuota_iva": 0}]}, f, "", "", None)
    assert r["lineas"][0]["base"] == "1250.00" and any("Conviértelos" in a for a in r["avisos"])
