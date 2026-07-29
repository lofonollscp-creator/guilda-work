"""Tests del cliente de Outline (app/outline.py) — se mockea
outline._peticion, sin un Outline de verdad."""
import pytest

from app import outline


def test_listar_colecciones_sin_token_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(outline, "OUTLINE_API_TOKEN", None)
    assert outline.listar_colecciones() == []


def test_buscar_documentos_sin_token_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(outline, "OUTLINE_API_TOKEN", None)
    assert outline.buscar_documentos("contrato") == []


def test_buscar_documentos_ok(monkeypatch):
    monkeypatch.setattr(outline, "OUTLINE_API_TOKEN", "token")

    def fake_peticion(endpoint, cuerpo=None):
        assert endpoint == "documents.search"
        assert cuerpo["query"] == "contrato"
        return 200, {"data": [{"document": {"id": "d1", "title": "Contrato"}}]}

    monkeypatch.setattr(outline, "_peticion", fake_peticion)
    assert outline.buscar_documentos("contrato") == [{"id": "d1", "title": "Contrato"}]


def test_leer_documento_sin_token_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(outline, "OUTLINE_API_TOKEN", None)
    with pytest.raises(outline.ErrorOutline):
        outline.leer_documento("d1")


def test_leer_documento_ok(monkeypatch):
    monkeypatch.setattr(outline, "OUTLINE_API_TOKEN", "token")
    monkeypatch.setattr(outline, "_peticion", lambda e, c=None: (200, {"data": {"id": "d1", "text": "hola"}}))
    assert outline.leer_documento("d1")["text"] == "hola"


def test_crear_documento_ok(monkeypatch):
    monkeypatch.setattr(outline, "OUTLINE_API_TOKEN", "token")

    def fake_peticion(endpoint, cuerpo=None):
        assert endpoint == "documents.create"
        assert cuerpo["title"] == "Nuevo"
        return 200, {"data": {"id": "d2", "title": "Nuevo"}}

    monkeypatch.setattr(outline, "_peticion", fake_peticion)
    assert outline.crear_documento("col1", "Nuevo")["id"] == "d2"


def test_crear_documento_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(outline, "OUTLINE_API_TOKEN", "token")
    monkeypatch.setattr(outline, "_peticion", lambda e, c=None: (400, {"error": "inválido"}))
    with pytest.raises(outline.ErrorOutline):
        outline.crear_documento("col1", "x")
