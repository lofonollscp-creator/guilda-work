"""Enderezar la foto de un documento (A1): propone el recorte en perspectiva solo si ve un papel claro."""
import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from app import enderezar_documento as ed


def _foto(torcida=True, ocupa=0.9):
    """Un folio con líneas de texto sobre una mesa oscura, fotografiado en perspectiva."""
    folio = np.full((1100, 780, 3), 245, np.uint8)
    for i in range(14):
        cv2.putText(folio, f"Linea {i} total 121,00", (40, 90 + i * 70), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 2)
    mesa = np.full((900, 1200, 3), 40, np.uint8)
    h = int(900 * ocupa)
    w = int(h * 0.71)                                                                         # proporción de un folio
    x0, y0 = (1200 - w) // 2, (900 - h) // 2
    destino = np.float32([[x0 + 40, y0 + 20], [x0 + w - 20, y0 + 50], [x0 + w - 60, y0 + h], [x0 + 10, y0 + h - 40]]) if torcida else np.float32([[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]])
    origen = np.float32([[0, 0], [780, 0], [780, 1100], [0, 1100]])
    m = cv2.getPerspectiveTransform(origen, destino)
    cv2.warpPerspective(folio, m, (1200, 900), dst=mesa, borderMode=cv2.BORDER_TRANSPARENT)
    ok, jpeg = cv2.imencode(".jpg", mesa)
    return jpeg.tobytes()


def test_un_folio_torcido_sobre_la_mesa_se_endereza_a_un_rectangulo_vertical():
    r = ed.enderezar(_foto())
    assert r is not None and 0.3 <= r["area"] <= 0.94
    img = cv2.imdecode(np.frombuffer(r["imagen"], np.uint8), cv2.IMREAD_COLOR)
    alto, ancho = img.shape[:2]
    assert alto > ancho and 1.2 < alto / ancho < 1.6                                         # un folio: más alto que ancho
    assert img[:20, :20].mean() > 180                                                       # la esquina es papel, ya no mesa oscura


def test_si_el_papel_ocupa_casi_toda_la_foto_no_hay_nada_que_proponer():
    folio = np.full((1100, 780, 3), 245, np.uint8)
    for i in range(14):
        cv2.putText(folio, f"Linea {i} total 121,00", (40, 90 + i * 70), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 2)
    ok, jpeg = cv2.imencode(".jpg", folio)
    assert ed.enderezar(jpeg.tobytes()) is None


def test_una_imagen_sin_documento_o_un_archivo_roto_devuelven_nada_sin_fallar():
    liso = np.full((600, 800, 3), 90, np.uint8)
    ok, jpeg = cv2.imencode(".jpg", liso)
    assert ed.enderezar(jpeg.tobytes()) is None
    assert ed.enderezar(b"esto no es una imagen") is None
    assert ed.enderezar(b"") is None


def test_la_ruta_del_portal_devuelve_la_foto_enderezada_o_204(cliente):
    import io
    from tests.test_portal_personas_avisos import _despacho, _entrar
    t, u, c = _despacho("Enderezar web")
    _entrar(cliente, c, "titular@ejemplo.com")
    r = cliente.post("/portal/facturas/enderezar", data={"archivo": (io.BytesIO(_foto()), "f.jpg", "image/jpeg")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.headers["Cache-Control"] == "no-store" and r.data[:2] == b"\xff\xd8"
    ok, liso = cv2.imencode(".jpg", np.full((300, 400, 3), 90, np.uint8))
    assert cliente.post("/portal/facturas/enderezar", data={"archivo": (io.BytesIO(liso.tobytes()), "l.jpg", "image/jpeg")}, content_type="multipart/form-data").status_code == 204
    assert cliente.post("/portal/facturas/enderezar", data={"archivo": (io.BytesIO(b"%PDF-1.4"), "a.pdf", "application/pdf")}, content_type="multipart/form-data").status_code == 204
    assert cliente.post("/portal/facturas/enderezar").status_code == 204
