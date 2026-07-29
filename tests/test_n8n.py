"""Tests del cliente de n8n (app/n8n.py) — se mockea n8n._peticion, sin
un n8n de verdad."""
import pytest

from app import n8n


def test_listar_flujos_sin_api_key_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(n8n, "N8N_API_KEY", None)
    assert n8n.listar_flujos() == []


def test_listar_flujos_ok(monkeypatch):
    monkeypatch.setattr(n8n, "N8N_API_KEY", "clave")
    monkeypatch.setattr(n8n, "_peticion", lambda url, **k: (200, {"data": [{"id": "1", "name": "Flujo"}]}))
    assert n8n.listar_flujos() == [{"id": "1", "name": "Flujo"}]


def test_ejecutar_flujo_sin_api_key_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(n8n, "N8N_API_KEY", None)
    with pytest.raises(n8n.ErrorN8n):
        n8n.ejecutar_flujo("1")


def test_ejecutar_flujo_ok(monkeypatch):
    monkeypatch.setattr(n8n, "N8N_API_KEY", "clave")

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        assert metodo == "POST"
        assert url.endswith("/api/v1/workflows/1/execute")
        return 201, {"data": {"finished": True}}

    monkeypatch.setattr(n8n, "_peticion", fake_peticion)
    assert n8n.ejecutar_flujo("1")["data"]["finished"] is True


def test_ejecutar_flujo_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(n8n, "N8N_API_KEY", "clave")
    monkeypatch.setattr(n8n, "_peticion", lambda *a, **k: (404, {"message": "no existe"}))
    with pytest.raises(n8n.ErrorN8n):
        n8n.ejecutar_flujo("no-existe")
