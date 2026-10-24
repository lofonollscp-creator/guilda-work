"""Tokens de diseño de la app móvil (`scripts/exportar_tokens_dart.py`): la web (`style.css`) es la fuente única y lo versionado no puede desfasarse.
También vigila que la paleta cumpla contraste AA (WCAG 2.2): si alguien cambia un color de marca y rompe la legibilidad, falla aquí, no en la tienda."""
import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("exportar_tokens_dart", RAIZ / "scripts/exportar_tokens_dart.py")
tokens = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tokens)


def _css() -> str:
    return (RAIZ / "app/static/style.css").read_text()


def test_lo_versionado_no_se_ha_desfasado_de_style_css():
    assert tokens.SALIDA.exists(), "falta mobile/lib/diseno/tokens.g.dart: ejecuta scripts/exportar_tokens_dart.py"
    assert tokens.SALIDA.read_text() == tokens.generar(_css()), "tokens.g.dart desfasado respecto a app/static/style.css: ejecuta scripts/exportar_tokens_dart.py"


def test_el_modo_oscuro_automatico_y_el_manual_dicen_lo_mismo():
    tokens.leer(_css())                         # lanza SystemExit si difieren


def test_estan_todos_los_colores_y_medidas_que_usa_la_app():
    claro, oscuro = tokens.leer(_css())
    for css in tokens.COLORES:
        assert css in claro and css in oscuro, css
    assert tokens._px(claro["radius-md"]) == "12.0" and tokens._px(claro["radius-sm"]) == "10.0" and tokens._px(claro["radius-lg"]) == "22.0"


def _luminancia(hexa: str) -> float:
    h = hexa.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lineal = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4          # noqa: E731
    return 0.2126 * lineal(r) + 0.7152 * lineal(g) + 0.0722 * lineal(b)


def _contraste(a: str, b: str) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (primer plano, fondo, mínimo): 4,5 para texto, 3 para componentes y anillo de foco.
PARES = [
    ("text", "bg", 4.5), ("text", "surface", 4.5), ("text-muted", "bg", 4.5), ("text-muted", "surface", 4.5),
    ("primary-text", "surface", 4.5), ("danger-text", "surface", 4.5), ("success-text", "surface", 4.5), ("warning-text", "surface", 4.5),
    ("on-accent", "primary", 4.5), ("focus-ring", "bg", 3.0),
]


@pytest.mark.parametrize("tema", ["claro", "oscuro"])
@pytest.mark.parametrize("fg,bg,minimo", PARES)
def test_contraste_aa_de_la_paleta(tema, fg, bg, minimo):
    claro, oscuro = tokens.leer(_css())
    v = claro if tema == "claro" else oscuro
    assert _contraste(v[fg], v[bg]) >= minimo, f"{fg} sobre {bg} ({tema}): {_contraste(v[fg], v[bg]):.2f}:1, mínimo {minimo}"
