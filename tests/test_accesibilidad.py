"""Accesibilidad: las pantallas de la app cumplen las reglas WCAG que se pueden comprobar sin navegador (ver tests/a11y.py), y los
colores de texto de los dos temas tienen contraste suficiente (AA: 4,5:1 para texto normal)."""
import re
from pathlib import Path

import pytest

from app import db
from tests import a11y
from tests.conftest import iniciar_sesion_de_prueba

RAIZ = Path(__file__).resolve().parent.parent
# Rutas que no son pantallas HTML (descargas, flujos de salida, endpoints de acción) o que exigen parámetros.
_OMITIR = ("/ia/panel", "/static", "/api/", "/hydra/", "/.ory", "/salir", "/apagar", "/exportar", "/captura", "/verificar", "/avatar", "/descargar", "/csp-")


def _paginas_get(app):
    visto = set()
    for regla in app.url_map.iter_rules():
        if "GET" not in regla.methods or regla.arguments or any(regla.rule.startswith(p) or p in regla.rule for p in _OMITIR):
            continue
        if regla.rule not in visto:
            visto.add(regla.rule)
            yield regla.rule


@pytest.fixture
def usuario_con_datos(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "a11y@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Despacho a11y")
    db.asignar_tenant(uid, tenant)
    conn = db.get_connection()
    conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
    cat = db.crear_categoria(uid, "Proyecto a11y", None)
    db.crear_tarea_outlook(uid, "Tarea a11y")
    db.crear_nota(uid, "Nota a11y")
    return uid


def test_las_pantallas_cumplen_las_reglas_de_accesibilidad(cliente, usuario_con_datos):
    from app.main import app
    resultados = {}
    revisadas = 0
    for ruta in sorted(_paginas_get(app)):
        r = cliente.get(ruta)
        if r.status_code != 200 or "text/html" not in r.headers.get("Content-Type", ""):
            continue
        revisadas += 1
        problemas = a11y.analizar(r.get_data(as_text=True))
        if problemas:
            resultados[ruta] = problemas
    assert revisadas >= 15, f"solo se pudieron revisar {revisadas} pantallas"
    por_problema = {}
    for ruta, lista in resultados.items():
        for p in set(lista):
            por_problema.setdefault(p, []).append(ruta)
    informe = "\n".join(f"[{len(rutas)} pág.] {p}  (p. ej. {rutas[0]})" for p, rutas in sorted(por_problema.items(), key=lambda x: -len(x[1])))
    assert not resultados, f"\n{len(resultados)} de {revisadas} pantallas con problemas:\n{informe}"


def _variables(bloque: str) -> dict:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,6})\s*;", bloque))


def _bloque_css(css: str, inicio: str) -> str:
    i = css.index(inicio)
    return css[i:css.index("}", i)]


@pytest.mark.parametrize("tema,selector", [("claro", ":root {"), ("oscuro", ':root[data-theme="dark"] {')])
def test_el_texto_tiene_contraste_suficiente_en_cada_tema(tema, selector):
    css = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")
    base = _variables(_bloque_css(css, ":root {"))
    v = {**base, **(_variables(_bloque_css(css, selector)) if selector != ":root {" else {})}
    pares = [("text", "bg"), ("text", "surface"), ("text-muted", "bg"), ("text-muted", "surface"),
             ("primary-text", "surface"), ("danger-text", "surface"), ("success-text", "surface"), ("warning-text", "surface")]
    malos = []
    for texto, fondo in pares:
        if texto in v and fondo in v:
            ratio = a11y.contraste(v[texto], v[fondo])
            if ratio < 4.5:
                malos.append(f"--{texto} sobre --{fondo}: {ratio:.2f}:1")
    assert not malos, f"tema {tema}: contraste insuficiente (AA pide 4,5:1): {malos}"


def test_el_css_no_quita_el_foco_sin_dejar_otro_indicador():
    """`outline: none` solo vale si el mismo selector (o su :focus-visible) pone otro indicador (box-shadow o border)."""
    css = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")
    sin_indicador = []
    for selector, cuerpo in re.findall(r"([^{}]+)\{([^{}]*outline:\s*(?:none|0)[^{}]*)\}", css):
        if not re.search(r"box-shadow|border|background|text-decoration", cuerpo):
            sin_indicador.append(" ".join(selector.split())[:70])
    assert not sin_indicador, f"selectores que quitan el foco sin alternativa: {sin_indicador}"


def test_hay_respeto_por_prefers_reduced_motion():
    css = (RAIZ / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css and ("animation" in css or "transition" in css)
