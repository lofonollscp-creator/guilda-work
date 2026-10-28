"""Evidencias de la lectura con IA: contraste de cada cita con su valor, recuadros válidos, comprobaciones propias y lo que se guarda al leer una factura."""
import json
from datetime import date

import pytest

from app import facturas_contables as fc, lectura_facturas as lf
from app import lectura_evidencias as le
from tests.test_facturas_contables import _despacho
from tests.test_lectura_facturas import RESPUESTA, _borrador, modelo  # noqa: F401  (el fixture `modelo` se usa por nombre)


@pytest.mark.parametrize("campo, texto, valor, esperado", [
    ("total", "TOTAL FACTURA 1.210,00 EUR", "1210.00", True), ("total", "Total: 1,210.00", "1210.00", True), ("total", "Total 121,00", "1210.00", False),
    ("base", "Base imponible 100,00", "100.00", True), ("iva", "IVA 21% 21,00", "21.00", True), ("total", "sin cifras", "10.00", False),
    ("fecha", "Fecha: 14/08/2026", "2026-08-14", True), ("fecha", "14 de agosto de 2026", "2026-08-14", True), ("fecha", "14-08-26", "2026-08-14", True),
    ("fecha", "Fecha: 15/08/2026", "2026-08-14", False), ("fecha", "14/09/2026", "2026-08-14", False),
    ("numero", "Factura nº 2026/118", "2026/118", True), ("numero", "Factura nº 2026/119", "2026/118", False),
    ("emisor_nif", "CIF: B-87654321", "B87654321", True), ("emisor_nif", "CIF: B-87654322", "B87654321", False), ("numero", "algo", "", False)])
def test_la_cita_debe_contener_el_valor(campo, texto, valor, esperado):
    assert le.coherente(campo, texto, valor) is esperado


def test_los_recuadros_invalidos_se_descartan():
    assert le._caja([0.1, 0.2, 0.5, 0.3]) == [0.1, 0.2, 0.5, 0.3]
    for malo in (None, "x", [1], [0.1, 0.2, 0.3], [0.5, 0.5, 0.4, 0.6], [-0.1, 0, 0.5, 0.5], [0, 0, 1.5, 0.5], [0.1, 0.1, 0.1, 0.1], ["a", 0, 1, 1], [float("nan"), 0, 1, 1]):
        assert le._caja(malo) is None


def test_limpiar_ignora_lo_desconocido_y_marca_lo_incoherente():
    ev = le.limpiar({"numero": {"texto": "Nº 2026/118", "caja": [0.1, 0.1, 0.3, 0.15]}, "total": {"texto": "Total 99,00"}, "invento": {"texto": "x"}, "fecha": None, "base": "texto", "iva": {"texto": ""}},
                    {"numero": "2026/118", "total": "121.00", "base": "100.00", "iva": "21.00", "fecha": "2026-08-14"})
    assert set(ev) == {"numero", "total"} and ev["numero"]["coherente"] and ev["numero"]["caja"] and not ev["total"]["coherente"] and ev["total"]["caja"] is None
    assert le.limpiar("no es un dict", {}) == {} and le.limpiar(None, {}) == {}


def test_avisos_de_evidencia():
    ev = {"numero": {"texto": "x", "caja": None, "valor": "A-1", "coherente": False}, "fecha": {"texto": "14/08/2026", "caja": None, "valor": "2026-08-14", "coherente": True}}
    avisos = le.avisos_de_evidencia(ev, ("numero", "fecha", "total"))
    assert any("número de factura" in a and "A-1" in a for a in avisos) and any("Sin evidencia" in a and "total" in a for a in avisos)
    assert le.avisos_de_evidencia({}, ("numero", "fecha", "total")) == []                       # sin ninguna evidencia no se avisa


def test_comprobaciones_propias():
    v = le.verificaciones(nif_contraparte="B87654321", lineas=[{"base": "100.00", "pct_iva": "21", "cuota_iva": "25.00"}, {"base": "50.00", "pct_iva": "10", "cuota_iva": "5.00"}], fecha="2030-01-01", hoy=date(2026, 10, 28))
    assert any("dígito de control" in x for x in v) and any(x.startswith("Línea 1") for x in v) and not any(x.startswith("Línea 2") for x in v) and any("posterior a hoy" in x for x in v)
    assert le.verificaciones(nif_contraparte="A12345674", lineas=[{"base": "100.00", "pct_iva": "21", "cuota_iva": "21.00"}], fecha="2026-01-01", hoy=date(2026, 10, 28)) == []


EVIDENCIAS = {"numero": {"texto": "Factura 2026/118", "caja": [0.6, 0.05, 0.9, 0.1]}, "fecha": {"texto": "Fecha 14/08/2026", "caja": None}, "emisor_nif": {"texto": "CIF B87654321"},
              "total": {"texto": "TOTAL 121,00 €", "caja": [0.6, 0.8, 0.9, 0.85]}, "base": {"texto": "Base 100,00"}, "iva": {"texto": "IVA 21% 21,00"}}


def test_al_leer_se_guardan_las_evidencias_y_las_comprobaciones(modelo):  # noqa: F811
    t, u, c = _despacho()
    modelo.respuesta = json.dumps({**RESPUESTA, "evidencias": EVIDENCIAS})
    fid = _borrador(t, u, c)
    assert lf.leer(t, u, fid) == []
    ev = lf.evidencia_de(fc.obtener(t, u, fid))
    assert ev["campos"]["total"]["coherente"] and ev["campos"]["total"]["caja"] == [0.6, 0.8, 0.9, 0.85] and ev["campos"]["emisor_nif"]["valor"] == "B87654321"
    assert any("dígito de control" in x for x in ev["verificaciones"])                       # B87654321 no es un NIF con dígito válido
    assert "Sin evidencia" not in fc.obtener(t, u, fid)["notas"]
    assert "evidencias" in modelo.llamadas[0][0]


def test_una_cita_que_no_contiene_el_valor_deja_un_aviso_en_las_notas(modelo):  # noqa: F811
    t, u, c = _despacho()
    modelo.respuesta = json.dumps({**RESPUESTA, "evidencias": {**EVIDENCIAS, "total": {"texto": "TOTAL 99,00 €"}}})
    fid = _borrador(t, u, c)
    avisos = lf.leer(t, u, fid)
    assert any("total" in a and "no contiene el valor" in a for a in avisos) and "no contiene el valor" in fc.obtener(t, u, fid)["notas"]
    assert not lf.evidencia_de(fc.obtener(t, u, fid))["campos"]["total"]["coherente"]


def test_sin_evidencias_no_hay_avisos_pero_si_comprobaciones(modelo):  # noqa: F811
    t, u, c = _despacho()
    fid = _borrador(t, u, c)
    assert lf.leer(t, u, fid) == []
    ev = lf.evidencia_de(fc.obtener(t, u, fid))
    assert ev["campos"] == {} and ev["verificaciones"]


def test_un_numero_repetido_del_mismo_proveedor_se_avisa_como_duplicado(modelo):  # noqa: F811
    t, u, c = _despacho()
    primera = _borrador(t, u, c)
    lf.leer(t, u, primera)
    segunda = _borrador(t, u, c)
    lf.leer(t, u, segunda)
    assert any("duplicado" in x and str(primera) in x for x in lf.evidencia_de(fc.obtener(t, u, segunda))["verificaciones"])


def test_el_panel_y_la_imagen_en_linea_desde_la_web(cliente, modelo):  # noqa: F811
    from tests.test_facturas_contables import _web
    uid, t, c = _web(cliente, email="evidencias@ejemplo.com")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 120
    modelo.respuesta = json.dumps({**RESPUESTA, "evidencias": EVIDENCIAS})
    fid = fc.subir_archivos(t, uid, c, "recibida", [("f.png", "image/png", png)])[0]
    lf.leer(t, uid, fid)
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert 'id="evidencias-lectura"' in html and "Ver en la imagen" in html and f"/contabilidad/{fid}/imagen" in html and "TOTAL 121,00" in html and "Coincide" in html
    assert 'data-evidencia-ver="0.6,0.8,0.9,0.85"' in html
    r = cliente.get(f"/contabilidad/{fid}/imagen")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data == png and r.headers["X-Content-Type-Options"] == "nosniff" and "sandbox" in r.headers["Content-Security-Policy"]
    # un PDF no se sirve en línea y su panel no ofrece la imagen
    pdf = fc.subir_archivos(t, uid, c, "recibida", [("f.pdf", "application/pdf", b"%PDF-1.4 " + b"x" * 60)])[0]
    lf.leer(t, uid, pdf)
    assert cliente.get(f"/contabilidad/{pdf}/imagen").status_code == 404
    html = cliente.get(f"/contabilidad/{pdf}").get_data(as_text=True)
    assert 'id="evidencias-lectura"' in html and "data-evidencia-ver" not in html and "/imagen" not in html
    assert cliente.get("/contabilidad/999999/imagen").status_code == 404
