"""Tests del cliente de Nextcloud (app/nextcloud.py) — mismo criterio que
tests/test_espocrm.py: se mockea nextcloud._peticion, sin un Nextcloud
de verdad."""
import pytest

from app import nextcloud

_PROPFIND_RESPUESTA = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/admin/Lueira/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/admin/Lueira/contrato.pdf</d:href>
    <d:propstat><d:prop><d:resourcetype/><d:getcontentlength>1024</d:getcontentlength></d:prop></d:propstat>
  </d:response>
</d:multistatus>"""


def test_crear_espacio_tenant_sin_credenciales_no_hace_nada(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", None)
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", None)
    assert nextcloud.crear_espacio_tenant("Lueira") is None


def test_crear_espacio_tenant_crea_grupo_y_carpeta(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")

    llamadas = []

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        llamadas.append((metodo, url, cuerpo))
        if "cloud/groups" in url:
            return 200, {"ocs": {"meta": {"statuscode": 100}}}
        if url.endswith("/apps/groupfolders/folders?format=json") and metodo == "GET":
            return 200, {"ocs": {"data": []}}
        if url.endswith("/apps/groupfolders/folders?format=json") and metodo == "POST":
            return 200, {"ocs": {"data": {"id": 7}}}
        if "/apps/groupfolders/folders/7/groups" in url:
            return 200, {"ocs": {"meta": {"statuscode": 100}}}
        raise AssertionError(f"llamada inesperada: {metodo} {url}")

    monkeypatch.setattr(nextcloud, "_peticion", fake_peticion)

    nextcloud.crear_espacio_tenant("Lueira")

    metodos_y_urls = [(m, u) for m, u, _ in llamadas]
    assert ("POST", f"{nextcloud.NEXTCLOUD_URL}/ocs/v1.php/cloud/groups?format=json") in metodos_y_urls
    assert ("POST", f"{nextcloud.NEXTCLOUD_URL}/apps/groupfolders/folders?format=json") in metodos_y_urls
    assert (
        "POST",
        f"{nextcloud.NEXTCLOUD_URL}/apps/groupfolders/folders/7/groups?format=json",
    ) in metodos_y_urls


def test_crear_espacio_tenant_grupo_ya_existente_no_falla(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        if "cloud/groups" in url:
            return 200, {"ocs": {"meta": {"statuscode": 102}}}  # ya existe
        if "/apps/groupfolders/folders?format=json" in url and metodo == "GET":
            return 200, {"ocs": {"data": []}}
        if "/apps/groupfolders/folders?format=json" in url and metodo == "POST":
            return 200, {"ocs": {"data": {"id": 1}}}
        return 200, {"ocs": {"meta": {"statuscode": 100}}}

    monkeypatch.setattr(nextcloud, "_peticion", fake_peticion)

    nextcloud.crear_espacio_tenant("Lueira")  # no debe lanzar


def test_crear_espacio_tenant_carpeta_ya_existente_es_idempotente(monkeypatch):
    """Si ya existe un Group Folder con ese mountpoint (repetir el alta
    del mismo tenant), se reutiliza en vez de crear uno duplicado."""
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")

    llamadas = []

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        llamadas.append((metodo, url))
        if "cloud/groups" in url:
            return 200, {"ocs": {"meta": {"statuscode": 100}}}
        if "/apps/groupfolders/folders?format=json" in url and metodo == "GET":
            return 200, {"ocs": {"data": [{"id": 3, "mount_point": "Lueira"}]}}
        if "/apps/groupfolders/folders/3/groups" in url:
            return 200, {"ocs": {"meta": {"statuscode": 100}}}
        raise AssertionError(f"no debería crear una carpeta nueva: {metodo} {url}")

    monkeypatch.setattr(nextcloud, "_peticion", fake_peticion)

    nextcloud.crear_espacio_tenant("Lueira")

    assert ("POST", f"{nextcloud.NEXTCLOUD_URL}/apps/groupfolders/folders?format=json") not in [
        (m, u) for m, u in llamadas
    ]


def test_listar_archivos_sin_credenciales_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", None)
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", None)
    assert nextcloud.listar_archivos("Lueira") == []


def test_listar_archivos_parsea_el_multistatus(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")

    def fake_peticion_webdav(url, *, metodo, cuerpo=None, cabeceras_extra=None):
        assert metodo == "PROPFIND"
        return 207, _PROPFIND_RESPUESTA

    monkeypatch.setattr(nextcloud, "_peticion_webdav", fake_peticion_webdav)
    resultado = nextcloud.listar_archivos("Lueira")
    assert resultado == [{"nombre": "contrato.pdf", "es_carpeta": False, "tamano_bytes": 1024}]


def test_listar_archivos_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")
    monkeypatch.setattr(nextcloud, "_peticion_webdav", lambda *a, **k: (404, b""))
    with pytest.raises(nextcloud.ErrorNextcloud):
        nextcloud.listar_archivos("NoExiste")


def test_subir_archivo_ok(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")
    capturado = {}

    def fake_peticion_webdav(url, *, metodo, cuerpo=None, cabeceras_extra=None):
        capturado["metodo"] = metodo
        capturado["cuerpo"] = cuerpo
        return 201, b""

    monkeypatch.setattr(nextcloud, "_peticion_webdav", fake_peticion_webdav)
    resultado = nextcloud.subir_archivo("Lueira/nota.txt", b"hola")
    assert resultado == {"ruta": "Lueira/nota.txt", "subido": True}
    assert capturado["metodo"] == "PUT"
    assert capturado["cuerpo"] == b"hola"


def test_subir_archivo_sin_credenciales_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", None)
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", None)
    with pytest.raises(nextcloud.ErrorNextcloud):
        nextcloud.subir_archivo("Lueira/nota.txt", b"hola")


def test_descargar_archivo_ok(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")
    monkeypatch.setattr(nextcloud, "_peticion_webdav", lambda *a, **k: (200, b"contenido real"))
    assert nextcloud.descargar_archivo("Lueira/nota.txt") == b"contenido real"


def test_buscar_archivos_sin_credenciales_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", None)
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", None)
    assert nextcloud.buscar_archivos("contrato") == []


def test_buscar_archivos_ok(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")

    def fake_peticion_webdav(url, *, metodo, cuerpo=None, cabeceras_extra=None):
        assert metodo == "SEARCH"
        return 207, _PROPFIND_RESPUESTA

    monkeypatch.setattr(nextcloud, "_peticion_webdav", fake_peticion_webdav)
    resultado = nextcloud.buscar_archivos("contrato")
    assert any(r["nombre"] == "contrato.pdf" for r in resultado)


def test_crear_espacio_tenant_error_real_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "clave")

    def fake_peticion(url, *, metodo="GET", cuerpo=None):
        if "cloud/groups" in url:
            return 200, {"ocs": {"meta": {"statuscode": 999, "message": "error interno"}}}
        return 200, {"ocs": {}}

    monkeypatch.setattr(nextcloud, "_peticion", fake_peticion)

    try:
        nextcloud.crear_espacio_tenant("Lueira")
        assert False, "debería haber lanzado ErrorNextcloud"
    except nextcloud.ErrorNextcloud as e:
        assert "error interno" in str(e)
