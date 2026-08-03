"""Tests del cliente de Umami (app/umami.py) — se mockea
umami._peticion/_login, sin un Umami de verdad.

El diseño en sí (aislamiento real por Team, verificado en vivo contra
un contenedor real: un sitio se crea ya asociado a un Team, un usuario
`team-member` de ese Team recibe 401 al acceder a un sitio de otro
tenant, `DELETE /api/teams/{id}` borra en cascada sus sitios; el
bootstrap del admin usa `POST /api/users/{id}` — no PUT/PATCH, ambos
devuelven 405, confirmado en vivo) se verificó en vivo durante el
desarrollo — ver el docstring del propio módulo. Aquí solo se comprueba
que app/umami.py ORQUESTA las llamadas correctas."""
import pytest

from app import umami as u


def _mock_admin_ok(monkeypatch):
    monkeypatch.setattr(u, "UMAMI_ADMIN_USER", "admin")
    monkeypatch.setattr(u, "UMAMI_ADMIN_PASSWORD", "secreto")


# --- bootstrap_admin ---------------------------------------------------------

def test_bootstrap_admin_sin_credenciales_lanza_error(monkeypatch):
    monkeypatch.setattr(u, "UMAMI_ADMIN_PASSWORD", None)
    with pytest.raises(u.ErrorUmami):
        u.bootstrap_admin()


def test_bootstrap_admin_ya_ejecutado_no_hace_nada(monkeypatch):
    _mock_admin_ok(monkeypatch)
    monkeypatch.setattr(u, "_login", lambda usuario, contrasena: "tok" if contrasena == "secreto" else None)

    def fake_peticion(*a, **k):
        raise AssertionError("no debería llamar a la API si el login ya funciona")

    monkeypatch.setattr(u, "_peticion", fake_peticion)
    u.bootstrap_admin()  # no lanza, no llama a nada más


def test_bootstrap_admin_cambia_la_contrasena_de_fabrica(monkeypatch):
    _mock_admin_ok(monkeypatch)

    def fake_login(usuario, contrasena):
        if contrasena == "secreto":
            return None
        if contrasena == "umami":
            return "tok_admin"
        return None

    llamadas = []

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, token=None):
        llamadas.append((endpoint, metodo, cuerpo, token))
        if endpoint == "/api/auth/login":
            return 200, {"token": "tok_admin", "user": {"id": "admin-uuid"}}
        if endpoint == "/api/users/admin-uuid":
            assert token == "tok_admin"
            assert cuerpo == {"password": "secreto"}
            return 200, {}
        raise AssertionError(f"endpoint inesperado: {endpoint}")

    monkeypatch.setattr(u, "_login", fake_login)
    monkeypatch.setattr(u, "_peticion", fake_peticion)
    u.bootstrap_admin()

    assert ("/api/users/admin-uuid", "POST", {"password": "secreto"}, "tok_admin") in llamadas


def test_bootstrap_admin_falla_si_ni_la_de_fabrica_funciona(monkeypatch):
    _mock_admin_ok(monkeypatch)
    monkeypatch.setattr(u, "_login", lambda usuario, contrasena: None)
    with pytest.raises(u.ErrorUmami):
        u.bootstrap_admin()


# --- aprovisionar_tenant ------------------------------------------------------

def test_aprovisionar_tenant_sin_credenciales_devuelve_none(monkeypatch):
    monkeypatch.setattr(u, "UMAMI_ADMIN_PASSWORD", None)
    assert u.aprovisionar_tenant(1, "Lueira") is None


def test_aprovisionar_tenant_completo_ok(monkeypatch):
    _mock_admin_ok(monkeypatch)
    monkeypatch.setattr(u, "_token_admin", lambda: "tok_admin")
    llamadas = []

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, token=None):
        llamadas.append((endpoint, metodo, cuerpo))
        if endpoint == "/api/teams":
            assert cuerpo["name"] == "tenant-7-cliente-alfa"
            return 200, [
                {"id": "team-uuid-7", "name": "tenant-7-cliente-alfa"},
                {"id": "teamuser-uuid", "teamId": "team-uuid-7", "userId": "admin-uuid"},
            ]
        if endpoint == "/api/websites":
            assert cuerpo["teamId"] == "team-uuid-7"
            assert cuerpo["domain"] == "cliente-alfa.guilda-work.local"
            return 200, {"id": "website-uuid-7"}
        raise AssertionError(f"endpoint inesperado: {endpoint}")

    monkeypatch.setattr(u, "_peticion", fake_peticion)
    resultado = u.aprovisionar_tenant(7, "Cliente Alfa")

    assert resultado == {"team_id": "team-uuid-7", "website_id": "website-uuid-7"}
    endpoints = [c[0] for c in llamadas]
    assert endpoints == ["/api/teams", "/api/websites"]


def test_aprovisionar_tenant_team_falla_lanza_error(monkeypatch):
    _mock_admin_ok(monkeypatch)
    monkeypatch.setattr(u, "_token_admin", lambda: "tok_admin")
    monkeypatch.setattr(u, "_peticion", lambda *a, **k: (400, {"message": "boom"}))
    with pytest.raises(u.ErrorUmami, match="boom"):
        u.aprovisionar_tenant(1, "Beta")


# --- crear_usuario_tenant ------------------------------------------------------

def test_crear_usuario_tenant_sin_credenciales_no_hace_nada(monkeypatch):
    monkeypatch.setattr(u, "UMAMI_ADMIN_PASSWORD", None)

    def fake_peticion(*a, **k):
        raise AssertionError("no debería llamar a la API")

    monkeypatch.setattr(u, "_peticion", fake_peticion)
    u.crear_usuario_tenant("tenant1@example.com", "team-uuid-7", "Clave123!")


def test_crear_usuario_tenant_da_de_alta_y_anade_al_team(monkeypatch):
    _mock_admin_ok(monkeypatch)
    monkeypatch.setattr(u, "_token_admin", lambda: "tok_admin")
    llamadas = []

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, token=None):
        llamadas.append((endpoint, metodo, cuerpo))
        if endpoint == "/api/users":
            assert cuerpo == {"username": "tenant1@example.com", "password": "Clave123!", "role": "user"}
            return 200, {"id": "user-uuid-1"}
        if endpoint == "/api/teams/team-uuid-7/users":
            assert cuerpo == {"userId": "user-uuid-1", "role": "team-member"}
            return 200, {}
        raise AssertionError(f"endpoint inesperado: {endpoint}")

    monkeypatch.setattr(u, "_peticion", fake_peticion)
    u.crear_usuario_tenant("tenant1@example.com", "team-uuid-7", "Clave123!")

    endpoints = [c[0] for c in llamadas]
    assert endpoints == ["/api/users", "/api/teams/team-uuid-7/users"]


def test_crear_usuario_tenant_falla_lanza_error(monkeypatch):
    _mock_admin_ok(monkeypatch)
    monkeypatch.setattr(u, "_token_admin", lambda: "tok_admin")
    monkeypatch.setattr(u, "_peticion", lambda *a, **k: (400, {"message": "email ya en uso"}))
    with pytest.raises(u.ErrorUmami, match="email ya en uso"):
        u.crear_usuario_tenant("tenant1@example.com", "team-uuid-7", "Clave123!")


# --- desaprovisionar_tenant ----------------------------------------------------

def test_desaprovisionar_tenant_sin_team_id_no_hace_nada(monkeypatch):
    _mock_admin_ok(monkeypatch)

    def fake_peticion(*a, **k):
        raise AssertionError("no debería llamar a la API")

    monkeypatch.setattr(u, "_peticion", fake_peticion)
    u.desaprovisionar_tenant(None)


def test_desaprovisionar_tenant_borra_el_team(monkeypatch):
    _mock_admin_ok(monkeypatch)
    monkeypatch.setattr(u, "_token_admin", lambda: "tok_admin")
    capturado = {}

    def fake_peticion(endpoint, *, metodo="GET", cuerpo=None, token=None):
        capturado["args"] = (endpoint, metodo, token)
        return 200, {"ok": True}

    monkeypatch.setattr(u, "_peticion", fake_peticion)
    u.desaprovisionar_tenant("team-uuid-7")

    assert capturado["args"] == ("/api/teams/team-uuid-7", "DELETE", "tok_admin")
