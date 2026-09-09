"""Ficha de tenant nueva del backoffice renovado (app/db.py:
ultima_actividad_tenant/alternar_activo_tenant, app/rutas_backoffice.py:
ficha_tenant/alternar_activo_tenant)."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


# --- Capa BD -----------------------------------------------------------

def test_tenant_activo_por_defecto():
    tenant_id = db.crear_tenant("Gestoria Ficha Activo")
    assert db.obtener_tenant(tenant_id)["activo"] == 1


def test_alternar_activo_tenant():
    tenant_id = db.crear_tenant("Gestoria Ficha Alternar")
    db.alternar_activo_tenant(tenant_id, False)
    assert db.obtener_tenant(tenant_id)["activo"] == 0
    db.alternar_activo_tenant(tenant_id, True)
    assert db.obtener_tenant(tenant_id)["activo"] == 1


def test_ultima_actividad_tenant_sin_usuarios_es_none():
    tenant_id = db.crear_tenant("Gestoria Ficha Sin Usuarios")
    assert db.ultima_actividad_tenant(tenant_id) is None


def test_ultima_actividad_tenant_sin_actividad_es_none():
    tenant_id = db.crear_tenant("Gestoria Ficha Sin Actividad")
    usuario_id = db.crear_usuario_vinculado_a_kratos("ficha-sin-actividad@ejemplo.com", "kratos-ficha-sin-actividad")
    db.asignar_tenant(usuario_id, tenant_id)
    assert db.ultima_actividad_tenant(tenant_id) is None


def test_ultima_actividad_tenant_detecta_una_nota():
    tenant_id = db.crear_tenant("Gestoria Ficha Con Nota")
    usuario_id = db.crear_usuario_vinculado_a_kratos("ficha-con-nota@ejemplo.com", "kratos-ficha-con-nota")
    db.asignar_tenant(usuario_id, tenant_id)
    db.crear_nota(usuario_id, "Nota de actividad")
    assert db.ultima_actividad_tenant(tenant_id) is not None


def test_ultima_actividad_tenant_detecta_un_fichaje():
    tenant_id = db.crear_tenant("Gestoria Ficha Con Fichaje")
    usuario_id = db.crear_usuario_vinculado_a_kratos("ficha-con-fichaje@ejemplo.com", "kratos-ficha-con-fichaje")
    db.asignar_tenant(usuario_id, tenant_id)
    db.fichar(usuario_id, tenant_id, "entrada")
    assert db.ultima_actividad_tenant(tenant_id) is not None


# --- Rutas ---------------------------------------------------------------

def test_ficha_tenant_requiere_admin(cliente):
    tenant_id = db.crear_tenant("Gestoria Ficha Ruta No Admin")
    iniciar_sesion_de_prueba(cliente, "ficha-no-admin@ejemplo.com", "contrasena123")
    resp = cliente.get(f"/backoffice/tenants/{tenant_id}")
    assert resp.status_code == 403


def test_ficha_tenant_404_si_no_existe(cliente):
    admin_id = iniciar_sesion_de_prueba(cliente, "ficha-admin-404@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(admin_id)["email"])
    resp = cliente.get("/backoffice/tenants/999999")
    assert resp.status_code == 404


def test_ficha_tenant_muestra_solo_sus_propios_usuarios(cliente):
    tenant_a = db.crear_tenant("Gestoria Ficha Ruta A")
    tenant_b = db.crear_tenant("Gestoria Ficha Ruta B")
    usuario_a = db.crear_usuario_vinculado_a_kratos("ficha-ruta-a@ejemplo.com", "kratos-ficha-ruta-a")
    usuario_b = db.crear_usuario_vinculado_a_kratos("ficha-ruta-b@ejemplo.com", "kratos-ficha-ruta-b")
    db.asignar_tenant(usuario_a, tenant_a)
    db.asignar_tenant(usuario_b, tenant_b)

    admin_id = iniciar_sesion_de_prueba(cliente, "ficha-admin-usuarios@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(admin_id)["email"])

    resp = cliente.get(f"/backoffice/tenants/{tenant_a}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "ficha-ruta-a@ejemplo.com" in html
    assert "ficha-ruta-b@ejemplo.com" not in html


def test_alternar_activo_tenant_ruta_requiere_admin(cliente):
    tenant_id = db.crear_tenant("Gestoria Alternar Activo No Admin")
    iniciar_sesion_de_prueba(cliente, "alternar-activo-no-admin@ejemplo.com", "contrasena123")
    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/activo")
    assert resp.status_code == 403
    assert db.obtener_tenant(tenant_id)["activo"] == 1


def test_alternar_activo_tenant_ruta_como_admin(cliente):
    tenant_id = db.crear_tenant("Gestoria Alternar Activo Admin")
    admin_id = iniciar_sesion_de_prueba(cliente, "alternar-activo-admin@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(admin_id)["email"])

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/activo")
    assert resp.status_code == 302
    assert db.obtener_tenant(tenant_id)["activo"] == 0

    cliente.post(f"/backoffice/tenants/{tenant_id}/activo")
    assert db.obtener_tenant(tenant_id)["activo"] == 1
