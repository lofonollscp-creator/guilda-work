"""Calidad de la documentación: lo que se añade al código no puede quedarse sin explicar.

- Toda variable de entorno propia (GUILDA_*, MCP_REMOTO_*) que lee el código está en la documentación (HOSTING.md o /docs).
- Toda herramienta MCP y toda operación de la API tienen una descripción útil.
- Todo enlace interno de /docs apunta a una página que existe."""
import re
from pathlib import Path

import pytest

import mcp_tools
from app import documentacion_dev as dd

RAIZ = Path(__file__).resolve().parent.parent
_PATRON_VAR = re.compile(r"""environ(?:\.get)?\(\s*["']((?:GUILDA|MCP_REMOTO)_[A-Z0-9_]+)["']|getenv\(\s*["']((?:GUILDA|MCP_REMOTO)_[A-Z0-9_]+)["']""")

# Variables internas que no se documentan al público (pruebas, plomería de despliegue). Mantener esta lista corta.
_INTERNAS = {
    "GUILDA_ACTUALIZAR_BASELINE_OPENAPI", "GUILDA_BASELINE_OPENAPI_DESTINO", "GUILDA_AYUDA_CONTENIDO",
}


def _variables_usadas() -> set[str]:
    usadas = set()
    for fuente in list((RAIZ / "app").glob("*.py")) + [RAIZ / "mcp_tools.py", RAIZ / "mcp_server_remoto.py", RAIZ / "serve.py", RAIZ / "run.py"]:
        for a, b in _PATRON_VAR.findall(fuente.read_text(encoding="utf-8", errors="ignore")):
            usadas.add(a or b)
    return usadas


def _texto_documentacion() -> str:
    texto = (RAIZ / "HOSTING.md").read_text(encoding="utf-8")
    texto += "\n".join(f.read_text(encoding="utf-8") for f in [RAIZ / "app" / "documentacion_dev.py"])
    return texto


def test_toda_variable_de_entorno_esta_documentada():
    documentado = _texto_documentacion()
    sin_documentar = sorted(v for v in _variables_usadas() - _INTERNAS if v not in documentado)
    assert not sin_documentar, f"variables leídas por el código y sin documentar (HOSTING.md o /docs): {sin_documentar}"


def test_toda_herramienta_mcp_tiene_descripcion_util():
    pobres = [t.__name__ for t in mcp_tools.TOOLS if len((t.__doc__ or "").strip()) < 25]
    assert not pobres, f"herramientas MCP sin descripción suficiente (docstring): {pobres}"


def test_toda_operacion_de_la_api_tiene_resumen_y_area(cliente):
    spec = cliente.get("/api/v1/openapi.json").get_json()
    sin_resumen, sin_area = [], []
    for ruta, ops in spec["paths"].items():
        for metodo, op in ops.items():
            if metodo not in {"get", "post", "put", "patch", "delete"}:
                continue
            if len((op.get("summary") or "").strip()) < 3:
                sin_resumen.append(f"{metodo.upper()} {ruta}")
            if not op.get("x-area"):
                sin_area.append(f"{metodo.upper()} {ruta}")
    assert not sin_resumen, sin_resumen
    assert not sin_area, sin_area


def test_los_enlaces_internos_de_docs_existen(cliente):
    slugs = {p["slug"] for p in dd.PAGINAS}
    rotos = []
    for pagina in dd.PAGINAS:
        html = cliente.get(f"/docs/{pagina['slug']}").get_data(as_text=True)
        for destino in set(re.findall(r'href="/docs/([a-z0-9\-]*)(?:#[^"]*)?"', html)):
            if destino and destino not in slugs and destino not in {"sdk"}:
                rotos.append((pagina["slug"], destino))
    assert not rotos, rotos


def test_el_mapa_por_temas_de_hosting_esta_al_dia():
    """Cada sección nueva de HOSTING.md debe entrar en el mapa por temas (python scripts/indice_hosting.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("indice_hosting", RAIZ / "scripts" / "indice_hosting.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.main(comprobar=True) == 0


def test_el_css_del_backoffice_no_redefine_una_clase_para_otro_componente():
    """Dos componentes distintos con la misma clase se pisan (así se descuadró la barra superior: `.barra` era también
    la columna del gráfico). Un selector simple solo puede definirse una vez salvo los pocos casos revisados."""
    import collections
    css = (RAIZ / "backoffice" / "static" / "backoffice.css").read_text(encoding="utf-8")
    cuenta = collections.Counter(re.findall(r"(?m)^(\.[a-z0-9_-]+)\s*\{", css))
    repetidos = {k for k, v in cuenta.items() if v > 1}
    revisados = {".admin-chip", ".en-linea", ".casilla"}   # se complementan (mismo componente); no cambiar el significado
    assert repetidos <= revisados, repetidos - revisados
