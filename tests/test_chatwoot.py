"""Tests del cliente de Chatwoot (app/chatwoot.py) — conversaciones vía
Application API (CHATWOOT_AGENT_API_TOKEN, distinta de la Platform API
usada para altas de usuarios). Se mockea chatwoot._peticion_agente, sin
un Chatwoot de verdad."""
import pytest

from app import chatwoot


def test_listar_conversaciones_sin_token_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(chatwoot, "CHATWOOT_AGENT_API_TOKEN", None)
    assert chatwoot.listar_conversaciones() == []


def test_listar_conversaciones_ok(monkeypatch):
    monkeypatch.setattr(chatwoot, "CHATWOOT_AGENT_API_TOKEN", "token-agente")
    monkeypatch.setattr(
        chatwoot, "_peticion_agente",
        lambda url, **k: (200, {"data": {"payload": [{"id": 1}, {"id": 2}]}}),
    )
    assert chatwoot.listar_conversaciones(limite=1) == [{"id": 1}]


def test_leer_conversacion_sin_token_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(chatwoot, "CHATWOOT_AGENT_API_TOKEN", None)
    with pytest.raises(chatwoot.ErrorChatwoot):
        chatwoot.leer_conversacion(1)


def test_leer_conversacion_ok(monkeypatch):
    monkeypatch.setattr(chatwoot, "CHATWOOT_AGENT_API_TOKEN", "token-agente")
    monkeypatch.setattr(
        chatwoot, "_peticion_agente", lambda url, **k: (200, {"payload": [{"content": "hola"}]})
    )
    assert chatwoot.leer_conversacion(1) == [{"content": "hola"}]


def test_responder_conversacion_ok(monkeypatch):
    monkeypatch.setattr(chatwoot, "CHATWOOT_AGENT_API_TOKEN", "token-agente")
    capturado = {}

    def fake_peticion_agente(url, *, metodo="GET", cuerpo=None):
        capturado["cuerpo"] = cuerpo
        return 201, {"id": 9, "content": "respuesta"}

    monkeypatch.setattr(chatwoot, "_peticion_agente", fake_peticion_agente)
    resultado = chatwoot.responder_conversacion(1, "respuesta")
    assert resultado["id"] == 9
    assert capturado["cuerpo"]["message_type"] == "outgoing"


def test_responder_conversacion_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(chatwoot, "CHATWOOT_AGENT_API_TOKEN", "token-agente")
    monkeypatch.setattr(chatwoot, "_peticion_agente", lambda *a, **k: (500, {"message": "fallo"}))
    with pytest.raises(chatwoot.ErrorChatwoot):
        chatwoot.responder_conversacion(1, "x")
