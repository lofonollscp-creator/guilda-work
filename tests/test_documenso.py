"""Tests del cliente de Documenso (app/documenso.py) — se mockea
documenso._peticion_json/urllib, sin un Documenso de verdad.

Sin tests de aprovisionamiento (no hay ninguno — verificado en vivo que
no existe API de Equipos/miembros, ver docstring del propio módulo). Las
cuatro funciones de aquí sí se verificaron en vivo contra un contenedor
real durante el desarrollo (crear documento, enviar a firma, listar,
descargar) — incluido el bug real encontrado en `descargar_firmado`
(el id de descarga correcto es el del "envelope item", no el del
documento) y corregido antes de escribir estos tests."""
import pytest

from app import documenso as d


def test_listar_documentos_sin_api_key_devuelve_vacio():
    assert d.listar_documentos("") == []


def test_listar_documentos_ok(monkeypatch):
    monkeypatch.setattr(d, "_peticion_json", lambda ep, key, **k: (200, {"data": [{"id": "envelope_1"}]}))
    assert d.listar_documentos("api_clave") == [{"id": "envelope_1"}]


def test_listar_documentos_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(d, "_peticion_json", lambda ep, key, **k: (500, {"message": "fallo"}))
    with pytest.raises(d.ErrorDocumenso):
        d.listar_documentos("api_clave")


def test_crear_documento_sin_api_key_lanza_excepcion():
    with pytest.raises(d.ErrorDocumenso):
        d.crear_documento("", "Título", b"%PDF-1.4", [{"email": "a@b.com"}])


def test_cuerpo_multipart_incluye_payload_y_pdf():
    cuerpo, content_type = d._cuerpo_multipart({"payload": '{"title":"x"}'}, "doc.pdf", b"%PDF-1.4-contenido")
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="payload"' in cuerpo
    assert b'name="files"; filename="doc.pdf"' in cuerpo
    assert b"%PDF-1.4-contenido" in cuerpo


def test_enviar_a_firma_sin_api_key_lanza_excepcion():
    with pytest.raises(d.ErrorDocumenso):
        d.enviar_a_firma("", "envelope_1")


def test_enviar_a_firma_ok(monkeypatch):
    capturado = {}

    def fake_peticion(ep, key, *, metodo="GET", cuerpo=None):
        capturado["ep"] = ep
        capturado["cuerpo"] = cuerpo
        return 200, {"success": True}

    monkeypatch.setattr(d, "_peticion_json", fake_peticion)
    assert d.enviar_a_firma("api_clave", "envelope_1") == {"success": True}
    assert capturado["ep"] == "/envelope/distribute"
    assert capturado["cuerpo"] == {"envelopeId": "envelope_1"}


def test_enviar_a_firma_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(d, "_peticion_json", lambda ep, key, **k: (400, {"message": "no encontrado"}))
    with pytest.raises(d.ErrorDocumenso):
        d.enviar_a_firma("api_clave", "envelope_1")


def test_descargar_firmado_sin_api_key_lanza_excepcion():
    with pytest.raises(d.ErrorDocumenso):
        d.descargar_firmado("", "envelope_1")


def test_descargar_firmado_resuelve_envelope_item_id(monkeypatch):
    """Regresión del bug real encontrado en vivo: hay que descargar por
    el id del envelope item, no por el id del documento/envelope."""
    def fake_peticion(ep, key, **k):
        assert ep == "/envelope/envelope_1"
        return 200, {"envelopeItems": [{"id": "envelope_item_abc"}]}

    monkeypatch.setattr(d, "_peticion_json", fake_peticion)

    class _RespuestaFalsa:
        def read(self):
            return b"%PDF-contenido"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["url"] = req.full_url
        return _RespuestaFalsa()

    monkeypatch.setattr(d.urllib.request, "urlopen", fake_urlopen)

    resultado = d.descargar_firmado("api_clave", "envelope_1")
    assert resultado == b"%PDF-contenido"
    assert capturado["url"].endswith("/envelope/item/envelope_item_abc/download")


def test_descargar_firmado_sin_items_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(d, "_peticion_json", lambda ep, key, **k: (200, {"envelopeItems": []}))
    with pytest.raises(d.ErrorDocumenso):
        d.descargar_firmado("api_clave", "envelope_1")
