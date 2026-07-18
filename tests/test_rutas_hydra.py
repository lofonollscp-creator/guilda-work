"""Tests del puente de login/consentimiento de Ory Hydra (app/rutas_hydra.py).

No usan un Hydra de verdad (a diferencia de los tests de Kratos, ver
conftest.py) — aquí basta con simular las respuestas de `hydra.py`/
`kratos.py` con monkeypatch, ya que lo que se prueba es la lógica propia
del puente, no la integración HTTP con Hydra en sí.
"""
from app import db
from app import rutas_hydra


def test_consent_provisiona_usuario_si_hydra_se_salta_el_login(cliente, monkeypatch):
    """Reproduce el bug real encontrado verificando Element: si Hydra ya
    recuerda una sesión de login de OTRO cliente OAuth2 para este mismo
    usuario, /hydra/login nunca llega a ejecutarse de verdad y la fila
    local puede no existir todavía en el momento del consentimiento —
    antes de este fix, eso mandaba email="" a la app cliente (Synapse
    lo rechazaba con "localpart is invalid")."""
    identity_id = "identidad-sin-fila-local"

    monkeypatch.setattr(
        rutas_hydra.hydra, "obtener_consent_request",
        lambda challenge: {"subject": identity_id, "requested_scope": ["openid", "email"]},
    )
    monkeypatch.setattr(
        rutas_hydra.kratos, "obtener_identidad",
        lambda subject: {"traits": {"email": "nueva-identidad@ejemplo.com"}},
    )
    capturado = {}

    def fake_aceptar_consent(challenge, *, scopes, email):
        capturado["email"] = email
        capturado["scopes"] = scopes
        return "https://matrix.localhost:8443/_synapse/client/oidc/callback?code=abc"

    monkeypatch.setattr(rutas_hydra.hydra, "aceptar_consent_request", fake_aceptar_consent)

    assert db.usuario_por_kratos_id(identity_id) is None

    resp = cliente.get("/hydra/consent?consent_challenge=abc123")

    assert resp.status_code == 302
    assert capturado["email"] == "nueva-identidad@ejemplo.com"
    usuario = db.usuario_por_kratos_id(identity_id)
    assert usuario is not None
    assert usuario["email"] == "nueva-identidad@ejemplo.com"


def test_consent_usa_la_fila_existente_si_ya_habia_una(cliente, monkeypatch):
    identity_id = "identidad-ya-conocida"
    db.crear_usuario_vinculado_a_kratos("conocido@ejemplo.com", identity_id)

    monkeypatch.setattr(
        rutas_hydra.hydra, "obtener_consent_request",
        lambda challenge: {"subject": identity_id, "requested_scope": ["openid", "email"]},
    )

    def obtener_identidad_no_deberia_llamarse(subject):
        raise AssertionError("no debería consultar Kratos si la fila local ya existe")

    monkeypatch.setattr(rutas_hydra.kratos, "obtener_identidad", obtener_identidad_no_deberia_llamarse)

    capturado = {}

    def fake_aceptar_consent(challenge, *, scopes, email):
        capturado["email"] = email
        return "https://matrix.localhost:8443/_synapse/client/oidc/callback?code=abc"

    monkeypatch.setattr(rutas_hydra.hydra, "aceptar_consent_request", fake_aceptar_consent)

    resp = cliente.get("/hydra/consent?consent_challenge=abc123")

    assert resp.status_code == 302
    assert capturado["email"] == "conocido@ejemplo.com"
