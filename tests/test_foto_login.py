"""Foto de montaña del inicio de sesión: va en una tarjeta propia, NUNCA debajo del texto, así que la legibilidad no depende de la foto.
Se comprueba la estructura (sin imagen ni degradado sobre el panel del texto), el contraste del texto contra el fondo liso, la banda
para móvil, el logotipo en tema claro, que la foto es decorativa (invisible para lectores de pantalla) y sus créditos."""
import re
from pathlib import Path

from tests.a11y import contraste

RAIZ = Path(__file__).resolve().parent.parent
CSS = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")


def _regla(selector: str) -> str:
    return re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS).group(1)


def test_el_panel_del_texto_no_lleva_foto_ni_degradado_debajo():
    hero = _regla(".auth-hero")
    assert "url(" not in hero and "gradient" not in hero and "background-image" not in hero
    assert "position: absolute" not in _regla(".auth-hero-foto") and "position: absolute" not in _regla(".auth-hero-foto img")


def test_el_texto_del_hero_tiene_contraste_aa_sobre_su_fondo_liso():
    fondo = re.search(r"--sidebar-bg:\s*(#[0-9a-fA-F]{6})", CSS).group(1)
    colores = {
        "titular": re.search(r"\.auth-hero\s*\{[^}]*?\bcolor:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
        "texto": re.search(r"\.auth-hero-texto\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
        "lista": re.search(r"\.auth-hero-lista\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
    }
    for nombre, color in colores.items():
        assert contraste(color, fondo) >= 4.5, f"{nombre} {color} sobre {fondo}: {contraste(color, fondo):.1f}:1"


def test_la_pagina_de_login_lleva_la_foto_decorativa_en_el_hero_y_en_la_banda_movil(cliente):
    html = cliente.get("/login", follow_redirects=True).get_data(as_text=True)
    for clase in ("auth-hero-foto", "auth-foto-movil"):
        figura = re.search(rf'<figure class="{clase}"[^>]*>.*?</figure>', html, re.S).group(0)
        assert 'aria-hidden="true"' in figura and 'alt=""' in figura and "montana-login.webp" in figura and "montana-login.jpg" in figura
        assert 'width="1600"' in figura and 'height="1067"' in figura                        # sin saltos de maquetación al cargar
    movil = re.search(r"@media \(max-width: 820px\) \{.*?\n\}", CSS, re.S).group(0)
    assert ".auth-hero { display: none; }" in movil and ".auth-foto-movil { display: block;" in movil
    assert "display: none" in _regla(".auth-foto-movil")                                   # en pantalla ancha no se duplica


def test_el_logotipo_blanco_va_sobre_pastilla_oscura_en_tema_claro():
    assert 'root[data-theme="light"] .auth-logo' in CSS and "prefers-color-scheme: light" in CSS
    pastilla = re.search(r':root\[data-theme="light"\] \.auth-logo \{([^}]*)\}', CSS).group(1)
    assert "var(--sidebar-bg)" in pastilla and "border-radius" in pastilla


def test_la_foto_pesa_poco_y_tiene_creditos_cc0():
    carpeta = RAIZ / "app" / "static" / "fotos"
    assert (carpeta / "montana-login.webp").stat().st_size < 200_000 and (carpeta / "montana-login.jpg").stat().st_size < 250_000
    creditos = (carpeta / "CREDITOS.md").read_text(encoding="utf-8")
    assert "CC0" in creditos and "commons.wikimedia.org" in creditos
