"""La foto de montaña del inicio de sesión no puede quitar legibilidad al texto: se recrea lo que dibuja el navegador (foto con
`background-size: cover`, degradado oscuro encima) y se mide el contraste de cada color de texto contra el PEOR píxel de la franja
donde van las letras, en varios tamaños de pantalla. WCAG AA: 4,5:1 para texto normal, 3:1 para el titular grande."""
import re
from pathlib import Path

import pytest
from PIL import Image

from tests.a11y import contraste

RAIZ = Path(__file__).resolve().parent.parent
CSS = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")


def _regla(selector: str) -> str:
    return re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS).group(1)


def _paradas() -> list[tuple[float, float]]:
    """(posición 0-1, alfa) del degradado que se pinta sobre la foto, leído del CSS real."""
    hero = _regla(".auth-hero")
    degradado = re.search(r"linear-gradient\(90deg,([^)]*\)[^)]*\)[^)]*\)[^)]*\))", hero)
    return [(float(pos) / 100, float(alfa)) for alfa, pos in re.findall(r"rgba\(\s*5,\s*5,\s*6,\s*([\d.]+)\)\s*(\d+)%", degradado.group(1))]


def _fondo(ancho: int, alto: int) -> Image.Image:
    foto = Image.open(RAIZ / "app" / "static" / "fotos" / "montana-login.jpg").convert("RGB")
    px, py = [float(v) / 100 for v in re.search(r"background-position:\s*([\d.]+)%\s+([\d.]+)%", _regla(".auth-hero")).groups()]
    escala = max(ancho / foto.width, alto / foto.height)                     # cover
    grande = foto.resize((max(ancho, round(foto.width * escala)), max(alto, round(foto.height * escala))))
    x0, y0 = round((grande.width - ancho) * px), round((grande.height - alto) * py)
    base = grande.crop((x0, y0, x0 + ancho, y0 + alto))
    paradas = _paradas()
    for x in range(ancho):
        f = x / (ancho - 1)
        for (p0, a0), (p1, a1) in zip(paradas, paradas[1:]):
            if p0 <= f <= p1:
                alfa = a0 + (a1 - a0) * (f - p0) / (p1 - p0)
                break
        else:
            alfa = paradas[-1][1]
        for y in range(alto):
            r, g, b = base.getpixel((x, y))
            base.putpixel((x, y), (round(r * (1 - alfa) + 5 * alfa), round(g * (1 - alfa) + 5 * alfa), round(b * (1 - alfa) + 6 * alfa)))
    return base


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


def _peor_pixel(imagen: Image.Image, caja) -> str:
    """El píxel MÁS CLARO de la zona (el peor para texto claro), tras un pequeño suavizado para no depender de un píxel suelto."""
    zona = imagen.crop(caja).resize((max((caja[2] - caja[0]) // 6, 1), max((caja[3] - caja[1]) // 6, 1)))
    return _hex(max(zona.getdata(), key=lambda p: sum(p)))


@pytest.mark.parametrize("ancho,alto", [(1005, 975), (1300, 800), (840, 1100)])
def test_el_texto_del_hero_mantiene_el_contraste_sobre_la_foto(ancho, alto):
    imagen = _fondo(ancho, alto)
    # Todo lo que es texto cae en la columna izquierda: padding de 64 px y como mucho ~580 px de ancho (max-width de los párrafos).
    zona_texto = (64, 56, min(64 + 580, ancho), alto - 56)
    fondo = _peor_pixel(imagen, zona_texto)
    texto_normal = [re.search(r"\.auth-hero-texto\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
                    re.search(r"\.auth-hero-lista\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", CSS).group(1),
                    re.search(r"\.auth-hero\s*\{[^}]*?\bcolor:\s*(#[0-9a-fA-F]{6})", CSS).group(1)]
    for color in texto_normal:
        assert contraste(color, fondo) >= 4.5, f"{color} sobre {fondo} ({ancho}x{alto}): {contraste(color, fondo):.2f}:1"


def test_la_foto_existe_en_dos_formatos_pesa_poco_y_tiene_creditos():
    carpeta = RAIZ / "app" / "static" / "fotos"
    assert (carpeta / "montana-login.webp").stat().st_size < 200_000 and (carpeta / "montana-login.jpg").stat().st_size < 250_000
    creditos = (carpeta / "CREDITOS.md").read_text(encoding="utf-8")
    assert "CC0" in creditos and "commons.wikimedia.org" in creditos
    assert "fotos/montana-login.webp" in CSS and "fotos/montana-login.jpg" in CSS
