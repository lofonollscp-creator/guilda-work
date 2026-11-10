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


def test_se_pueden_subir_al_chat_fotos_y_pdf_y_se_rechaza_lo_que_no_es_texto_ni_eso(cliente):
    import io
    from tests.conftest import iniciar_sesion_de_prueba
    iniciar_sesion_de_prueba(cliente, "adjuntopdf@ejemplo.com", "contrasena123")
    def subir(contenido, nombre):
        return cliente.post("/ia/adjuntos", data={"adjunto": (io.BytesIO(contenido), nombre)}, content_type="multipart/form-data").get_json()
    pdf = subir(b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\xff", "factura.pdf")
    assert pdf["ok"] and pdf["id"]
    assert subir(b"\xff\xd8\xff\xe0" + b"0" * 100, "foto.jpg")["ok"] and subir(b"\x89PNG\r\n\x1a\n" + b"0" * 100, "foto.png")["ok"]
    r = subir(b"MZ\x90\x00\xff\xff", "virus.pdf")                                                # la extensión no cuenta: no es un PDF ni texto
    assert not r["ok"] and "fotos" in r["error"]
    assert subir("a;b\n1;2\n".encode(), "datos.csv")["ok"]
    assert not subir(b"%PDF-" + b"0" * (8 * 1024 * 1024 + 1), "grande.pdf")["ok"]
