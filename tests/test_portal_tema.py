"""Tema del portal (V14), contraste de la marca en claro y oscuro y reparto del CSS del portal (V2)."""
import glob
import re

import pytest

from app import marca, portal_diseno
from tests.test_portal_nuevo import _con_portal
from tests.test_portal_personas_avisos import _html

COLORES = ["#0a7d5a", "#ffee00", "#101010", "#ffffff", "#ff0000", "#1e3a8a", "#7c3aed", "#00ffcc", "#808080", "#8b4513"]


def _contraste(a, b):
    return marca._contraste(marca._luminancia(a), marca._luminancia(b))


def _variables(css, selector_inicio):
    bloque = css[css.index(selector_inicio):].split("}", 1)[0]
    return dict(re.findall(r"(--[a-z-]+): (#[0-9a-f]{6});", bloque))


@pytest.mark.parametrize("color", COLORES)
def test_cualquier_color_de_marca_da_contraste_aa_en_claro_y_en_oscuro(color):
    css = portal_diseno.css_de_marca(color)
    claro = _variables(css, ":root { --primary")
    oscuro = _variables(css, ':root[data-theme="dark"] { --primary')
    for nombre, v, fondo_tarjeta in (("claro", claro, "#ffffff"), ("oscuro", oscuro, "#1e1b14")):
        assert _contraste(v["--on-accent"], v["--primary"]) >= 4.5, (color, nombre, "texto sobre el relleno")
        assert _contraste(v["--primary-text"], fondo_tarjeta) >= 4.5, (color, nombre, "acento como texto")
    portal = _variables(css, ":root { --portal-accent")
    portal_oscuro = _variables(css, ':root[data-theme="dark"] { --portal-accent')
    assert _contraste(portal["--pv-accent-text"], portal["--pv-accent-soft"]) >= 4.5, (color, "pestaña activa en claro")
    assert _contraste(portal_oscuro["--pv-accent-text"], portal_oscuro["--pv-accent-soft"]) >= 4.5, (color, "pestaña activa en oscuro")
    assert _contraste(portal_oscuro["--pv-on-accent"], portal_oscuro["--pv-accent"]) >= 4.5, (color, "botón en oscuro")


def test_el_tema_del_sistema_oscuro_tambien_recibe_la_marca():
    css = portal_diseno.css_de_marca("#0a7d5a")
    assert "@media (prefers-color-scheme: dark) { :root:not([data-theme=\"light\"])" in css          # sin elegir tema, el dispositivo oscuro usa el acento aclarado
    assert css.count("prefers-color-scheme: dark") == 2                                             # marca.css (botones y enlaces) y el portal nuevo


def test_el_menu_de_perfil_trae_el_selector_de_tema_y_el_color_de_la_barra(cliente):
    _con_portal(cliente)
    html = _html(cliente, "/portal/")
    assert 'data-temas' in html and html.count('data-tema="') == 3
    for valor in ("system", "light", "dark"):
        assert f'data-tema="{valor}"' in html
    assert html.count('name="theme-color"') == 3 and "(prefers-color-scheme: dark)" in html


def test_el_tema_claro_y_oscuro_cubren_el_mismo_conjunto_de_variables_del_portal():
    css = open("app/static/style.css", encoding="utf-8").read()
    claro = set(re.findall(r"(--portal-[a-z-]+):", css[css.index("--portal-paper: #faf8f3"):].split("}", 1)[0]))
    oscuro = set(re.findall(r"(--portal-[a-z-]+):", css.split(':root[data-theme="dark"] {', 1)[1].split("}", 1)[0]))
    assert claro == oscuro


def test_las_pantallas_del_portal_cargan_su_propia_hoja_de_estilos():
    for f in glob.glob("app/templates/portal_*.html"):
        s = open(f, encoding="utf-8").read()
        if "style.css" in s:
            assert "portal.css" in s, f


def test_portal_css_solo_trae_clases_que_no_se_usan_fuera_del_portal():
    css = open("app/static/portal.css", encoding="utf-8").read()
    clases = set(re.findall(r"\.(portal-[a-z0-9-]+)", css))
    fuera = set()
    for f in glob.glob("app/templates/*.html"):
        nombre = f.rsplit("/", 1)[-1]
        if not (nombre.startswith("portal_") or nombre.startswith("_portal")):
            fuera |= set(re.findall(r"portal-[a-z0-9-]+", open(f, encoding="utf-8").read()))
    assert not clases & fuera
    style = re.sub(r"/\*.*?\*/", "", open("app/static/style.css", encoding="utf-8").read(), flags=re.S)
    repartidas = sorted(c for c in clases if re.search(rf"\.{re.escape(c)}(?![a-z0-9-])", style))
    assert not repartidas, f"clases con reglas en style.css y en portal.css (cambia la cascada): {repartidas[:5]}"       # el orden entre hojas es lo que se rompió con .portal-rejilla
