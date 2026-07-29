"""Tests del cliente de Ory Hydra (app/hydra.py) — construcción del
id_token en aceptar_consent_request, sin un Hydra de verdad (se mockea
hydra._peticion, mismo criterio que tests/test_rutas_hydra.py mockea
hydra.aceptar_consent_request un nivel más arriba)."""
from app import hydra


def test_aceptar_consent_incluye_groups_si_hay_tenant(monkeypatch):
    capturado = {}

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        capturado["cuerpo"] = cuerpo
        return 200, {"redirect_to": "https://crm.localhost/callback?code=abc"}

    monkeypatch.setattr(hydra, "_peticion", fake_peticion)

    hydra.aceptar_consent_request(
        "challenge123", scopes=["openid", "email"], email="a@b.com", tenant_nombre="Lueira"
    )

    assert capturado["cuerpo"]["session"]["id_token"] == {"email": "a@b.com", "groups": ["Lueira"]}


def test_aceptar_consent_omite_groups_sin_tenant(monkeypatch):
    capturado = {}

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        capturado["cuerpo"] = cuerpo
        return 200, {"redirect_to": "https://outline.localhost/callback?code=abc"}

    monkeypatch.setattr(hydra, "_peticion", fake_peticion)

    hydra.aceptar_consent_request("challenge123", scopes=["openid", "email"], email="a@b.com")

    assert capturado["cuerpo"]["session"]["id_token"] == {"email": "a@b.com"}
    assert "groups" not in capturado["cuerpo"]["session"]["id_token"]
