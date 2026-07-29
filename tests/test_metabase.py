"""Tests del cliente de Metabase (app/metabase.py) — preguntas/dashboards
ya guardados, nunca SQL nuevo por prompt. Se mockea metabase._peticion,
sin un Metabase de verdad."""
from app import metabase


def test_listar_preguntas_sin_api_key_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(metabase, "METABASE_API_KEY", None)
    assert metabase.listar_preguntas() == []


def test_listar_preguntas_ok(monkeypatch):
    monkeypatch.setattr(metabase, "METABASE_API_KEY", "clave")
    monkeypatch.setattr(metabase, "_peticion", lambda url, **k: (200, [{"id": 1, "name": "Ventas"}]))
    assert metabase.listar_preguntas() == [{"id": 1, "name": "Ventas"}]


def test_ejecutar_pregunta_sin_api_key_lanza_excepcion(monkeypatch):
    import pytest
    monkeypatch.setattr(metabase, "METABASE_API_KEY", None)
    with pytest.raises(metabase.ErrorMetabase):
        metabase.ejecutar_pregunta(1)


def test_ejecutar_pregunta_ok(monkeypatch):
    monkeypatch.setattr(metabase, "METABASE_API_KEY", "clave")

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        assert metodo == "POST"
        return 200, {"data": {"cols": [{"name": "total"}], "rows": [[100]]}}

    monkeypatch.setattr(metabase, "_peticion", fake_peticion)
    resultado = metabase.ejecutar_pregunta(1)
    assert resultado == {"columnas": ["total"], "filas": [[100]]}


def test_listar_dashboards_ok(monkeypatch):
    monkeypatch.setattr(metabase, "METABASE_API_KEY", "clave")
    monkeypatch.setattr(metabase, "_peticion", lambda url, **k: (200, [{"id": 2, "name": "General"}]))
    assert metabase.listar_dashboards() == [{"id": 2, "name": "General"}]
