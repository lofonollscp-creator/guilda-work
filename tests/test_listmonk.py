"""Tests del cliente de Listmonk (app/listmonk.py) — se mockean
listmonk._peticion/_sesion_admin, sin un Listmonk de verdad.

El diseño en sí (dos Roles: uno de usuario compartido con los permisos
de acción, uno de lista por tenant con list:get/list:manage; sesión por
cookie para las llamadas de admin; token en la propia respuesta de
POST /api/users tipo "api") se verificó en vivo contra un contenedor
real durante el desarrollo — ver el docstring del propio módulo. Aquí
solo se comprueba que app/listmonk.py ORQUESTA las llamadas correctas."""
import pytest

from app import listmonk as l


_OPENER = object()  # sentinel: las llamadas HTTP reales están mockeadas


def _mock_sesion_admin_ok(monkeypatch):
    monkeypatch.setattr(l, "_sesion_admin", lambda: _OPENER)


# --- _sesion_admin / bootstrap -----------------------------------------

def test_aprovisionar_tenant_sin_credenciales_devuelve_none(monkeypatch):
    monkeypatch.setattr(l, "LISTMONK_ADMIN_USER", None)
    monkeypatch.setattr(l, "LISTMONK_ADMIN_PASSWORD", None)
    assert l.aprovisionar_tenant("Lueira") is None


# --- aprovisionar_tenant --------------------------------------------------

def test_aprovisionar_tenant_completo_ok(monkeypatch):
    _mock_sesion_admin_ok(monkeypatch)
    llamadas = []

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        llamadas.append((endpoint, metodo, cuerpo))
        if endpoint == "/api/lists" and metodo == "GET":
            return 200, {"data": {"results": []}}
        if endpoint == "/api/lists" and metodo == "POST":
            return 201, {"data": {"id": 3, "name": "Lueira"}}
        if endpoint == "/api/roles/lists" and metodo == "GET":
            return 200, {"data": {"results": []}}
        if endpoint == "/api/roles/lists" and metodo == "POST":
            return 200, {"data": {"id": 5, "name": "Lueira"}}
        if endpoint == "/api/roles/users" and metodo == "GET":
            return 200, {"data": {"results": []}}
        if endpoint == "/api/roles/users" and metodo == "POST":
            return 200, {"data": {"id": 2, "name": "Tenant"}}
        if endpoint == "/api/users" and metodo == "POST":
            return 200, {"data": {"id": 9, "username": "tenant-lueira-api", "password": "eltoken123"}}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    resultado = l.aprovisionar_tenant("Lueira")

    assert resultado == {"list_id": 3, "list_role_id": 5, "api_key": "tenant-lueira-api:eltoken123"}
    # la lista se creó con nombre correcto, el rol de lista solo con list:get/list:manage
    cuerpo_lista = next(c for e, m, c in llamadas if e == "/api/lists" and m == "POST")
    assert cuerpo_lista["name"] == "Lueira"
    cuerpo_rol = next(c for e, m, c in llamadas if e == "/api/roles/lists" and m == "POST")
    assert cuerpo_rol["lists"] == [{"id": 3, "permissions": ["list:get", "list:manage"]}]
    cuerpo_usuario = next(c for e, m, c in llamadas if e == "/api/users" and m == "POST")
    assert cuerpo_usuario["type"] == "api"
    assert cuerpo_usuario["list_role_id"] == 5
    assert cuerpo_usuario["user_role_id"] == 2


def test_aprovisionar_tenant_idempotente_reutiliza_lista_y_rol(monkeypatch):
    _mock_sesion_admin_ok(monkeypatch)

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        if endpoint == "/api/lists" and metodo == "GET":
            return 200, {"data": {"results": [{"id": 3, "name": "Lueira"}]}}
        if endpoint == "/api/roles/lists" and metodo == "GET":
            return 200, {"data": {"results": [{"id": 5, "name": "Lueira"}]}}
        if endpoint == "/api/roles/users" and metodo == "GET":
            return 200, {"data": {"results": [{"id": 2, "name": "Tenant"}]}}
        if endpoint == "/api/users" and metodo == "POST":
            return 200, {"data": {"id": 9, "username": "tenant-lueira-api", "password": "otrotoken"}}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    resultado = l.aprovisionar_tenant("Lueira")
    assert resultado["list_id"] == 3
    assert resultado["list_role_id"] == 5


def test_aprovisionar_tenant_usuario_ya_existe_lo_recrea(monkeypatch):
    """Verificado en vivo: Listmonk no vuelve a enseñar el token de un
    usuario 'api' ya creado — hay que borrarlo y recrearlo."""
    _mock_sesion_admin_ok(monkeypatch)
    llamadas = []

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        llamadas.append((endpoint, metodo))
        if endpoint == "/api/lists" and metodo == "GET":
            return 200, {"data": {"results": [{"id": 3, "name": "Lueira"}]}}
        if endpoint == "/api/roles/lists" and metodo == "GET":
            return 200, {"data": {"results": [{"id": 5, "name": "Lueira"}]}}
        if endpoint == "/api/roles/users" and metodo == "GET":
            return 200, {"data": {"results": [{"id": 2, "name": "Tenant"}]}}
        if endpoint == "/api/users" and metodo == "POST":
            n_previos = sum(1 for e, m in llamadas if e == "/api/users" and m == "POST")
            if n_previos <= 1:
                return 409, {"message": "username already exists"}
            return 200, {"data": {"id": 9, "username": "tenant-lueira-api", "password": "tokennuevo"}}
        if endpoint == "/api/users" and metodo == "GET":
            return 200, {"data": {"results": [{"id": 9, "username": "tenant-lueira-api"}]}}
        if endpoint == "/api/users/9" and metodo == "DELETE":
            return 200, {"data": True}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    resultado = l.aprovisionar_tenant("Lueira")
    assert resultado["api_key"] == "tenant-lueira-api:tokennuevo"
    assert ("/api/users/9", "DELETE") in llamadas


def test_aprovisionar_tenant_error_real_lanza_excepcion(monkeypatch):
    _mock_sesion_admin_ok(monkeypatch)
    monkeypatch.setattr(l, "_peticion", lambda *a, **k: (500, {"message": "fallo interno"}))
    with pytest.raises(l.ErrorListmonk):
        l.aprovisionar_tenant("Lueira")


# --- crear_usuario_tenant ----------------------------------------------

def test_crear_usuario_tenant_sin_credenciales_no_hace_nada(monkeypatch):
    monkeypatch.setattr(l, "LISTMONK_ADMIN_USER", None)
    monkeypatch.setattr(l, "LISTMONK_ADMIN_PASSWORD", None)
    l.crear_usuario_tenant("persona@ejemplo.com", 5)  # no debe lanzar


def test_crear_usuario_tenant_nuevo(monkeypatch):
    _mock_sesion_admin_ok(monkeypatch)
    llamadas = []

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        llamadas.append((endpoint, metodo, cuerpo))
        if endpoint == "/api/roles/users" and metodo == "GET":
            return 200, {"data": {"results": [{"id": 2, "name": "Tenant"}]}}
        if endpoint == "/api/users" and metodo == "GET":
            return 200, {"data": {"results": []}}
        if endpoint == "/api/users" and metodo == "POST":
            return 201, {"data": {"id": 4}}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    l.crear_usuario_tenant("persona@ejemplo.com", 5)
    cuerpo = next(c for e, m, c in llamadas if e == "/api/users" and m == "POST")
    assert cuerpo["email"] == "persona@ejemplo.com"
    assert cuerpo["password_login"] is False
    assert cuerpo["list_role_id"] == 5


def test_crear_usuario_tenant_error_lanza_excepcion(monkeypatch):
    _mock_sesion_admin_ok(monkeypatch)

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        if metodo == "GET":
            return 200, {"data": {"results": []}}
        return 500, {"message": "fallo"}

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    with pytest.raises(l.ErrorListmonk):
        l.crear_usuario_tenant("persona@ejemplo.com", 5)


# --- desaprovisionar_tenant ----------------------------------------------

def test_desaprovisionar_tenant_sin_credenciales_no_hace_nada(monkeypatch):
    monkeypatch.setattr(l, "LISTMONK_ADMIN_USER", None)
    monkeypatch.setattr(l, "LISTMONK_ADMIN_PASSWORD", None)
    l.desaprovisionar_tenant(3, 5)  # no debe lanzar


def test_desaprovisionar_tenant_borra_lista_y_rol(monkeypatch):
    _mock_sesion_admin_ok(monkeypatch)
    llamadas = []
    monkeypatch.setattr(l, "_peticion", lambda endpoint, **k: (llamadas.append((endpoint, k.get("metodo"))), (200, {}))[1])
    l.desaprovisionar_tenant(3, 5)
    assert ("/api/roles/5", "DELETE") in llamadas
    assert ("/api/lists/3", "DELETE") in llamadas


# --- API de negocio ---------------------------------------------------------

def test_listar_suscriptores_sin_api_key_devuelve_vacio():
    assert l.listar_suscriptores("", 3) == []


def test_listar_suscriptores_ok(monkeypatch):
    capturado = {}

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        capturado["endpoint"] = endpoint
        capturado["cabeceras"] = cabeceras
        return 200, {"data": {"results": [{"email": "a@b.com"}]}}

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    resultado = l.listar_suscriptores("usuario:token", 3)
    assert resultado == [{"email": "a@b.com"}]
    assert "list_id=3" in capturado["endpoint"]
    assert capturado["cabeceras"] == {"Authorization": "token usuario:token"}


def test_listar_suscriptores_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(l, "_peticion", lambda *a, **k: (500, {"message": "fallo"}))
    with pytest.raises(l.ErrorListmonk):
        l.listar_suscriptores("usuario:token", 3)


def test_crear_suscriptor_sin_api_key_lanza_excepcion():
    with pytest.raises(l.ErrorListmonk):
        l.crear_suscriptor("", 3, "a@b.com", "Ana")


def test_crear_suscriptor_ok(monkeypatch):
    capturado = {}

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        capturado["args"] = (endpoint, metodo, cuerpo)
        return 200, {"data": {"email": "a@b.com"}}

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    resultado = l.crear_suscriptor("usuario:token", 3, "a@b.com", "Ana", {"empresa": "X"})
    assert resultado["email"] == "a@b.com"
    endpoint, metodo, cuerpo = capturado["args"]
    assert endpoint == "/api/subscribers"
    assert metodo == "POST"
    assert cuerpo["lists"] == [3]
    assert cuerpo["attribs"] == {"empresa": "X"}


def test_crear_suscriptor_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(l, "_peticion", lambda *a, **k: (403, {"message": "Permission denied: lists"}))
    with pytest.raises(l.ErrorListmonk):
        l.crear_suscriptor("usuario:token", 3, "a@b.com", "Ana")


def test_listar_campanas_sin_api_key_devuelve_vacio():
    assert l.listar_campanas("") == []


def test_listar_campanas_ok(monkeypatch):
    monkeypatch.setattr(l, "_peticion", lambda *a, **k: (200, {"data": {"results": [{"id": 1}]}}))
    assert l.listar_campanas("usuario:token") == [{"id": 1}]


def test_crear_campana_sin_api_key_lanza_excepcion():
    with pytest.raises(l.ErrorListmonk):
        l.crear_campana("", 3, "Prueba", "Hola", "<p>hola</p>")


def test_crear_campana_ok(monkeypatch):
    capturado = {}

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        capturado["args"] = (endpoint, metodo, cuerpo)
        return 200, {"data": {"id": 2, "status": "draft"}}

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    resultado = l.crear_campana("usuario:token", 3, "Prueba", "Hola", "<p>hola</p>")
    assert resultado["status"] == "draft"
    endpoint, metodo, cuerpo = capturado["args"]
    assert endpoint == "/api/campaigns"
    assert cuerpo["lists"] == [3]
    assert cuerpo["subject"] == "Hola"


def test_enviar_campana_sin_api_key_lanza_excepcion():
    with pytest.raises(l.ErrorListmonk):
        l.enviar_campana("", 2)


def test_enviar_campana_ok(monkeypatch):
    capturado = {}

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, cabeceras=None, opener=None):
        capturado["args"] = (endpoint, metodo, cuerpo)
        return 200, {"data": {"id": 2, "status": "running"}}

    monkeypatch.setattr(l, "_peticion", fake_peticion)
    resultado = l.enviar_campana("usuario:token", 2)
    assert resultado["status"] == "running"
    endpoint, metodo, cuerpo = capturado["args"]
    assert endpoint == "/api/campaigns/2/status"
    assert cuerpo == {"status": "running"}


def test_enviar_campana_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(l, "_peticion", lambda *a, **k: (404, {"message": "no encontrada"}))
    with pytest.raises(l.ErrorListmonk):
        l.enviar_campana("usuario:token", 999)
