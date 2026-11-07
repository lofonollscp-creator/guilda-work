"""Un PDF con varias facturas se separa y cada una se lee (R5)."""
import io
import json

import pytest
from PIL import Image

from app import db, facturas_contables as fc, ia_asistente, ia_despacho, lectura_facturas as lf, segmentacion_pdf as sg
from tests.test_facturas_contables import _despacho
from tests.test_lectura_pipeline import RESPUESTA, TEXTO_FACTURA, _pdf_con_texto
from tests.test_lectura_facturas import modelo as modelo_base  # noqa: F401 -- fixture


def _pdf_multipagina(paginas: list[list[str]]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    salida = io.BytesIO()
    c = canvas.Canvas(salida, pagesize=A4)
    for lineas in paginas:
        y = 800
        for linea in lineas:
            c.drawString(50, y, linea)
            y -= 18
        c.showPage()
    c.save()
    return salida.getvalue()


RELLENO = ["Calle Mayor 1, Madrid. Registro Mercantil de Madrid, tomo 123, folio 45, hoja M-12345.", "Forma de pago: transferencia bancaria a 30 dias. Gracias por confiar en nosotros."]


def _factura(numero: str) -> list[str]:
    return [l.replace("2026/118", numero) for l in TEXTO_FACTURA]


def test_el_numero_de_factura_se_encuentra_en_distintos_formatos():
    assert sg.numero_en("FACTURA Nº 2026/118   Fecha 14/08/2026") == "2026/118"
    assert sg.numero_en("Invoice #INV-0042 date") == "INV-0042"
    assert sg.numero_en("Factura: A-000123") == "A-000123"
    assert sg.numero_en("Fra. 77/2026") == "77/2026"
    assert sg.numero_en("Condiciones generales de contratación") is None
    assert sg.numero_en("FACTURA SIMPLIFICADA") is None and sg.numero_en("Factura de venta") is None


def test_agrupar_por_numero_pega_las_paginas_sin_numero_a_la_anterior():
    assert sg.agrupar_por_numero(["A1", None, "A2", "A2", None, "A3"]) == [[1, 2], [3, 4, 5], [6]]
    assert sg.agrupar_por_numero(["A1", "A1", "A1"]) == [[1, 2, 3]]
    assert sg.agrupar_por_numero([None, None]) == [[1, 2]]
    assert sg.agrupar_por_numero([None, "B1", None]) == [[1, 2, 3]] or sg.agrupar_por_numero([None, "B1", None]) == [[1], [2, 3]]


def test_por_texto_reparte_un_pdf_con_dos_facturas_y_deja_en_paz_una_de_varias_paginas():
    dos = _pdf_multipagina([_factura("2026/118"), RELLENO + ["Condiciones adicionales de la factura anterior y datos bancarios del emisor."], _factura("2026/119")])
    assert sg.por_texto(dos) == [[1, 2], [3]]
    una = _pdf_multipagina([_factura("2026/118"), RELLENO + ["Segunda hoja de la misma factura con más líneas de detalle de los servicios prestados."]])
    assert sg.por_texto(una) == [[1, 2]] and sg.segmentar(1, una) is None
    assert sg.segmentar(1, _pdf_multipagina([_factura("2026/118")])) is None                    # una sola página
    assert sg.segmentar(1, b"no es un pdf") is None


def test_partir_conserva_las_paginas_y_el_texto():
    pdf = _pdf_multipagina([_factura("2026/118"), _factura("2026/119")])
    partes = sg.partir(pdf, [[1], [2]])
    from app import pdf_facturas
    assert [pdf_facturas.numero_de_paginas(p) for p in partes] == [1, 1]
    assert "2026/119" in pdf_facturas.texto_de_paginas(partes[1])[0] and "2026/118" in pdf_facturas.texto_de_paginas(partes[0])[0]


def _escaneo(n: int) -> bytes:
    b = io.BytesIO()
    imgs = [Image.new("RGB", (300, 400), (240 - 10 * i,) * 3) for i in range(n)]
    imgs[0].save(b, "PDF", save_all=True, append_images=imgs[1:])
    return b.getvalue()


def test_un_escaneo_sin_texto_se_pregunta_a_la_ia_y_se_valida_su_respuesta(monkeypatch):
    escaneo = _escaneo(3)
    assert sg.por_texto(escaneo) is None
    respuestas = iter(['{"facturas": [[1], [2, 3]]}'])
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda uid, s, p, timeout=90: next(respuestas))
    assert sg.segmentar(1, escaneo) == [[1], [2, 3]]
    for mala in ('{"facturas": [[1], [3]]}', '{"facturas": [[2], [1, 3]]}', '{"facturas": "x"}', "no es json", '{"facturas": [[1, 2, 3]]}'):
        monkeypatch.setattr(ia_asistente, "completar_partes", lambda uid, s, p, timeout=90, m=mala: m)
        assert sg.segmentar(1, escaneo) is None, mala                                        # incoherente o una sola factura: se trata como una


@pytest.fixture
def modelo(modelo_base):
    def falso(uid, sistema, partes, timeout=90):
        modelo_base.llamadas.append((sistema, partes))
        texto = " ".join(p.get("text", "") for p in partes)
        numero = "2026/119" if "2026/119" in texto else "2026/118"
        return json.dumps({**RESPUESTA, "emisor_nif": "B87654323", "numero": numero})
    ia_asistente.completar_partes = falso
    return modelo_base


def test_leer_separa_el_pdf_y_cada_factura_queda_leida(modelo):
    t, u, c = _despacho()
    pdf = _pdf_multipagina([_factura("2026/118"), _factura("2026/119")])
    fid = fc.subir_archivos(t, u, c, "recibida", [("mes.pdf", "application/pdf", pdf)])[0]
    avisos = lf.leer(t, u, fid)
    todas = fc.listar(t, u, cliente_fiscal_id=c)
    assert len(todas) == 2 and sorted(f["numero"] for f in todas) == ["2026/118", "2026/119"]
    assert all(f["lectura"] == "ia" for f in todas) and any("tenía 2 facturas" in a for a in avisos)
    from app import almacen_documentos, pdf_facturas
    docs = {f["id"]: almacen_documentos.leer_de_cliente_fiscal(t, c, f["documento_id"], u) for f in todas}
    assert all(pdf_facturas.numero_de_paginas(bytes(d["contenido"])) == 1 for d in docs.values())          # cada una con su propia página
    assert fc.obtener(t, u, fid)["numero"] == "2026/118"
    conn = db.get_connection()
    acciones = [r["accion"] for r in conn.execute("SELECT accion FROM auditoria_eventos WHERE entidad_id = ?", (str(fid),)).fetchall()]
    conn.close()
    assert "factura_contable.pdf_separado" in acciones


def test_si_el_despacho_lo_apaga_el_pdf_se_lee_entero(modelo):
    t, u, c = _despacho()
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="compartida", umbral_confianza=90, separar_pdf=False, por=u)
    pdf = _pdf_multipagina([_factura("2026/118"), _factura("2026/119")])
    fid = fc.subir_archivos(t, u, c, "recibida", [("mes.pdf", "application/pdf", pdf)])[0]
    lf.leer(t, u, fid)
    assert len(fc.listar(t, u, cliente_fiscal_id=c)) == 1


def test_una_factura_de_dos_paginas_no_se_parte(modelo):
    t, u, c = _despacho()
    pdf = _pdf_multipagina([_factura("2026/118"), RELLENO + ["Segunda hoja con el detalle de las líneas de la factura y las condiciones de pago acordadas."]])
    fid = fc.subir_archivos(t, u, c, "recibida", [("una.pdf", "application/pdf", pdf)])[0]
    avisos = lf.leer(t, u, fid)
    assert len(fc.listar(t, u, cliente_fiscal_id=c)) == 1 and not any("tenía" in a for a in avisos)
