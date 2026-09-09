"""Tests de app/rutas_ia.py: por ahora solo la ruta de descarga de
adjuntos del chat (GET /ia/adjuntos/<id>) -- el resto de rutas (mensaje,
confirmar, adjuntos POST) ya se ejercitan indirectamente vía
tests/test_ia_herramientas.py y tests/test_ia_asistente.py."""
from app import db
from tests.conftest import iniciar_sesion_de_prueba


def test_descargar_adjunto_requiere_login(cliente):
    resp = cliente.get("/ia/adjuntos/1")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_descargar_adjunto_imagen_sirve_content_disposition_inline(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "ia-adjunto-imagen@ejemplo.com", "contrasena123")
    adjunto_id = db.crear_adjunto_ia(usuario_id, "foto.jpg", "image/jpeg", b"\xff\xd8\xff", origen="asistente")

    resp = cliente.get(f"/ia/adjuntos/{adjunto_id}")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith("inline")
    assert resp.data == b"\xff\xd8\xff"


def test_descargar_adjunto_csv_fuerza_descarga(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "ia-adjunto-csv@ejemplo.com", "contrasena123")
    adjunto_id = db.crear_adjunto_ia(usuario_id, "datos.csv", "text/csv", b"a,b\n1,2\n")

    resp = cliente.get(f"/ia/adjuntos/{adjunto_id}")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith("attachment")


def test_descargar_adjunto_de_otro_usuario_da_404(cliente):
    from app.auth import limiter
    from app.main import app as flask_app

    dueno_id = iniciar_sesion_de_prueba(cliente, "ia-adjunto-dueno@ejemplo.com", "contrasena123")
    adjunto_id = db.crear_adjunto_ia(dueno_id, "privado.pdf", "application/pdf", b"%PDF-1")

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as otro_cliente:
        iniciar_sesion_de_prueba(otro_cliente, "ia-adjunto-intruso@ejemplo.com", "contrasena123")
        resp = otro_cliente.get(f"/ia/adjuntos/{adjunto_id}")
        assert resp.status_code == 404
