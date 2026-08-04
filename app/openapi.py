"""Genera el documento OpenAPI 3.0 de `/api/v1/*` (`app/rutas_api.py`,
ver `GET /api/v1/openapi.json`) **por introspección en vivo**, no un
YAML escrito a mano — mismo motivo que
`app/documentacion_dev.py:_firma_tool` deriva las firmas de las tools
MCP con `inspect.signature()` en vez de copiarlas: un documento aparte
se desincroniza del código real la primera vez que alguien cambia una
ruta y se olvida de actualizarlo.

## Qué se deriva y qué se escribe a mano

- Ruta, método(s) y tipo de cada parámetro de camino: de la propia
  regla de Flask (`current_app.url_map`, filtrado al blueprint `api`)
  — `<int:tarea_id>` da `integer` directamente, sin adivinar nada.
- `summary` de cada operación: la primera línea del docstring de la
  función vista si existe; si no (la mayoría de rutas de
  `rutas_api.py` no tienen, verificado antes de escribir esto), se
  deriva humanizando el nombre de la función (`crear_nota` →
  "Crear nota") — sigue sin ser texto duplicado a mano, cambia solo si
  cambia el nombre de la función.
- Cuerpo JSON esperado en POST/PUT: **sí escrito a mano**, en
  `_CUERPOS` más abajo — Flask no expone esa forma en su `url_map` (no
  hay validación de esquema en las rutas, son `datos.get(...)`
  sueltos), así que no hay nada real de qué derivarlo. Se mantiene
  deliberadamente pequeño (solo los campos que ya se leen en el
  cuerpo de cada función).

Sin Swagger UI ni ninguna dependencia JS nueva (mismo criterio de
minimizar dependencias que el resto del proyecto) — el JSON es
directamente importable en Postman/Insomnia/cualquier generador de
cliente, que es el caso de uso real para integraciones externas.
"""
import re

from flask import current_app

# Claves = nombre de clase del converter de Werkzeug en minúsculas y sin
# el sufijo "converter" (verificado en vivo: IntegerConverter → "integer",
# UnicodeConverter → "unicode" — Werkzeug usa "unicode", no "string", para
# el converter por defecto de un `<variable>` sin tipo explícito).
_TIPOS_CONVERTER = {
    "integer": "integer",
    "float": "number",
    "unicode": "string",
    "path": "string",
    "uuid": "string",
}

# Cuerpo JSON esperado en los POST/PUT donde de verdad hace falta
# aclararlo (Flask no lo expone, ver docstring del módulo) — clave:
# "<endpoint_de_flask>" tal cual aparece en url_map (p.ej.
# "api.crear_nota"), valor: {campo: {"type": ..., "required": bool}}.
_CUERPOS: dict[str, dict[str, dict]] = {
    "api.registro": {
        "email": {"type": "string", "required": True},
        "contrasena": {"type": "string", "required": True},
        "nombre_dispositivo": {"type": "string", "required": False},
    },
    "api.login": {
        "email": {"type": "string", "required": True},
        "contrasena": {"type": "string", "required": True},
    },
    "api.crear_categoria": {
        "nombre": {"type": "string", "required": True},
        "color": {"type": "string", "required": False},
    },
    "api.reordenar_categorias": {
        "orden": {"type": "array", "items": {"type": "integer"}, "required": True},
    },
    "api.crear_nota": {
        "texto": {"type": "string", "required": True},
        "categoria_id": {"type": "integer", "required": False},
    },
    "api.editar_nota": {
        "texto": {"type": "string", "required": True},
    },
    "api.crear_tarea": {
        "nombre": {"type": "string", "required": True},
        "categoria_id": {"type": "integer", "required": True},
        "tipo": {"type": "string", "required": False, "enum": ["duracion", "instantanea"]},
    },
    "api.editar_tarea": {
        "nombre": {"type": "string", "required": True},
    },
    "api.enviar_correo": {
        "cuenta_id": {"type": "integer", "required": True},
        "para": {"type": "array", "items": {"type": "string"}, "required": True},
        "asunto": {"type": "string", "required": True},
        "cuerpo": {"type": "string", "required": True},
    },
}

_RESPUESTA_OK = {
    "type": "object",
    "properties": {"ok": {"type": "boolean", "enum": [True]}, "data": {}},
}
_RESPUESTA_ERROR = {
    "type": "object",
    "properties": {"ok": {"type": "boolean", "enum": [False]}, "error": {"type": "string"}},
}


def _humanizar(nombre_funcion: str) -> str:
    palabras = nombre_funcion.replace("_", " ").strip()
    return palabras[0].upper() + palabras[1:] if palabras else nombre_funcion


def _parametros_de_ruta(regla) -> list[dict]:
    parametros = []
    for variable in regla.arguments:
        tipo_flask = regla._converters[variable].__class__.__name__.lower().replace("converter", "") or "default"
        parametros.append({
            "name": variable,
            "in": "path",
            "required": True,
            "schema": {"type": _TIPOS_CONVERTER.get(tipo_flask, "string")},
        })
    return parametros


def _request_body(endpoint: str) -> dict | None:
    campos = _CUERPOS.get(endpoint)
    if not campos:
        return None
    propiedades = {nombre: {k: v for k, v in info.items() if k != "required"} for nombre, info in campos.items()}
    requeridos = [nombre for nombre, info in campos.items() if info.get("required")]
    esquema = {"type": "object", "properties": propiedades}
    if requeridos:
        esquema["required"] = requeridos
    return {"required": True, "content": {"application/json": {"schema": esquema}}}


def generar_spec() -> dict:
    """Recorre `current_app.url_map` y construye el documento OpenAPI
    3.0 completo de `/api/v1/*` — se llama en cada petición a
    `GET /api/v1/openapi.json` (barato: 66 rutas, nada que cachear)."""
    paths: dict[str, dict] = {}
    for regla in current_app.url_map.iter_rules():
        if not regla.endpoint.startswith("api."):
            continue
        vista = current_app.view_functions[regla.endpoint]
        docstring = (vista.__doc__ or "").strip().splitlines()[0] if vista.__doc__ else ""
        resumen = docstring or _humanizar(vista.__name__)
        ruta_openapi = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", regla.rule)

        # "/api/v1/correo/mensajes/..." -> "correo"; "/api/v1/notas" -> "notas".
        segmentos = regla.rule.removeprefix("/api/v1/").strip("/").split("/")
        etiqueta = segmentos[0] if segmentos and segmentos[0] else "raíz"

        operaciones = paths.setdefault(ruta_openapi, {})
        for metodo in regla.methods - {"HEAD", "OPTIONS"}:
            operacion = {
                "summary": resumen,
                "operationId": regla.endpoint.replace("api.", ""),
                "tags": [etiqueta],
                "parameters": _parametros_de_ruta(regla),
                "responses": {
                    "200": {"description": "OK", "content": {"application/json": {"schema": _RESPUESTA_OK}}},
                    "400": {"description": "Error de validación", "content": {"application/json": {"schema": _RESPUESTA_ERROR}}},
                    "401": {"description": "Token ausente o inválido", "content": {"application/json": {"schema": _RESPUESTA_ERROR}}},
                    "404": {"description": "No encontrado", "content": {"application/json": {"schema": _RESPUESTA_ERROR}}},
                },
                "security": [{"bearerAuth": []}] if regla.endpoint not in ("api.registro", "api.login") else [],
            }
            cuerpo = _request_body(regla.endpoint)
            if cuerpo and metodo in ("POST", "PUT"):
                operacion["requestBody"] = cuerpo
            operaciones[metodo.lower()] = operacion

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Guilda Work API",
            "version": "1.0.0",
            "description": (
                "API REST de la app móvil de Guilda Work — autenticación por "
                "cabecera `Authorization: Bearer <token>`. Todas las respuestas "
                "siguen el mismo sobre: `{\"ok\": true, \"data\": ...}` en éxito, "
                "`{\"ok\": false, \"error\": \"...\"}` en fallo."
            ),
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            },
        },
        "paths": dict(sorted(paths.items())),
    }
