"""Pantalla de revisión de una factura con el documento a la vista junto a los datos (visor, confianza y revisión automática)."""
import io
import json
from pathlib import Path

from app import facturas_contables as fc, ia_asistente, ia_despacho, lectura_facturas as lf
from tests.test_facturas_contables import _web
from tests.test_lectura_pipeline import RESPUESTA, TEXTO_FACTURA, _facturae, _pdf_con_texto

CLIENTE_NIF = "B12345678"


def _factura_con(cliente, uid, t, c, nombre, mime, contenido, tipo="recibida"):
    return fc.subir_archivos(t, uid, c, tipo, [(nombre, mime, contenido)])[0]


def _leer_con_modelo(monkeypatch, respuesta=None):
    monkeypatch.setattr(lf, "configurada", lambda uid: True)
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda uid, s, p, timeout=90: json.dumps(respuesta or RESPUESTA))


def test_un_pdf_se_enseña_por_paginas_junto_a_los_datos_con_su_confianza(cliente, monkeypatch):
    uid, t, c = _web(cliente, "visor1@ejemplo.com")
    _leer_con_modelo(monkeypatch, {**RESPUESTA, "evidencias": {"numero": {"texto": "FACTURA Nº 2026/118", "caja": [0.1, 0.2, 0.5, 0.25]}, "total": {"texto": "TOTAL FACTURA: 121,00 EUR", "caja": [0.1, 0.8, 0.6, 0.85]}}})
    fid = _factura_con(cliente, uid, t, c, "f.pdf", "application/pdf", _pdf_con_texto(TEXTO_FACTURA))
    lf.leer(t, uid, fid)
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "data-visor-revision" in html and "con-documento" in html and f"/contabilidad/{fid}/pagina/1" in html and "data-visor-imagen" in html
    assert 'id="visor-evidencias"' in html and "0.1, 0.2, 0.5, 0.25" in html
    assert "confianza-alta" in html and "Fuente: texto del PDF" in html and "Leída con IA: falta tu revisión" in html
    assert 'data-evidencia-campo="numero"' in html and 'data-evidencia-campo="fecha"' in html and "Ver en el documento" in html
    assert 'src="/static/contabilidad_visor.js' in html or "contabilidad_visor.js" in html


def test_las_paginas_del_pdf_son_png_y_fuera_de_rango_es_404(cliente):
    uid, t, c = _web(cliente, "visor2@ejemplo.com")
    fid = _factura_con(cliente, uid, t, c, "f.pdf", "application/pdf", _pdf_con_texto(TEXTO_FACTURA))
    r = cliente.get(f"/contabilidad/{fid}/pagina/1")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert "private" in r.headers["Cache-Control"] and r.headers["X-Content-Type-Options"] == "nosniff" and "sandbox" in r.headers["Content-Security-Policy"]
    assert cliente.get(f"/contabilidad/{fid}/pagina/2").status_code == 404 and cliente.get(f"/contabilidad/{fid}/pagina/0").status_code == 404 and cliente.get("/contabilidad/99999/pagina/1").status_code == 404


def test_pdf_de_varias_paginas_enseña_los_controles_de_pagina(cliente):
    from pypdf import PdfWriter
    uid, t, c = _web(cliente, "visor3@ejemplo.com")
    w = PdfWriter()
    for _ in range(3):
        w.add_blank_page(300, 400)
    b = io.BytesIO(); w.write(b)
    fid = _factura_con(cliente, uid, t, c, "tres.pdf", "application/pdf", b.getvalue())
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert 'data-visor-pagina="1"' in html and "1 / 3" in html
    assert cliente.get(f"/contabilidad/{fid}/pagina/3").status_code == 200 and cliente.get(f"/contabilidad/{fid}/pagina/4").status_code == 404


def test_una_foto_se_enseña_con_la_ruta_de_imagen(cliente):
    from PIL import Image
    uid, t, c = _web(cliente, "visor4@ejemplo.com")
    b = io.BytesIO(); Image.new("RGB", (60, 40), "white").save(b, "PNG")
    fid = _factura_con(cliente, uid, t, c, "foto.png", "image/png", b.getvalue())
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert f"/contabilidad/{fid}/imagen" in html and "data-visor-pagina" not in html


def test_una_factura_electronica_xml_enseña_sus_datos_exactos_en_lugar_de_una_imagen(cliente):
    uid, t, c = _web(cliente, "visor5@ejemplo.com")
    fid = _factura_con(cliente, uid, t, c, "f.xml", "application/xml", _facturae())
    lf.leer(t, uid, fid)
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "Factura electrónica (XML)" in html and "Papelería Sol, S.L." in html and "data-visor-imagen" not in html and "Descargar el XML" in html
    assert "Leída de la factura electrónica (datos exactos)" in html and "Confianza 100" in html and "visor-evidencias" not in html
    assert 'name="numero" value="A-000123"' in html


def test_sin_archivo_no_hay_visor_y_la_pantalla_sigue_funcionando(cliente):
    uid, t, c = _web(cliente, "visor6@ejemplo.com")
    r = cliente.post("/contabilidad/nueva", data={"cliente_id": c, "tipo": "recibida", "fecha": "2026-08-14", "numero": "X-1", "tercero_nombre": "Proveedor", "base_0": "100,00", "pct_iva_0": "21"})
    assert r.status_code == 302
    fid = int(r.headers["Location"].rstrip("/").split("/")[-1])
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "data-visor-revision" in html and "con-documento" not in html and "data-visor-imagen" not in html


def test_una_revision_automatica_se_ve_marcada_y_se_puede_reabrir(cliente):
    uid, t, c = _web(cliente, "visor7@ejemplo.com")
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="auto", umbral_confianza=90, por=uid)
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})                       # sin la configuración de a3 una factura no se puede revisar
    fid = _factura_con(cliente, uid, t, c, "f.xml", "application/xml", _facturae())
    lf.leer(t, uid, fid)
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "Revisada automáticamente por la IA" in html and "Reabrir" in html
    assert cliente.post(f"/contabilidad/{fid}/estado", data={"estado": "pendiente"}).status_code == 302
    assert fc.obtener(t, uid, fid)["estado"] == "pendiente"


def test_el_boton_de_leer_se_activa_con_un_xml_aunque_no_haya_ia(cliente, monkeypatch):
    monkeypatch.setattr(lf, "configurada", lambda uid: False)
    uid, t, c = _web(cliente, "visor8@ejemplo.com")
    fid = _factura_con(cliente, uid, t, c, "f.xml", "application/xml", _facturae())
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    boton = html[html.index(f"/contabilidad/{fid}/leer"):][:400]
    assert "disabled" not in boton.split("</button>")[0]
    fid2 = _factura_con(cliente, uid, t, c, "g.pdf", "application/pdf", _pdf_con_texto(TEXTO_FACTURA))
    html2 = cliente.get(f"/contabilidad/{fid2}").get_data(as_text=True)
    assert "disabled" in html2[html2.index(f"/contabilidad/{fid2}/leer"):][:400].split("</button>")[0]
