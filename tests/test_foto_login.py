"""Inicio de sesión con la foto de montaña a TODA la pantalla y dos paneles de cristal encima (el del texto, siempre oscuro, y la tarjeta del
formulario, oscura o clara según el tema). Aquí se recrea lo que dibuja el navegador (foto con `cover`, velo liso, desenfoque y tinte de cada
panel) y se mide el contraste de cada color de texto contra el PEOR píxel de la zona del panel (el más claro para texto claro, el más oscuro para
texto oscuro), en escritorio, portátil y dos móviles. AA: 4,5:1. También: estructura (todo el texto dentro del panel), que no hay nada oculto tras
la foto en móvil, logotipo en tema claro, fotos decorativas y créditos."""
import re
from pathlib import Path

import pytest
from PIL import Image, ImageFilter

from tests.a11y import contraste

RAIZ = Path(__file__).resolve().parent.parent
CSS = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")
ANCHO_MOVIL_MAX = 820


def _regla(selector: str) -> str:
    return re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS).group(1)


def _rgba(texto: str):
    r, g, b, a = re.search(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", texto).groups()
    return int(r), int(g), int(b), float(a)


def _posicion(texto: str):
    return tuple(float(v) / 100 for v in re.search(r"background-position:\s*([\d.]+)%\s+([\d.]+)%", texto).groups())


def _parametros() -> dict:
    escritorio = _regla(".auth-dividido")
    movil = re.search(r"@media \(max-width: 820px\) \{.*?\n\}", CSS, re.S).group(0)
    panel = _regla(".auth-hero-panel")
    oscura = _regla(".auth-dividido .auth-card")
    clara = re.search(r':root\[data-theme="light"\] \.auth-dividido \.auth-card \{([^}]*)\}', CSS).group(1)
    return {
        "velo": float(re.search(r"linear-gradient\(rgba\(5,\s*5,\s*6,\s*([\d.]+)\)", escritorio).group(1)),
        "pos_escritorio": _posicion(escritorio), "pos_movil": _posicion(movil),
        "hero": {"tinte": _rgba(re.search(r"background:\s*(rgba\([^)]*\))", panel).group(1)), "blur": float(re.search(r"(?<!-webkit-)backdrop-filter:\s*blur\((\d+)px", panel).group(1)),
                 "ancho_max": int(re.search(r"width:\s*min\(100%,\s*(\d+)px\)", panel).group(1))},
        "tarjeta": {"oscura": _rgba(re.search(r"background:\s*(rgba\([^)]*\))", oscura).group(1)), "clara": _rgba(re.search(r"background:\s*(rgba\([^)]*\))", clara).group(1)),
                    "blur": float(re.search(r"(?<!-webkit-)backdrop-filter:\s*blur\((\d+)px", oscura).group(1)),
                    "ancho_max": int(re.search(r"max-width:\s*(\d+)px", _regla(".auth-card")).group(1))},
        "colores_oscura": {"texto": "#e8eae9", "apoyo": re.search(r"--text-muted:\s*(#[0-9a-fA-F]{6})", oscura).group(1), "enlace": re.search(r"--primary-text:\s*(#[0-9a-fA-F]{6})", oscura).group(1)},
        "colores_clara": {k: re.search(rf"--{v}:\s*(#[0-9a-fA-F]{{6}})", clara).group(1) for k, v in (("texto", "text"), ("apoyo", "text-muted"), ("enlace", "primary-text"))},
        "colores_hero": {"titular": re.search(r"\.auth-hero\s*\{[^}]*?\bcolor:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
                         "texto": re.search(r"\.auth-hero-texto\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
                         "lista": re.search(r"\.auth-hero-lista\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", CSS).group(1)},
    }


def _fondo(ancho: int, alto: int, posicion, velo: float) -> Image.Image:
    foto = Image.open(RAIZ / "app" / "static" / "fotos" / "montana-login.jpg").convert("RGB")
    escala = max(ancho / foto.width, alto / foto.height)                                    # background-size: cover
    grande = foto.resize((max(ancho, round(foto.width * escala)), max(alto, round(foto.height * escala))))
    x0, y0 = round((grande.width - ancho) * posicion[0]), round((grande.height - alto) * posicion[1])
    base = grande.crop((x0, y0, x0 + ancho, y0 + alto))
    return Image.blend(base, Image.new("RGB", (ancho, alto), (5, 5, 6)), velo)


def _cristal(base: Image.Image, tinte, blur: float) -> Image.Image:
    desenfocada = base.filter(ImageFilter.GaussianBlur(blur))                               # backdrop-filter: blur()
    r, g, b, alfa = tinte
    return Image.blend(desenfocada, Image.new("RGB", base.size, (r, g, b)), alfa)          # fondo semitransparente


def _extremos(imagen: Image.Image, caja):
    zona = imagen.crop(caja)
    zona = zona.resize((max(zona.width // 5, 1), max(zona.height // 5, 1)))
    datos = list(zona.get_flattened_data() if hasattr(zona, "get_flattened_data") else zona.getdata())
    hexa = lambda p: "#%02x%02x%02x" % tuple(p)
    return hexa(max(datos, key=sum)), hexa(min(datos, key=sum))                              # (más claro, más oscuro)


# (ancho, alto): escritorio, portátil, tablet vertical (ya con la vista de móvil), dos móviles
PANTALLAS = [(1920, 1080), (1366, 768), (820, 1180), (390, 844), (360, 740)]


def _zonas(ancho: int, alto: int, par: dict):
    """Rectángulos de (panel del texto, tarjeta del formulario) tal como los coloca el CSS; el panel del texto es None en móvil."""
    ancho_tarjeta, alto_tarjeta = par["tarjeta"]["ancho_max"], min(560, alto - 48)
    if ancho <= ANCHO_MOVIL_MAX:
        w = min(ancho_tarjeta, ancho - 32)
        return None, ((ancho - w) // 2, (alto - alto_tarjeta) // 2, (ancho + w) // 2, (alto + alto_tarjeta) // 2)
    col_hero = round(ancho * 1.05 / 2.05)
    ph = min(560, alto - 112)
    panel = (64, (alto - ph) // 2, 64 + min(par["hero"]["ancho_max"], col_hero - 128), (alto + ph) // 2)
    x0 = col_hero + (ancho - col_hero - ancho_tarjeta) // 2
    return panel, (x0, (alto - alto_tarjeta) // 2, x0 + ancho_tarjeta, (alto + alto_tarjeta) // 2)


@pytest.mark.parametrize("ancho,alto", PANTALLAS)
def test_el_texto_de_los_paneles_de_cristal_mantiene_el_contraste_sobre_la_foto(ancho, alto):
    par = _parametros()
    base = _fondo(ancho, alto, par["pos_movil"] if ancho <= ANCHO_MOVIL_MAX else par["pos_escritorio"], par["velo"])
    panel, tarjeta = _zonas(ancho, alto, par)
    fallos = []

    def revisar(nombre, imagen, caja, colores, claro_sobre_oscuro):
        mas_claro, mas_oscuro = _extremos(imagen, caja)
        fondo = mas_claro if claro_sobre_oscuro else mas_oscuro                            # el peor píxel para ese tipo de texto
        for color_nombre, color in colores.items():
            ratio = contraste(color, fondo)
            if ratio < 4.5:
                fallos.append(f"{nombre}/{color_nombre} {color} sobre {fondo} ({ancho}x{alto}): {ratio:.2f}:1")

    if panel:
        revisar("panel de texto", _cristal(base, par["hero"]["tinte"], par["hero"]["blur"]), panel, par["colores_hero"], True)
    revisar("tarjeta oscura", _cristal(base, par["tarjeta"]["oscura"], par["tarjeta"]["blur"]), tarjeta, par["colores_oscura"], True)
    revisar("tarjeta clara", _cristal(base, par["tarjeta"]["clara"], par["tarjeta"]["blur"]), tarjeta, par["colores_clara"], False)
    assert not fallos, fallos


def _bloques_sin_desenfoque() -> str:
    """Texto de todos los bloques `@supports not (backdrop-filter...)` (con las llaves bien emparejadas)."""
    trozos = []
    for m in re.finditer(r"@supports not \(\(backdrop-filter", CSS):
        i = CSS.index("{", m.end()); nivel, j = 0, i
        while True:
            nivel += {"{": 1, "}": -1}.get(CSS[j], 0)
            if nivel == 0:
                break
            j += 1
        trozos.append(CSS[i:j + 1])
    return "\n".join(trozos)


def test_sin_desenfoque_los_paneles_pasan_a_un_tinte_casi_opaco():
    """Sin backdrop-filter el cristal no desenfoca: el tinte sube a casi opaco para que el contraste no dependa de ese efecto."""
    texto = _bloques_sin_desenfoque()
    for selector in (".auth-hero-panel", ".auth-dividido .auth-card", ':root[data-theme="light"] .auth-dividido .auth-card'):
        alfa = re.search(re.escape(selector) + r"\s*\{\s*background:\s*rgba\(\d+,\s*\d+,\s*\d+,\s*([\d.]+)\)", texto)
        assert alfa and float(alfa.group(1)) >= 0.93, selector


def test_todo_el_texto_del_hero_esta_dentro_del_panel_de_cristal(cliente):
    html = cliente.get("/login", follow_redirects=True).get_data(as_text=True)
    hero = re.search(r'<section class="auth-hero".*?</section>', html, re.S).group(0)
    panel = re.search(r'<div class="auth-hero-panel">.*</div>\s*$', hero.replace("</section>", ""), re.S)
    assert panel, "el hero debe contener un único panel"
    assert not re.search(r">[^<>\s][^<>]*<", hero.replace(panel.group(0), "").split(">", 1)[1])
    for clase in ("auth-hero-marca", "auth-hero-titulo", "auth-hero-texto", "auth-hero-lista"):
        assert clase in panel.group(0)
    assert "montana-login" not in html, "la foto va de fondo (CSS): no se descarga como <img> ni se repite en la página"


def test_en_movil_el_panel_grande_se_oculta_y_la_foto_sigue_detras_del_formulario():
    movil = re.search(r"@media \(max-width: 820px\) \{.*?\n\}", CSS, re.S).group(0)
    assert ".auth-hero { display: none; }" in movil and "background-position" in movil
    assert "min-height: 100dvh" in _regla(".auth-dividido")                                  # ocupa toda la pantalla en el móvil también


def test_el_logotipo_blanco_va_sobre_pastilla_oscura_en_tema_claro():
    assert 'root[data-theme="light"] .auth-logo' in CSS and "prefers-color-scheme: light" in CSS
    pastilla = re.search(r':root\[data-theme="light"\] \.auth-logo \{([^}]*)\}', CSS).group(1)
    assert "var(--sidebar-bg)" in pastilla and "border-radius" in pastilla


def test_la_foto_pesa_poco_y_tiene_creditos_cc0():
    carpeta = RAIZ / "app" / "static" / "fotos"
    assert (carpeta / "montana-login.webp").stat().st_size < 220_000 and (carpeta / "montana-login.jpg").stat().st_size < 320_000
    creditos = (carpeta / "CREDITOS.md").read_text(encoding="utf-8")
    assert "CC0" in creditos and "commons.wikimedia.org" in creditos
    assert "fotos/montana-login.webp" in CSS and "fotos/montana-login.jpg" in CSS
