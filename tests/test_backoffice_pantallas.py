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





# --- /backoffice/leads -------------------------------------------------------





# --- /backoffice/solicitudes-portal ------------------------------------------





# --- /backoffice/webhooks ----------------------------------------------------





# --- /backoffice/auditoria ---------------------------------------------------





# --- Tenants (panel principal) ya no carga usuarios/leads/webhooks/auditoria



# --- /backoffice/resumen -----------------------------------------------------



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




# --- /backoffice/monitorizacion ----------------------------------------------









# --- /backoffice/ingresos -----------------------------------------------------



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




# --- /backoffice/backups ------------------------------------------------------



def test_listar_backups_vacio_sin_directorio():
    # base_de_datos_temporal ya apunta BACKUPS_DIR a un tmp_path que
    # todavía no existe como directorio (nadie ha hecho backup aún).
    assert db.listar_backups() == []


def test_hacer_backup_y_listar_backups():
    # DB_PATH/BACKUPS_DIR ya apuntan al tmp_path aislado del test gracias
    # al fixture autouse base_de_datos_temporal (tests/conftest.py) -- no
    # hace falta (ni conviene) redefinirlos aquí, o se pierde el esquema
    # ya inicializado por db.init_db().
    db.hacer_backup_si_hace_falta()
    backups = db.listar_backups()
    assert len(backups) == 1
    assert backups[0]["nombre"].startswith("registro_")
    assert backups[0]["tamano_bytes"] > 0






# --- /backoffice/catalogo-herramientas ---------------------------------------



def test_adopcion_herramientas_cuenta_solo_las_visibles():
    tenant_a = db.crear_tenant("Catalogo Tenant A")
    tenant_b = db.crear_tenant("Catalogo Tenant B")
    db.ocultar_herramienta(tenant_a, "outline")

    ocultas = db.herramientas_ocultas_de_tenants([tenant_a, tenant_b])
    adopcion = db.adopcion_herramientas(ocultas, ["outline", "chat"])
    assert adopcion["outline"] == 1  # oculta en A, visible en B
    assert adopcion["chat"] == 2  # visible en ambos por defecto




# --- /backoffice/diagnostico --------------------------------------------------
