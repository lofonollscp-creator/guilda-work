"""Los errores de una pantalla se ven con el estilo de la app (no el «Not Found» crudo del servidor); la API sigue devolviendo JSON."""
from tests.conftest import iniciar_sesion_de_prueba


def test_un_404_de_pantalla_sale_con_el_estilo_de_la_app(cliente):
    iniciar_sesion_de_prueba(cliente, "errores@ejemplo.com", "contrasena123")
    r = cliente.get("/esta-ruta-no-existe", headers={"Accept": "text/html"})
    assert r.status_code == 404
    html = r.get_data(as_text=True)
    assert "Esta página no existe" in html and "Ir al inicio" in html and 'href="/"' in html
    assert "The requested URL was not found" not in html


def test_el_404_de_la_api_sigue_siendo_json(cliente):
    r = cliente.get("/api/v1/esto-no-existe", headers={"Accept": "application/json"})
    assert r.status_code == 404 and r.is_json


def test_quien_no_acepta_html_recibe_la_respuesta_de_siempre(cliente):
    iniciar_sesion_de_prueba(cliente, "errores2@ejemplo.com", "contrasena123")
    r = cliente.get("/esta-ruta-no-existe", headers={"Accept": "application/json"})
    assert r.status_code == 404 and "Esta página no existe" not in r.get_data(as_text=True)


def test_un_texto_traducido_cabe_en_un_literal_de_javascript():
    from app.main import app
    f = app.jinja_env.filters["js_texto"]
    assert f("No s'ha pogut carregar.") == "No s\\u0027ha pogut carregar."
    assert f('Dis "hola" <b>') == 'Dis \\"hola\\" \\u003cb\\u003e'
    assert "\n" not in f("dos\nlíneas") and f("l'été") == "l\\u0027été"


def test_ningun_script_mete_texto_traducido_sin_escapar():
    """Dentro de un <script>, `{{ _('…') }}` sin `|js_texto` (o `|tojson`) rompe el JavaScript en catalán y francés (d', l', s'…)."""
    import glob
    import re
    bloque = re.compile(r"(<script\b(?![^>]*type=[\"']application/(?:ld\+)?json)[^>]*>)(.*?)(</script>)", re.S)
    exp = re.compile(r"\{\{\s*(?:_|gettext|ngettext)\((?:[^{}]|\{[^{}]*\})*?\)\s*\}\}")
    malos = []
    for f in glob.glob("app/templates/**/*.html", recursive=True) + glob.glob("backoffice/templates/**/*.html", recursive=True):
        for m in bloque.finditer(open(f, encoding="utf-8").read()):
            for linea in m.group(2).splitlines():
                if exp.search(linea) and not linea.lstrip().startswith("//"):
                    malos.append(f"{f}: {linea.strip()[:90]}")
    assert not malos, "\n".join(malos)
