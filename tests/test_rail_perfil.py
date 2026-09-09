"""Tarjeta de cuenta fija abajo del rail (app/main.py:inyectar_perfil_rail
+ app/templates/base.html) -- sustituye al icono de engranaje que antes
vivía en la topbar."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def test_dashboard_muestra_la_tarjeta_de_perfil_con_el_email(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "rail-perfil@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Rail Perfil Email")
    db.asignar_tenant(usuario_id, tenant_id)
    resp = cliente.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="perfil-toggle"' in html
    assert "rail-perfil@ejemplo.com" in html


def test_dashboard_muestra_el_nombre_del_tenant_si_tiene(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "rail-perfil-tenant@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Rail Perfil")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.get("/")
    assert resp.status_code == 200
    assert "Gestoria Rail Perfil" in resp.get_data(as_text=True)


def test_grupos_fiscal_y_correo_llegan_abiertos_en_su_pagina(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "rail-grupo-abierto@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Rail Grupo")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.get("/citas/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'icon-rail-grupo-plegable is-abierto' in html
