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
