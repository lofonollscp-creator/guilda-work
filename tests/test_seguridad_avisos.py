"""Avisos de seguridad de la cuenta (Y10): se avisa a la persona cuando se añade o quita una passkey, el segundo factor o los códigos de recuperación, y solo entonces."""
import io

import pytest

from app import db, kratos, seguridad_avisos
from tests.conftest import iniciar_sesion_de_prueba


def test_cambios_distingue_lo_anadido_de_lo_quitado_y_ignora_lo_que_no_se_sigue():
    assert seguridad_avisos.cambios({"password"}, {"password", "passkey"}) == [("passkey", "añadido")]
    assert seguridad_avisos.cambios({"password", "totp", "lookup_secret"}, {"password"}) == [("totp", "quitado"), ("lookup_secret", "quitado")]
    assert seguridad_avisos.cambios({"password"}, {"password", "oidc"}) == []                          # un método que no se sigue
    assert seguridad_avisos.cambios(None, {"password"}) == [] and seguridad_avisos.cambios({"password"}, None) == []   # sin foto: no se inventa nada


@pytest.fixture
def avisos(monkeypatch):
    enviados = []
    from app import notificaciones
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda uid, tipo, titulo, cuerpo, **kw: enviados.append((uid, tipo, titulo)))
    return enviados


def test_avisar_notifica_cada_cambio_a_la_persona(avisos, cliente):
    u = db.crear_usuario_vinculado_a_kratos("avisos@ejemplo.com", "k-avisos")
    with cliente.application.test_request_context("/"):
        hechos = seguridad_avisos.avisar(u, {"password"}, {"password", "passkey", "totp"})
    assert [h[0] for h in hechos] == ["passkey", "totp"]
    assert [a[0] for a in avisos] == [u, u] and all(a[1] == "seguridad_cuenta" for a in avisos)
    assert "passkey" in avisos[0][2] and "dos pasos" in avisos[1][2]
    with cliente.application.test_request_context("/"):
        assert seguridad_avisos.avisar(u, {"password"}, {"password"}) == []
    assert len(avisos) == 2                                                                              # sin cambios, sin aviso


class _Resp(io.BytesIO):
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_un_envio_de_ajustes_que_sale_bien_avisa_y_uno_fallido_no(cliente, avisos, monkeypatch):
    from app import rutas_kratos_proxy as proxy
    u = iniciar_sesion_de_prueba(cliente, "proxy-avisos@ejemplo.com", "contrasena123")
    fotos = iter([{"password"}, {"password", "passkey"}])
    monkeypatch.setattr(seguridad_avisos, "instantanea", lambda uid: next(fotos))
    estado = {"codigo": 200}

    class Opener:
        def open(self, peticion, timeout=None):
            r = _Resp(b"{}")
            r.status = estado["codigo"]
            return r
    monkeypatch.setattr(kratos, "opener_sin_redireccion", lambda: Opener())
    cliente.post("/.ory/self-service/settings?flow=abc", data={"method": "passkey"})
    assert len(avisos) == 1 and avisos[0][0] == u and "passkey" in avisos[0][2]
    fotos = iter([{"password"}, {"password", "passkey"}])
    estado["codigo"] = 400                                                                               # Kratos rechazó el envío: no cambió nada
    cliente.post("/.ory/self-service/settings?flow=abc", data={"method": "passkey"})
    assert len(avisos) == 1
    cliente.post("/.ory/self-service/login?flow=abc", data={"method": "password"})                        # otro flujo: ni se mira
    assert len(avisos) == 1
