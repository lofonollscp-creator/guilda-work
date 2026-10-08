"""Estimación de tiempo en las tareas: texto libre (~2h), formulario, API, comparación con lo registrado."""
from datetime import date

import pytest

from app import db, quickadd
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_proyectos_paginas import _dueno

HOY = date(2026, 10, 7)


@pytest.mark.parametrize("texto,minutos", [
    ("revisar balance ~2h", 120), ("x ~1h30", 90), ("x ~1h 30m", 90), ("x ~90m", 90), ("x ~45 min", 45), ("x ~1,5h", 90), ("x ~1.5 h", 90),
    ("x ~ 2 horas", 120), ("x ~3 hours", 180), ("x ~2 heures", 120), ("x ~30 minuts", 30),
])
def test_estimacion_en_texto_libre(texto, minutos):
    r = quickadd.interpretar(texto, HOY)
    assert r.estimacion_min == minutos and "~" not in r.asunto


@pytest.mark.parametrize("texto", ["x ~5", "x ~0m", "x ~200h", "x ~", "pesa ~2kg", "aprox 2h", "x 2h"])
def test_lo_que_no_es_una_estimacion_se_deja_en_el_titulo(texto):
    r = quickadd.interpretar(texto, HOY)
    assert r.estimacion_min is None


def test_estimacion_junto_al_resto_de_marcas():
    r = quickadd.interpretar("viernes 10h pedir extractos ~1h30 !alta", HOY)
    assert (r.asunto, r.estimacion_min, r.prioridad, r.hora) == ("pedir extractos", 90, "alta", "10:00")
    solo = quickadd.interpretar("~2h", HOY)
    assert solo.estimacion_min == 120 and solo.asunto == "~2h"           # nunca se queda una tarea sin título


@pytest.mark.parametrize("texto,minutos", [("1h30", 90), ("2", 120), ("8", 480), ("24", 1440), ("25", 25), ("90", 90), ("1,5", 90), ("45 min", 45),
                                          ("", None), ("abc", None), ("0", None), ("6001", None), ("-1", None), ("2 dias", None)])
def test_duracion_a_minutos(texto, minutos):
    assert quickadd.duracion_a_minutos(texto) == minutos


def test_formatear_minutos_y_vuelta():
    assert [quickadd.formatear_minutos(m) for m in (None, 0, 45, 60, 90, 125)] == ["", "", "45 min", "1h", "1h 30", "2h 05"]
    for m in (45, 60, 90, 125, 600):
        assert quickadd.duracion_a_minutos(quickadd.formatear_minutos(m)) == m            # lo que muestra el formulario se entiende al guardarlo


def test_db_valida_la_estimacion_al_crear_y_editar():
    uid = db.crear_usuario("est-1@x.com", "contrasena123")
    bien, mal, fuera = (db.crear_tarea_outlook(uid, n, estimacion_min=v) for n, v in (("a", 90), ("b", "xx"), ("c", 99999)))
    assert [db.obtener_tarea_outlook(uid, t)["estimacion_min"] for t in (bien, mal, fuera)] == [90, None, None]
    db.editar_tarea_outlook(uid, bien, estimacion_min=120)
    assert db.obtener_tarea_outlook(uid, bien)["estimacion_min"] == 120
    db.editar_tarea_outlook(uid, bien, estimacion_min=None)
    assert db.obtener_tarea_outlook(uid, bien)["estimacion_min"] is None
    assert any(a["tipo"] == "editada" and "estimación" in a["detalle"] for a in db.actividad_de_tarea(uid, bien))


def test_alta_en_la_lista_general_con_texto_y_con_campo(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "est-2@x.com", "contrasena123")
    cliente.post("/tareas/", data={"asunto": "preparar informe ~2h"})
    cliente.post("/tareas/", data={"asunto": "otra ~2h", "estimacion": "30 min"})                 # el campo manda sobre el texto
    por_asunto = {t["asunto"]: t for t in db.listar_tareas_outlook(uid)}
    assert por_asunto["preparar informe"]["estimacion_min"] == 120 and por_asunto["otra"]["estimacion_min"] == 30


def test_editar_desde_el_formulario_y_ver_estimado_frente_a_real(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "est-3@x.com", "contrasena123")
    categoria = db.crear_categoria(uid, "P")
    t = db.crear_tarea_outlook(uid, "Con tiempo", categoria_id=categoria)
    html = cliente.get(f"/tareas/{t}/editar").get_data(as_text=True)
    assert 'name="estimacion"' in html
    cliente.post(f"/tareas/{t}/editar", data={"asunto": "Con tiempo", "estado": "no_iniciada", "prioridad": "normal", "estimacion": "1h", "categoria_id": str(categoria)})
    assert db.obtener_tarea_outlook(uid, t)["estimacion_min"] == 60
    assert 'value="1h"' in cliente.get(f"/tareas/{t}/editar").get_data(as_text=True)
    # tiempo registrado por el cronómetro (2 h): se pasa de lo estimado
    cron = db.iniciar_cronometro_tarea_outlook(uid, t)
    conn = db.get_connection()
    conn.execute("UPDATE tareas SET estado = 'finalizada', duracion_segundos = 7200 WHERE id = ?", (cron,))
    conn.commit()
    conn.close()
    assert db.cronometros_de_tareas_outlook(uid, [t])[t]["equipo_segundos"] == 7200
    fila = cliente.get("/tareas/").get_data(as_text=True)
    assert "tarea-estimacion texto-peligro" in fila and "2h / 1h" in fila
    cliente.post(f"/tareas/{t}/editar", data={"asunto": "Con tiempo", "estado": "no_iniciada", "prioridad": "normal", "estimacion": "", "categoria_id": str(categoria)})
    assert db.obtener_tarea_outlook(uid, t)["estimacion_min"] is None
    assert "tarea-estimacion" not in cliente.get("/tareas/").get_data(as_text=True)


def test_el_tiempo_del_equipo_suma_a_todas_las_personas():
    tenant = db.crear_tenant("Despacho est")
    ana, luis = (db.crear_usuario(f"est-{n}@x.com", "contrasena123") for n in ("a", "l"))
    for u in (ana, luis):
        db.asignar_tenant(u, tenant)
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, luis, "colabora")
    t = db.crear_tarea_en_proyecto(ana, p, "Compartida", estimacion_min=240)
    for quien, seg in ((ana, 3600), (luis, 1800)):
        n = db.iniciar_cronometro_tarea_outlook(quien, t)
        conn = db.get_connection()
        conn.execute("UPDATE tareas SET estado = 'finalizada', duracion_segundos = ? WHERE id = ?", (seg, n))
        conn.commit()
        conn.close()
    cr = db.cronometros_de_tareas_outlook(luis, [t])[t]
    assert (cr["total_segundos"], cr["equipo_segundos"]) == (1800, 5400)


def test_proyecto_alta_rapida_resumen_y_vista_previa(cliente):
    uid, tenant, p = _dueno(cliente, "est-p@x.com")
    cliente.post(f"/proyecto/{p}/tareas", data={"asunto": "Cuadrar IVA ~3h"})
    cliente.post(f"/proyecto/{p}/tareas", data={"asunto": "Otra ~90m"})
    cliente.post(f"/proyecto/{p}/tareas", data={"asunto": "Sin estimar"})
    resumen = db.resumen_proyecto(uid, p)
    assert resumen["estimado_pendiente_min"] == 270 and resumen["sin_estimar"] == 1
    html = cliente.get(f"/proyecto/{p}").get_data(as_text=True)
    assert "Estimado pendiente" in html and "4h 30" in html and "1 sin estimar" in html
    previa = cliente.get(f"/proyecto/{p}/interpretar", query_string={"texto": "algo ~1h30"}).get_json()
    assert previa["estimacion"] == "1h 30" and previa["asunto"] == "algo"
    t = [x for x in db.tareas_de_proyecto(uid, p) if x["asunto"] == "Cuadrar IVA"][0]
    db.completar_tarea_outlook(uid, t["id"])
    assert db.resumen_proyecto(uid, p)["estimado_pendiente_min"] == 90                 # lo completado ya no cuenta como pendiente


def test_api_acepta_la_estimacion(cliente):
    token = cliente.post("/api/v1/auth/registro", json={"email": "est-api@x.com", "contrasena": "contrasena123"}).get_json()["data"]["token"]
    cab = {"Authorization": f"Bearer {token}"}
    r = cliente.post("/api/v1/tareas-outlook", json={"asunto": "Desde la API", "estimacion_min": 75}, headers=cab)
    assert r.status_code == 201 and r.get_json()["data"]["estimacion_min"] == 75
    tid = r.get_json()["data"]["id"]
    r = cliente.put(f"/api/v1/tareas-outlook/{tid}", json={"estimacion_min": 500000}, headers=cab)
    assert r.get_json()["data"]["estimacion_min"] is None                                 # fuera de rango: se descarta
