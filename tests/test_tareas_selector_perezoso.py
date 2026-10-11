"""El selector de proyecto del cronómetro no repite sus opciones en cada fila: van una vez en una <template>."""
import re

from app import db
from tests.conftest import iniciar_sesion_de_prueba


def test_las_filas_sin_proyecto_no_repiten_la_lista_de_proyectos(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "perezoso@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, db.crear_tenant("Despacho perezoso"))
    for i in range(30):
        db.crear_categoria(uid, f"Proyecto {i}", None)
    for i in range(25):
        db.crear_tarea_outlook(uid, f"Tarea {i}")
    for ruta in ("/tareas/", "/tareas/hoy"):
        html = cliente.get(ruta).get_data(as_text=True)
        if ruta == "/tareas/":
            assert html.count('<template id="opciones-proyectos-cronometro">') == 1
            assert html.count("data-proyectos-perezoso") >= 25
            # los selectores del formulario y del filtro llevan sus 30; las 25 filas no añaden nada (antes: +750)
            assert len(re.findall(r'<option value="\d+">Proyecto \d+</option>', html)) <= 4 * 30
        else:
            assert html.count('id="opciones-proyectos-cronometro"') <= 1


def test_el_script_vuelca_las_opciones_al_tocar_el_selector():
    js = open("app/static/timer.js", encoding="utf-8").read()
    assert "opciones-proyectos-cronometro" in js and "data-proyectos-perezoso" in js and "pointerdown" in js
