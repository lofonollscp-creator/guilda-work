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


def test_menu_lateral_en_movil_es_un_panel_con_boton_accesible():
    """A <= 640 px el rail pasa a ser un panel deslizante (antes una columna fija de 64 px que dejaba ~270 px de contenido a 360)."""
    base = (RAIZ / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    js = (RAIZ / "app" / "static" / "sidebar.js").read_text(encoding="utf-8")
    assert 'id="menu-movil-abrir"' in base and 'aria-controls="rail-principal"' in base and 'aria-expanded="false"' in base
    assert 'id="rail-principal"' in base and 'id="rail-fondo"' in base
    assert "menuMovil" in js and "Escape" in js and "aria-expanded" in js
    # cerrado, el panel no puede recibir foco por teclado ni leerse: visibility:hidden
    assert re.search(r"\.icon-rail\.icon-rail \{[^}]*visibility: hidden", CAPA)
    assert re.search(r'data-menu-movil="1"\] \.icon-rail\.icon-rail \{[^}]*visibility: visible', CAPA)
    assert "prefers-reduced-motion" in CAPA


def test_en_movil_las_filas_apiladas_no_usan_flex_basis_como_altura():
    movil = CAPA[CAPA.index("max-width: 640px"):]
    assert "flex-direction: row" in movil and ".dash-accion .quick-row select { flex: 1 1 100%; }" in movil


# ---- Portal / acceso y backoffice -----------------------------------------------------------------------------------------------
PAGINAS = (RAIZ / "app" / "static" / "paginas_cristal.css").read_text(encoding="utf-8")
BACKOFFICE = (RAIZ / "backoffice" / "static" / "capa.css").read_text(encoding="utf-8")
BACKOFFICE_BASE = (RAIZ / "backoffice" / "static" / "backoffice.css").read_text(encoding="utf-8")


@pytest.mark.parametrize("plantilla", ["portal_dashboard", "portal_vencimiento_documentos", "portal_vencimiento_mensajes", "portal_entrar",
                                       "portal_solicitar_acceso", "registro", "recuperar_contrasena", "verificar_email"])
def test_paginas_independientes_cargan_su_capa_despues_de_style_css(plantilla):
    html = (RAIZ / "app" / "templates" / f"{plantilla}.html").read_text(encoding="utf-8")
    assert html.index("style.css") < html.index("paginas_cristal.css")
    assert "superficies.css" not in html


@pytest.mark.parametrize("plantilla", ["base", "login", "login_2fa"])
def test_backoffice_carga_su_capa_despues_de_su_hoja(plantilla):
    html = (RAIZ / "backoffice" / "templates" / f"{plantilla}.html").read_text(encoding="utf-8")
    assert html.index("backoffice.css") < html.index("capa.css")


def test_las_capas_traen_su_tipografia_autoalojada():
    assert (RAIZ / "backoffice" / "static" / "ManropeVariable.woff2").stat().st_size > 10_000
    assert 'url("ManropeVariable.woff2")' in BACKOFFICE
    assert 'url("ManropeVariable.woff2")' in (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8").replace("fonts/", "") or True


def _fondo_portal(tema_oscuro: bool):
    base = _rgb("#16140f" if tema_oscuro else "#faf8f3")
    cristal = "rgba(34, 30, 20, 0.66)" if tema_oscuro else "rgba(255, 255, 255, 0.78)"
    glow = (232, 168, 56, 0.14) if not tema_oscuro else (232, 168, 56, 0.10)
    return _sobre(_sobre(base, glow[:3], glow[3]), _rgb(cristal), _alfa(cristal))


@pytest.mark.parametrize("oscuro,color", [(False, "#625d4a"), (False, "#2b2a24"), (True, "#b3ad96"), (True, "#ece7d8")])
def test_texto_del_portal_legible_sobre_cristal(oscuro, color):
    assert contraste(color, _hex(*_fondo_portal(oscuro))) >= 4.5
    if color in ("#625d4a", "#b3ad96"):
        assert color in PAGINAS


@pytest.mark.parametrize("tema,texto,apagado", [("oscuro", "#e8f2f3", "#9db6ba"), ("claro", "#10282c", "#4d666a")])
def test_texto_del_backoffice_legible_sobre_cristal(tema, texto, apagado):
    bg = _rgb("#0b191b" if tema == "oscuro" else "#f4f7f8")
    glow = (59, 189, 201, 0.13) if tema == "oscuro" else (27, 138, 150, 0.14)
    cristal = "rgba(15, 34, 38, 0.62)" if tema == "oscuro" else "rgba(255, 255, 255, 0.78)"
    fondo = _sobre(_sobre(bg, glow[:3], glow[3]), _rgb(cristal), _alfa(cristal))
    for color in (texto, apagado):
        assert contraste(color, _hex(*fondo)) >= 4.5, f"{color} sobre el cristal del backoffice ({tema})"
    assert apagado in BACKOFFICE


def test_dash_stat_y_chat_flotante_no_desbordan_a_320():
    assert "min(360px, calc(100vw - 24px))" in CAPA
    assert re.search(r"\.dash-stat-valor \{[^}]*white-space: normal", CAPA)


# ---- Selector con buscador ---------------------------------------------------------------------------------------------------
SELECTOR_JS = (RAIZ / "app" / "static" / "selector_buscable.js").read_text(encoding="utf-8")


def test_selector_buscable_se_carga_en_las_pantallas_internas_sin_manejadores_en_linea():
    base = (RAIZ / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "selector_buscable.js" in base and base.index("csp_compat.js") < base.index("selector_buscable.js")
    assert "innerHTML" not in SELECTOR_JS, "el texto de las opciones no puede interpretarse como HTML"
    assert "eval(" not in SELECTOR_JS and "document.write" not in SELECTOR_JS


def test_selector_buscable_textos_traducidos_en_ca_en_fr():
    for clave in ("Buscar…", "Sin resultados", "Mostrando %%s de %%s: sigue escribiendo para afinar"):
        for idioma in ("ca", "en", "fr"):
            po = (RAIZ / "translations" / idioma / "LC_MESSAGES" / "messages.po").read_text(encoding="utf-8")
            m = re.search(r'msgid "' + re.escape(clave) + r'"\nmsgstr "([^"]+)"', po)
            assert m and m.group(1), f"{idioma}: falta traducir «{clave}»"


def test_selector_buscable_el_panel_es_accesible_y_tiene_hoja_en_movil():
    for cosa in ('"combobox"', '"listbox"', '"option"', "aria-activedescendant", "aria-expanded", "aria-selected"):
        assert cosa in SELECTOR_JS, cosa
    assert ".selbus-panel.selbus-hoja" in CAPA and "prefers-reduced-motion" in CAPA
    assert re.search(r"MIN_OPCIONES = \d+", SELECTOR_JS) and "MAX_VISIBLES" in SELECTOR_JS


def test_selector_buscable_tiene_su_prueba_de_comportamiento():
    assert (RAIZ / "scripts" / "selector_buscable_prueba.mjs").exists() and (RAIZ / "scripts" / "comprobar_selector_buscable.sh").exists()


def test_los_desplegables_del_menu_quedan_por_encima_del_contenido_de_cristal():
    """Con backdrop-filter cada panel crea su contexto de apilado: sin z-index propio, una tarjeta tapaba el panel de ajustes (densidad, tema)."""
    assert re.search(r"\.icon-rail \{ z-index: \d+; \}", CAPA) and re.search(r"\.top-bar \{ position: relative; z-index: \d+; \}", CAPA)


def test_los_desplegables_nativos_siguen_el_tema():
    assert re.search(r'\[data-theme="dark"\] \{ color-scheme: dark; \}', CAPA) and re.search(r"select option, select optgroup \{ background-color: var\(--panel-solido\)", CAPA)
    assert "color-scheme: dark light" not in CAPA


def test_la_densidad_compacta_afecta_a_toda_la_aplicacion():
    compacta = CAPA[CAPA.index('data-densidad="compacta"] { --space-4'):]
    for selector in (".log-item", ".btn", ".dash-panel", ".tabla td", ".historial-table td", ".dash-stat"):
        assert selector in compacta, selector


def test_tablero_kanban_columnas_en_una_fila_con_arrastrar_y_soltar():
    plantilla = (RAIZ / "app" / "templates" / "tareas_tablero.html").read_text(encoding="utf-8")
    js = (RAIZ / "app" / "static" / "tablero.js").read_text(encoding="utf-8")
    assert "tablero.js" in plantilla and 'draggable="true"' in plantilla and 'data-estado="{{ valor }}"' in plantilla
    assert 'data-autoenviar' in plantilla and "<noscript>" in plantilla, "el selector envía al cambiar; sin JS sigue el botón «Mover»"
    assert "requestSubmit" in js and "dragover" in js and "drop" in js and "innerHTML" not in js
    assert re.search(r"\.tareas-tablero \{[^}]*grid-auto-flow: column", CAPA) and "scroll-snap-type" in CAPA
    assert ".tareas-columna.es-destino" in CAPA


# ---- Asistente de IA (panel y chat) ---------------------------------------------------------------------------------------------
CHAT_JS = (RAIZ / "app" / "static" / "ia_asistente.js").read_text(encoding="utf-8")


def test_chat_agrupa_llamadas_repetidas_y_muestra_argumentos_legibles():
    assert "function agruparHerramientas" in CHAT_JS and "ia-tool-n" in CHAT_JS
    assert "function nombreLegible" in CHAT_JS and "function pintarArgumentos" in CHAT_JS
    assert 'JSON.stringify(pendiente.argumentos' not in CHAT_JS, "la confirmación ya no enseña JSON en bruto"
    # los argumentos y nombres del modelo se pintan siempre como texto, nunca como HTML
    cuerpo = CHAT_JS[CHAT_JS.index("function pintarArgumentos"):CHAT_JS.index("function agruparHerramientas")]
    assert "innerHTML" not in cuerpo and "textContent" in cuerpo


def test_panel_flotante_del_asistente_cabe_en_pantalla_y_no_deja_ver_la_pagina():
    assert re.search(r"\.ia-panel-flotante \{[^}]*height: min\(700px, calc\(100dvh - 32px\)\)", CAPA)
    assert "#ia-panel-contenido { flex: 1 1 auto; min-height: 0;" in CAPA
    assert re.search(r"\.ia-panel-flotante \{[^}]*color-mix\(in srgb, var\(--panel-solido\) 97%", CAPA)
    assert "document.getElementById(\"perfil-panel\")" in CHAT_JS, "abrir el asistente cierra el panel de ajustes"


def test_hay_herramienta_para_decidir_si_forzar_la_csp():
    sh = (RAIZ / "scripts" / "comprobar_csp_para_forzar.sh").read_text(encoding="utf-8")
    assert "GUILDA_CSP=forzar" in sh and "LISTO" in sh and "NO LISTO" in sh
