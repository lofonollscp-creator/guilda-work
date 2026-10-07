"""Backoffice: visión global de tenants, usuarios y roles (resumen, filtros,
agrupación por tenant y mapa de acceso)."""
from app import db, herramientas
from tests.conftest import iniciar_sesion_de_prueba


def _admin(cliente, email="bo-vision-admin@ejemplo.com"):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.hacer_admin(email)
    return uid


def _usuario(email, tenant_id=None, gestor=False, supervisor=False):
    uid = db.crear_usuario_vinculado_a_kratos(email, "kratos-" + email)
    if tenant_id:
        db.asignar_tenant(uid, tenant_id)
    if gestor:
        db.asignar_gestor_fichajes(uid, True)
    if supervisor:
        db.asignar_supervisor_tenant(uid, True)
    return uid


def test_resumen_equipos_cuenta_roles_clientes_y_plan():
    t = db.crear_tenant("Equipo A")
    _usuario("a1@ejemplo.com", t, gestor=True)
    _usuario("a2@ejemplo.com", t, supervisor=True)
    _usuario("a3@ejemplo.com", t)
    db.hacer_admin("a3@ejemplo.com")
    db.crear_cliente_fiscal(t, "Cliente 1")
    vacio = db.crear_tenant("Equipo vacío")
    r = db.resumen_equipos_tenants()
    assert r[t]["usuarios"] == 3 and r[t]["admins"] == 1 and r[t]["gestores"] == 1 and r[t]["supervisores"] == 1
    assert r[t]["clientes"] == 1 and r[vacio]["usuarios"] == 0
