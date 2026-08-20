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


# --- /backoffice/resumen -----------------------------------------------------

def test_resumen_vista_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-resumen@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/resumen")
    assert resp.status_code == 403


def test_resumen_plataforma_agrega_datos_correctamente():
    tenant_activo = db.crear_tenant("Resumen Activo")
    tenant_suspendido = db.crear_tenant("Resumen Suspendido")
    db.alternar_activo_tenant(tenant_suspendido, False)
    db.crear_usuario("resumen-usuario-1@ejemplo.com", "contrasena123")
    db.crear_usuario("resumen-usuario-2@ejemplo.com", "contrasena123")

    plan_id = db.crear_plan_guilda("Plan Resumen", None, 4900, None)
    db.asignar_plan_tenant(tenant_activo, plan_id)
    db.actualizar_suscripcion_estado(tenant_activo, "activa")
    # Un tenant con plan pero SIN suscripcion activa no debe sumar al MRR.
    otro_tenant = db.crear_tenant("Resumen Sin Activar")
    db.asignar_plan_tenant(otro_tenant, plan_id)

    resumen = db.resumen_plataforma()
    assert resumen["tenants_total"] >= 3
    assert resumen["tenants_activos"] >= 1
    assert resumen["usuarios_total"] >= 2
    assert resumen["mrr_centimos"] >= 4900
    assert any(t["id"] == tenant_activo for t in resumen["tenants_recientes"]) or len(resumen["tenants_recientes"]) == 5


def test_resumen_vista_muestra_el_mrr(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-resumen-mrr@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("Resumen MRR Vista")
    plan_id = db.crear_plan_guilda("Plan Resumen Vista", None, 2500, None)
    db.asignar_plan_tenant(tenant_id, plan_id)
    db.actualizar_suscripcion_estado(tenant_id, "activa")

    resp = cliente.get("/backoffice/resumen")
    assert resp.status_code == 200
    assert b"25,00" in resp.data or b"25.00" in resp.data


# --- /backoffice/monitorizacion ----------------------------------------------

def test_monitorizacion_vista_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-monitor@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/monitorizacion")
    assert resp.status_code == 403


def test_monitorizacion_vista_muestra_monitores(cliente, monkeypatch):
    from app import rutas_backoffice
    _admin(cliente, "admin-monitor-ok@ejemplo.com")

    monkeypatch.setattr(
        rutas_backoffice.uptime_kuma, "listar_monitores",
        lambda: [
            {"nombre": "app-guildawork-unico", "estado": "activo", "tiempo_respuesta_ms": 12.5},
            {"nombre": "kratos-unico", "estado": "caido"},
        ],
    )
    resp = cliente.get("/backoffice/monitorizacion")
    assert resp.status_code == 200
    assert b"app-guildawork-unico" in resp.data
    assert b"kratos-unico" in resp.data


def test_monitorizacion_vista_sin_configurar_no_rompe(cliente, monkeypatch):
    from app import rutas_backoffice
    _admin(cliente, "admin-monitor-vacio@ejemplo.com")

    monkeypatch.setattr(rutas_backoffice.uptime_kuma, "listar_monitores", lambda: [])
    resp = cliente.get("/backoffice/monitorizacion")
    assert resp.status_code == 200


def test_monitorizacion_vista_error_de_conexion_no_rompe(cliente, monkeypatch):
    from app import rutas_backoffice

    _admin(cliente, "admin-monitor-error@ejemplo.com")

    def _falla():
        raise rutas_backoffice.uptime_kuma.ErrorUptimeKuma("Uptime Kuma caído")
    monkeypatch.setattr(rutas_backoffice.uptime_kuma, "listar_monitores", _falla)

    resp = cliente.get("/backoffice/monitorizacion")
    assert resp.status_code == 200
    assert b"Uptime Kuma ca\xc3\xaddo" in resp.data


# --- /backoffice/ingresos -----------------------------------------------------

def test_ingresos_vista_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-ingresos@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/ingresos")
    assert resp.status_code == 403


def test_listar_suscripciones_tenants_incluye_plan_y_estado():
    tenant_id = db.crear_tenant("Ingresos Suscripcion")
    plan_id = db.crear_plan_guilda("Plan Ingresos", None, 3500, None)
    db.asignar_plan_tenant(tenant_id, plan_id)
    db.actualizar_suscripcion_estado(tenant_id, "activa")

    filas = {t["id"]: t for t in db.listar_suscripciones_tenants()}
    fila = filas[tenant_id]
    assert fila["plan_nombre"] == "Plan Ingresos"
    assert fila["plan_precio_centimos"] == 3500
    assert fila["suscripcion_estado"] == "activa"


def test_listar_suscripciones_tenants_sin_plan_da_nombre_nulo():
    tenant_id = db.crear_tenant("Ingresos Sin Plan")
    filas = {t["id"]: t for t in db.listar_suscripciones_tenants()}
    assert filas[tenant_id]["plan_nombre"] is None


def test_ingresos_vista_lista_el_tenant_y_su_plan(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-ingresos-vista@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("Ingresos Vista Unico")
    plan_id = db.crear_plan_guilda("Plan Vista Unico", None, 1500, None)
    db.asignar_plan_tenant(tenant_id, plan_id)
    db.actualizar_suscripcion_estado(tenant_id, "activa")

    resp = cliente.get("/backoffice/ingresos")
    assert resp.status_code == 200
    assert b"Ingresos Vista Unico" in resp.data
    assert b"Plan Vista Unico" in resp.data
