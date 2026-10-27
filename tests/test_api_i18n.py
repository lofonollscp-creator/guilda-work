"""Los errores de la API salen en el idioma de la persona (cabecera `Accept-Language` o el idioma de su perfil), y todo texto de error escrito en las rutas
de la API tiene traducción a catalán, inglés y francés."""
import ast
import glob
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from tests.test_rutas_api import _auth, _registrar

RAIZ = Path(__file__).resolve().parent.parent


def _mensajes_de_las_rutas() -> set[str]:
    textos = set()
    for f in sorted(glob.glob(str(RAIZ / "app" / "rutas_api*.py"))):
        for nodo in ast.walk(ast.parse(Path(f).read_text(encoding="utf8"))):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "gettext" and nodo.args:
                if isinstance(nodo.args[0], ast.Constant) and isinstance(nodo.args[0].value, str):
                    textos.add(nodo.args[0].value)
    return textos


@pytest.mark.parametrize("idioma", ["ca", "en", "fr"])
def test_cada_error_de_la_api_esta_traducido(idioma):
    catalogo = read_po(open(RAIZ / "translations" / idioma / "LC_MESSAGES" / "messages.po", "rb"))
    sin_traducir = [m for m in sorted(_mensajes_de_las_rutas()) if not (catalogo.get(m) and catalogo.get(m).string) or catalogo.get(m).fuzzy]
    assert sin_traducir == [], f"faltan en translations/{idioma}: añade su traducción al .po y compila (pybabel compile -d translations)"


def test_hay_mensajes_envueltos():
    assert len(_mensajes_de_las_rutas()) > 150  # si baja de golpe, alguien ha quitado el gettext de las rutas


@pytest.mark.parametrize("cabecera,esperado", [
    (None, "Nota no encontrada."),
    ("es", "Nota no encontrada."),
    ("ca", "Nota no trobada."),
    ("en", "Note not found."),
    ("fr-FR,fr;q=0.9", "Note introuvable."),
    ("de", "Nota no encontrada."),  # sin traducción: castellano
])
def test_el_error_sale_en_el_idioma_pedido(cliente, cabecera, esperado):
    h = _auth(_registrar(cliente, "idioma-api@ejemplo.com")["token"])
    if cabecera:
        h = {**h, "Accept-Language": cabecera}
    r = cliente.get("/api/v1/notas/99999", headers=h)
    assert r.status_code == 404 and r.get_json()["error"] == esperado and r.get_json()["codigo"] == "no_encontrado"


def test_los_errores_con_datos_se_formatean_en_el_idioma(cliente):
    h = {**_auth(_registrar(cliente, "idioma-api2@ejemplo.com")["token"]), "Accept-Language": "en"}
    r = cliente.get("/api/v1/tareas-outlook?estado=raro", headers=h)
    # la lista de estados válidos va dentro del mensaje, sin llaves ni %() sin sustituir
    if r.status_code == 400:
        assert "%(" not in r.get_json()["error"] and "must be one of" in r.get_json()["error"]


def test_los_textos_de_dominio_no_fallan_fuera_de_la_app_web():
    """El backoffice, el MCP y las tareas periódicas no tienen Flask-Babel: el texto sale tal cual (castellano) en vez de lanzar KeyError."""
    from flask import Flask

    from app import textos

    with Flask("sin_babel").app_context():
        assert textos.gettext("Hola %(x)s", x=3) == "Hola 3"
        assert str(textos.lazy_gettext("Adiós")) == "Adiós"
    assert textos.gettext("Sin contexto") == "Sin contexto"
