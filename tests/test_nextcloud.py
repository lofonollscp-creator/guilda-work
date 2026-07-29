"""Tests del cliente de Nextcloud (app/nextcloud.py) — mismo criterio que
tests/test_espocrm.py: se mockea nextcloud._peticion, sin un Nextcloud
de verdad."""
from app import nextcloud


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
