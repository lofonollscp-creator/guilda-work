"""Pantallas propias del backoffice para Usuarios/Leads/Solicitudes portal/
Webhooks/Auditoría (antes todo vivía en una única página, /backoffice/,
junto con Tenants -- ver app/rutas_backoffice.py). Cada una es ahora su
propia ruta GET, con el mismo admin_required de siempre."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def _admin(cliente, email="admin-pantallas@ejemplo.com"):
    usuario_id = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])
    return usuario_id


# --- /backoffice/usuarios ---------------------------------------------------

def test_usuarios_vista_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-usuarios@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/usuarios")
    assert resp.status_code == 403


def test_usuarios_vista_lista_usuarios(cliente):
    _admin(cliente)
    db.crear_usuario("usuario-listado@ejemplo.com", "contrasena123")

    resp = cliente.get("/backoffice/usuarios")
    assert resp.status_code == 200
    assert b"usuario-listado@ejemplo.com" in resp.data


# --- /backoffice/leads -------------------------------------------------------

def test_leads_vista_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-leads@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/leads")
    assert resp.status_code == 403


def test_leads_vista_lista_leads(cliente):
    _admin(cliente)
    db.crear_lead_contacto("Nombre Lead", "lead-unico@ejemplo.com", empresa=None, telefono=None, mensaje=None)

    resp = cliente.get("/backoffice/leads")
    assert resp.status_code == 200
    assert b"lead-unico@ejemplo.com" in resp.data


# --- /backoffice/solicitudes-portal ------------------------------------------

def test_solicitudes_portal_vista_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-solicitudes@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/solicitudes-portal")
    assert resp.status_code == 403


def test_solicitudes_portal_vista_lista_solicitudes(cliente):
    _admin(cliente)
    db.crear_solicitud_acceso_portal("Nombre Solicitud", "solicitud-unica@ejemplo.com", nif=None, mensaje=None)

    resp = cliente.get("/backoffice/solicitudes-portal")
    assert resp.status_code == 200
    assert b"solicitud-unica@ejemplo.com" in resp.data


# --- /backoffice/webhooks ----------------------------------------------------

def test_webhooks_vista_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-webhooks@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/webhooks")
    assert resp.status_code == 403


def test_webhooks_vista_lista_webhooks(cliente):
    usuario_id = _admin(cliente)
    db.crear_webhook(usuario_id, None, "https://ejemplo.com/webhook-vista-unico", ["nota.creada"])

    resp = cliente.get("/backoffice/webhooks")
    assert resp.status_code == 200
    assert b"webhook-vista-unico" in resp.data


# --- /backoffice/auditoria ---------------------------------------------------

def test_auditoria_vista_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-auditoria@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/auditoria")
    assert resp.status_code == 403


def test_auditoria_vista_lista_entradas(cliente):
    usuario_id = _admin(cliente)
    db.registrar_auditoria(usuario_id, "accion_de_prueba_unica", None)

    resp = cliente.get("/backoffice/auditoria")
    assert resp.status_code == 200
    assert b"accion_de_prueba_unica" in resp.data


# --- Tenants (panel principal) ya no carga usuarios/leads/webhooks/auditoria

def test_panel_tenants_ya_no_incluye_usuarios(cliente):
    """El panel principal (Tenants) ya no arrastra la tabla de usuarios --
    confirma que la separación de pantallas realmente quitó el contenido
    de la página, no solo lo ocultó visualmente."""
    _admin(cliente)
    db.crear_usuario("usuario-no-en-tenants@ejemplo.com", "contrasena123")

    resp = cliente.get("/backoffice/")
    assert resp.status_code == 200
    assert b"usuario-no-en-tenants@ejemplo.com" not in resp.data
