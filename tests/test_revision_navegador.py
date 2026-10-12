"""Defectos que solo se vieron al abrir las pantallas en un navegador (revisión del 12 de octubre): se vigila que no vuelvan."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _plantillas():
    return sorted((RAIZ / "app" / "templates").rglob("*.html"))


def test_una_celda_de_tabla_nunca_es_flex():
    """`<td class="ds-fila">` (display: flex) deja de ser una celda y descuadra las líneas de la fila."""
    malas = [p.name for p in _plantillas() if re.search(r'<t[dh]\s+class="[^"]*\bds-(?:fila|flex|grid)\b', p.read_text(encoding="utf-8"))]
    assert not malas, f"celdas flex en: {malas}"


def test_los_formularios_de_datos_de_los_modulos_llevan_etiqueta_visible():
    """Un campo con solo `placeholder` (y `aria-label`) pierde su nombre en cuanto se rellena: en los formularios de datos cada campo lleva su `<label>`."""
    for nombre in ("inmobiliaria", "abogados"):
        texto = (RAIZ / "app" / "templates" / nombre / "_panel_expediente.html").read_text(encoding="utf-8")
        for bloque in re.findall(r'<form[^>]*class="edit-form"[^>]*>.*?</form>', texto, re.S):
            for linea in bloque.splitlines():
                if re.match(r"\s*<(input|select|textarea)\b", linea) and not re.search(r'type="(hidden|checkbox|file)"', linea):
                    raise AssertionError(f"{nombre}: campo sin etiqueta visible: {linea.strip()[:90]}")


def test_el_panel_del_modulo_va_antes_que_los_plazos_y_horas_genericos():
    texto = (RAIZ / "app" / "templates" / "expediente_ficha.html").read_text(encoding="utf-8")
    assert texto.index("include p.plantilla") < texto.index("_('Plazos')"), "el panel del módulo es lo principal del expediente: debe ir primero"


def test_el_css_arregla_las_casillas_de_los_filtros_y_el_selector_de_archivos():
    css = (RAIZ / "app" / "static" / "ds.css").read_text(encoding="utf-8")
    assert ".filters .checkbox-label" in css and "file-selector-button" in css
