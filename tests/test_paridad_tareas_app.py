"""Paridad web ↔ app en tareas (docs/plan-tareas-paridad-app.md, regla 4): para los mismos datos, la lista de la web y la lista que pide la app a la API traen las mismas tareas y en el mismo orden."""
import re
from datetime import date, timedelta

import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_rutas_api import _auth, _registrar


def _sembrar(uid):
    hoy = date.today()
    datos = [
        ("T01 vencida alta", dict(prioridad="alta", fecha_vencimiento=(hoy - timedelta(days=3)).isoformat(), categoria_outlook="Fiscal")),
        ("T02 hoy", dict(fecha_vencimiento=hoy.isoformat())),
        ("T03 en curso", dict(estado="en_progreso", prioridad="baja")),
        ("T04 hecha", dict(estado="completada")),
        ("T05 esperando", dict(estado="esperando", categoria_outlook="Laboral")),
        ("T06 sin fecha alta", dict(prioridad="alta")),
        ("T07 hecha alta", dict(estado="completada", prioridad="alta")),
    ]
    for asunto, extra in datos:
        db.crear_tarea_outlook(uid, asunto=asunto, **extra)


def _asuntos_web(cliente, **q):
    html = cliente.get("/tareas/", query_string=q).get_data(as_text=True)
    visto, orden = set(), []
    for m in re.finditer(r'href="/tareas/\d+(?:/editar)?">(T\d\d[^<]*)</a>', html):
        if m.group(1) not in visto:
            visto.add(m.group(1)); orden.append(m.group(1))
    return orden


def _asuntos_api(cliente, h, **q):
    r = cliente.get("/api/v1/tareas-outlook", query_string={"limit": 50, **q}, headers=h)
    assert r.status_code == 200
    return [t["asunto"] for t in r.get_json()["data"]]


@pytest.fixture
def ambos(cliente):
    web = iniciar_sesion_de_prueba(cliente, "paridad-web@ejemplo.com", "contrasena123")
    api = _registrar(cliente.application.test_client(), "paridad-api@ejemplo.com")
    _sembrar(web)
    _sembrar(api["usuario"]["id"])
    return cliente, cliente.application.test_client(), _auth(api["token"])


# (parámetros de la web, parámetros de la app): la app manda lo que la web llama de otra forma
CASOS = [
    ({}, {"ambito": "todas", "completadas": "0"}),                                              # vista por defecto: oculta las completadas
    ({"completadas": "1"}, {"ambito": "todas", "completadas": "1"}),
    ({"vista": "mias"}, {"ambito": "propias", "completadas": "0"}),
    ({"estado": "en_progreso"}, {"ambito": "todas", "estado": "en_progreso", "completadas": "0"}),
    ({"estado": "completada"}, {"ambito": "todas", "estado": "completada", "completadas": "0"}),   # pedir un estado manda sobre «ocultar completadas»
    ({"prioridad": "alta"}, {"ambito": "todas", "prioridad": "alta", "completadas": "0"}),
    ({"prioridad": "alta", "completadas": "1"}, {"ambito": "todas", "prioridad": "alta", "completadas": "1"}),
    ({"categoria": "Fiscal"}, {"ambito": "todas", "categoria": "Fiscal", "completadas": "0"}),
    ({"q": "hoy"}, {"ambito": "todas", "q": "hoy", "completadas": "0"}),
]


@pytest.mark.parametrize("web,app", CASOS, ids=[str(c[0]) for c in CASOS])
def test_la_lista_de_la_app_trae_lo_mismo_que_la_de_la_web(ambos, web, app):
    cliente_web, cliente_api, h = ambos
    esperado = _asuntos_web(cliente_web, **web)
    assert esperado, "el caso tiene que traer algo para que la comparación valga"
    assert _asuntos_api(cliente_api, h, **app) == esperado


# --- «Mi día» y tablero ---------------------------------------------------------------------------------------------

def _asuntos_de(html: str) -> list[str]:
    visto, orden = set(), []
    for m in re.finditer(r'href="/tareas/\d+(?:/editar)?">(T\d\d[^<]*)</a>', html):
        if m.group(1) not in visto:
            visto.add(m.group(1)); orden.append(m.group(1))
    return orden


def _sembrar_dia(uid):
    hoy = date.today()
    for asunto, extra in [
        ("T01 vencida", dict(fecha_vencimiento=(hoy - timedelta(days=2)).isoformat())),
        ("T02 hoy", dict(fecha_vencimiento=hoy.isoformat())),
        ("T03 en curso", dict(estado="en_progreso")),
        ("T04 hecha", dict(estado="completada")),
        ("T05 esperando", dict(estado="esperando")),
        ("T06 sin fecha", dict()),
        ("T07 aplazada", dict(estado="aplazada")),
    ]:
        db.crear_tarea_outlook(uid, asunto=asunto, **extra)


@pytest.fixture
def ambos_dia(cliente):
    web = iniciar_sesion_de_prueba(cliente, "paridad-dia-web@ejemplo.com", "contrasena123")
    api = _registrar(cliente.application.test_client(), "paridad-dia-api@ejemplo.com")
    _sembrar_dia(web)
    _sembrar_dia(api["usuario"]["id"])
    return cliente, cliente.application.test_client(), _auth(api["token"])


def test_mi_dia_de_la_app_tiene_las_mismas_secciones_y_tareas_que_la_web(ambos_dia):
    web, api, h = ambos_dia
    html = web.get("/tareas/hoy").get_data(as_text=True)
    secciones_web = {}
    for m in re.finditer(r'<section class="tareas-dia-seccion tareas-dia-(\w+)" id="seccion-\w+">(.*?)</section>', html, re.S):
        secciones_web[m.group(1)] = _asuntos_de(m.group(2))
    datos = api.get("/api/v1/mi-dia", headers=h).get_json()["data"]
    assert set(datos) == {"vencidas", "hoy", "en_progreso", "asignadas", "compartidas"}
    assert secciones_web == {k: [t["asunto"] for t in v] for k, v in datos.items() if v}
    assert secciones_web["vencidas"] == ["T01 vencida"] and secciones_web["hoy"] == ["T02 hoy"]
    fila = datos["vencidas"][0]
    assert fila["vencida"] is True and fila["rol"] == "dueno" and fila["n_comentarios"] == 0


def test_el_tablero_de_la_app_tiene_las_mismas_columnas_y_tareas_que_el_de_la_web(ambos_dia):
    web, api, h = ambos_dia
    html = web.get("/tareas/tablero").get_data(as_text=True)
    columnas_web = {}
    for m in re.finditer(r'<section class="tareas-columna estado-(\w+)".*?</section>', html, re.S):
        columnas_web[m.group(1)] = _asuntos_de(m.group(0))
    datos = api.get("/api/v1/tareas-outlook/tablero", query_string={"recientes": 15}, headers=h).get_json()["data"]
    assert columnas_web == {k: [t["asunto"] for t in datos.get(k, [])] for k in columnas_web}
    assert columnas_web["completada"] == ["T04 hecha"] and columnas_web["en_progreso"] == ["T03 en curso"]
