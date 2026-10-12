"""Sistema de diseño (PLAN_MAESTRO.md §3): candado contra controles «de fábrica» y pruebas de los componentes propios.

El candado funciona como un trinquete: cada pantalla puede MEJORAR pero nunca empeorar. La línea base vive en
tests/datos/sistema_diseno_base.json; al migrar una pantalla el recuento baja y hay que regenerarla con
`python3 scripts/sistema_diseno_base.py` (el test lo exige, para que la lista de excepciones se vaya vaciando de verdad)."""
import re
from pathlib import Path

import pytest

from tests import sistema_diseno_reglas as r

RAIZ = r.RAIZ


# --- candado --------------------------------------------------------------------------------------------------------------------------
def test_no_aparecen_nuevos_controles_de_fabrica():
    base, ahora = r.cargar_base(), r.contar()
    nuevos = []
    for regla, por_fichero in ahora.items():
        for fichero, n in por_fichero.items():
            if n > base.get(regla, {}).get(fichero, 0):
                nuevos.append(f"{fichero}: {n} × «{r.REGLAS[regla][0]}» (antes {base.get(regla, {}).get(fichero, 0)})")
    assert not nuevos, "Controles de fábrica nuevos (usa los componentes de _ds/componentes.html y ds.js):\n  " + "\n  ".join(nuevos)


def test_la_linea_base_se_ajusta_cuando_se_migra_una_pantalla():
    base, ahora = r.cargar_base(), r.contar()
    obsoletas = [f"{f}: {regla} {n} → {ahora[regla].get(f, 0)}" for regla, por_fichero in base.items() for f, n in por_fichero.items() if ahora.get(regla, {}).get(f, 0) < n]
    assert not obsoletas, "Has mejorado estas pantallas: baja la línea base con `python3 scripts/sistema_diseno_base.py`:\n  " + "\n  ".join(obsoletas)


def test_nada_de_manejadores_en_linea_ni_etiquetas_obsoletas():
    assert r.prohibidas() == {}, r.prohibidas()


def test_las_pantallas_migradas_no_tienen_excepciones():
    """Cuando se migra una pantalla se añade aquí y deja de poder tener controles de fábrica."""
    migradas = ["app/templates/correo_redactar.html"]
    for regla in ("dialogo_nativo",):
        for f in migradas:
            assert r.contar()[regla].get(f, 0) == 0, (regla, f)


# --- ds.js y csp_compat.js ----------------------------------------------------------------------------------------------------------------
def test_base_carga_el_sistema_de_diseno_antes_que_los_scripts_que_lo_usan():
    base = (RAIZ / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "filename='ds.css'" in base and base.index("filename='ds.js'") < base.index("filename='toasts.js'") < base.index("filename='csp_compat.js'")
    for clave in ("dsAceptar", "dsCancelar", "dsAtencion", "dsConfirmarPeligro", "correoEliminarConfirmar", "correoEnlaceUrl", "correoEnlaceInvalido"):
        assert clave + ":" in base, clave


def test_el_dialogo_es_accesible_y_no_usa_html_del_texto():
    js = (RAIZ / "app" / "static" / "ds.js").read_text(encoding="utf-8")
    assert "showModal()" in js and "aria-labelledby" in js and "aria-describedby" in js
    assert "p.textContent = mensaje" in js and "p.innerHTML" not in js, "el mensaje se pinta como texto, nunca como HTML"
    assert "opciones.peligro && c.cancelar ? c.cancelar : c.aceptar" in js, "en una acción destructiva el foco empieza en Cancelar"
    assert "window.confirm" in js and "window.prompt" in js and "window.alert" in js, "alternativa si el navegador no soporta <dialog>"


def test_las_confirmaciones_pasan_por_el_dialogo_del_sistema():
    cc = (RAIZ / "app" / "static" / "csp_compat.js").read_text(encoding="utf-8")
    assert "GuildaDS.confirmar" in cc and "data-confirmar-excepto" in cc
    redactar = (RAIZ / "app" / "templates" / "correo_redactar.html").read_text(encoding="utf-8")
    assert 'data-confirmar-envio="' in redactar and 'data-confirmar-excepto="programar"' in redactar and "onsubmit" not in redactar, \
        "con la CSP forzada un onsubmit en línea no se ejecuta: el envío salía sin confirmar"


# --- macros ---------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def jinja(cliente):
    from app.main import app

    def render(fuente: str, **ctx) -> str:
        with app.test_request_context("/"):
            return app.jinja_env.from_string('{% from "_ds/componentes.html" import boton, interruptor, estado_vacio, campo, seccion, esqueleto, chip, sin_validar, icono %}' + fuente).render(**ctx)
    return render


def test_boton_variantes_y_confirmacion(jinja):
    html = jinja('{{ boton("Guardar", "primario", tipo="submit") }}{{ boton("Borrar", "peligro", confirmar="¿Seguro?") }}{{ boton("Ir", href="/x", pequeno=True) }}')
    assert 'class="btn btn-primary" type="submit"' in html
    assert 'class="btn btn-peligro" type="button"' in html and 'data-confirmar-clic="¿Seguro?"' in html
    assert '<a class="btn btn-sm" href="/x">Ir</a>' in html


def test_los_macros_escapan_el_texto(jinja):
    malo = '<img src=x onerror=alert(1)>'
    html = jinja("{{ boton(t) }}{{ interruptor('a', t, ayuda=t) }}{{ estado_vacio(t, t) }}{{ chip(t) }}", t=malo)
    assert "<img src=x" not in html and "&lt;img" in html


def test_interruptor_es_un_checkbox_accesible(jinja):
    html = jinja('{{ interruptor("avisos", "Avisos", marcado=True, ayuda="Te avisamos") }}')
    assert 'type="checkbox" role="switch"' in html and "checked" in html and 'aria-describedby="sw-avisos-ayuda"' in html and 'for="sw-avisos"' in html


def test_estado_vacio_y_error(jinja):
    assert 'class="ds-vacio"' in jinja('{{ estado_vacio("Sin clientes", "Crea el primero", accion_texto="Nuevo", accion_href="/n") }}')
    err = jinja('{{ estado_vacio("Falló", error=True) }}')
    assert "ds-vacio-error" in err and 'role="alert"' in err


def test_campo_con_error_y_requerido(jinja):
    html = jinja('{% call campo("Nombre", para="n", error="Obligatorio", requerido=True) %}<input id="n">{% endcall %}')
    assert "ds-campo-con-error" in html and "ds-campo-requerido" in html and 'role="alert"' in html and '<input id="n">' in html


def test_marca_sin_validar(jinja):
    assert "ds-sinvalidar" in jinja("{{ sin_validar() }}") and "Sin validar" in jinja("{{ sin_validar() }}")


def test_el_css_cubre_todas_las_clases_de_las_macros():
    css = (RAIZ / "app" / "static" / "ds.css").read_text(encoding="utf-8")
    macros = (RAIZ / "app" / "templates" / "_ds" / "componentes.html").read_text(encoding="utf-8")
    clases = set(re.findall(r'class="([a-z][a-z0-9 -]*)', macros)) | set(re.findall(r"btn-(?:peligro|sm)", macros))
    usadas = {c for lista in clases for c in lista.split() if c.startswith(("ds-", "btn-peligro", "btn-sm"))}
    faltan = sorted(c for c in usadas if "." + c not in css)
    assert not faltan, faltan


# --- selector propio y selector de fecha ------------------------------------------------------------------------------------------------
def test_todos_los_desplegables_y_fechas_pasan_por_los_componentes_propios():
    sel = (RAIZ / "app" / "static" / "selector_buscable.js").read_text(encoding="utf-8")
    assert "MIN_OPCIONES = 1" in sel and "MIN_BUSCADOR = 6" in sel and "selbus-sin-buscador" in sel
    fecha = (RAIZ / "app" / "static" / "ds_fecha.js").read_text(encoding="utf-8")
    for tipo in ('"date"', '"datetime-local"', '"time"'):
        assert tipo in fecha
    base = (RAIZ / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "filename='ds_fecha.js'" in base and "filename='selector_buscable.js'" in base


def test_el_selector_de_fecha_es_accesible_y_tiene_hoja_en_movil():
    js = (RAIZ / "app" / "static" / "ds_fecha.js").read_text(encoding="utf-8")
    for cosa in ('role", "dialog"', 'role", "grid"', "gridcell", "aria-label", "aria-selected", "aria-current", "ArrowRight", "PageDown", "Escape", "F4"):
        assert cosa in js, cosa
    css = (RAIZ / "app" / "static" / "ds.css").read_text(encoding="utf-8")
    assert ".ds-cal.ds-cal-hoja" in css and "prefers-reduced-motion" in css
    assert (RAIZ / "scripts" / "ds_fecha_prueba.mjs").exists() and (RAIZ / "scripts" / "comprobar_ds_fecha.sh").exists()


def test_los_textos_del_selector_de_fecha_estan_traducidos():
    base = (RAIZ / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    for idioma in ("ca", "en", "fr"):
        po = (RAIZ / "translations" / idioma / "LC_MESSAGES" / "messages.po").read_text(encoding="utf-8")
        for clave in re.findall(r"ds(?:Hoy|Borrar|Fecha|Hora|Minutos|Periodo|MesAnterior|MesSiguiente|EstaSemana|EsteMes|MesPasado|EsteTrimestre|EsteAnio):\s*\{\{ _\('([^']+)'\)", base):
            assert re.search(r'msgid "' + re.escape(clave) + r'"\nmsgstr "[^"]+"', po), (idioma, clave)


def test_ningun_texto_traducible_lleva_un_porcentaje_suelto():
    """flask-babel formatea con % los textos de _(): un «50 %» suelto rompe la página con un error 500 (ValueError). Hay que escribir %% o evitar el símbolo."""
    malos = []
    for p in sorted((RAIZ / "app" / "templates").rglob("*.html")):
        for m in re.finditer(r"\b_\('((?:[^'\\]|\\.)*)'\)|\b_\(\"((?:[^\"\\]|\\.)*)\"\)", p.read_text(encoding="utf-8")):
            texto = m.group(1) or m.group(2) or ""
            if re.search(r"%(?!\(\w+\)[sd]|%|s\b|d\b)", texto) and not re.search(r"%\(\w+\)", texto):
                malos.append(f"{p.relative_to(RAIZ)}: {texto[:70]}")
    assert not malos, "Textos con «%» suelto:\n  " + "\n  ".join(malos)
