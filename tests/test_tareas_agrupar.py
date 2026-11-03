"""Agrupar la lista de tareas (T1): la función pura, la pantalla y que las vistas guardadas recuerden el agrupado."""
from datetime import date, timedelta

from app import db, tareas_agrupar
from tests.conftest import iniciar_sesion_de_prueba

HOY = date(2026, 11, 3)
ESTADOS = {"no_iniciada": "No iniciada", "en_progreso": "En curso", "completada": "Completada"}
PRIORIDADES = {"alta": "Alta", "normal": "Normal", "baja": "Baja"}


def _t(**kw):
    base = {"cliente_fiscal_id": None, "categoria_id": None, "asignada_a": None, "usuario_id": 1, "fecha_vencimiento": None, "estado": "no_iniciada", "prioridad": "normal", "asunto": "x"}
    return {**base, **kw}


def test_agrupa_por_cliente_con_los_sin_cliente_al_final():
    tareas = [_t(asunto="a", cliente_fiscal_id=2), _t(asunto="b"), _t(asunto="c", cliente_fiscal_id=1), _t(asunto="d", cliente_fiscal_id=2)]
    g = tareas_agrupar.agrupar("cliente", tareas, clientes={1: "Zeta SL", 2: "Alfa SA"}, proyectos={}, personas={}, estados=ESTADOS, prioridades=PRIORIDADES, hoy=HOY)
    assert [(x["titulo"], [t["asunto"] for t in x["tareas"]]) for x in g] == [("Alfa SA", ["a", "d"]), ("Zeta SL", ["c"]), ("Sin cliente", ["b"])]


def test_agrupa_por_fecha_en_tramos_ordenados():
    d = lambda n: (HOY + timedelta(days=n)).isoformat()
    tareas = [_t(asunto="lejos", fecha_vencimiento=d(90)), _t(asunto="ayer", fecha_vencimiento=d(-1)), _t(asunto="sin"), _t(asunto="hoy", fecha_vencimiento=d(0) + "T09:00"),
              _t(asunto="semana", fecha_vencimiento=d(5)), _t(asunto="mañana", fecha_vencimiento=d(1))]
    g = tareas_agrupar.agrupar("fecha", tareas, clientes={}, proyectos={}, personas={}, estados=ESTADOS, prioridades=PRIORIDADES, hoy=HOY)
    assert [(x["titulo"], [t["asunto"] for t in x["tareas"]]) for x in g] == [("Vencidas", ["ayer"]), ("Hoy", ["hoy"]), ("Mañana", ["mañana"]), ("Esta semana", ["semana"]), ("Más adelante", ["lejos"]), ("Sin fecha", ["sin"])]


def test_agrupa_por_responsable_estado_y_prioridad():
    tareas = [_t(asunto="mia", usuario_id=1), _t(asunto="de_ana", usuario_id=1, asignada_a=2, estado="completada", prioridad="alta")]
    g = tareas_agrupar.agrupar("responsable", tareas, clientes={}, proyectos={}, personas={1: "Yo", 2: "Ana"}, estados=ESTADOS, prioridades=PRIORIDADES, hoy=HOY)
    assert [x["titulo"] for x in g] == ["Ana", "Yo"]
    g = tareas_agrupar.agrupar("estado", tareas, clientes={}, proyectos={}, personas={}, estados=ESTADOS, prioridades=PRIORIDADES, hoy=HOY)
    assert [x["titulo"] for x in g] == ["No iniciada", "Completada"]
    g = tareas_agrupar.agrupar("prioridad", tareas, clientes={}, proyectos={}, personas={}, estados=ESTADOS, prioridades=PRIORIDADES, hoy=HOY)
    assert [x["titulo"] for x in g] == ["Alta", "Normal"]
    assert tareas_agrupar.agrupar("otra", tareas, clientes={}, proyectos={}, personas={}, estados=ESTADOS, prioridades=PRIORIDADES) == []


def test_la_lista_se_agrupa_sin_paginar_y_la_vista_guardada_lo_recuerda(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "agrupar-1@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho agrupar")
    db.asignar_tenant(uid, t)
    cf = db.crear_cliente_fiscal(t, "Panadería Marta")
    db.crear_tarea_outlook(uid, "Presentar 303 de Marta", cliente_fiscal_id=cf)
    db.crear_tarea_outlook(uid, "Tarea suelta")
    html = cliente.get("/tareas/?agrupar=cliente").get_data(as_text=True)
    assert 'class="tareas-grupo"' in html and "Panadería Marta" in html and "Sin cliente" in html and "Presentar 303 de Marta" in html and "Tarea suelta" in html
    plana = cliente.get("/tareas/").get_data(as_text=True)
    assert "tareas-grupo-titulo" not in plana
    assert cliente.get("/tareas/?agrupar=inventado").status_code == 200 and "tareas-grupo-titulo" not in cliente.get("/tareas/?agrupar=inventado").get_data(as_text=True)
    assert cliente.post("/tareas/vistas", data={"nombre": "Por cliente", "agrupar": "cliente", "vista": "mias"}).status_code == 302
    assert db.listar_vistas_tareas(uid)[0]["filtros"].get("agrupar") == "cliente"
