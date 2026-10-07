"""Memoria por petición: varias partes de una misma página (context processors de la
barra, el rail, las rutas) necesitan el mismo dato (el tenant, el usuario, los no leídos);
con esto se consulta una sola vez por petición en vez de una por cada sitio."""
from flask import g, has_request_context


def memo(clave: str, fabrica):
    """Devuelve el valor guardado para esta petición o lo calcula con `fabrica()` y lo guarda.
    Fuera de una petición (scripts, tests de funciones) no memoriza nada."""
    if not has_request_context():
        return fabrica()
    cache = g.__dict__.setdefault("_memo_peticion", {})
    if clave not in cache:
        cache[clave] = fabrica()
    return cache[clave]
