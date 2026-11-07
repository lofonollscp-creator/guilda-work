"""QR de VeriFactu y TicketBAI en facturas y tickets (R1)."""
import io

import pytest

from app import qr_facturas as qr

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

VERIFACTU = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR?nif=B12345678&numserie=F-123&fecha=15-10-2026&importe=121.00"
TICKETBAI = "https://batuz.eus/QRTBAI/?id=TBAI-B12345678-151026-Tm9ib3JkZXI-473&s=T&nf=0000001&i=2.50"


def _png_con_qr(texto: str, lado=6) -> bytes:
    img = cv2.QRCodeEncoder.create().encode(texto)
    img = cv2.resize(img, None, fx=lado, fy=lado, interpolation=cv2.INTER_NEAREST)
    img = cv2.copyMakeBorder(img, 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def test_interpretar_verifactu_y_ticketbai():
    assert qr.interpretar(VERIFACTU) == {"tipo": "verifactu", "nif": "B12345678", "numero": "F-123", "fecha": "2026-10-15", "total": "121.00"}
    assert qr.interpretar(TICKETBAI) == {"tipo": "ticketbai", "nif": "B12345678", "numero": "T0000001", "fecha": "2026-10-15", "total": "2.50"}
    assert qr.interpretar(VERIFACTU.replace("importe=121.00", "importe=1.234,50"))["total"] == ""        # importe ambiguo: no se inventa
    assert qr.interpretar(VERIFACTU.replace("importe=121.00", "importe=121,5"))["total"] == "121.50"


def test_lo_que_no_es_de_factura_se_ignora():
    for texto in ("https://www.ejemplo.com/pago?id=1", "BEGIN:VCARD", "", "https://www2.agenciatributaria.gob.es/otra/cosa?nif=B1&numserie=1",
                  "https://evil.com/wlpl/TIKE-CONT/ValidarQR?nif=B12345678&numserie=F-1&fecha=15-10-2026&importe=1",
                  "https://agenciatributaria.gob.es.evil.com/wlpl/TIKE-CONT/ValidarQR?nif=B12345678&numserie=F-1", "javascript:alert(1)"):
        assert qr.interpretar(texto) is None


def test_fecha_imposible_no_rompe():
    assert qr.interpretar(VERIFACTU.replace("15-10-2026", "31-02-2026"))["fecha"] == ""


def test_leer_un_qr_en_una_imagen_y_en_un_pdf():
    assert qr.leer(_png_con_qr(VERIFACTU), "image/png")["numero"] == "F-123"
    assert qr.leer(_png_con_qr(TICKETBAI), "image/png")["tipo"] == "ticketbai"
    assert qr.leer(_png_con_qr("https://www.ejemplo.com"), "image/png") is None
    from PIL import Image
    pagina = Image.open(io.BytesIO(_png_con_qr(VERIFACTU, 8))).convert("RGB")
    salida = io.BytesIO()
    pagina.save(salida, "PDF", resolution=100)
    assert qr.leer(salida.getvalue(), "application/pdf")["total"] == "121.00"


def test_sin_qr_o_con_basura_devuelve_none_sin_romper():
    assert qr.leer(b"", "image/png") is None and qr.leer(b"no es una imagen", "image/jpeg") is None and qr.leer(b"%PDF-1.4 roto", "application/pdf") is None
    blanco = cv2.imencode(".png", np.full((200, 200, 3), 255, np.uint8))[1].tobytes()
    assert qr.leer(blanco, "image/png") is None
