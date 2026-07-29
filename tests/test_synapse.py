"""Tests del cliente de Synapse/Matrix (app/synapse.py) — se mockea
synapse._peticion, sin un Synapse de verdad."""
import pytest

from app import synapse


def test_listar_salas_sin_token_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(synapse, "SYNAPSE_BOT_ACCESS_TOKEN", None)
    assert synapse.listar_salas() == []


def test_listar_salas_ok(monkeypatch):
    monkeypatch.setattr(synapse, "SYNAPSE_BOT_ACCESS_TOKEN", "token-bot")

    def fake_peticion(ruta, *, metodo="GET", cuerpo=None):
        if ruta == "/_matrix/client/v3/joined_rooms":
            return 200, {"joined_rooms": ["!sala1:matrix.local"]}
        return 200, {"name": "General"}

    monkeypatch.setattr(synapse, "_peticion", fake_peticion)
    assert synapse.listar_salas() == [{"sala_id": "!sala1:matrix.local", "nombre": "General"}]


def test_enviar_mensaje_sin_token_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(synapse, "SYNAPSE_BOT_ACCESS_TOKEN", None)
    with pytest.raises(synapse.ErrorSynapse):
        synapse.enviar_mensaje("!sala1:matrix.local", "hola")


def test_enviar_mensaje_ok(monkeypatch):
    monkeypatch.setattr(synapse, "SYNAPSE_BOT_ACCESS_TOKEN", "token-bot")
    capturado = {}

    def fake_peticion(ruta, *, metodo="GET", cuerpo=None):
        capturado["metodo"] = metodo
        capturado["cuerpo"] = cuerpo
        return 200, {"event_id": "abc"}

    monkeypatch.setattr(synapse, "_peticion", fake_peticion)
    resultado = synapse.enviar_mensaje("!sala1:matrix.local", "hola")
    assert resultado["event_id"] == "abc"
    assert capturado["metodo"] == "PUT"
    assert capturado["cuerpo"]["body"] == "hola"


def test_enviar_mensaje_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(synapse, "SYNAPSE_BOT_ACCESS_TOKEN", "token-bot")
    monkeypatch.setattr(synapse, "_peticion", lambda *a, **k: (403, {"error": "sin permiso"}))
    with pytest.raises(synapse.ErrorSynapse):
        synapse.enviar_mensaje("!sala1:matrix.local", "hola")
