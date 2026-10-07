"""Los "menús" de Guilda Work se llaman "Proyectos" (ver el plan de renombrado):
solo cambia el texto visible, no los identificadores técnicos (tabla
`categorias`, rutas /categorias, parámetros `menu`/`categoria`). Estos tests
vigilan que ningún idioma vuelva a decir "menú" para ese concepto."""
import json
import re
from pathlib import Path

import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba

RAIZ = Path(__file__).resolve().parent.parent

# "menú" sigue siendo la palabra correcta para el menú lateral de la app.
MENU_LATERAL_PERMITIDO = {"Expandir/contraer menú", "Expandir o contraer el menú"}

TEXTOS_POR_IDIOMA = {
    "es": ("Nuevo proyecto", "Crear proyecto", "Sin proyecto"),
    "ca": ("Nou projecte", "Crear projecte", "Sense projecte"),
    "en": ("New project", "Create project", "No project"),
    "fr": ("Nouveau projet", "Créer un projet", "Sans projet"),
}
TEXTOS_ANTIGUOS = {
    "es": ("Nuevo menú", "Crear menú", "Sin menú"),
    "ca": ("Nou menú", "Crear menú", "Sense menú"),
    "en": ("New menu", "Create menu", "No menu"),
    "fr": ("Nouveau menu", "Créer un menu", "Sans menu"),
}


@pytest.mark.parametrize("idioma", ["es", "ca", "en", "fr"])
def test_el_dashboard_habla_de_proyectos_en_cada_idioma(cliente, idioma):
    usuario_id = iniciar_sesion_de_prueba(cliente, f"proy-{idioma}@ejemplo.com", "contrasena123")
    db.asignar_tenant(usuario_id, db.crear_tenant(f"Despacho {idioma}"))  # sin despacho, "/" redirige a activación
    db.crear_categoria(usuario_id, "Lueira")
    db.cambiar_idioma_usuario(usuario_id, idioma)

    html = cliente.get("/").get_data(as_text=True)

    for texto in TEXTOS_POR_IDIOMA[idioma]:
        assert texto in html, f"{idioma}: falta «{texto}»"
    for antiguo in TEXTOS_ANTIGUOS[idioma]:
        assert antiguo not in html, f"{idioma}: sigue diciendo «{antiguo}»"


@pytest.mark.parametrize("idioma", ["es", "ca", "en", "fr"])
def test_historial_estadisticas_y_papelera_dicen_proyecto(cliente, idioma):
    usuario_id = iniciar_sesion_de_prueba(cliente, f"proy2-{idioma}@ejemplo.com", "contrasena123")
    categoria_id = db.crear_categoria(usuario_id, "Lueira")
    db.cambiar_idioma_usuario(usuario_id, idioma)
    palabra = {"es": "Proyecto", "ca": "Projecte", "en": "Project", "fr": "Projet"}[idioma]
    antigua = {"es": "Menú", "ca": "Menú", "en": "Menu", "fr": "Menu"}[idioma]

    for ruta in ("/historial", "/estadisticas"):
        html = cliente.get(ruta).get_data(as_text=True)
        assert f"{palabra}</" in html, f"{idioma} {ruta}"
        assert f">{antigua}<" not in html, f"{idioma} {ruta}"

    pagina = cliente.get(f"/menu/{categoria_id}?registro=1")
    assert pagina.status_code == 200
    assert palabra.lower() in pagina.get_data(as_text=True).lower()


def test_las_plantillas_no_dicen_menu_salvo_el_menu_lateral():
    problemas = []
    for plantilla in (RAIZ / "app" / "templates").rglob("*.html"):
        texto = plantilla.read_text(encoding="utf-8")
        for m in re.finditer(r"""_\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""", texto):
            cadena = (m.group(1) or m.group(2)).replace("\\'", "'")
            if re.search(r"menús?", cadena, re.I) and cadena not in MENU_LATERAL_PERMITIDO:
                problemas.append(f"{plantilla.name}: {cadena[:60]}")
    assert not problemas, problemas


@pytest.mark.parametrize("idioma", ["es", "ca", "en", "fr"])
def test_la_app_movil_no_dice_menu_para_los_proyectos(idioma):
    arb = json.loads((RAIZ / "mobile" / "lib" / "l10n" / f"app_{idioma}.arb").read_text(encoding="utf-8"))
    for clave, valor in arb.items():
        if isinstance(valor, str):
            assert not re.search(r"\bmen[uú]s?\b", valor, re.I), f"{idioma}.{clave}: {valor}"
