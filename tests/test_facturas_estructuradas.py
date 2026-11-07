"""Lectura exacta de facturas electrónicas: Facturae, UBL/Peppol y Factur-X/CII (R1)."""
import io
from pathlib import Path

from app import facturas_estructuradas as fe

DATOS = Path(__file__).parent / "datos_facturas"


def _xml(nombre):
    return (DATOS / nombre).read_bytes()


def test_facturae_se_lee_con_serie_lineas_por_tipo_retencion_y_nombres():
    r = fe.extraer(_xml("facturae_322.xml"), "application/xml", "factura.xml")
    assert r["formato"] == "facturae" and r["origen"] == "xml"
    d = r["datos"]
    assert d["numero"] == "A-000123" and d["fecha"] == "2026-10-15" and d["fecha_operacion"] == "2026-10-10"
    assert (d["emisor_nombre"], d["emisor_nif"]) == ("Papelería Sol, S.L.", "B87654323")           # sin el prefijo ES
    assert (d["receptor_nombre"], d["receptor_nif"]) == ("María García López", "12345678Z")
    assert d["lineas"] == [{"base": "800.00", "pct_iva": "21.00", "cuota_iva": "168.00", "pct_retencion": "15.00"},
                           {"base": "200.00", "pct_iva": "10.00", "cuota_iva": "20.00", "pct_retencion": "15.00"}]
    assert d["total"] == "1038.00" and d["es_abono"] is False and d["concepto"].startswith("Material de oficina")


def test_ubl_peppol_y_nota_de_credito():
    r = fe.extraer(_xml("ubl_peppol.xml"), "text/xml")
    d = r["datos"]
    assert r["formato"] == "ubl" and d["numero"] == "F-2026/045" and d["fecha"] == "2026-09-30"
    assert (d["emisor_nombre"], d["emisor_nif"], d["receptor_nif"]) == ("Consultores Mar, S.A.", "A11111119", "B12345678")
    assert d["lineas"] == [{"base": "1000.00", "pct_iva": "21.00", "cuota_iva": "210.00"}] and d["total"] == "1210.00" and d["es_abono"] is False
    abono = _xml("ubl_peppol.xml").replace(b"<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>", b"<cbc:InvoiceTypeCode>381</cbc:InvoiceTypeCode>")
    assert fe.extraer(abono, "text/xml")["datos"]["es_abono"] is True


def test_cii_facturx_abono_intracomunitario_con_nif_extranjero():
    d = fe.extraer(_xml("facturx_cii.xml"), "application/xml")["datos"]
    assert d["numero"] == "INV-7788" and d["fecha"] == "2026-11-05" and d["es_abono"] is True
    assert d["emisor_nif"] == "DE123456789" and d["receptor_nif"] == "B12345678"                   # un VAT alemán no se toca
    assert d["lineas"] == [{"base": "500.00", "pct_iva": "0.00", "cuota_iva": "0.00"}] and d["total"] == "500.00"


def _pdf_con_xml(xml: bytes, nombre="factur-x.xml") -> bytes:
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.add_attachment(nombre, xml)
    salida = io.BytesIO()
    w.write(salida)
    return salida.getvalue()


def test_pdf_con_xml_incrustado_se_lee_sin_ia():
    r = fe.extraer(_pdf_con_xml(_xml("facturx_cii.xml")), "application/pdf")
    assert r["formato"] == "cii" and r["origen"] == "pdf_incrustado" and r["datos"]["numero"] == "INV-7788"
    r = fe.extraer(_pdf_con_xml(_xml("facturae_322.xml"), "adjunto-cualquiera.xml"), "application/pdf")
    assert r["formato"] == "facturae"


def test_lo_que_no_es_una_factura_electronica_devuelve_none():
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(100, 100)
    b = io.BytesIO(); w.write(b)
    assert fe.extraer(b.getvalue(), "application/pdf") is None                                     # PDF normal
    assert fe.extraer(b"<?xml version='1.0'?><otro><cosa/></otro>", "text/xml") is None            # XML que no es factura
    assert fe.extraer(b"esto no es xml", "text/xml", "x.xml") is None
    assert fe.extraer(b"\x89PNG\r\n\x1a\n", "image/png") is None
    assert fe.extraer(b"", "application/pdf") is None
    sin_lo_esencial = _xml("ubl_peppol.xml").replace(b"<cbc:ID>F-2026/045</cbc:ID>", b"")
    assert fe.extraer(sin_lo_esencial, "text/xml") is None                                         # sin número no se da por leída


def test_un_xml_hostil_no_lee_ficheros_ni_abre_la_red(tmp_path):
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("CONTENIDO-SECRETO")
    hostil = f'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file://{secreto}">]><Invoice xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"><cbc:ID>&e;</cbc:ID></Invoice>'.encode()
    r = fe.extraer(hostil, "text/xml")
    assert r is None or "CONTENIDO-SECRETO" not in str(r)
    bomba = b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><Invoice>&c;</Invoice>'
    assert fe.extraer(bomba, "text/xml") is None
    assert fe.extraer(b"<a>" + b"x" * (fe.MAX_XML_BYTES + 1) + b"</a>", "text/xml") is None
