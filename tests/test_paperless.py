"""Tests del cliente de Paperless-ngx (app/paperless.py) — se mockea
paperless._peticion/_token, sin un Paperless-ngx de verdad.

A diferencia de test_documenso.py, aquí SÍ hay tests de aprovisionamiento
(Grupo + usuario de servicio + token) porque, a diferencia de Documenso,
Paperless-ngx sí tiene una API real de Usuarios/Grupos (verificado leyendo
el código fuente, ver docstring de app/paperless.py) — el aprovisionamiento
es 100% automático.
"""
import pytest

from app import paperless as p


# --- Aprovisionamiento --------------------------------------------------

def test_aprovisionar_tenant_sin_admin_configurado_devuelve_none(monkeypatch):
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_USER", None)
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_PASSWORD", None)
    assert p.aprovisionar_tenant("Lueira") is None


def test_aprovisionar_tenant_crea_grupo_usuario_y_token(monkeypatch):
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_USER", "admin")
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_PASSWORD", "adminpass")
    monkeypatch.setattr(p, "_token_admin", lambda: "token-admin")

    llamadas = []

    def fake_peticion(endpoint, api_key, *, metodo="GET", cuerpo=None):
        llamadas.append((endpoint, metodo, cuerpo))
        if endpoint == "/api/groups/" and metodo == "POST":
            assert cuerpo == {"name": "Lueira", "permissions": p.PERMISOS_GRUPO_TENANT}
            return 201, {"id": 5}
        if endpoint == "/api/users/" and metodo == "POST":
            assert cuerpo["groups"] == [5]
            assert cuerpo["is_superuser"] is False
            return 201, {"id": 9}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(p, "_peticion", fake_peticion)
    monkeypatch.setattr(p, "_token", lambda username, password: "token-tenant-real")

    resultado = p.aprovisionar_tenant("Lueira")
    assert resultado == {"group_id": 5, "user_id": 9, "api_key": "token-tenant-real"}


def test_aprovisionar_tenant_grupo_ya_existente_es_idempotente(monkeypatch):
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_USER", "admin")
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_PASSWORD", "adminpass")
    monkeypatch.setattr(p, "_token_admin", lambda: "token-admin")

    def fake_peticion(endpoint, api_key, *, metodo="GET", cuerpo=None):
        if endpoint == "/api/groups/" and metodo == "POST":
            return 400, {"non_field_errors": ["ya existe"]}
        if endpoint.startswith("/api/groups/?") and metodo == "GET":
            return 200, {"results": [{"id": 5, "name": "Lueira"}]}
        if endpoint == "/api/users/" and metodo == "POST":
            return 201, {"id": 9}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(p, "_peticion", fake_peticion)
    monkeypatch.setattr(p, "_token", lambda username, password: "token-tenant-real")

    resultado = p.aprovisionar_tenant("Lueira")
    assert resultado["group_id"] == 5


def test_aprovisionar_tenant_usuario_ya_existente_restablece_contrasena(monkeypatch):
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_USER", "admin")
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_PASSWORD", "adminpass")
    monkeypatch.setattr(p, "_token_admin", lambda: "token-admin")

    patch_llamado = {}

    def fake_peticion(endpoint, api_key, *, metodo="GET", cuerpo=None):
        if endpoint == "/api/groups/" and metodo == "POST":
            return 201, {"id": 5}
        if endpoint == "/api/users/" and metodo == "POST":
            return 400, {"username": ["ya existe"]}
        if endpoint.startswith("/api/users/?") and metodo == "GET":
            return 200, {"results": [{"id": 9, "username": "tenant-lueira"}]}
        if endpoint == "/api/users/9/" and metodo == "PATCH":
            patch_llamado["cuerpo"] = cuerpo
            return 200, {"id": 9}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(p, "_peticion", fake_peticion)
    monkeypatch.setattr(p, "_token", lambda username, password: "token-tenant-real")

    resultado = p.aprovisionar_tenant("Lueira")
    assert resultado["user_id"] == 9
    assert "password" in patch_llamado["cuerpo"]


def test_desaprovisionar_tenant_sin_admin_configurado_no_hace_nada(monkeypatch):
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_USER", None)
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_PASSWORD", None)
    p.desaprovisionar_tenant(9, 5)  # no debe lanzar


def test_desaprovisionar_tenant_borra_usuario_y_grupo(monkeypatch):
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_USER", "admin")
    monkeypatch.setattr(p, "PAPERLESS_ADMIN_PASSWORD", "adminpass")
    monkeypatch.setattr(p, "_token_admin", lambda: "token-admin")

    llamadas = []
    monkeypatch.setattr(p, "_peticion", lambda endpoint, api_key, **k: (llamadas.append(endpoint), (204, {}))[1])

    p.desaprovisionar_tenant(9, 5)
    assert "/api/users/9/" in llamadas
    assert "/api/groups/5/" in llamadas


# --- API de negocio -------------------------------------------------------

def test_listar_documentos_sin_api_key_devuelve_vacio():
    assert p.listar_documentos("") == []


def test_listar_documentos_ok(monkeypatch):
    monkeypatch.setattr(p, "_peticion", lambda ep, key, **k: (200, {"results": [{"id": 1, "title": "Factura"}]}))
    assert p.listar_documentos("api_clave") == [{"id": 1, "title": "Factura"}]


def test_listar_documentos_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(p, "_peticion", lambda ep, key, **k: (500, {"detail": "fallo"}))
    with pytest.raises(p.ErrorPaperless):
        p.listar_documentos("api_clave")


def test_subir_documento_sin_api_key_lanza_excepcion():
    with pytest.raises(p.ErrorPaperless):
        p.subir_documento("", 9, 5, "Título", b"%PDF-1.4", "doc.pdf")


def test_subir_documento_sube_espera_tarea_y_aplica_permisos(monkeypatch):
    """Regresión del flujo real: subir (multipart, urllib directo, sin
    pasar por _peticion) → sondear /api/tasks/ hasta SUCCESS → PATCH con
    owner + set_permissions restringidos al Grupo del tenant."""

    class _RespuestaFalsa:
        def __init__(self, cuerpo: bytes):
            self._cuerpo = cuerpo

        def read(self):
            return self._cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        import json
        return _RespuestaFalsa(json.dumps("tarea-uuid-1").encode("utf-8"))

    monkeypatch.setattr(p.urllib.request, "urlopen", fake_urlopen)

    llamadas_patch = {}

    def fake_peticion(endpoint, api_key, *, metodo="GET", cuerpo=None):
        if endpoint.startswith("/api/tasks/?task_id="):
            # Verificado en vivo: status en minúscula, y el id del
            # documento viaja en una LISTA (related_document_ids), no en
            # un campo singular.
            return 200, {"results": [{"status": "success", "related_document_ids": [42]}]}
        if endpoint == "/api/documents/42/" and metodo == "PATCH":
            llamadas_patch["cuerpo"] = cuerpo
            return 200, {"id": 42, "title": "Factura"}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(p, "_peticion", fake_peticion)

    resultado = p.subir_documento("api_clave", 9, 5, "Factura", b"%PDF-1.4", "doc.pdf")
    assert resultado == {"id": 42, "title": "Factura"}
    assert llamadas_patch["cuerpo"]["owner"] == 9
    assert llamadas_patch["cuerpo"]["set_permissions"]["view"]["groups"] == [5]
    assert llamadas_patch["cuerpo"]["set_permissions"]["change"]["groups"] == [5]


def test_descargar_documento_sin_api_key_lanza_excepcion():
    with pytest.raises(p.ErrorPaperless):
        p.descargar_documento("", "42")


def test_descargar_documento_ok(monkeypatch):
    class _RespuestaFalsa:
        def read(self):
            return b"%PDF-contenido"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(p.urllib.request, "urlopen", lambda req, timeout=None: _RespuestaFalsa())
    assert p.descargar_documento("api_clave", "42") == b"%PDF-contenido"
