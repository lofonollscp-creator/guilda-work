"""Las herramientas que están a la vez en el MCP y en el asistente de IA no pueden desfasarse: mismos parámetros, mismos obligatorios y todas clasificadas como lectura o escritura."""
import inspect

import mcp_tools
from app import herramientas_grupos as hg, ia_herramientas as ih


def _comunes():
    en_mcp = {t.__name__: t for t in mcp_tools.TOOLS}
    for t in ih.HERRAMIENTAS:
        f = t["function"]
        if f["name"] in en_mcp:
            yield f["name"], en_mcp[f["name"]], f["parameters"]


def test_cada_parametro_del_asistente_existe_en_la_funcion_del_mcp():
    fallos = []
    for nombre, fn, esquema in _comunes():
        firma = inspect.signature(fn).parameters
        sobran = set(esquema.get("properties", {})) - set(firma)
        if sobran:
            fallos.append(f"{nombre}: el asistente ofrece {sorted(sobran)} y la función no los acepta")
        sin_valor = {n for n, p in firma.items() if p.default is inspect.Parameter.empty}
        faltan = sin_valor - set(esquema.get("required", []))
        if faltan:
            fallos.append(f"{nombre}: la función exige {sorted(faltan)} y el asistente no los marca como obligatorios")
    assert not fallos, "\n".join(fallos)


def test_las_de_contabilidad_estan_clasificadas_y_agrupadas():
    en_modulo = {n for n, f in inspect.getmembers(mcp_tools, inspect.isfunction) if n.startswith("contabilidad_")}
    assert en_modulo, "no se encontró ninguna herramienta de contabilidad en el MCP"
    for n in sorted(en_modulo):
        assert hg.grupo_de(n) == "contabilidad", n
        assert (n in ih.LECTURA) != (n in ih.ESCRITURA), f"{n} debe ser de lectura o de escritura, no de las dos ni de ninguna"
        assert any(t["function"]["name"] == n for t in ih.HERRAMIENTAS), f"{n} no está en el asistente"
