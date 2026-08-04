"""Tests del cliente de embeddings de Ollama (app/embeddings.py) — se
mockea urllib.request.urlopen, sin un Ollama de verdad.

El formato real de la API (`POST /api/embed` -> `{"embeddings": [[...]]}`,
768 dimensiones con `nomic-embed-text`) se verificó en vivo contra un
Ollama real antes de escribir este módulo — ver el docstring propio y
el de app/busqueda.py. Aquí solo se comprueba que app/embeddings.py
interpreta correctamente esa forma y degrada con gracia cuando Ollama
no está disponible."""
import json
import urllib.error

import pytest

from app import embeddings as e


class _RespuestaFalsa:
    def __init__(self, cuerpo: bytes):
        self._cuerpo = cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._cuerpo


def test_generar_embedding_devuelve_el_primer_vector(monkeypatch):
    cuerpo = json.dumps({"embeddings": [[0.1, 0.2, 0.3]], "model": "nomic-embed-text"}).encode()
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["url"] = req.full_url
        capturado["body"] = json.loads(req.data)
        return _RespuestaFalsa(cuerpo)

    monkeypatch.setattr(e.urllib.request, "urlopen", fake_urlopen)
    vector = e.generar_embedding("texto de prueba")

    assert vector == [0.1, 0.2, 0.3]
    assert capturado["url"] == e.OLLAMA_EMBED_URL
    assert capturado["body"] == {"model": e.OLLAMA_EMBED_MODEL, "input": "texto de prueba"}


def test_generar_embedding_texto_vacio_no_llama_a_ollama(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise AssertionError("no debería llamar a Ollama con texto vacío")

    monkeypatch.setattr(e.urllib.request, "urlopen", fake_urlopen)
    assert e.generar_embedding("   ") is None


def test_generar_embedding_ollama_no_disponible_devuelve_none(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("conexión rechazada")

    monkeypatch.setattr(e.urllib.request, "urlopen", fake_urlopen)
    assert e.generar_embedding("texto") is None


def test_generar_embedding_respuesta_sin_embeddings_devuelve_none(monkeypatch):
    cuerpo = json.dumps({"error": "model not found"}).encode()
    monkeypatch.setattr(e.urllib.request, "urlopen", lambda req, timeout=None: _RespuestaFalsa(cuerpo))
    assert e.generar_embedding("texto") is None


def test_generar_embedding_respuesta_json_invalido_devuelve_none(monkeypatch):
    monkeypatch.setattr(e.urllib.request, "urlopen", lambda req, timeout=None: _RespuestaFalsa(b"no es json"))
    assert e.generar_embedding("texto") is None
