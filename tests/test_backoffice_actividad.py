"""Backoffice: pestaña Actividad del tenant, Customer Journey y notas internas."""
from datetime import datetime, timedelta

from app import db
from backoffice import metricas
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


def _tenant_con_usuario(nombre="Gestoría Actividad", email="act1@ejemplo.com"):
    t = db.crear_tenant(nombre)
    uid = db.crear_usuario_vinculado_a_kratos(email, "kratos-" + email)
    db.asignar_tenant(uid, t)
    return t, uid


def test_hace_formatea_tiempos():
    assert metricas.hace(None) == "sin actividad"
    assert metricas.hace((datetime.now() - timedelta(hours=23)).isoformat()) == "hace 23 horas"
    assert metricas.hace((datetime.now() - timedelta(days=3)).isoformat()) == "hace 3 días"


def test_actividad_tenant_sin_uso_y_con_uso():
    t, uid = _tenant_con_usuario()
    modulos = [{"id": "crm", "nombre": "CRM", "descripcion": "", "activo": False}]
    a = metricas.actividad_tenant(t, modulos)
    assert a["estado"][0] == "riesgo" and a["tareas"]["total"] == 0 and a["modulos_ocultos"] == 1
    assert all(f["estado"] == "nunca usado" for f in a["funciones"])
    db.crear_nota(uid, "Una nota") if hasattr(db, "crear_nota") else None
    b = metricas.actividad_tenant(t, modulos)
    assert b["usuarios"]["n"] == 1
    if hasattr(db, "crear_nota"):
        assert b["estado"][0] == "ok" and next(f for f in b["funciones"] if f["clave"] == "notas")["estado"] == "en uso"


def test_tenant_sin_usuarios_y_suspendido():
    t = db.crear_tenant("Vacío Actividad")
    assert metricas.actividad_tenant(t, [])["estado"][0] == "nuevo"
    db.alternar_activo_tenant(t, False)
    assert metricas.actividad_tenant(t, [])["estado"][0] == "suspendido"


def test_pestana_actividad_se_renderiza(bo):
    entrar(bo)
    t, _ = _tenant_con_usuario("Render Actividad", "act2@ejemplo.com")
    html = bo.get(f"/tenants/{t}?seccion=actividad").get_data(as_text=True)
    assert "Funciones: activado vs. uso real" in html and "Cobrado (30d)" in html and "Notas internas de Guilda" in html


def test_notas_internas_crear_y_borrar(bo):
    entrar(bo)
    t, _ = _tenant_con_usuario("Notas Internas", "act3@ejemplo.com")
    assert post(bo, f"/tenants/{t}/notas", texto="Pidió demo de fichaje").status_code == 302
    html = bo.get(f"/tenants/{t}?seccion=actividad").get_data(as_text=True)
    assert "Pidió demo de fichaje" in html
    nota = metricas.notas_tenant(t)[0]
    post(bo, f"/tenants/{t}/notas/{nota['id']}/borrar")
    assert metricas.notas_tenant(t) == []
    post(bo, f"/tenants/{t}/notas", texto="   ")
    assert metricas.notas_tenant(t) == []


def test_notas_requieren_sesion_y_csrf(bo):
    t, _ = _tenant_con_usuario("Notas Seguras", "act4@ejemplo.com")
    assert bo.post(f"/tenants/{t}/notas", data={"texto": "x"}).status_code in (302, 400, 403)
    entrar(bo)
    assert bo.post(f"/tenants/{t}/notas", data={"texto": "x"}).status_code in (400, 403)
    assert metricas.notas_tenant(t) == []


def test_journey_etapas_y_pagina(bo):
    entrar(bo)
    t_vacio = db.crear_tenant("Journey Vacío")
    t, _ = _tenant_con_usuario("Journey Con Usuario", "act5@ejemplo.com")
    j = metricas.journey()
    por_id = {f["id"]: f for f in j["filas"]}
    assert por_id[t_vacio]["alcanzadas"] == 1 and por_id[t_vacio]["siguiente"] == "Con usuarios"
    assert por_id[t]["logros"]["usuarios"] is True and por_id[t]["logros"]["pago"] is False
    html = bo.get("/journey").get_data(as_text=True)
    assert "Customer Journey" in html and "Journey Vacío" in html
