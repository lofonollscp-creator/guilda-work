"""Inicio de sesión con foto de montaña a todo el panel: el texto va en un panel de cristal oscuro (desenfoque + tinte), así que su contraste
no depende de la foto. Aquí se recrea lo que dibuja el navegador (foto con `cover` y su velo liso, desenfocada y teñida) y se mide el contraste
de cada color de texto contra el píxel MÁS CLARO de todo el panel, en varios tamaños de pantalla (AA: 4,5:1). También se comprueba la estructura
(todo el texto dentro del panel), la banda de móvil, el logotipo en tema claro, que la foto es decorativa y sus créditos."""
import re
from pathlib import Path

import pytest
from PIL import Image, ImageFilter

from tests.a11y import contraste

RAIZ = Path(__file__).resolve().parent.parent
CSS = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")


def _regla(selector: str) -> str:
    return re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS).group(1)


def _parametros() -> dict:
    hero, panel = _regla(".auth-hero"), _regla(".auth-hero-panel")
    px, py = [float(v) / 100 for v in re.search(r"background-position:\s*([\d.]+)%\s+([\d.]+)%", hero).groups()]
    velo = float(re.search(r"linear-gradient\(rgba\(5,\s*5,\s*6,\s*([\d.]+)\)", hero).group(1))
    r, g, b, tinte = [float(v) for v in re.search(r"background:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", panel).groups()]
    desenfoque = float(re.search(r"(?<!-webkit-)backdrop-filter:\s*blur\((\d+)px\)", panel).group(1))
    ancho = float(re.search(r"width:\s*min\(100%,\s*(\d+)px\)", panel).group(1))
    return {"pos": (px, py), "velo": velo, "tinte": (int(r), int(g), int(b), tinte), "blur": desenfoque, "ancho_max": int(ancho)}


def _panel_compuesto(ancho: int, alto: int) -> Image.Image:
    par = _parametros()
    foto = Image.open(RAIZ / "app" / "static" / "fotos" / "montana-login.jpg").convert("RGB")
    escala = max(ancho / foto.width, alto / foto.height)                                    # background-size: cover
    grande = foto.resize((max(ancho, round(foto.width * escala)), max(alto, round(foto.height * escala))))
    x0, y0 = round((grande.width - ancho) * par["pos"][0]), round((grande.height - alto) * par["pos"][1])
    base = grande.crop((x0, y0, x0 + ancho, y0 + alto))
    base = Image.blend(base, Image.new("RGB", (ancho, alto), (5, 5, 6)), par["velo"])      # velo liso
    base = base.filter(ImageFilter.GaussianBlur(par["blur"]))                                # backdrop-filter: blur()
    r, g, b, tinte = par["tinte"]
    return Image.blend(base, Image.new("RGB", (ancho, alto), (r, g, b)), tinte)            # fondo semitransparente del panel


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


def _mas_claro(imagen: Image.Image, caja) -> str:
    zona = imagen.crop(caja)
    zona = zona.resize((max(zona.width // 5, 1), max(zona.height // 5, 1)))
    datos = zona.get_flattened_data() if hasattr(zona, "get_flattened_data") else zona.getdata()
    return _hex(max(datos, key=sum))


@pytest.mark.parametrize("ancho,alto", [(1005, 975), (1300, 800), (1100, 1100), (840, 1100)])
def test_el_texto_del_panel_de_cristal_mantiene_el_contraste_sobre_la_foto(ancho, alto):
    par = _parametros()
    imagen = _panel_compuesto(ancho, alto)
    ancho_panel, alto_panel = min(par["ancho_max"], ancho - 128), min(560, alto - 112)          # alto máximo prudente del panel
    x0, y0 = 64, (alto - alto_panel) // 2
    fondo = _mas_claro(imagen, (x0, y0, x0 + ancho_panel, y0 + alto_panel))
    colores = {
        "titular": re.search(r"\.auth-hero\s*\{[^}]*?\bcolor:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
        "texto": re.search(r"\.auth-hero-texto\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
        "lista": re.search(r"\.auth-hero-lista\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
    }
    for nombre, color in colores.items():
        assert contraste(color, fondo) >= 4.5, f"{nombre} {color} sobre {fondo} ({ancho}x{alto}): {contraste(color, fondo):.2f}:1"


def test_sin_desenfoque_el_panel_es_casi_opaco():
    """Si el navegador no soporta backdrop-filter, el panel pasa a un tinte casi opaco (el contraste no puede depender del desenfoque)."""
    sin_soporte = re.search(r"@supports not \(\(backdrop-filter[^{]*\{\s*\.auth-hero-panel \{\s*background:\s*rgba\([^)]*,\s*([\d.]+)\)", CSS)
    assert sin_soporte and float(sin_soporte.group(1)) >= 0.9


def test_todo_el_texto_del_hero_esta_dentro_del_panel_de_cristal(cliente):
    html = cliente.get("/login", follow_redirects=True).get_data(as_text=True)
    hero = re.search(r'<section class="auth-hero".*?</section>', html, re.S).group(0)
    panel = re.search(r'<div class="auth-hero-panel">.*</div>\s*$', hero.replace("</section>", ""), re.S)
    assert panel, "el hero debe contener un único panel"
    fuera = hero.replace(panel.group(0), "")
    assert not re.search(r">[^<>\s][^<>]*<", fuera.split(">", 1)[1]), f"texto del hero fuera del panel: {fuera[:200]}"
    for clase in ("auth-hero-marca", "auth-hero-titulo", "auth-hero-texto", "auth-hero-lista"):
        assert clase in panel.group(0)
    assert "<img" not in re.sub(r'<img src="[^"]*logo\.png[^"]*"[^>]*>', "", hero), "la foto va de fondo (CSS), no como imagen que ocupe sitio"


def test_la_banda_movil_existe_y_la_foto_es_decorativa(cliente):
    html = cliente.get("/login", follow_redirects=True).get_data(as_text=True)
    figura = re.search(r'<figure class="auth-foto-movil"[^>]*>.*?</figure>', html, re.S).group(0)
    assert 'aria-hidden="true"' in figura and 'alt=""' in figura and "montana-login.webp" in figura and "montana-login.jpg" in figura
    assert 'width="1600"' in figura and 'height="1067"' in figura
    movil = re.search(r"@media \(max-width: 820px\) \{.*?\n\}", CSS, re.S).group(0)
    assert ".auth-hero { display: none; }" in movil and ".auth-foto-movil { display: block;" in movil
    assert "display: none" in _regla(".auth-foto-movil")


def test_el_logotipo_blanco_va_sobre_pastilla_oscura_en_tema_claro():
    assert 'root[data-theme="light"] .auth-logo' in CSS and "prefers-color-scheme: light" in CSS
    pastilla = re.search(r':root\[data-theme="light"\] \.auth-logo \{([^}]*)\}', CSS).group(1)
    assert "var(--sidebar-bg)" in pastilla and "border-radius" in pastilla


def test_la_foto_pesa_poco_y_tiene_creditos_cc0():
    carpeta = RAIZ / "app" / "static" / "fotos"
    assert (carpeta / "montana-login.webp").stat().st_size < 200_000 and (carpeta / "montana-login.jpg").stat().st_size < 250_000
    creditos = (carpeta / "CREDITOS.md").read_text(encoding="utf-8")
    assert "CC0" in creditos and "commons.wikimedia.org" in creditos
    assert "fotos/montana-login.webp" in CSS and "fotos/montana-login.jpg" in CSS
