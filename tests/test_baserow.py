"""Tests del cliente de Baserow (app/baserow.py) — se mockea
baserow._peticion, sin un Baserow de verdad.

Aprovisionamiento parcial (a diferencia de Paperless-ngx 100% y
Documenso 0%): SÍ hay API para crear Workspace+token (confirmado en el
spec OpenAPI real, ver docstring del módulo), NO hay API para añadir un
usuario ya existente a un Workspace — solo invitación+aceptación.
"""
import pytest

from app import baserow as b


# --- Aprovisionamiento --------------------------------------------------

def test_aprovisionar_tenant_sin_admin_configurado_devuelve_none(monkeypatch):
    monkeypatch.setattr(b, "BASEROW_ADMIN_EMAIL", None)
    monkeypatch.setattr(b, "BASEROW_ADMIN_PASSWORD", None)
    assert b.aprovisionar_tenant("Lueira") is None


def test_aprovisionar_tenant_crea_workspace_y_token(monkeypatch):
    monkeypatch.setattr(b, "BASEROW_ADMIN_EMAIL", "admin@ejemplo.com")
    monkeypatch.setattr(b, "BASEROW_ADMIN_PASSWORD", "adminpass")
    monkeypatch.setattr(b, "_jwt_admin", lambda forzar_nuevo=False: "jwt-admin")

    llamadas = []

    def fake_peticion_admin(endpoint, *, metodo="GET", cuerpo=None):
        llamadas.append((endpoint, metodo, cuerpo))
        if endpoint == "/api/workspaces/" and metodo == "GET":
            return 200, []  # todavía no existe ningún Workspace con ese nombre
        if endpoint == "/api/workspaces/" and metodo == "POST":
            assert cuerpo == {"name": "Lueira"}
            return 200, {"id": 5}
        if endpoint == "/api/database/tokens/" and metodo == "POST":
            assert cuerpo == {"name": "Lueira", "workspace": 5}
            return 200, {"key": "token-real"}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(b, "_peticion_admin", fake_peticion_admin)

    resultado = b.aprovisionar_tenant("Lueira")
    assert resultado == {"workspace_id": 5, "api_key": "token-real"}


def test_aprovisionar_tenant_workspace_ya_existente_es_idempotente(monkeypatch):
    """Verificado en vivo: Baserow NO rechaza nombres de Workspace
    duplicados (a diferencia de EspoCRM/Nextcloud/Paperless-ngx) — hay
    que buscar por nombre ANTES de crear, no solo si el POST falla, o
    cada reintento crearía un Workspace nuevo en vez de reutilizar el
    existente."""
    monkeypatch.setattr(b, "BASEROW_ADMIN_EMAIL", "admin@ejemplo.com")
    monkeypatch.setattr(b, "BASEROW_ADMIN_PASSWORD", "adminpass")
    monkeypatch.setattr(b, "_jwt_admin", lambda forzar_nuevo=False: "jwt-admin")

    def fake_peticion_admin(endpoint, *, metodo="GET", cuerpo=None):
        if endpoint == "/api/workspaces/" and metodo == "GET":
            return 200, [{"id": 5, "name": "Lueira"}]
        if endpoint == "/api/workspaces/" and metodo == "POST":
            raise AssertionError("no debería intentar crear un Workspace que ya existe")
        if endpoint == "/api/database/tokens/" and metodo == "POST":
            return 200, {"key": "token-real"}
        raise AssertionError(f"llamada inesperada: {endpoint} {metodo}")

    monkeypatch.setattr(b, "_peticion_admin", fake_peticion_admin)

    resultado = b.aprovisionar_tenant("Lueira")
    assert resultado["workspace_id"] == 5


def test_jwt_admin_cachea_y_se_puede_forzar(monkeypatch):
    monkeypatch.setattr(b, "BASEROW_ADMIN_EMAIL", "admin@ejemplo.com")
    monkeypatch.setattr(b, "BASEROW_ADMIN_PASSWORD", "adminpass")
    b._jwt_admin_cache = None

    llamadas = {"n": 0}

    def fake_peticion(endpoint, *, auth, metodo="GET", cuerpo=None):
        llamadas["n"] += 1
        return 200, {"access_token": f"jwt-{llamadas['n']}"}

    monkeypatch.setattr(b, "_peticion", fake_peticion)

    assert b._jwt_admin() == "jwt-1"
    assert b._jwt_admin() == "jwt-1"  # cacheado, no pide uno nuevo
    assert b._jwt_admin(forzar_nuevo=True) == "jwt-2"
    b._jwt_admin_cache = None  # no contaminar otros tests


def test_peticion_admin_reintenta_una_vez_si_el_jwt_ha_caducado(monkeypatch):
    monkeypatch.setattr(b, "BASEROW_ADMIN_EMAIL", "admin@ejemplo.com")
    monkeypatch.setattr(b, "BASEROW_ADMIN_PASSWORD", "adminpass")
    b._jwt_admin_cache = "jwt-caducado"

    llamadas = []

    def fake_jwt_admin(forzar_nuevo=False):
        if forzar_nuevo:
            b._jwt_admin_cache = "jwt-nuevo"
        return b._jwt_admin_cache

    monkeypatch.setattr(b, "_jwt_admin", fake_jwt_admin)

    def fake_peticion(endpoint, *, auth, metodo="GET", cuerpo=None):
        llamadas.append(auth)
        if auth == "JWT jwt-caducado":
            return 401, {"detail": "token caducado"}
        return 200, [{"id": 5, "name": "Lueira"}]

    monkeypatch.setattr(b, "_peticion", fake_peticion)

    estado, cuerpo = b._peticion_admin("/api/workspaces/")
    assert estado == 200
    assert llamadas == ["JWT jwt-caducado", "JWT jwt-nuevo"]
    b._jwt_admin_cache = None  # no contaminar otros tests


def test_desaprovisionar_tenant_sin_workspace_id_no_hace_nada(monkeypatch):
    llamado = []
    monkeypatch.setattr(b, "_peticion_admin", lambda *a, **k: llamado.append(1))
    b.desaprovisionar_tenant(None)
    assert llamado == []


def test_desaprovisionar_tenant_borra_workspace_y_vacia_la_papelera(monkeypatch):
    """Regresión del hallazgo real: DELETE /api/workspaces/{id}/ solo
    manda a la papelera — hace falta una segunda llamada a
    /api/trash/workspace/{id}/ para borrarlo de verdad (ver docstring
    de app/baserow.py:desaprovisionar_tenant)."""
    llamadas = []
    monkeypatch.setattr(b, "_peticion_admin", lambda endpoint, **k: (llamadas.append((endpoint, k)), (204, {}))[1])
    b.desaprovisionar_tenant(5)
    assert llamadas[0][0] == "/api/workspaces/5/"
    assert llamadas[0][1]["metodo"] == "DELETE"
    assert llamadas[1][0] == "/api/trash/workspace/5/"
    assert llamadas[1][1]["metodo"] == "DELETE"


def test_invitar_usuario_sin_admin_configurado_no_hace_nada(monkeypatch):
    monkeypatch.setattr(b, "_jwt_admin", lambda forzar_nuevo=False: None)
    llamado = []
    monkeypatch.setattr(b, "_peticion_admin", lambda *a, **k: llamado.append(1))
    b.invitar_usuario(5, "ana@ejemplo.com")
    assert llamado == []


def test_invitar_usuario_ok(monkeypatch):
    monkeypatch.setattr(b, "_jwt_admin", lambda forzar_nuevo=False: "jwt-admin")

    capturado = {}

    def fake_peticion_admin(endpoint, *, metodo="GET", cuerpo=None):
        capturado["endpoint"] = endpoint
        capturado["cuerpo"] = cuerpo
        return 200, {"id": 1}

    monkeypatch.setattr(b, "_peticion_admin", fake_peticion_admin)
    b.invitar_usuario(5, "ana@ejemplo.com")
    assert capturado["endpoint"] == "/api/workspaces/invitations/workspace/5/"
    assert capturado["cuerpo"]["email"] == "ana@ejemplo.com"
    assert capturado["cuerpo"]["base_url"]  # obligatoria, verificado en vivo (HTTP 400 sin ella)


def test_invitar_usuario_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(b, "_jwt_admin", lambda forzar_nuevo=False: "jwt-admin")
    monkeypatch.setattr(b, "_peticion_admin", lambda *a, **k: (400, {"detail": "email inválido"}))
    with pytest.raises(b.ErrorBaserow):
        b.invitar_usuario(5, "no-es-un-email")


# --- API de negocio -------------------------------------------------------

def test_listar_tablas_sin_api_key_devuelve_vacio():
    assert b.listar_tablas("") == []


def test_listar_tablas_ok(monkeypatch):
    monkeypatch.setattr(b, "_peticion", lambda ep, *, auth, **k: (200, [{"id": 1, "name": "Clientes"}]))
    assert b.listar_tablas("api_clave") == [{"id": 1, "name": "Clientes"}]


def test_listar_tablas_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(b, "_peticion", lambda ep, *, auth, **k: (500, {"detail": "fallo"}))
    with pytest.raises(b.ErrorBaserow):
        b.listar_tablas("api_clave")


def test_listar_filas_sin_api_key_devuelve_vacio():
    assert b.listar_filas("", 1) == []


def test_listar_filas_ok(monkeypatch):
    capturado = {}

    def fake_peticion(endpoint, *, auth, metodo="GET", cuerpo=None):
        capturado["endpoint"] = endpoint
        capturado["auth"] = auth
        return 200, {"results": [{"id": 1, "field_1": "Ana"}]}

    monkeypatch.setattr(b, "_peticion", fake_peticion)
    resultado = b.listar_filas("api_clave", 42, texto="Ana")
    assert resultado == [{"id": 1, "field_1": "Ana"}]
    assert capturado["endpoint"].startswith("/api/database/rows/table/42/")
    assert capturado["auth"] == "Token api_clave"


def test_crear_fila_sin_api_key_lanza_excepcion():
    with pytest.raises(b.ErrorBaserow):
        b.crear_fila("", 42, {"Nombre": "Ana"})


def test_crear_fila_ok(monkeypatch):
    capturado = {}

    def fake_peticion(endpoint, *, auth, metodo="GET", cuerpo=None):
        capturado["args"] = (endpoint, auth, metodo, cuerpo)
        return 200, {"id": 1, "Nombre": "Ana"}

    monkeypatch.setattr(b, "_peticion", fake_peticion)
    resultado = b.crear_fila("api_clave", 42, {"Nombre": "Ana"})
    assert resultado == {"id": 1, "Nombre": "Ana"}
    assert capturado["args"] == ("/api/database/rows/table/42/", "Token api_clave", "POST", {"Nombre": "Ana"})
