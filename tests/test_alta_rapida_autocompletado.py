"""Autocompletado del alta rápida: lo que se inserta al elegir una opción lo resuelve el propio alta a esa misma persona o proyecto."""
from datetime import date

from app import db, quickadd
from tests.conftest import iniciar_sesion_de_prueba

HOY = date(2026, 11, 3)


def test_cada_opcion_se_resuelve_a_su_persona_y_a_su_proyecto():
    personas = [(1, "Luis Gómez", "luis.gomez@x.es"), (2, "Luis Pérez", "luis.perez@x.es"), (3, "Marta Puig", "marta@x.es")]
    etiquetas = [(10, "Cierre trimestral"), (11, "IVA"), (12, "Declaración de la renta 2025")]
    o = quickadd.opciones_autocompletado(personas, etiquetas)
    assert [p["insertar"] for p in o["personas"]] == ["@Gómez", "@Pérez", "@Marta"]       # los dos Luis se distinguen por el apellido
    assert [e["insertar"] for e in o["etiquetas"]] == ['#"Cierre trimestral"', "#IVA", '#"Declaración de la renta 2025"']
    for (pid, _n, _e), op in zip(personas, o["personas"]):
        assert quickadd.interpretar(f"llamar {op['insertar']}", HOY, personas, etiquetas).persona_id == pid
    for (eid, _n), op in zip(etiquetas, o["etiquetas"]):
        assert quickadd.interpretar(f"revisar {op['insertar']}", HOY, personas, etiquetas).etiqueta_id == eid


def test_la_lista_de_tareas_ofrece_sugerencias_y_vista_previa(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "autoc-1@x.com", "contrasena123")
    t = db.crear_tenant("Despacho autocompletado")
    db.asignar_tenant(uid, t)
    luis = db.crear_usuario("luis.autoc@x.com", "contrasena123")
    db.asignar_tenant(luis, t)
    db.crear_categoria(uid, "Cierre trimestral")
    d = cliente.get("/tareas/sugerencias-alta.json").get_json()
    assert any(p["insertar"].startswith("@") for p in d["personas"]) and {"nombre": "Cierre trimestral", "insertar": '#"Cierre trimestral"'} in d["etiquetas"]
    v = cliente.get("/tareas/interpretar-alta", query_string={"texto": "viernes 10h llamar @luis !alta"}).get_json()
    assert v["prioridad"] == "alta" and v["hora"] and v["persona"] and v["asunto"] == "llamar"
    html = cliente.get("/tareas/").get_data(as_text=True)
    assert "data-alta-rapida" in html and "alta_rapida.js" in html and 'id="tarea-alta-previa"' in html


def test_las_sugerencias_exigen_sesion(cliente):
    assert cliente.get("/tareas/sugerencias-alta.json").status_code in (302, 401)
