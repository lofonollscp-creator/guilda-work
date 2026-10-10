"""Memoria por petición: varias partes de una misma página (context processors de la
barra, el rail, las rutas) necesitan el mismo dato (el tenant, el usuario, los no leídos);
con esto se consulta una sola vez por petición en vez de una por cada sitio."""
import re
import uuid

from flask import g, has_request_context, request


def memo(clave: str, fabrica):
    """Devuelve el valor guardado para esta petición o lo calcula con `fabrica()` y lo guarda.
    Fuera de una petición (scripts, tests de funciones) no memoriza nada."""
    if not has_request_context():
        return fabrica()
    cache = g.__dict__.setdefault("_memo_peticion", {})
    if clave not in cache:
        cache[clave] = fabrica()
    return cache[clave]


_ID_VALIDO = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def asignar_id() -> str:
    """Id de esta petición: el que mande el cliente en `X-Request-Id` (si tiene un formato sano) o uno nuevo. Sale en la
    cabecera de la respuesta, en los errores de la API, en los registros y en Sentry: con él, soporte localiza una
    petición concreta."""
    entrante = request.headers.get("X-Request-Id", "")
    g.request_id = entrante if _ID_VALIDO.match(entrante) else uuid.uuid4().hex
    return g.request_id


def id_actual() -> str | None:
    return g.get("request_id") if has_request_context() else None
