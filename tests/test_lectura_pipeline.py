"""Lectura de facturas por capas (R1, R4, R7): factura electrónica exacta, QR, texto del PDF con puerta de calidad, confianza, modo «decide sola» y casos fiscales especiales."""
import io
import json
from pathlib import Path

import pytest

from app import db, facturas_contables as fc, ia_asistente, ia_despacho, lectura_confianza as lc, lectura_facturas as lf, vies
from tests.test_facturas_contables import PDF, _despacho
from tests.test_lectura_facturas import CLIENTE_NIF, RESPUESTA as RESPUESTA_BASE, modelo as modelo_base  # noqa: F401 -- fixture

RESPUESTA = {**RESPUESTA_BASE, "emisor_nif": "B87654323"}          # con un NIF de emisor de dígito de control válido


@pytest.fixture
def modelo(modelo_base):
    modelo_base.respuesta = json.dumps(RESPUESTA)
    return modelo_base

DATOS = Path(__file__).parent / "datos_facturas"


def _subir(t, u, c, nombre, mime, contenido, tipo="recibida"):
    return fc.subir_archivos(t, u, c, tipo, [(nombre, mime, contenido)])[0]


def _facturae(receptor_nif=CLIENTE_NIF):
    return (DATOS / "facturae_322.xml").read_bytes().replace(b"12345678Z", receptor_nif.encode())


def _pdf_con_texto(lineas: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    salida = io.BytesIO()
    c = canvas.Canvas(salida, pagesize=A4)
    y = 800
    for linea in lineas:
        c.drawString(50, y, linea)
        y -= 18
    c.save()
    return salida.getvalue()


TEXTO_FACTURA = ["PAPELERIA SOL S.L.   CIF B87654323", "Calle Mayor 1, Madrid", "FACTURA Nº 2026/118        Fecha: 14/08/2026", "Cliente: Cliente Conta S.L.   CIF B12345678",
                 "Concepto: Material de oficina para el trimestre y suministros varios de papeleria", "Base imponible: 100,00 EUR", "IVA 21 %: 21,00 EUR", "TOTAL FACTURA: 121,00 EUR",
                 "Forma de pago: transferencia bancaria a 30 dias. Gracias por confiar en nosotros. Registro Mercantil de Madrid, tomo 123, folio 45."]


def test_la_factura_electronica_xml_se_lee_sin_ia_y_con_confianza_total(modelo):
    t, u, c = _despacho()
    fid = _subir(t, u, c, "factura.xml", "application/xml", _facturae())
    assert lf.leer(t, u, fid) == []
    f = fc.obtener(t, u, fid)
    assert modelo.llamadas == []                                                              # ni una consulta a la IA
    assert (f["numero"], f["fecha"], f["tercero_nombre"], f["tercero_nif"], f["tipo"], f["total_centimos"]) == ("A-000123", "2026-10-15", "Papelería Sol, S.L.", "B87654323", "recibida", 103800)
    assert f["lectura"] == "xml" and f["lectura_fuente"] == "xml" and f["lectura_confianza"] == 100 and "factura electrónica" in f["notas"] and f["estado"] == "pendiente"
    assert sorted((l["base_centimos"], l["pct_iva"], l["pct_retencion"]) for l in f["lineas"]) == [(20000, 1000, 1500), (80000, 2100, 1500)]
    ev = lf.evidencia_de(f)
    assert ev["origen"] == "xml" and ev["campos"] == {} and ev["confianza"]["total"] == 100


def test_la_factura_electronica_se_lee_aunque_no_haya_ia_configurada(monkeypatch):
    t, u, c = _despacho()
    monkeypatch.setattr(lf, "configurada", lambda uid: False)
    fid = _subir(t, u, c, "factura.xml", "text/xml", _facturae())
    lf.leer(t, u, fid)
    assert fc.obtener(t, u, fid)["lectura"] == "xml"
    fid2 = _subir(t, u, c, "b.pdf", "application/pdf", PDF + b"2")
    with pytest.raises(ValueError, match="hace falta un modelo"):
        lf.leer(t, u, fid2)                                                                    # un PDF normal sí necesita IA


def test_pdf_con_xml_facturx_incrustado_se_lee_sin_ia(modelo):
    from pypdf import PdfWriter
    t, u, c = _despacho()
    w = PdfWriter(); w.add_blank_page(200, 200); w.add_attachment("factur-x.xml", (DATOS / "facturx_cii.xml").read_bytes().replace(b"ESB12345678", CLIENTE_NIF.encode().join([b"ES", b""])[:0] + b"ES" + CLIENTE_NIF.encode()))
    b = io.BytesIO(); w.write(b)
    fid = _subir(t, u, c, "f.pdf", "application/pdf", b.getvalue())
    lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert modelo.llamadas == [] and f["lectura"] == "xml" and f["numero"] == "INV-7788" and f["abono"] and f["tercero_nif"] == "DE123456789"


def test_xml_que_no_es_factura_cae_a_la_ia_o_falla_con_claridad(modelo):
    t, u, c = _despacho()
    modelo.respuesta = "No veo ninguna factura en este documento."
    fid = _subir(t, u, c, "otro.xml", "text/xml", b"<?xml version='1.0'?><pedido><x/></pedido>")
    with pytest.raises(ValueError):
        lf.leer(t, u, fid)                                                                     # tampoco la IA lo lee: se marca fallida con el texto claro
    assert fc.obtener(t, u, fid)["lectura"] == "fallida"


def _png_con_qr(texto):
    import cv2
    img = cv2.QRCodeEncoder.create().encode(texto)
    img = cv2.copyMakeBorder(cv2.resize(img, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST), 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=255)
    return cv2.imencode(".png", img)[1].tobytes()


def test_el_qr_corrige_lo_que_la_ia_lee_mal_y_sube_la_confianza(modelo):
    t, u, c = _despacho()
    qr = f"https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR?nif=B87654323&numserie=2026/118&fecha=14-08-2026&importe=121.00"
    modelo.respuesta = json.dumps({**RESPUESTA, "numero": "2026/999", "fecha": "2026-08-15"})
    fid = _subir(t, u, c, "ticket.png", "image/png", _png_con_qr(qr))
    avisos = lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert (f["numero"], f["fecha"]) == ("2026/118", "2026-08-14")
    assert any("QR" in a and "número" in a for a in avisos) and any("QR" in a and "fecha" in a for a in avisos)
    assert lf.evidencia_de(f)["qr"]["tipo"] == "verifactu" and lf.evidencia_de(f)["confianza"]["numero"] == 100


def test_un_qr_que_no_es_de_factura_no_cambia_nada(modelo):
    t, u, c = _despacho()
    fid = _subir(t, u, c, "ticket.png", "image/png", _png_con_qr("https://www.ejemplo.com/promo"))
    assert lf.leer(t, u, fid) == [] and fc.obtener(t, u, fid)["numero"] == "2026/118" and lf.evidencia_de(fc.obtener(t, u, fid))["qr"] is None


# --- Texto del PDF con puerta de calidad ---------------------------------------------------------------------------------------------------------------

def test_pdf_con_texto_se_lee_solo_con_el_texto_si_todo_cuadra(modelo):
    t, u, c = _despacho()
    fid = _subir(t, u, c, "f.pdf", "application/pdf", _pdf_con_texto(TEXTO_FACTURA))
    lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert len(modelo.llamadas) == 1                                                           # UNA consulta, y solo con texto
    sistema, partes = modelo.llamadas[0]
    assert [p["type"] for p in partes] == ["text"] and "PAPELERIA SOL" in partes[0]["text"] and "caja\": null" in sistema
    assert f["lectura_fuente"] == "texto" and "texto del PDF" in f["notas"] and f["lectura_confianza"] >= 96 and f["total_centimos"] == 12100


def test_si_lo_leido_del_texto_no_aparece_en_el_texto_se_vuelve_a_leer_con_la_imagen(modelo):
    t, u, c = _despacho()
    respuestas = [json.dumps({**RESPUESTA, "numero": "ZZ-NO-ESTA"}), json.dumps(RESPUESTA)]
    modelo_respuestas = iter(respuestas)

    def falso(uid, sistema, partes, timeout=90):
        modelo.llamadas.append((sistema, partes))
        return next(modelo_respuestas)
    ia_asistente.completar_partes = falso                                                      # el fixture restaura el original al terminar
    fid = _subir(t, u, c, "f.pdf", "application/pdf", _pdf_con_texto(TEXTO_FACTURA))
    avisos = lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert len(modelo.llamadas) == 2 and [p["type"] for p in modelo.llamadas[1][1]] == ["text", "file"]       # la segunda vez, con el documento
    assert f["lectura_fuente"] == "imagen" and f["numero"] == "2026/118" and any("volver" in a.lower() or "vuelto a leer" in a for a in avisos)


def test_si_el_texto_no_cuadra_con_las_lineas_tambien_escala(monkeypatch, modelo):
    t, u, c = _despacho()
    respuestas = iter([json.dumps({**RESPUESTA, "lineas": [{"base": 50, "pct_iva": 21, "cuota_iva": 10.5}]}), json.dumps(RESPUESTA)])
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda uid, s, p, timeout=90: modelo.llamadas.append((s, p)) or next(respuestas))
    fid = _subir(t, u, c, "f.pdf", "application/pdf", _pdf_con_texto(TEXTO_FACTURA))
    lf.leer(t, u, fid)
    assert len(modelo.llamadas) == 2 and fc.obtener(t, u, fid)["lectura_fuente"] == "imagen"


def test_si_el_cliente_no_aparece_en_el_documento_escala(monkeypatch, modelo):
    t, u, c = _despacho()
    texto = [l.replace("B12345678", "B99999999") for l in TEXTO_FACTURA]
    respuestas = iter([json.dumps({**RESPUESTA, "receptor_nif": "B99999999"}), json.dumps(RESPUESTA)])
    monkeypatch.setattr(ia_asistente, "completar_partes", lambda uid, s, p, timeout=90: modelo.llamadas.append((s, p)) or next(respuestas))
    fid = _subir(t, u, c, "f.pdf", "application/pdf", _pdf_con_texto(texto))
    lf.leer(t, u, fid)
    assert len(modelo.llamadas) == 2


def test_el_despacho_puede_apagar_la_lectura_por_texto(modelo):
    t, u, c = _despacho()
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="compartida", umbral_confianza=90, lectura_texto=False, por=u)
    fid = _subir(t, u, c, "f.pdf", "application/pdf", _pdf_con_texto(TEXTO_FACTURA))
    lf.leer(t, u, fid)
    assert len(modelo.llamadas) == 1 and [p["type"] for p in modelo.llamadas[0][1]] == ["text", "file"] and fc.obtener(t, u, fid)["lectura_fuente"] == "imagen"


def test_un_escaneo_sin_texto_va_directo_a_la_imagen(modelo):
    t, u, c = _despacho()
    fid = _subir(t, u, c, "f.pdf", "application/pdf", PDF + b"9")
    lf.leer(t, u, fid)
    assert len(modelo.llamadas) == 1 and [p["type"] for p in modelo.llamadas[0][1]] == ["text", "file"]


# --- Modo «decide sola» -------------------------------------------------------------------------------------------------------------------------------

def test_en_modo_auto_la_factura_segura_queda_revisada_y_marcada(modelo):
    t, u, c = _despacho()
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="auto", umbral_confianza=90, por=u)
    fid = _subir(t, u, c, "factura.xml", "application/xml", _facturae())
    lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert f["estado"] == "revisada" and f["revision_auto"] == 1 and f["revisado_por"] is None
    conn = db.get_connection()
    acciones = [r["accion"] for r in conn.execute("SELECT accion FROM auditoria_eventos WHERE entidad_id = ?", (str(fid),)).fetchall()]
    conn.close()
    assert "factura_contable.revisada_auto" in acciones


def test_en_modo_auto_una_lectura_insegura_la_revisa_una_persona(modelo):
    t, u, c = _despacho()
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="auto", umbral_confianza=90, por=u)
    fid = _subir(t, u, c, "f.pdf", "application/pdf", PDF + b"5")                              # sin texto ni evidencias: el modelo se queda en 75 como mucho
    lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert f["estado"] == "pendiente" and f["revision_auto"] == 0 and f["lectura_confianza"] <= lc.TOPE_SIN_EVIDENCIA


def test_en_modo_compartido_nunca_se_revisa_sola(modelo):
    t, u, c = _despacho()
    fid = _subir(t, u, c, "factura.xml", "application/xml", _facturae())
    lf.leer(t, u, fid)
    assert fc.obtener(t, u, fid)["estado"] == "pendiente"


def test_en_modo_auto_un_aviso_o_comprobacion_impide_la_revision_automatica(modelo):
    t, u, c = _despacho()
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="auto", umbral_confianza=60, por=u)
    fid = _subir(t, u, c, "factura.xml", "application/xml", _facturae(receptor_nif="B00000000"))     # el NIF del receptor no es el del cliente: aviso de tipo
    avisos = lf.leer(t, u, fid)
    assert avisos and fc.obtener(t, u, fid)["estado"] == "pendiente"


# --- Casos fiscales (R7) -----------------------------------------------------------------------------------------------------------------------------

def test_inversion_del_sujeto_pasivo_marca_la_operacion_en_las_lineas(modelo):
    t, u, c = _despacho()
    modelo.respuesta = json.dumps({**RESPUESTA, "operacion": "inversion_sujeto_pasivo", "lineas": [{"base": 100, "pct_iva": 0, "cuota_iva": 0}], "total": 100})
    fid = _subir(t, u, c, "f.pdf", "application/pdf", PDF + b"6")
    avisos = lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert [l["subtipo"] for l in f["lineas"]] == ["04"] and any("inversion sujeto pasivo" in a for a in avisos)


def test_operaciones_intracomunitarias_y_de_canarias(modelo):
    t, u, c = _despacho()
    for operacion, esperado in (("intracomunitaria_bienes", "03"), ("intracomunitaria_servicios", "08"), ("canarias_ceuta_melilla", "07")):
        modelo.respuesta = json.dumps({**RESPUESTA, "operacion": operacion, "lineas": [{"base": 100, "pct_iva": 0, "cuota_iva": 0}], "total": 100})
        fid = _subir(t, u, c, f"{operacion}.pdf", "application/pdf", PDF + operacion.encode())
        lf.leer(t, u, fid)
        assert [l["subtipo"] for l in fc.obtener(t, u, fid)["lineas"]] == [esperado], operacion
    modelo.respuesta = json.dumps({**RESPUESTA, "operacion": "exportacion"})
    fid = _subir(t, u, c, "ex.pdf", "application/pdf", PDF + b"ex")
    assert any("elige a mano" in a for a in lf.leer(t, u, fid))                                # una exportación en una factura recibida no se adivina


def test_otra_moneda_y_gasto_de_vehiculo_avisan(modelo):
    t, u, c = _despacho()
    modelo.respuesta = json.dumps({**RESPUESTA, "moneda": "USD", "concepto": "Gasolina del mes"})
    fid = _subir(t, u, c, "f.pdf", "application/pdf", PDF + b"usd")
    avisos = lf.leer(t, u, fid)
    assert any("USD" in a and "euros" in a for a in avisos) and any("vehículo" in a for a in avisos)


def test_un_nif_iva_europeo_que_vies_niega_genera_comprobacion(monkeypatch, modelo):
    t, u, c = _despacho()
    monkeypatch.setattr(vies, "valido", lambda nif, ahora=None: False)
    modelo.respuesta = json.dumps({**RESPUESTA, "emisor_nif": "DE123456789"})
    fid = _subir(t, u, c, "f.pdf", "application/pdf", PDF + b"de")
    lf.leer(t, u, fid)
    assert any("VIES" in v for v in lf.evidencia_de(fc.obtener(t, u, fid))["verificaciones"])
    monkeypatch.setattr(vies, "valido", lambda nif, ahora=None: None)                          # VIES no responde: no se acusa a nadie
    fid2 = _subir(t, u, c, "g.pdf", "application/pdf", PDF + b"de2")
    lf.leer(t, u, fid2)
    assert not any("VIES" in v for v in lf.evidencia_de(fc.obtener(t, u, fid2))["verificaciones"])


# --- Confianza (funciones puras) y VIES --------------------------------------------------------------------------------------------------------------

def _puntuar(**kw):
    base = dict(datos={"confianza": {"numero": 95, "fecha": 95, "total": 95, "emisor_nif": 95, "receptor_nif": 95}}, valores={"numero": "A1", "fecha": "2026-08-14", "total": "121.00", "emisor_nif": "B87654323",
                "receptor_nif": "B12345678", "base": "100.00", "iva": "21.00"}, evidencias={}, fuente="imagen")
    base.update(kw)
    return lc.puntuar(**base)


def _ev(coherente=True):
    return {"texto": "x", "caja": None, "valor": "v", "coherente": coherente}


def test_sin_evidencias_el_modelo_no_pasa_de_75_y_con_evidencia_coherente_si():
    assert _puntuar()["global"] == lc.TOPE_SIN_EVIDENCIA
    todas = {c: _ev() for c in ("numero", "fecha", "total", "emisor_nif", "receptor_nif", "base", "iva")}
    assert _puntuar(evidencias=todas)["global"] == 95
    assert _puntuar(evidencias={**todas, "total": _ev(False)})["global"] == lc.TOPE_CITA_INCOHERENTE


def test_xml_y_qr_dan_100_y_el_texto_literal_da_al_menos_96():
    assert _puntuar(fuente="xml")["global"] == 100
    assert _puntuar(texto_documento="Factura A1 de fecha 14/08/2026 total 121,00 EUR CIF B87654323")["campos"]["numero"] >= 96
    r = _puntuar(qr={"numero": "A1", "fecha": "2026-08-14", "total": "121.00", "nif": "B87654323"})
    assert r["campos"]["numero"] == r["campos"]["total"] == 100
    r = _puntuar(qr={"numero": "OTRO", "total": "121.00"})
    assert r["campos"]["numero"] == lc.TOPE_CONTRADICE_QR and r["global"] == lc.TOPE_CONTRADICE_QR and any("QR" in m for m in r["motivos"])


def test_nif_invalido_no_cuadre_comprobaciones_y_avisos_bajan_la_global():
    evid = {c: _ev() for c in ("numero", "fecha", "total", "emisor_nif", "receptor_nif", "base", "iva")}
    assert _puntuar(evidencias=evid, nif_invalido=True, campo_contraparte="emisor_nif")["global"] == lc.TOPE_NIF_INVALIDO
    assert _puntuar(evidencias=evid, cuadra=False)["global"] == lc.TOPE_NO_CUADRA
    assert _puntuar(evidencias=evid, comprobaciones=["x"])["global"] == lc.TOPE_CON_COMPROBACIONES
    assert _puntuar(evidencias=evid, avisos=["x"])["global"] == lc.TOPE_CON_AVISOS
    assert _puntuar(evidencias=evid, valores={"numero": "A1", "fecha": "", "total": "1.00", "emisor_nif": "B1"})["global"] == 0     # falta la fecha: no hay confianza


def test_el_semaforo():
    assert [lc.nivel(x) for x in (None, 100, 90, 89, 70, 69)] == ["sin_dato", "alta", "alta", "media", "media", "baja"]


def test_vies_separa_paises_cachea_y_nunca_acusa_si_no_responde(monkeypatch):
    assert vies.separar("DE 123-456.789") == ("DE", "123456789") and vies.separar("B12345678") is None and vies.separar("ESB12345678") is None and vies.separar("US123456789") is None
    llamadas = []

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(vies.urllib.request, "urlopen", lambda req, timeout=0: llamadas.append(req) or R(b'{"valid": false}'))
    vies._cache.clear()
    assert vies.valido("DE123456789", ahora=1000.0) is False and vies.valido("DE123456789", ahora=2000.0) is False and len(llamadas) == 1       # segunda vez, de la caché
    assert vies.valido("DE123456789", ahora=1000.0 + vies.CACHE_SEGUNDOS + 1) is False and len(llamadas) == 2
    def roto(req, timeout=0):
        raise TimeoutError()
    monkeypatch.setattr(vies.urllib.request, "urlopen", roto)
    assert vies.valido("FR12345678901", ahora=5.0) is None and vies.valido("B12345678") is None
