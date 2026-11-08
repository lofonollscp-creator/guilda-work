"""Pantalla de revisión de una factura: el documento junto a los datos, con páginas, zoom y el recuadro de lo que leyó la IA (R4)."""
import io
import json

from app import db, facturas_contables as fc, verticales
from tests.test_lectura_pipeline import TEXTO_FACTURA, _pdf_con_texto


def _pdf_de_tres_paginas() -> bytes:
    from pypdf import PdfReader, PdfWriter
    base = PdfReader(io.BytesIO(_pdf_con_texto(TEXTO_FACTURA)))
    w = PdfWriter()
    for _ in range(3):
        w.add_page(base.pages[0])
    b = io.BytesIO(); w.write(b)
    return b.getvalue()


def test_el_visor_enseña_el_pdf_a_la_izquierda_con_paginas_zoom_y_recuadro(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho visor")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "visor-e2e@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Visor", nif="B12345678", email="visor@ejemplo.com")
    fid = fc.subir_archivos(t, uid, c, "recibida", [("tres.pdf", "application/pdf", _pdf_de_tres_paginas())])[0]
    evidencia = {"origen": "imagen", "campos": {"numero": {"texto": "FACTURA Nº 2026/118", "caja": [0.1, 0.1, 0.5, 0.15], "valor": "2026/118", "coherente": True}}, "verificaciones": [], "confianza": {"numero": 95}, "motivos": []}
    conn = db.get_connection()
    conn.execute("UPDATE facturas_contables SET lectura = 'ia', lectura_fuente = 'imagen', lectura_confianza = 95, numero = '2026/118', lectura_evidencia = ? WHERE id = ?", (json.dumps(evidencia), fid))
    conn.commit(); conn.close()
    errores = []
    pagina.on("pageerror", lambda e: errores.append(str(e)))
    for ancho, alto in ((1280, 900), (768, 1000), (375, 800)):
        pagina.set_viewport_size({"width": ancho, "height": alto})
        pagina.goto(f"{servidor.url}/contabilidad/{fid}")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_function("document.querySelector('[data-visor-imagen]').complete && document.querySelector('[data-visor-imagen]').naturalWidth > 0")
        assert pagina.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"), f"desborde horizontal a {ancho}px"
        visor = pagina.locator("[data-visor-revision] .visor-documento").bounding_box()
        formulario = pagina.locator("form.edit-form").first.bounding_box()
        if ancho >= 1100:
            assert visor["x"] < formulario["x"] and abs(visor["y"] - formulario["y"]) < 400, "en pantalla ancha el documento va junto a los datos"
        else:
            assert visor["y"] < formulario["y"], "en móvil el documento va encima de los datos"
    pagina.set_viewport_size({"width": 1280, "height": 900})
    pagina.goto(f"{servidor.url}/contabilidad/{fid}")
    pagina.wait_for_function("document.querySelector('[data-visor-imagen]').naturalWidth > 0")
    assert pagina.locator("[data-visor-estado]").inner_text().strip() == "1 / 3"
    pagina.locator('[data-visor-pagina="1"]').click()
    pagina.wait_for_function("document.querySelector('[data-visor-estado]').innerText.trim() === '2 / 3' && document.querySelector('[data-visor-imagen]').src.endsWith('/pagina/2')")
    pagina.locator('[data-visor-pagina="-1"]').click()
    pagina.wait_for_function("document.querySelector('[data-visor-estado]').innerText.trim() === '1 / 3'")
    ancho_inicial = pagina.locator("[data-visor-hoja]").bounding_box()["width"]
    pagina.locator('[data-visor-zoom="1"]').click()
    pagina.wait_for_function("ancho => document.querySelector('[data-visor-hoja]').getBoundingClientRect().width > ancho", arg=ancho_inicial)   # el zoom tiene una transición corta
    pagina.locator('[data-visor-zoom="0"]').click()
    pagina.wait_for_function("ancho => Math.abs(document.querySelector('[data-visor-hoja]').getBoundingClientRect().width - ancho) < 2", arg=ancho_inicial)
    assert pagina.locator("[data-visor-caja]").is_hidden()
    pagina.locator('input[name="numero"]').focus()
    assert pagina.locator("[data-visor-caja]").is_visible(), "al enfocar el número se resalta de dónde lo leyó la IA"
    pagina.locator('input[name="fecha"]').focus()
    assert pagina.locator("[data-visor-caja]").is_hidden(), "un dato sin recuadro no resalta nada"
    assert not errores, errores


def test_una_factura_xml_enseña_sus_datos_sin_imagen_y_sin_errores(servidor, abrir, entrar_como_equipo, chromium):
    from pathlib import Path
    t = db.crear_tenant("Despacho visor xml")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "visor-xml@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Visor", nif="B12345678", email="visor2@ejemplo.com")
    xml = (Path(__file__).resolve().parent.parent / "datos_facturas" / "facturae_322.xml").read_bytes().replace(b"12345678Z", b"B12345678")
    fid = fc.subir_archivos(t, uid, c, "recibida", [("f.xml", "application/xml", xml)])[0]
    from app import lectura_facturas as lf
    lf.leer(t, uid, fid)
    errores = []
    pagina.on("pageerror", lambda e: errores.append(str(e)))
    pagina.goto(f"{servidor.url}/contabilidad/{fid}")
    pagina.wait_for_load_state("networkidle")
    assert pagina.locator(".visor-xml").is_visible() and "Papelería Sol" in pagina.locator(".visor-xml").inner_text() and pagina.locator("[data-visor-imagen]").count() == 0
    assert "Confianza 100" in pagina.locator(".lectura-resumen").inner_text()
    assert pagina.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    assert not errores, errores
