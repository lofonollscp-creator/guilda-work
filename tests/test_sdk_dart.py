"""SDK de Dart de la app móvil generado del contrato OpenAPI (`app/sdk_dart.py`, `scripts/generar_sdk_dart.py`).

Si falla `test_lo_versionado_no_se_ha_desfasado`, la API cambió y falta regenerar `mobile/lib/api/generado/`:
    GUILDA_SDK_DART_DESTINO=$PWD/mobile/lib/api/generado scripts/probar.sh --ejecutar scripts/generar_sdk_dart.py"""
from pathlib import Path

import pytest

from app import openapi, sdk_dart

GENERADO = Path(__file__).parent.parent / "mobile/lib/api/generado"


@pytest.fixture
def spec(base_de_datos_temporal):
    from app.main import app as flask_app
    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    with flask_app.test_request_context():
        return openapi.generar_spec()


def _operaciones(spec):
    return sum(1 for ops in spec["paths"].values() for m in ops if m in ("get", "post", "put", "patch", "delete"))


def test_genera_todas_las_operaciones_y_los_modelos(spec):
    ficheros = sdk_dart.generar(spec)
    assert set(ficheros) == {"modelos.g.dart", "operaciones.g.dart"}
    r = sdk_dart.resumen(spec)
    assert r["operaciones"] == _operaciones(spec)
    assert r["modelos"] > 100 and r["enums"] > 0
    assert "class TareaOutlook {" in ficheros["modelos.g.dart"]
    assert "sinReconocer" in ficheros["modelos.g.dart"]       # un estado nuevo del servidor no rompe a una app antigua
    assert "Future<TareaOutlook> obtenerTareaOutlook(" in ficheros["operaciones.g.dart"]


def test_la_salida_es_determinista(spec):
    assert sdk_dart.generar(spec) == sdk_dart.generar(spec)


def test_los_parametros_de_ruta_van_en_el_orden_de_la_ruta():
    spec = {"components": {"schemas": {}}, "paths": {"/api/v1/a/{b_id}/c/{a_id}": {"get": {
        "operationId": "x", "parameters": [{"name": "a_id", "in": "path", "schema": {"type": "integer"}},
                                           {"name": "b_id", "in": "path", "schema": {"type": "integer"}}],
        "responses": {"200": {}}}}}}
    assert "required int bId, required int aId" in sdk_dart.generar(spec)["operaciones.g.dart"]


def test_lo_versionado_no_se_ha_desfasado(spec):
    for nombre, contenido in sdk_dart.generar(spec).items():
        versionado = GENERADO / nombre
        assert versionado.exists(), f"falta {versionado}: ejecuta scripts/generar_sdk_dart.py"
        assert versionado.read_text() == contenido, f"{nombre} desfasado respecto al contrato: regenera el SDK de Dart"
