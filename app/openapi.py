"""Genera el documento OpenAPI 3.0 de `/api/v1/*` (`GET /api/v1/openapi.json`) **a partir del propio código**, no de un fichero escrito
a mano que se desincroniza:

- rutas, métodos y parámetros de camino: de `current_app.url_map`;
- cuerpo de la petición (JSON o multipart), parámetros de consulta y códigos de respuesta: se leen de cada vista con `ast`
  (ver `openapi_analisis.py`);
- esquemas de las entidades (Nota, TareaOutlook, ClienteFiscal...): de las columnas de las tablas reales;
- lo que solo sabe una persona (tipos de campos, descripciones, esquemas a medida, ejemplos): `openapi_catalogo.py`.

Un test de contrato (`tests/test_openapi_contrato.py`) comprueba que el documento es válido, que cada campo que lee una vista aparece
documentado, que lo que devuelve la API cumple su esquema y que no desaparece nada documentado respecto a la versión anterior."""
from __future__ import annotations

import inspect
import re

from flask import current_app, request

from . import db, openapi_analisis as analisis
from . import openapi_catalogo as cat
from .api_areas import AREAS, area_de_ruta

_TIPOS_CONVERTER = {"integer": "integer", "float": "number", "unicode": "string", "path": "string", "uuid": "string"}
_DESCRIPCION_CODIGO = {200: "Correcto", 201: "Creado", 202: "Aceptado (se procesará en segundo plano)"}
_ERRORES = {
    400: ("Petición no válida: falta un campo, un valor no vale o el formato es incorrecto.", "peticion_invalida"),
    401: ("Token ausente, inválido o caducado (`token_invalido`, `token_caducado`).", "token_invalido"),
    403: ("Sin permiso: el token es de solo lectura o de otra área (`token_solo_lectura`, `token_area_no_permitida`), o no tienes el rol necesario (`prohibido`, `sin_permiso`).", "prohibido"),
    404: ("No existe, o no es tuyo (no se distingue, a propósito).", "no_encontrado"),
    409: ("Conflicto: duplicado (`referencia_duplicada`, `vencimiento_duplicado`), tarea bloqueada o idempotencia en curso.", "conflicto"),
    422: ("Entidad no procesable: misma `Idempotency-Key` con una petición distinta.", "idempotencia_conflicto"),
    429: ("Demasiadas peticiones. Espera los segundos de `Retry-After`.", "limite_excedido"),
    500: ("Error interno. Indica el `request_id` al pedir soporte.", "error_interno"),
    503: ("Servicio no disponible ahora mismo (almacén de documentos, mantenimiento...).", "error_interno"),
}


def _humanizar(nombre_funcion: str) -> str:
    palabras = nombre_funcion.replace("_", " ").strip()
    return palabras[0].upper() + palabras[1:] if palabras else nombre_funcion


def _parametros_de_ruta(regla) -> list[dict]:
    parametros = []
    for variable in regla.arguments:
        tipo_flask = regla._converters[variable].__class__.__name__.lower().replace("converter", "") or "default"
        parametros.append({
            "name": variable, "in": "path", "required": True,
            "description": cat.DESCRIPCIONES.get(variable, "Identificador."),
            "schema": {"type": _TIPOS_CONVERTER.get(tipo_flask, "string")},
        })
    return parametros


def _esquema_de_tabla(tabla: str, excluir: tuple[str, ...], extra: dict) -> dict:
    """Propiedades a partir de las columnas reales de la tabla (con su tipo y si admiten nulos)."""
    propiedades: dict[str, dict] = {}
    conn = db.get_connection()
    try:
        columnas = conn.execute(f"PRAGMA table_info({tabla})").fetchall()
    finally:
        conn.close()
    for c in columnas:
        if c["name"] in excluir:
            continue
        tipo = cat._AFINIDAD.get((c["type"] or "").upper().split("(")[0].strip(), "string")
        esquema = {"type": tipo}
        if not c["notnull"] and not c["pk"]:
            esquema["nullable"] = True
        if c["name"] in cat.DESCRIPCIONES:
            esquema["description"] = cat.DESCRIPCIONES[c["name"]]
        propiedades[c["name"]] = esquema
    propiedades.update(extra)
    esquema = {"type": "object", "properties": propiedades}
    if "id" in propiedades:
        esquema["required"] = ["id"]
    return esquema


def _componentes_de_esquemas() -> dict:
    esquemas = {nombre: dict(valor) for nombre, valor in cat.ESQUEMAS.items()}
    for nombre, (tabla, excluir, extra) in cat.TABLAS.items():
        try:
            esquemas[nombre] = _esquema_de_tabla(tabla, excluir, extra)
        except Exception:  # noqa: BLE001 -- una tabla ausente no debe romper la documentación
            esquemas[nombre] = {"type": "object"}
    if "ClienteFiscal" in esquemas:     # el detalle devuelve los modelos ya como lista (los listados y las escrituras, como texto JSON)
        detalle = {**esquemas["ClienteFiscal"], "properties": {**esquemas["ClienteFiscal"].get("properties", {}),
                   "modelos_fiscales": {"type": "array", "items": {"type": "string"}, "description": "Modelos que se le generan (303, 130...)."}}}
        esquemas["ClienteFiscalDetalle"] = detalle
    return esquemas


def _ref(nombre: str) -> dict:
    return {"$ref": f"#/components/schemas/{nombre}"}


def _resolver_getters(esquema):
    """Cambia los marcadores `x-getter` que deja el análisis por la referencia al esquema de esa entidad (si la conocemos)."""
    if isinstance(esquema, dict):
        if "x-getter" in esquema:
            nombre = esquema["x-getter"]
            if nombre in cat.GETTERS:
                componente, lista = cat.GETTERS[nombre]
                return {"type": "array", "items": _ref(componente)} if (lista or esquema.get("x-lista")) else _ref(componente)
            if nombre in cat.TIPOS_FUNCION:
                return dict(cat.TIPOS_FUNCION[nombre])
            if nombre.startswith("contar_"):
                return {"type": "integer"}
            if nombre.startswith(("es_", "tiene_", "tarea_bloqueada", "puede_")):
                return {"type": "boolean"}
            return {"type": "array", "items": {"type": "object"}} if esquema.get("x-lista") and nombre.startswith(("listar_", "mensajes_del")) else {}
        return {k: _resolver_getters(v) for k, v in esquema.items()}
    if isinstance(esquema, list):
        return [_resolver_getters(v) for v in esquema]
    return esquema


def _esquema_de_datos(operacion: str, a: dict) -> tuple[dict | None, bool]:
    """(esquema de `data`, está tipado). `None` = la respuesta no lleva datos útiles. Prioridad: lo escrito a mano en el catálogo, un
    literal devuelto por la vista (`_ok({"id": ..})`) y, por último, la entidad de la función de datos que use."""
    if operacion in cat.RESPUESTAS:
        nombre, lista = cat.RESPUESTAS[operacion]
        return ({"type": "array", "items": _ref(nombre)} if lista else _ref(nombre)), True
    if a.get("literal"):
        return _resolver_getters(a["literal"]), True
    for llamada in sorted(a["llamadas"]):
        if llamada in cat.GETTERS:
            nombre, lista = cat.GETTERS[llamada]
            return ({"type": "array", "items": _ref(nombre)} if lista or a["pagina"] else _ref(nombre)), True
    if operacion in cat.SIN_DATOS_ESPERADOS:
        return None, True
    return {"type": "object", "description": "Datos de la respuesta."}, False


def _propiedades_cuerpo(operacion: str, campos: dict[str, bool]) -> tuple[dict, list[str]]:
    propiedades = {nombre: cat.tipo_de_campo(nombre) for nombre in campos}
    requeridos = [n for n, obligatorio in campos.items() if obligatorio]
    for n in cat.REQUERIDOS.get(operacion, ()):
        propiedades.setdefault(n, cat.tipo_de_campo(n))
        if n not in requeridos:
            requeridos.append(n)
    return propiedades, requeridos


def _cuerpo_de_peticion(operacion: str, a: dict, metodo: str) -> dict | None:
    if metodo not in ("POST", "PUT", "PATCH"):
        return None
    propiedades, requeridos = _propiedades_cuerpo(operacion, a["cuerpo"])
    ejemplo = cat.EJEMPLOS.get(operacion, {}).get("peticion")
    contenido: dict = {}
    if a["archivos"] or a["formulario"]:
        multi = {n: cat.tipo_de_campo(n) for n in a["formulario"]}
        for n, varios in a["archivos"].items():
            fichero = {"type": "string", "format": "binary", "description": cat.DESCRIPCIONES.get(n, "Archivo.")}
            multi[n] = {"type": "array", "items": fichero} if varios else fichero
        if a["usa_cuerpo_json"]:                       # el mismo endpoint admite JSON y multipart: los campos de texto valen en ambos
            for n, esquema in propiedades.items():
                multi.setdefault(n, esquema)
        esquema_multi = {"type": "object", "properties": multi}
        if requeridos and a["usa_cuerpo_json"]:
            esquema_multi["required"] = [r for r in requeridos if r in multi]
        contenido["multipart/form-data"] = {"schema": esquema_multi}
    if a["usa_cuerpo_json"] or (propiedades and not contenido):
        esquema = {"type": "object", "properties": propiedades}
        if requeridos:
            esquema["required"] = requeridos
        contenido["application/json"] = {"schema": esquema, **({"example": ejemplo} if ejemplo else {})}
    if not contenido:
        return None
    return {"required": bool(requeridos), "content": contenido}


def _parametros_de_consulta(a: dict, metodo: str, operacion: str) -> list[dict]:
    parametros = []
    nombres = dict(a["consulta"])
    if (a["pagina"] or operacion in cat.PAGINADAS_EXTRA) and metodo == "GET":
        nombres.setdefault("limit", {"tipo": "integer", "lista": False, "defecto": None})
        nombres.setdefault("offset", {"tipo": "integer", "lista": False, "defecto": 0})
    for nombre, info in sorted(nombres.items()):
        base = cat.tipo_de_campo(nombre)
        esquema = {"type": info["tipo"]} if info["tipo"] != "string" or "format" not in base else {"type": "string", "format": base["format"]}
        if info["lista"]:
            esquema = {"type": "array", "items": esquema}
        if info["defecto"] is not None:
            esquema["default"] = info["defecto"]
        parametros.append({"name": nombre, "in": "query", "required": False, "description": cat.DESCRIPCIONES.get(nombre, "Filtro."), "schema": esquema})
    if metodo == "GET" and "campos" not in nombres:
        parametros.append({"name": "campos", "in": "query", "required": False, "description": cat.DESCRIPCIONES["campos"], "schema": {"type": "string"}, "example": "id,asunto"})
    return parametros


def _respuestas(operacion: str, a: dict, metodo: str, tiene_cuerpo: bool, tiene_ruta: bool, publica: bool) -> dict:
    cabeceras = {
        "X-Request-Id": {"$ref": "#/components/headers/XRequestId"},
        "X-RateLimit-Remaining": {"$ref": "#/components/headers/XRateLimitRemaining"},
    }
    esquema_datos, tipado = _esquema_de_datos(operacion, a)
    respuestas: dict = {}
    for codigo in sorted(a["codigos_ok"]):
        if operacion in cat.BINARIAS:
            contenido = {cat.BINARIAS[operacion]: {"schema": {"type": "string", "format": "binary"}}}
        elif operacion in cat.STREAMS:
            contenido = {"text/event-stream": {"schema": {"type": "string"}}}
        elif operacion in cat.JSON_SIN_SOBRE:
            contenido = {"application/json": {"schema": {"type": "object", "description": "El propio documento OpenAPI 3.0."}}}
        else:
            sobre = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean", "enum": [True]}}}
            if esquema_datos is not None:
                sobre["properties"]["data"] = esquema_datos
            ejemplo = cat.EJEMPLOS.get(operacion, {}).get("respuesta")
            contenido = {"application/json": {"schema": sobre, **({"example": {"ok": True, "data": ejemplo}} if ejemplo is not None and codigo == min(a["codigos_ok"]) else {})}}
        cab = dict(cabeceras)
        if metodo == "GET":
            cab["ETag"] = {"$ref": "#/components/headers/ETag"}
        if (a["pagina"] or operacion in cat.PAGINADAS_EXTRA) and metodo == "GET":
            cab["X-Total-Count"] = {"$ref": "#/components/headers/XTotalCount"}
        respuestas[str(codigo)] = {"description": _DESCRIPCION_CODIGO.get(codigo, "Correcto"), "headers": cab, "content": contenido}
    if metodo == "GET":
        respuestas["304"] = {"description": "Sin cambios desde el `ETag` enviado en `If-None-Match`."}
    codigos = set(a["codigos_error"]) | {500}
    if not publica:
        codigos |= {401, 403, 429}
    else:
        codigos |= {429}
    if tiene_cuerpo or a["consulta"]:
        codigos.add(400)
    if tiene_ruta:
        codigos.add(404)
    if metodo == "POST" and not publica:
        codigos |= {409, 422}
    for codigo in sorted(codigos):
        if codigo in _ERRORES:
            respuestas[str(codigo)] = {"$ref": f"#/components/responses/Error{codigo}"}
    return respuestas


def _descripcion_de_vista(vista) -> tuple[str, str]:
    doc = inspect.cleandoc(inspect.unwrap(vista).__doc__ or "")
    primera = doc.splitlines()[0].strip() if doc else ""
    resumen = primera.rstrip(".") if primera and len(primera) <= 110 else (primera[:107] + "…" if primera else _humanizar(inspect.unwrap(vista).__name__))
    return resumen or _humanizar(vista.__name__), doc


def _componentes(esquemas: dict) -> dict:
    respuestas = {}
    for codigo, (descripcion, clave) in _ERRORES.items():
        respuestas[f"Error{codigo}"] = {
            "description": descripcion, "headers": {"X-Request-Id": {"$ref": "#/components/headers/XRequestId"}, **({"Retry-After": {"$ref": "#/components/headers/RetryAfter"}} if codigo == 429 else {})},
            "content": {"application/json": {"schema": _ref("Error"), "example": {"ok": False, "error": descripcion.split(":")[0].split(".")[0], "codigo": clave, "request_id": "9f3c2a1b7d8e4f6a8b0c1d2e3f4a5b6c"}}},
        }
    return {
        "securitySchemes": {"bearerAuth": {
            "type": "http", "scheme": "bearer",
            "description": "Token de API en `Authorization: Bearer <token>`. Se obtiene con `POST /auth/login`, desde «Mis dispositivos» en la web o con `POST /tokens` "
                           "(con áreas y caducidad). Un token de solo lectura solo admite GET; uno con áreas solo llega a ellas."}},
        "schemas": dict(sorted(esquemas.items())),
        "parameters": {
            "IdempotencyKey": {"name": "Idempotency-Key", "in": "header", "required": False, "schema": {"type": "string", "maxLength": 128},
                               "description": "Cadena única por intento. Si reintentas la misma petición (corte de red) recibes la respuesta original con `Idempotent-Replay: true` en vez de duplicar. 24 h."},
            "RequestId": {"name": "X-Request-Id", "in": "header", "required": False, "schema": {"type": "string", "pattern": "^[A-Za-z0-9._-]{8,64}$"},
                          "description": "Tu propio identificador de la petición (8-64 caracteres) para correlacionar; si no lo envías, se genera uno."},
        },
        "headers": {
            "XRequestId": {"description": "Identificador de la petición; indícalo al pedir soporte.", "schema": {"type": "string"}},
            "XRateLimitRemaining": {"description": "Peticiones que te quedan en el minuto actual (límite por usuario: 600/min).", "schema": {"type": "integer"}},
            "XTotalCount": {"description": "Total de filas sin paginar.", "schema": {"type": "integer"}},
            "ETag": {"description": "Huella de la respuesta: reenvíala en `If-None-Match` para recibir `304` si no ha cambiado.", "schema": {"type": "string"}},
            "RetryAfter": {"description": "Segundos de espera antes de reintentar.", "schema": {"type": "integer"}},
        },
        "responses": respuestas,
    }


_DESCRIPCION_GENERAL = """\
API REST de Guilda Work: notas, tareas, correo, calendario fiscal, fichaje, webhooks y más. La usan la app móvil y las integraciones externas.

## Autenticación y alcance
`Authorization: Bearer <token>`. Un token puede ser **de solo lectura** (solo `GET`), estar **limitado a áreas** (`notas`, `tareas`, `correo`, `fiscal`, `fichaje`, `tiquets`, `ia`, `avisos`, `webhooks`)
y **caducar**. Cada operación indica su área en `x-area`; las rutas transversales (`/historial`, `/sync`, `/buscar`...) y la gestión de tokens exigen un token sin límite de áreas.

## Sobre de respuesta
Éxito: `{"ok": true, "data": ...}`. Error: `{"ok": false, "error": "texto", "codigo": "clave_estable", "request_id": "..."}`. **Programa contra `codigo`**, no contra el texto.

## Límites, reintentos y caché
- **600 peticiones por minuto y usuario**, de ellas **200 escrituras** (POST/PUT/PATCH/DELETE) y **20 operaciones pesadas** (IA, exportaciones, importaciones, sincronizar un buzón, enviar correo). `X-RateLimit-Remaining` y `X-RateLimit-Scope` indican el cupo más ajustado; al pasarte, `429` con `Retry-After` y el cupo en `cupo`.
- **Restricciones por token**: IP permitidas (`ips_permitidas`) y orígenes web para navegador (`origenes_cors`); `GET /health` sirve para monitorizar.
- **Idempotencia**: en cualquier `POST` envía `Idempotency-Key` para reintentar sin duplicar.
- **Caché**: los `GET` llevan `ETag`; reenvíalo en `If-None-Match` y recibirás `304`.
- **Paginación**: `limit` y `offset`; el total llega en `X-Total-Count`. `?campos=id,nombre` devuelve solo esos campos.
- **Sincronización incremental**: `GET /sync` (cursor) para no volver a descargarlo todo.
- **Referencias externas**: notas, tareas de lista y clientes fiscales aceptan `referencia_externa` y se pueden crear o actualizar por ella (`PUT .../por-referencia/{ref}`).

## Versionado
La cabecera `X-API-Version` (`{version}`) lleva `mayor.menor`: el menor sube con cada ampliación compatible (campos nuevos siempre opcionales); el mayor solo si algo se rompe.
Los **webhooks** (firma `X-Guilda-Signature-V2`, reintentos, eventos) se documentan en la referencia de desarrolladores de la app.
"""


_ANALISIS: dict[str, dict] = {}


def _analisis_de(endpoint: str, vistas: dict) -> dict:
    """El análisis de una vista no cambia mientras el proceso vive (el código no cambia): se hace una vez por ruta, no en cada petición
    al documento (que es público y se pide a menudo)."""
    if endpoint not in _ANALISIS:
        operacion = endpoint.removeprefix("api.")
        hijas = {n: vistas[f"api.{n}"] for n in cat.HEREDA.get(operacion, ()) if f"api.{n}" in vistas}
        _ANALISIS[endpoint] = analisis.analizar(vistas[endpoint], hijas)
    return _ANALISIS[endpoint]


def generar_spec() -> dict:
    """Recorre `current_app.url_map` y construye el documento OpenAPI 3.0 completo de `/api/v1/*` (se llama en cada petición a
    `GET /api/v1/openapi.json`)."""
    from .rutas_api import API_VERSION

    vistas = current_app.view_functions
    esquemas = _componentes_de_esquemas()
    paths: dict[str, dict] = {}
    for regla in current_app.url_map.iter_rules():
        if not regla.endpoint.startswith("api."):
            continue
        vista = vistas[regla.endpoint]
        operacion = regla.endpoint.removeprefix("api.")
        a = _analisis_de(regla.endpoint, vistas)
        resumen, descripcion = _descripcion_de_vista(vista)
        ruta_openapi = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", regla.rule)
        segmentos = regla.rule.removeprefix("/api/v1/").strip("/").split("/")
        etiqueta = segmentos[0] if segmentos and segmentos[0] else "raíz"
        publica = operacion in cat.PUBLICAS
        area = area_de_ruta(regla.rule)
        operaciones = paths.setdefault(ruta_openapi, {})
        parametros_ruta = _parametros_de_ruta(regla)
        for metodo in sorted(regla.methods - {"HEAD", "OPTIONS"}):
            cuerpo = _cuerpo_de_peticion(operacion, a, metodo)
            parametros = parametros_ruta + _parametros_de_consulta(a, metodo, operacion)
            if not publica:
                parametros.append({"$ref": "#/components/parameters/RequestId"})
                if metodo == "POST" and operacion not in cat.STREAMS:
                    parametros.append({"$ref": "#/components/parameters/IdempotencyKey"})
            op = {
                "summary": resumen, "operationId": operacion, "tags": [etiqueta], "parameters": parametros,
                "responses": _respuestas(operacion, a, metodo, cuerpo is not None, bool(parametros_ruta), publica),
                "security": [] if publica else [{"bearerAuth": []}],
                "x-area": area or "libre", "x-escribe": metodo != "GET",
            }
            if descripcion and descripcion != resumen:
                op["description"] = descripcion
            if cuerpo:
                op["requestBody"] = cuerpo
            if not _esquema_de_datos(operacion, a)[1] and operacion not in cat.BINARIAS and operacion not in cat.STREAMS and operacion not in cat.JSON_SIN_SOBRE:
                op["x-esquema-pendiente"] = True
            operaciones[metodo.lower()] = op

    usadas = {t for ruta in paths.values() for op in ruta.values() for t in op["tags"]}
    version = API_VERSION
    return {
        "openapi": "3.0.3",
        "info": {"title": "Guilda Work API", "version": version, "description": _DESCRIPCION_GENERAL.replace("{version}", version)},
        "servers": [{"url": request.url_root.rstrip("/"), "description": "Esta instancia"}] if request else [],
        "tags": [{"name": t, "description": cat.ETIQUETAS.get(t, "")} for t in sorted(usadas)],
        "components": _componentes(esquemas),
        "paths": dict(sorted(paths.items())),
    }
