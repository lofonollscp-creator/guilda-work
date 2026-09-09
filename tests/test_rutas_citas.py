"""Agenda de citas (app/rutas_citas.py): vista de solo lectura sobre
app/calcom.py -- un calendario compartido POR TENANT (no una agenda
personal), correlación best-effort con la ficha del cliente fiscal por
email de asistente."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def test_agenda_requiere_login(cliente):
    resp = cliente.get("/citas/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_agenda_sin_tenant_da_403(cliente):
    iniciar_sesion_de_prueba(cliente, "agenda-sin-tenant@ejemplo.com", "contrasena123")
    resp = cliente.get("/citas/")
    assert resp.status_code == 403


def test_agenda_sin_calcom_configurado_muestra_aviso(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "agenda-sin-calcom@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Agenda Sin Calcom")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.get("/citas/")
    assert resp.status_code == 200
    assert "no tiene Cal.diy configurado" in resp.get_data(as_text=True)


def test_agenda_lista_las_reservas(cliente, monkeypatch):
    from app import rutas_citas

    usuario_id = iniciar_sesion_de_prueba(cliente, "agenda-con-reservas@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Agenda Con Reservas")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_calcom_api_key(tenant_id, "clave-calcom")

    monkeypatch.setattr(
        rutas_citas.calcom, "listar_reservas",
        lambda api_key, desde=None, hasta=None: [
            {"title": "Reunión anual", "start": "2026-05-01T10:00:00Z", "attendees": [{"name": "Juana Pérez"}]},
        ],
    )

    resp = cliente.get("/citas/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Reunión anual" in html
    assert "Juana Pérez" in html


def test_agenda_calcom_caido_muestra_error_sin_romper(cliente, monkeypatch):
    from app import rutas_citas

    usuario_id = iniciar_sesion_de_prueba(cliente, "agenda-calcom-caido@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Agenda Calcom Caido")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_calcom_api_key(tenant_id, "clave-calcom")

    def _falla(*a, **k):
        raise rutas_citas.calcom.ErrorCalcom("caído")
    monkeypatch.setattr(rutas_citas.calcom, "listar_reservas", _falla)

    resp = cliente.get("/citas/")
    assert resp.status_code == 200
    assert "caído" in resp.get_data(as_text=True)


# --- Correlación en la ficha del cliente fiscal -----------------------------

def test_ficha_cliente_muestra_proxima_cita_si_coincide_el_email(cliente, monkeypatch):
    from app import rutas_fiscal

    usuario_id = iniciar_sesion_de_prueba(cliente, "ficha-cita@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Ficha Cita")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_calcom_api_key(tenant_id, "clave-calcom")
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Con Cita", email="cliente-cita@ejemplo.com")

    monkeypatch.setattr(
        rutas_fiscal.calcom, "listar_reservas",
        lambda api_key, desde=None, hasta=None: [
            {"title": "Revisión trimestral", "start": "2026-05-01T10:00:00Z",
             "attendees": [{"email": "Cliente-Cita@Ejemplo.com"}]},
        ],
    )

    resp = cliente.get(f"/fiscal/clientes/{cliente_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Próxima cita" in html
    assert "Revisión trimestral" in html


def test_ficha_cliente_sin_email_no_consulta_calcom(cliente, monkeypatch):
    from app import rutas_fiscal

    usuario_id = iniciar_sesion_de_prueba(cliente, "ficha-sin-email@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Ficha Sin Email")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_calcom_api_key(tenant_id, "clave-calcom")
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Sin Email")

    monkeypatch.setattr(
        rutas_fiscal.calcom, "listar_reservas",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debería llamar")),
    )

    resp = cliente.get(f"/fiscal/clientes/{cliente_id}")
    assert resp.status_code == 200
    assert "Próxima cita" not in resp.get_data(as_text=True)


def test_ficha_cliente_calcom_caido_no_rompe_la_ficha(cliente, monkeypatch):
    from app import rutas_fiscal

    usuario_id = iniciar_sesion_de_prueba(cliente, "ficha-calcom-caido@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Ficha Calcom Caido")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_calcom_api_key(tenant_id, "clave-calcom")
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Ficha Calcom Caido", email="caido@ejemplo.com")

    def _falla(*a, **k):
        raise rutas_fiscal.calcom.ErrorCalcom("caído")
    monkeypatch.setattr(rutas_fiscal.calcom, "listar_reservas", _falla)

    resp = cliente.get(f"/fiscal/clientes/{cliente_id}")
    assert resp.status_code == 200
