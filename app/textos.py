"""Textos traducibles para el código de dominio (reglas de tareas, notas, ausencias, fichaje...), que también corre fuera de la app web: el backoffice, el
servidor MCP y las tareas periódicas no tienen Flask-Babel registrado. Aquí `gettext` traduce cuando hay petición y Babel, y si no, devuelve el texto tal cual
(castellano), en vez de fallar. Mismo nombre que el de Flask-Babel para que `pybabel extract` encuentre los textos."""
from __future__ import annotations

from flask_babel import LazyString
from flask_babel import gettext as _gettext


def gettext(texto: str, **variables) -> str:
    try:
        return _gettext(texto, **variables)
    except (KeyError, RuntimeError):  # sin Flask-Babel (otra aplicación) o sin contexto: castellano
        return texto % variables if variables else texto


def lazy_gettext(texto: str, **variables) -> LazyString:
    """Para constantes de módulo: se traduce al usarse, no al importarse."""
    return LazyString(gettext, texto, **variables)
