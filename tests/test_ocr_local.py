"""OCR local (R2): norma por despacho, respaldo cuando el modelo no puede con la imagen y modo «nada sale del servidor»."""
import io
import json

import pytest

from app import facturas_contables as fc, ia_asistente, ia_despacho, lectura_facturas as lf, ocr_local
from tests.test_facturas_contables import PDF, _despacho
from tests.test_lectura_pipeline import RESPUESTA, TEXTO_FACTURA, _pdf_con_texto, _subir
from tests.test_lectura_facturas import modelo as modelo_base  # noqa: F401 -- fixture


@pytest.fixture
def ocr(monkeypatch):
    """OCR simulado: devuelve el texto de una factura legible y anota cuántas veces se usó."""
    class O:
        usos = 0
        texto = "--- página 1 ---\n" + "\n".join(TEXTO_FACTURA)
    o = O()
    def falso(contenido, mime):
        o.usos += 1
        return o.texto
    monkeypatch.setattr(ocr_local, "texto_de", falso)
    monkeypatch.setattr(ocr_local, "disponible", lambda: True)
    return o


@pytest.fixture
def modelo_sin_vision(monkeypatch):
    """Un modelo que solo entiende texto: rechaza (400) cualquier consulta con imagen o PDF."""
    class M:
        llamadas = []
    m = M()
    monkeypatch.setattr(lf, "configurada", lambda uid: True)
    def falso(uid, sistema, partes, timeout=90):
        m.llamadas.append((sistema, partes))
        if any(p.get("type") != "text" for p in partes):
            raise ia_asistente.ErrorIA("sin visión", codigo_http=400)
        return json.dumps({**RESPUESTA, "emisor_nif": "B87654323"})
    monkeypatch.setattr(ia_asistente, "completar_partes", falso)
    return m


def _norma(t, u, modo, facturas_modo="compartida"):
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo=facturas_modo, umbral_confianza=50, ocr_local=modo, por=u)


def test_la_norma_por_defecto_es_de_respaldo_y_solo_admite_sus_tres_valores():
    t, u, c = _despacho()
    assert ia_despacho.config(t)["ocr_local"] == "respaldo"
    _norma(t, u, "solo_local")
    assert ia_despacho.config(t)["ocr_local"] == "solo_local"
    with pytest.raises(ValueError, match="OCR"):
        _norma(t, u, "siempre")


def test_de_respaldo_un_modelo_sin_vision_lee_el_texto_del_ocr_y_queda_para_revisar(modelo_sin_vision, ocr):
    t, u, c = _despacho()
    _norma(t, u, "respaldo", facturas_modo="auto")                                           # aunque la IA decida sola, un texto de OCR lo revisa una persona
    fid = _subir(t, u, c, "escaneo.pdf", "application/pdf", PDF + b"ocr1")
    avisos = lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert f["lectura_fuente"] == "ocr" and ocr.usos == 1 and f["total_centimos"] == 12100
    assert f["estado"] == "pendiente" and not f["revision_auto"]
    assert any("OCR local" in a for a in avisos) and "OCR local" in f["notas"]
    assert any(p.get("type") != "text" for _s, ps in modelo_sin_vision.llamadas[:1] for p in ps)  # primero se intentó con la imagen


def test_sin_ocr_el_modelo_sin_vision_da_el_aviso_de_siempre(modelo_sin_vision, ocr):
    t, u, c = _despacho()
    _norma(t, u, "no")
    fid = _subir(t, u, c, "escaneo.pdf", "application/pdf", PDF + b"ocr2")
    with pytest.raises(ValueError, match="no admite imágenes"):
        lf.leer(t, u, fid)
    assert ocr.usos == 0


def test_con_nada_sale_del_servidor_no_se_manda_ninguna_imagen(modelo_sin_vision, ocr):
    t, u, c = _despacho()
    _norma(t, u, "solo_local")
    fid = _subir(t, u, c, "escaneo.pdf", "application/pdf", PDF + b"ocr3")
    lf.leer(t, u, fid)
    assert fc.obtener(t, u, fid)["lectura_fuente"] == "ocr"
    assert modelo_sin_vision.llamadas and all(p.get("type") == "text" for _s, ps in modelo_sin_vision.llamadas for p in ps)


def test_con_nada_sale_del_servidor_un_pdf_con_texto_no_necesita_ocr(modelo_sin_vision, ocr):
    t, u, c = _despacho()
    _norma(t, u, "solo_local")
    fid = _subir(t, u, c, "con_texto.pdf", "application/pdf", _pdf_con_texto(TEXTO_FACTURA))
    lf.leer(t, u, fid)
    assert ocr.usos == 0 and fc.obtener(t, u, fid)["lectura_fuente"] == "ocr"


def test_con_nada_sale_del_servidor_y_sin_texto_legible_pide_rellenar_a_mano(modelo_sin_vision, ocr):
    t, u, c = _despacho()
    _norma(t, u, "solo_local")
    ocr.texto = ""
    fid = _subir(t, u, c, "ilegible.pdf", "application/pdf", PDF + b"ocr4")
    with pytest.raises(ValueError, match="Rellena los datos a mano"):
        lf.leer(t, u, fid)
    assert modelo_sin_vision.llamadas == []


def test_con_nada_sale_del_servidor_solo_quedan_los_modelos_locales(monkeypatch):
    t, u, c = _despacho()
    _norma(t, u, "solo_local")
    externos = [{"proveedor": "openrouter", "modelo": "m", "claves": ["k"], "url_base": None, "origen": "despacho"}, {"proveedor": "ollama", "modelo": "llava", "claves": [""], "url_base": None, "origen": "despacho"}]
    monkeypatch.setattr(ia_despacho, "candidatos", lambda tenant_id, tarea: list(externos))
    assert [x["proveedor"] for x in ia_asistente.candidatos(u, "facturas")] == ["ollama"]
    assert [x["proveedor"] for x in ia_asistente.candidatos(u, "asistente")] == ["openrouter", "ollama"]     # el chat del asistente no entra en la norma de facturas
    _norma(t, u, "respaldo")
    assert len(ia_asistente.candidatos(u, "facturas")) == 2


@pytest.mark.skipif(not ocr_local.disponible(), reason="Tesseract no está instalado")
def test_tesseract_real_reconoce_los_importes_de_una_foto():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1000, 500), "white")
    d = ImageDraw.Draw(img)
    fuente = ImageFont.load_default(size=36)
    for i, linea in enumerate(("FACTURA N. A-2026/118", "Fecha: 12/03/2026", "TOTAL 121,00 EUR")):
        d.text((40, 40 + i * 80), linea, fill="black", font=fuente)
    salida = io.BytesIO()
    img.save(salida, "PNG")
    texto = ocr_local.texto_de(salida.getvalue(), "image/png")
    assert "121,00" in texto and "12/03/2026" in texto
    assert ocr_local.texto_de(b"no es una imagen", "image/png") == ""
