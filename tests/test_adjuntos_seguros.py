"""Los archivos de usuario solo se muestran en línea si son imagen rasterizada o PDF; un SVG o un HTML se descarga."""
import pytest

from app import adjuntos_seguros as a


@pytest.mark.parametrize("tipo", ["image/png", "IMAGE/JPEG", "image/webp; charset=binary", "application/pdf"])
def test_se_muestran_en_linea(tipo):
    assert a.se_muestra_en_linea(tipo)


@pytest.mark.parametrize("tipo", ["image/svg+xml", "text/html", "application/xhtml+xml", "image/x-icon", "text/xml", "application/octet-stream", "", None])
def test_se_descargan(tipo):
    assert not a.se_muestra_en_linea(tipo)


def test_sin_pdf_en_las_notas():
    assert not a.se_muestra_en_linea("application/pdf", pdf=False) and a.se_muestra_en_linea("image/png", pdf=False)


def test_un_adjunto_svg_del_chat_se_descarga_y_va_en_sandbox(cliente):
    from app import db
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "adj@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho adjuntos"))
    for nombre, tipo, esperado in (("x.svg", "image/svg+xml", "attachment"), ("x.png", "image/png", "inline")):
        aid = db.crear_adjunto_ia(uid, nombre, tipo, b"<svg onload='alert(1)'/>")
        r = cliente.get(f"/ia/adjuntos/{aid}")
        assert r.status_code == 200 and r.headers["Content-Disposition"].startswith(esperado), tipo
        assert r.headers["X-Content-Type-Options"] == "nosniff" and "sandbox" in r.headers["Content-Security-Policy"]
