"""Reglas «una tarea por cada vencimiento fiscal de un modelo»."""
from datetime import date, timedelta

import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba

HOY = date(2026, 10, 7)


def _d(n):
    return (HOY + timedelta(days=n)).isoformat()


def _despacho():
    tenant = db.crear_tenant("Despacho por vencimiento")
    ana, luis = (db.crear_usuario(f"pv-{n}@x.com", "contrasena123") for n in ("a", "l"))
    for u in (ana, luis):
        db.asignar_tenant(u, tenant)
    return tenant, ana, luis


def test_validaciones():
    tenant, ana, _ = _despacho()
    for kwargs, mensaje in (({"modelo": "", "asunto": "x"}, "Indica el modelo"), ({"modelo": "303", "asunto": " "}, "Indica el modelo"),
                            ({"modelo": "303", "asunto": "x", "crear_dias_antes": 200}, "0 a 120"),
                            ({"modelo": "303", "asunto": "x", "crear_dias_antes": 3, "vence_dias_antes": 5}, "no puede vencer antes")):
        with pytest.raises(ValueError, match=mensaje):
            db.crear_regla_por_vencimiento(ana, **kwargs)
    sin_despacho = db.crear_usuario("pv-sd@x.com", "contrasena123")
    with pytest.raises(ValueError, match="ningún despacho"):
        db.crear_regla_por_vencimiento(sin_despacho, "303", "x")


def test_crea_una_tarea_por_vencimiento_dentro_de_la_ventana_y_es_idempotente():
    tenant, ana, luis = _despacho()
    c1, c2 = db.crear_cliente_fiscal(tenant, "Panadería"), db.crear_cliente_fiscal(tenant, "Taller")
    v_cerca = db.crear_vencimiento_fiscal(tenant, c1, "303", "2T", _d(10), usuario_id=luis)
    v_sin_resp = db.crear_vencimiento_fiscal(tenant, c2, "303", "2T", _d(14))
    db.crear_vencimiento_fiscal(tenant, c1, "303", "3T", _d(40))                            # aún lejos
    db.crear_vencimiento_fiscal(tenant, c1, "303", "1T", _d(-3))                            # ya pasado
    db.crear_vencimiento_fiscal(tenant, c1, "130", "2T", _d(5))                             # otro modelo
    hecho = db.crear_vencimiento_fiscal(tenant, c2, "303", "1T", _d(6))
    db.marcar_presentado_vencimiento_fiscal(tenant, hecho)
    otro_tenant = db.crear_tenant("Otro")
    db.crear_vencimiento_fiscal(otro_tenant, db.crear_cliente_fiscal(otro_tenant, "Ajeno"), "303", "2T", _d(5))
    regla = db.crear_regla_por_vencimiento(ana, "303", "Preparar el {modelo} de {cliente} ({periodo})", 14, 2, estimacion_min=90, prioridad="alta")
    assert db.generar_tareas_por_vencimiento(HOY) == 2
    tareas = {t["asunto"]: t for t in db.listar_tareas_outlook(ana, incluir_asignadas=True)}
    assert set(tareas) == {"Preparar el 303 de Panadería (2T)", "Preparar el 303 de Taller (2T)"}
    pan, taller = tareas["Preparar el 303 de Panadería (2T)"], tareas["Preparar el 303 de Taller (2T)"]
    assert pan["fecha_vencimiento"] == _d(8) and pan["asignada_a"] == luis and pan["cliente_fiscal_id"] == c1        # vence 2 días antes; va al responsable
    assert taller["fecha_vencimiento"] == _d(12) and taller["asignada_a"] is None and (taller["prioridad"], taller["estimacion_min"]) == ("alta", 90)
    assert db.generar_tareas_por_vencimiento(HOY) == 0                                                                   # idempotente
    assert db.listar_reglas_por_vencimiento(ana)[0]["generadas"] == 2
    # más adelante entra el que estaba lejos
    assert db.generar_tareas_por_vencimiento(HOY + timedelta(days=30)) == 1
    # pausada o eliminada no genera
    nuevo = db.crear_vencimiento_fiscal(tenant, c1, "303", "4T", _d(60))
    db.alternar_regla_por_vencimiento(ana, regla)
    assert db.generar_tareas_por_vencimiento(HOY + timedelta(days=50)) == 0
    db.alternar_regla_por_vencimiento(ana, regla)
    assert db.generar_tareas_por_vencimiento(HOY + timedelta(days=50)) == 1
    db.eliminar_regla_por_vencimiento(ana, regla)
    assert db.generar_tareas_por_vencimiento(HOY + timedelta(days=100)) == 0 and v_cerca and v_sin_resp and nuevo


def test_si_la_ventana_ya_empezo_el_vencimiento_de_la_tarea_no_queda_en_el_pasado():
    tenant, ana, _ = _despacho()
    cid = db.crear_cliente_fiscal(tenant, "Urgente")
    db.crear_vencimiento_fiscal(tenant, cid, "111", "2T", _d(1))
    db.crear_regla_por_vencimiento(ana, "111", "Hacer el 111 de {cliente}", 14, 5)
    db.generar_tareas_por_vencimiento(HOY)
    assert db.listar_tareas_outlook(ana)[0]["fecha_vencimiento"] == _d(0)                      # 1 - 5 < hoy: vence hoy


def test_el_responsable_de_otro_despacho_o_el_propio_dueno_no_se_asigna():
    tenant, ana, luis = _despacho()
    cid = db.crear_cliente_fiscal(tenant, "C")
    db.crear_vencimiento_fiscal(tenant, cid, "303", "2T", _d(5), usuario_id=ana)               # el responsable es la propia dueña
    db.crear_regla_por_vencimiento(ana, "303", "Tarea {cliente}")
    db.generar_tareas_por_vencimiento(HOY)
    assert db.listar_tareas_outlook(ana)[0]["asignada_a"] is None
    v2 = db.crear_vencimiento_fiscal(tenant, db.crear_cliente_fiscal(tenant, "D"), "303", "2T", _d(5), usuario_id=luis)
    db.crear_regla_por_vencimiento(ana, "303", "Sin asignar {cliente}", asignar_responsable=False)
    db.generar_tareas_por_vencimiento(HOY)
    sin = [t for t in db.listar_tareas_outlook(ana, incluir_asignadas=True) if t["asunto"] == "Sin asignar D"][0]
    assert sin["asignada_a"] is None and v2


def test_pantalla_y_aplicacion_inmediata(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "pv-p@x.com", "contrasena123")
    tenant = db.crear_tenant("Despacho pantalla pv")
    db.asignar_tenant(uid, tenant)
    cid = db.crear_cliente_fiscal(tenant, "Cliente Pantalla")
    db.crear_vencimiento_fiscal(tenant, cid, "303", "2T", (date.today() + timedelta(days=6)).isoformat())
    html = cliente.get("/tareas/recurrentes").get_data(as_text=True)
    assert "Nueva regla por vencimiento fiscal" in html
    r = cliente.post("/tareas/recurrentes/vencimiento", data={"modelo": "303", "asunto": "Preparar {modelo} de {cliente}", "crear_dias_antes": "14", "vence_dias_antes": "2",
                                                              "estimacion": "1h30", "prioridad": "alta", "asignar_responsable": "on"})
    assert r.status_code == 302 and "error" not in r.headers["Location"]
    [t] = db.listar_tareas_outlook(uid)
    assert t["asunto"] == "Preparar 303 de Cliente Pantalla" and t["estimacion_min"] == 90 and t["prioridad"] == "alta"          # se aplicó al momento
    html = cliente.get("/tareas/recurrentes").get_data(as_text=True)
    assert "Reglas por vencimiento fiscal" in html and "crea 14 d antes · vence 2 d antes" in html
    assert "error=" in cliente.post("/tareas/recurrentes/vencimiento", data={"modelo": "", "asunto": "x"}).headers["Location"]
    regla = db.listar_reglas_por_vencimiento(uid)[0]["id"]
    assert cliente.post(f"/tareas/recurrentes/vencimiento/{regla}/alternar").status_code == 302 and not db.listar_reglas_por_vencimiento(uid)[0]["activa"]
    assert cliente.post(f"/tareas/recurrentes/vencimiento/{regla}/eliminar").status_code == 302 and db.listar_reglas_por_vencimiento(uid) == []
    assert len(db.listar_tareas_outlook(uid)) == 1                                                                              # las ya creadas se quedan
