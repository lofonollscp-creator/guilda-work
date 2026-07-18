"""Tests del backoffice (Fase 7c): rol admin y gestión de tenants/usuarios,
tanto a nivel de app/db.py como de las rutas de app/rutas_backoffice.py.
"""
import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba


# --- app/db.py -----------------------------------------------------------

def test_usuario_nuevo_no_es_admin_por_defecto(usuario_id):
    assert db.es_admin(usuario_id) is False


def test_hacer_admin_y_quitar_admin(usuario_id):
    usuario = db.obtener_usuario(usuario_id)
    db.hacer_admin(usuario["email"])
    assert db.es_admin(usuario_id) is True
    db.quitar_admin(usuario["email"])
    assert db.es_admin(usuario_id) is False


def test_hacer_admin_email_inexistente_lanza_value_error():
    with pytest.raises(ValueError):
        db.hacer_admin("no-existe@ejemplo.com")


def test_listar_usuarios_incluye_tenant(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    usuarios = db.listar_usuarios()
    fila = next(u for u in usuarios if u["id"] == usuario_id)
    assert fila["tenant_nombre"] == "Lueira"


def test_listar_tenants_con_conteo(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.crear_tenant("Guilda")
    db.asignar_tenant(usuario_id, tenant_id)
    tenants = {t["nombre"]: t["n_usuarios"] for t in db.listar_tenants_con_conteo()}
    assert tenants["Lueira"] == 1
    assert tenants["Guilda"] == 0


def test_renombrar_tenant():
    tenant_id = db.crear_tenant("Lueira")
    db.renombrar_tenant(tenant_id, "Lueira SL")
    assert db.obtener_tenant(tenant_id)["nombre"] == "Lueira SL"


def test_borrar_tenant_desasigna_a_sus_usuarios(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    db.borrar_tenant(tenant_id)
    assert db.obtener_tenant(tenant_id) is None
    assert db.tenant_de_usuario(usuario_id) is None


def test_desasignar_tenant(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    db.desasignar_tenant(usuario_id)
    assert db.tenant_de_usuario(usuario_id) is None


# --- app/rutas_backoffice.py ----------------------------------------------

def test_backoffice_sin_admin_devuelve_403(cliente):
    iniciar_sesion_de_prueba(cliente, "usuario-normal@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/")
    assert resp.status_code == 403


def test_backoffice_sin_sesion_redirige_a_login(cliente):
    resp = cliente.get("/backoffice/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_backoffice_con_admin_permite_entrar(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.get("/backoffice/")
    assert resp.status_code == 200


def test_backoffice_crear_tenant_y_asignar_usuario(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "Lueira"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("Lueira")
    assert tenant is not None

    cliente.post(f"/backoffice/usuarios/{usuario_id}/tenant", data={"tenant_id": str(tenant["id"])})
    assert db.tenant_de_usuario(usuario_id)["nombre"] == "Lueira"

    cliente.post(f"/backoffice/usuarios/{usuario_id}/tenant", data={"tenant_id": ""})
    assert db.tenant_de_usuario(usuario_id) is None


def test_backoffice_crear_usuario_muestra_contrasena_temporal(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/usuarios", data={"email": "cliente-nuevo@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    assert "cliente-nuevo@ejemplo.com" in resp.get_data(as_text=True)
    nuevo = db.obtener_usuario_por_email("cliente-nuevo@ejemplo.com")
    assert nuevo is not None


def test_backoffice_admin_no_puede_quitarse_el_rol_a_si_mismo(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post(f"/backoffice/usuarios/{usuario_id}/rol")
    assert resp.status_code == 400
    assert db.es_admin(usuario_id) is True
