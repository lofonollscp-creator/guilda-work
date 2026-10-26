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
