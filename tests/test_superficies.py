"""Capa de superficies de la app (app/static/superficies.css): paneles de cristal sobre un fondo con luz ambiente.

Lo que se vigila:
  - contraste AA (4,5:1) de cada color de texto del tema sobre el PEOR caso de panel (la luz ambiente más intensa bajo el panel
    translúcido), en claro y en oscuro;
  - que la hoja se carga después de style.css en las pantallas internas y que no se mete en las pantallas de acceso ni en el portal;
  - que sin soporte de desenfoque los fondos pasan a casi opacos;
  - que no quedan las marcas del estilo anterior (mayúsculas monoespaciadas en botones y títulos);
  - los filtros de fecha legibles (sin «2026-10-11T20:43:13» en pantalla)."""
import re
from pathlib import Path

import pytest

from tests.a11y import contraste

RAIZ = Path(__file__).resolve().parent.parent
BASE = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")
CAPA = (RAIZ / "app" / "static" / "superficies.css").read_text(encoding="utf-8")


def _hex(r, g, b) -> str:
    return "#%02x%02x%02x" % (round(r), round(g), round(b))


def _sobre(fondo: tuple, color: tuple, alfa: float) -> tuple:
    return tuple(f * (1 - alfa) + c * alfa for f, c in zip(fondo, color))


def _rgb(texto: str) -> tuple:
    if texto.startswith("#"):
        t = texto.lstrip("#")
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(v) for v in re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", texto).groups())


def _alfa(texto: str) -> float:
    return float(re.search(r"rgba\([^)]*,\s*([\d.]+)\)", texto).group(1))


def _token(bloque: str, nombre: str) -> str:
    return re.search(r"--" + re.escape(nombre) + r":\s*([^;]+);", bloque).group(1).strip()


def _color(tema: dict, nombre: str) -> str:
    """El valor que de verdad se aplica: el de la capa si lo redefine, y si no el de style.css."""
    try:
        return _token(tema["capa"], nombre)
    except AttributeError:
        return _token(tema["base"], nombre)


def _bloque(origen: str, abre: str) -> str:
    inicio = origen.index(abre) + len(abre)
    return origen[inicio:origen.index("\n}", inicio)]


# Temas: bloque de tokens de style.css (colores base) + bloque de la capa (cristal) + color de la luz ambiente más intensa (la peor para el texto
# claro es la más CLARA bajo el panel; para el texto oscuro, la más oscura).
OSCURO = {"base": _bloque(BASE, ':root[data-theme="dark"] {'), "capa": _bloque(CAPA, ':root[data-theme="dark"] {'),
          "luces": [(204, 255, 51, 0.075), (76, 110, 245, 0.10)]}
CLARO = {"base": _bloque(BASE, ":root {"), "capa": _bloque(CAPA, ":root:not([data-theme=\"dark\"]) {"),
         "luces": [(166, 230, 0, 0.13), (76, 110, 245, 0.10)]}


def _peores_fondos(tema: dict):
    bg = _rgb(_token(tema["base"], "bg"))
    cristal = _token(tema["capa"], "glass-bg")
    for luz in tema["luces"]:
        # la luz ambiente tiene su máximo en el centro del degradado: se toma entera (peor caso)
        ambiente = _sobre(bg, luz[:3], luz[3])
        yield _sobre(ambiente, _rgb(cristal), _alfa(cristal))


@pytest.mark.parametrize("nombre,tema", [("oscuro", OSCURO), ("claro", CLARO)])
@pytest.mark.parametrize("token", ["text", "text-muted", "primary-text", "danger-text", "success-text", "warning-text"])
def test_texto_legible_sobre_panel_de_cristal(nombre, tema, token):
    color = _color(tema, token)
    for fondo in _peores_fondos(tema):
        relacion = contraste(_hex(*_rgb(color)), _hex(*fondo))
        assert relacion >= 4.5, f"{token} ({color}) sobre el panel {nombre}: {relacion:.2f}:1"


@pytest.mark.parametrize("nombre,tema", [("oscuro", OSCURO), ("claro", CLARO)])
def test_texto_sobre_fila_resaltada(nombre, tema):
    """Las filas (.log-item, tarjetas del tablero) llevan encima un relleno --panel-2-hover: se suma al panel."""
    resalte = _token(tema["capa"], "panel-2-hover")
    for fondo in _peores_fondos(tema):
        fila = _sobre(fondo, _rgb(resalte), _alfa(resalte))
        for token in ("text", "text-muted"):
            relacion = contraste(_hex(*_rgb(_color(tema, token))), _hex(*fila))
            assert relacion >= 4.5, f"{token} sobre fila resaltada ({nombre}): {relacion:.2f}:1"


def test_sin_desenfoque_los_fondos_pasan_a_casi_opacos():
    bloque = re.search(r"@supports not \(.*?\{(.*?)\n\}", CAPA, re.S).group(1)
    for alfa in re.findall(r"--glass-bg: rgba\([^)]*,\s*([\d.]+)\)", bloque):
        assert float(alfa) >= 0.95


def test_cada_panel_translucido_tiene_su_alternativa_sin_desenfoque_o_es_un_menu_opaco():
    assert "backdrop-filter" in CAPA and "@supports not" in CAPA
    assert re.search(r"\.busqueda-modal,[^{]*\{[^}]*background:\s*color-mix\(in srgb, var\(--panel-solido\) 94%", CAPA)


def test_se_carga_despues_de_style_css_solo_en_las_pantallas_internas():
    base = (RAIZ / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert base.index("style.css") < base.index("superficies.css")
    for acceso in ("login", "registro", "recuperar_contrasena", "verificar_email", "portal_dashboard", "portal_entrar"):
        assert "superficies.css" not in (RAIZ / "app" / "templates" / f"{acceso}.html").read_text(encoding="utf-8"), acceso


def test_nada_de_monoespaciado_en_mayusculas_en_botones_y_titulos():
    assert re.search(r"\.page-header h1[^{]*\{[^}]*text-transform:\s*none", CAPA)
    assert re.search(r"\.btn,[^{]*\{[^}]*text-transform:\s*none", CAPA)
    assert re.search(r"--font-mono:\s*\"Manrope\"", CAPA)
    # el código sí sigue en monoespaciado
    assert re.search(r"code, pre, kbd, samp[^{]*\{\s*font-family:\s*var\(--font-codigo\)", CAPA)


def test_las_casillas_nativas_no_quedan_a_ancho_cero():
    """`.checkbox-label input { width: auto }` dejaba la casilla sin apariencia nativa en 0 px de ancho."""
    regla = re.search(r'input\[type="checkbox"\], input\[type="radio"\] \{(.*?)\}', CAPA, re.S).group(1)
    assert "min-width: 18px" in regla and "min-height: 18px" in regla


def test_se_respeta_prefers_reduced_motion():
    assert re.search(r"@media \(prefers-reduced-motion: reduce\)[^{]*\{[^}]*transform:\s*none", CAPA)


def test_filas_apiladas_en_movil_no_heredan_un_flex_basis_de_altura():
    assert re.search(r"max-width: 820px\) \{[^}]*quick-card-full \.quick-row input\[name=\"asunto\"\]", CAPA, re.S)


@pytest.mark.parametrize("valor,esperado", [
    ("2026-10-11T20:43:13", "11 oct 2026, 20:43"), ("2026-10-11 20:43", "11 oct 2026, 20:43"), ("2026-10-11", "11 oct 2026"),
    ("", ""), (None, ""), ("no es una fecha", "no es una fecha"),
])
def test_filtro_de_fecha_legible(valor, esperado, base_de_datos_temporal):
    from app.main import app
    with app.test_request_context("/"):
        assert app.jinja_env.filters["fecha_y_hora"](valor) == esperado


def test_filtro_solo_fecha(base_de_datos_temporal):
    from app.main import app
    with app.test_request_context("/"):
        assert app.jinja_env.filters["fecha_dia"]("2026-10-11T20:43:13") == "11 oct 2026"
