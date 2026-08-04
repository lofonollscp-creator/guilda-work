"""Tests del documento OpenAPI de /api/v1/* (app/openapi.py) — generado
por introspección en vivo de app/rutas_api.py, no un YAML escrito a mano
(ver el docstring del propio módulo). Aquí se comprueba que la
introspección cubre de verdad todas las rutas reales (si se añade una
ruta nueva a rutas_api.py sin querer, este test lo detecta) y que el
documento resultante es un OpenAPI 3.0 válido de verdad, no solo JSON
bien formado.

Usa un cliente de Flask propio (no el fixture `cliente` de conftest.py)
a propósito: `/api/v1/openapi.json` no toca autenticación ni Kratos, así
que no hace falta pagar el coste de un Kratos de verdad
(`docker-compose.test.yml`) solo para generar/leer este documento."""
import re

import pytest
from openapi_spec_validator import validate

from app import openapi


@pytest.fixture
def cliente_ligero(base_de_datos_temporal):
    from app.main import app as flask_app
    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    with flask_app.test_client() as client:
        yield client


def test_openapi_json_es_publico_sin_token(cliente_ligero):
    resp = cliente_ligero.get("/api/v1/openapi.json")
    assert resp.status_code == 200


def test_openapi_cubre_todas_las_rutas_reales_de_la_api(cliente_ligero):
    with cliente_ligero.application.app_context(), cliente_ligero.application.test_request_context():
        rutas_reales = {
            regla.rule for regla in cliente_ligero.application.url_map.iter_rules()
            if regla.endpoint.startswith("api.")
        }
        spec = openapi.generar_spec()

    rutas_openapi = {re.sub(r"\{(\w+)\}", r"<\1>", ruta) for ruta in spec["paths"]}
    # Las variables de camino en la regla real llevan tipo (<int:tarea_id>),
    # el spec solo el nombre (<tarea_id>) — se compara solo la forma, no el tipo.
    rutas_reales_normalizadas = {re.sub(r"<(?:\w+:)?(\w+)>", r"<\1>", r) for r in rutas_reales}
    assert rutas_openapi == rutas_reales_normalizadas


def test_openapi_documento_es_valido_segun_el_esquema_openapi_3(cliente_ligero):
    with cliente_ligero.application.app_context(), cliente_ligero.application.test_request_context():
        spec = openapi.generar_spec()
    validate(spec)  # lanza si el documento no es un OpenAPI 3.0 válido


def test_openapi_parametro_de_camino_tiene_el_tipo_correcto(cliente_ligero):
    with cliente_ligero.application.app_context(), cliente_ligero.application.test_request_context():
        spec = openapi.generar_spec()
    operacion = spec["paths"]["/api/v1/tareas/{tarea_id}"]["put"]
    parametro = next(p for p in operacion["parameters"] if p["name"] == "tarea_id")
    assert parametro["schema"]["type"] == "integer"


def test_openapi_rutas_publicas_no_llevan_seguridad_bearer(cliente_ligero):
    with cliente_ligero.application.app_context(), cliente_ligero.application.test_request_context():
        spec = openapi.generar_spec()
    assert spec["paths"]["/api/v1/auth/login"]["post"]["security"] == []
    assert spec["paths"]["/api/v1/auth/registro"]["post"]["security"] == []
    assert spec["paths"]["/api/v1/notas"]["post"]["security"] == [{"bearerAuth": []}]


def test_openapi_cuerpo_json_documentado_para_crear_nota(cliente_ligero):
    with cliente_ligero.application.app_context(), cliente_ligero.application.test_request_context():
        spec = openapi.generar_spec()
    cuerpo = spec["paths"]["/api/v1/notas"]["post"]["requestBody"]
    esquema = cuerpo["content"]["application/json"]["schema"]
    assert esquema["required"] == ["texto"]
    assert "categoria_id" in esquema["properties"]
