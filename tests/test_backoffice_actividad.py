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


def test_ultimo_acceso_se_registra_con_limite_y_se_muestra(bo):
    entrar(bo)
    t, uid = _tenant_con_usuario("Acceso Reciente", "acc1@ejemplo.com")
    assert db.obtener_usuario(uid)["ultimo_acceso"] is None
    db.registrar_acceso(uid)
    primero = db.obtener_usuario(uid)["ultimo_acceso"]
    assert primero
    db.registrar_acceso(uid)  # dentro de los 10 min: no reescribe
    assert db.obtener_usuario(uid)["ultimo_acceso"] == primero
    assert "hace" in bo.get(f"/usuarios/{uid}").get_data(as_text=True)


def test_datos_fiscales_y_zona_horaria_desde_el_backoffice(bo):
    entrar(bo)
    t, _ = _tenant_con_usuario("Datos Fiscales", "fis1@ejemplo.com")
    post(bo, f"/tenants/{t}/datos", cif="B12345678", direccion_fiscal="Calle Mayor 1", zona_horaria="Atlantic/Canary")
    fila = db.obtener_tenant(t)
    assert fila["cif"] == "B12345678" and fila["zona_horaria"] == "Atlantic/Canary"
    post(bo, f"/tenants/{t}/datos", cif="B1", direccion_fiscal="", zona_horaria="Marte/Olimpo")
    assert db.obtener_tenant(t)["zona_horaria"] == "Atlantic/Canary"  # zona inválida: no cambia
    html = bo.get(f"/tenants/{t}").get_data(as_text=True)
    assert "B12345678" in html and "Datos fiscales y zona horaria" in html


def test_mapa_de_acceso_muestra_modulos_por_tenant(bo):
    entrar(bo)
    t = db.crear_tenant("Mapa Acceso")
    db.ocultar_herramienta(t, "crm") if hasattr(db, "ocultar_herramienta") else None
    html = bo.get("/mapa").get_data(as_text=True)
    assert "Mapa de acceso" in html and "Mapa Acceso" in html
