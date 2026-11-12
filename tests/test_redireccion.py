"""Open redirect: `volver_a`/`volver` y el referrer solo llevan a rutas de esta aplicación."""
import pytest

from app import db, redireccion
from app.main import app
from tests.conftest import iniciar_sesion_de_prueba


@pytest.mark.parametrize("valor", ["/tareas?x=1", "/", "/a/b#c", "http://localhost/tareas", "https://localhost/x"])
def test_destinos_locales(valor):
    with app.test_request_context("/", base_url="http://localhost"):
        assert redireccion.es_local(valor)


@pytest.mark.parametrize("valor", ["//evil.com", "/\\evil.com", "\\\\evil.com", "https://evil.com/", "http://localhost.evil.com/", "javascript:alert(1)", "/ok\r\nSet-Cookie: x=1", "evil.com", "", None, " ", "/" + "a" * 2001])
def test_destinos_ajenos(valor):
    with app.test_request_context("/", base_url="http://localhost"):
        assert not redireccion.es_local(valor)


def test_el_primer_candidato_valido_gana_y_si_no_el_defecto():
    with app.test_request_context("/", base_url="http://localhost"):
        assert redireccion.destino_local("//evil.com", "/b", por_defecto="/x") == "/b"
        assert redireccion.destino_local("https://evil.com", None, por_defecto="/x") == "/x"


@pytest.mark.parametrize("malo", ["https://evil.example/", "//evil.example", "/\\evil.example"])
def test_una_ruta_real_no_redirige_fuera(cliente, malo):
    uid = iniciar_sesion_de_prueba(cliente, "redir@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho redir"))
    tarea = db.crear_tarea_outlook(uid, "Tarea redir")
    r = cliente.post(f"/tareas/{tarea}/eliminar", data={"volver_a": malo}, base_url="http://localhost")
    assert r.status_code == 302 and "evil" not in r.headers["Location"]
