"""Tests del cliente de OpenProject (app/openproject.py) — mismo criterio
que tests/test_espocrm.py: se mockea openproject._peticion, sin un
OpenProject de verdad."""
import pytest

from app import openproject


def test_listar_proyectos_sin_token_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(openproject, "OPENPROJECT_API_TOKEN", None)
    assert openproject.listar_proyectos() == []


def test_listar_proyectos_ok(monkeypatch):
    monkeypatch.setattr(openproject, "OPENPROJECT_API_TOKEN", "token")
    monkeypatch.setattr(
        openproject, "_peticion",
        lambda url, **k: (200, {"_embedded": {"elements": [{"id": 1, "name": "Lueira"}]}}),
    )
    assert openproject.listar_proyectos() == [{"id": 1, "name": "Lueira"}]


def test_listar_paquetes_trabajo_filtra_por_proyecto(monkeypatch):
    monkeypatch.setattr(openproject, "OPENPROJECT_API_TOKEN", "token")
    capturado = {}

    def fake_peticion(url, **k):
        capturado["url"] = url
        return 200, {"_embedded": {"elements": [{"id": 5, "subject": "Tarea"}]}}

    monkeypatch.setattr(openproject, "_peticion", fake_peticion)
    resultado = openproject.listar_paquetes_trabajo(proyecto_id=1, texto="Tarea")
    assert resultado == [{"id": 5, "subject": "Tarea"}]
    assert "/projects/1/work_packages" in capturado["url"]


def test_listar_paquetes_trabajo_sin_proyecto_usa_endpoint_global(monkeypatch):
    monkeypatch.setattr(openproject, "OPENPROJECT_API_TOKEN", "token")
    capturado = {}

    def fake_peticion(url, **k):
        capturado["url"] = url
        return 200, {"_embedded": {"elements": []}}

    monkeypatch.setattr(openproject, "_peticion", fake_peticion)
    openproject.listar_paquetes_trabajo()
    assert capturado["url"].startswith(f"{openproject.OPENPROJECT_URL}/api/v3/work_packages")


def test_crear_paquete_trabajo_sin_token_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(openproject, "OPENPROJECT_API_TOKEN", None)
    with pytest.raises(openproject.ErrorOpenProject):
        openproject.crear_paquete_trabajo(1, "Nueva tarea")


def test_crear_paquete_trabajo_ok(monkeypatch):
    monkeypatch.setattr(openproject, "OPENPROJECT_API_TOKEN", "token")

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        assert metodo == "POST"
        assert cuerpo["subject"] == "Nueva tarea"
        return 201, {"id": 42, "subject": "Nueva tarea"}

    monkeypatch.setattr(openproject, "_peticion", fake_peticion)
    assert openproject.crear_paquete_trabajo(1, "Nueva tarea")["id"] == 42


def test_crear_paquete_trabajo_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(openproject, "OPENPROJECT_API_TOKEN", "token")
    monkeypatch.setattr(openproject, "_peticion", lambda *a, **k: (422, {"message": "inválido"}))
    with pytest.raises(openproject.ErrorOpenProject):
        openproject.crear_paquete_trabajo(1, "x")
