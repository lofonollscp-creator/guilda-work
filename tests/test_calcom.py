"""Tests del cliente de Cal.diy (app/calcom.py) — se mockean
calcom._peticion_web/_peticion_api, sin un Cal.diy de verdad.

A diferencia de FacturaScripts, aquí no hay `subprocess`/Docker que
mockear — todo el aprovisionamiento es HTTP contra la instancia
compartida (ver docstring del módulo para el porqué de esa decisión de
diseño)."""
import pytest

from app import calcom as c


# --- Helpers --------------------------------------------------------------

def test_generar_password_valida_cumple_los_requisitos():
    """Cal.diy exige mínimo 15 caracteres, mayúscula, minúscula y número."""
    for _ in range(20):
        password = c._generar_password_valida()
        assert len(password) >= 15
        assert any(ch.isupper() for ch in password)
        assert any(ch.islower() for ch in password)
        assert any(ch.isdigit() for ch in password)


def test_slug_normaliza_caracteres_no_permitidos():
    assert c._slug("Lo Fonoll SCP") == "lo-fonoll-scp"
    assert c._slug("Cliente  &  Asociados.") == "cliente-asociados"


# --- bootstrap_admin --------------------------------------------------------

def test_bootstrap_admin_sin_credenciales_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(c, "CALCOM_ADMIN_EMAIL", None)
    monkeypatch.setattr(c, "CALCOM_ADMIN_PASSWORD", None)
    with pytest.raises(c.ErrorCalcom):
        c.bootstrap_admin()


def test_bootstrap_admin_ok(monkeypatch):
    monkeypatch.setattr(c, "CALCOM_ADMIN_EMAIL", "admin@ejemplo.com")
    monkeypatch.setattr(c, "CALCOM_ADMIN_PASSWORD", "ContraseñaSegura123")

    capturado = {}

    def fake_peticion_web(endpoint, cuerpo):
        capturado["endpoint"] = endpoint
        capturado["cuerpo"] = cuerpo
        return 200, {"message": "First admin user created successfully."}

    monkeypatch.setattr(c, "_peticion_web", fake_peticion_web)
    c.bootstrap_admin()
    assert capturado["endpoint"] == "/api/auth/setup"
    assert capturado["cuerpo"]["email_address"] == "admin@ejemplo.com"
    assert capturado["cuerpo"]["password"] == "ContraseñaSegura123"


def test_bootstrap_admin_ya_hecho_es_idempotente(monkeypatch):
    """Verificado leyendo el código fuente real de la ruta /api/auth/setup:
    devuelve 400 "No setup needed" si la tabla de usuarios ya no está
    vacía — eso NO es un error, es la instancia ya arrancada."""
    monkeypatch.setattr(c, "CALCOM_ADMIN_EMAIL", "admin@ejemplo.com")
    monkeypatch.setattr(c, "CALCOM_ADMIN_PASSWORD", "ContraseñaSegura123")
    monkeypatch.setattr(c, "_peticion_web", lambda *a, **k: (400, {"message": "No setup needed."}))
    c.bootstrap_admin()  # no debe lanzar


def test_bootstrap_admin_error_real_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(c, "CALCOM_ADMIN_EMAIL", "admin@ejemplo.com")
    monkeypatch.setattr(c, "CALCOM_ADMIN_PASSWORD", "ContraseñaSegura123")
    monkeypatch.setattr(c, "_peticion_web", lambda *a, **k: (500, {"message": "Internal server error"}))
    with pytest.raises(c.ErrorCalcom):
        c.bootstrap_admin()


# --- aprovisionar_tenant ----------------------------------------------------

def test_aprovisionar_tenant_ok(monkeypatch):
    capturado = {}

    def fake_peticion_web(endpoint, cuerpo):
        capturado["endpoint"] = endpoint
        capturado["cuerpo"] = cuerpo
        return 201, {"message": "Created user"}

    monkeypatch.setattr(c, "_peticion_web", fake_peticion_web)
    resultado = c.aprovisionar_tenant(7, "Lueira")

    assert resultado["email"] == "tenant-lueira@calcom.local"
    assert len(resultado["admin_pass"]) >= 15
    assert capturado["endpoint"] == "/api/auth/signup"
    assert capturado["cuerpo"]["email"] == "tenant-lueira@calcom.local"
    assert capturado["cuerpo"]["username"] == "tenant-lueira"


def test_aprovisionar_tenant_ya_existente_es_idempotente(monkeypatch):
    monkeypatch.setattr(c, "_peticion_web", lambda *a, **k: (409, {"message": "Username or email is already taken"}))
    resultado = c.aprovisionar_tenant(7, "Lueira")
    assert resultado["email"] == "tenant-lueira@calcom.local"


def test_aprovisionar_tenant_error_real_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(c, "_peticion_web", lambda *a, **k: (500, {"message": "Internal server error"}))
    with pytest.raises(c.ErrorCalcom):
        c.aprovisionar_tenant(7, "Lueira")


# --- API de negocio ---------------------------------------------------------

def test_listar_tipos_evento_sin_api_key_devuelve_vacio():
    assert c.listar_tipos_evento("") == []


def test_listar_tipos_evento_ok(monkeypatch):
    capturado = {}

    def fake_peticion_api(endpoint, api_key, version, *, metodo="GET", cuerpo=None):
        capturado["args"] = (endpoint, api_key, version, metodo)
        return 200, {"data": [{"id": 1, "title": "Consulta inicial"}]}

    monkeypatch.setattr(c, "_peticion_api", fake_peticion_api)
    resultado = c.listar_tipos_evento("api_clave")
    assert resultado == [{"id": 1, "title": "Consulta inicial"}]
    assert capturado["args"] == ("/event-types", "api_clave", c._VERSION_EVENT_TYPES, "GET")


def test_listar_tipos_evento_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(c, "_peticion_api", lambda *a, **k: (500, {"message": "fallo"}))
    with pytest.raises(c.ErrorCalcom):
        c.listar_tipos_evento("api_clave")


def test_listar_reservas_sin_api_key_devuelve_vacio():
    assert c.listar_reservas("") == []


def test_listar_reservas_ok_sin_filtros(monkeypatch):
    capturado = {}

    def fake_peticion_api(endpoint, api_key, version, *, metodo="GET", cuerpo=None):
        capturado["endpoint"] = endpoint
        return 200, {"data": [{"uid": "abc123"}]}

    monkeypatch.setattr(c, "_peticion_api", fake_peticion_api)
    resultado = c.listar_reservas("api_clave")
    assert resultado == [{"uid": "abc123"}]
    assert capturado["endpoint"] == "/bookings"


def test_listar_reservas_ok_con_filtros(monkeypatch):
    capturado = {}

    def fake_peticion_api(endpoint, api_key, version, *, metodo="GET", cuerpo=None):
        capturado["endpoint"] = endpoint
        return 200, {"data": []}

    monkeypatch.setattr(c, "_peticion_api", fake_peticion_api)
    c.listar_reservas("api_clave", desde="2026-08-01T00:00:00Z", hasta="2026-08-31T23:59:59Z")
    assert "afterStart=" in capturado["endpoint"]
    assert "beforeEnd=" in capturado["endpoint"]


def test_crear_reserva_sin_api_key_lanza_excepcion():
    with pytest.raises(c.ErrorCalcom):
        c.crear_reserva("", 1, "2026-08-01T10:00:00Z", "Ana", "ana@ejemplo.com")


def test_crear_reserva_ok(monkeypatch):
    capturado = {}

    def fake_peticion_api(endpoint, api_key, version, *, metodo="GET", cuerpo=None):
        capturado["args"] = (endpoint, version, metodo, cuerpo)
        return 201, {"data": {"uid": "abc123"}}

    monkeypatch.setattr(c, "_peticion_api", fake_peticion_api)
    resultado = c.crear_reserva("api_clave", 1, "2026-08-01T10:00:00Z", "Ana", "ana@ejemplo.com")
    assert resultado == {"uid": "abc123"}
    endpoint, version, metodo, cuerpo = capturado["args"]
    assert endpoint == "/bookings"
    assert version == c._VERSION_BOOKINGS_CREAR
    assert metodo == "POST"
    assert cuerpo["eventTypeId"] == 1
    assert cuerpo["attendee"]["name"] == "Ana"
    assert cuerpo["attendee"]["email"] == "ana@ejemplo.com"


def test_crear_reserva_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(c, "_peticion_api", lambda *a, **k: (400, {"message": "slot no disponible"}))
    with pytest.raises(c.ErrorCalcom):
        c.crear_reserva("api_clave", 1, "2026-08-01T10:00:00Z", "Ana", "ana@ejemplo.com")


def test_cancelar_reserva_sin_api_key_lanza_excepcion():
    with pytest.raises(c.ErrorCalcom):
        c.cancelar_reserva("", "abc123")


def test_cancelar_reserva_ok(monkeypatch):
    capturado = {}

    def fake_peticion_api(endpoint, api_key, version, *, metodo="GET", cuerpo=None):
        capturado["args"] = (endpoint, version, metodo, cuerpo)
        return 200, {"data": {"uid": "abc123", "status": "cancelled"}}

    monkeypatch.setattr(c, "_peticion_api", fake_peticion_api)
    resultado = c.cancelar_reserva("api_clave", "abc123", "Cliente no puede asistir")
    assert resultado["status"] == "cancelled"
    endpoint, version, metodo, cuerpo = capturado["args"]
    assert endpoint == "/bookings/abc123/cancel"
    assert version == c._VERSION_BOOKINGS_CANCELAR
    assert cuerpo == {"cancellationReason": "Cliente no puede asistir"}


def test_cancelar_reserva_error_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(c, "_peticion_api", lambda *a, **k: (404, {"message": "no encontrada"}))
    with pytest.raises(c.ErrorCalcom):
        c.cancelar_reserva("api_clave", "no-existe")
