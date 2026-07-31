"""Tests de app/rutas_docs.py (Guía para desarrolladores, /docs/*) —
sobre todo comprueba que cada página listada en app/documentacion_dev.py
renderiza sin reventar (sin login, a propósito: quien va a integrar un
sistema externo no tiene por qué tener ya una cuenta) y que las cifras
de tools mostradas cuadran con el catálogo real de mcp_tools.py."""
from app import documentacion_dev as dd


def test_portada_no_requiere_login(cliente):
    resp = cliente.get("/docs/")
    assert resp.status_code == 200
    assert "Guía para desarrolladores".encode() in resp.data


def test_todas_las_paginas_del_indice_renderizan_200(cliente):
    for pagina in dd.PAGINAS:
        resp = cliente.get(f"/docs/{pagina['slug']}")
        assert resp.status_code == 200, f"falló /docs/{pagina['slug']}"
        assert pagina["titulo"].encode() in resp.data


def test_slug_inexistente_da_404(cliente):
    resp = cliente.get("/docs/no-existe-esta-pagina")
    assert resp.status_code == 404


def test_barra_lateral_incluye_todas_las_paginas_con_grupo(cliente):
    resp = cliente.get("/docs/")
    html = resp.get_data(as_text=True)
    for pagina in dd.PAGINAS:
        if pagina["grupo"] is None:
            continue
        assert pagina["titulo"] in html


def test_pagina_con_tablas_incluye_sus_filas(cliente):
    resp = cliente.get("/docs/asistente-ia")
    html = resp.get_data(as_text=True)
    assert "mcp_server.py" in html
    assert "mcp_server_remoto.py" in html


def test_navegacion_agrupa_por_grupo_en_orden_de_aparicion():
    grupos = dd.navegacion()
    nombres = [g for g, _ in grupos]
    assert nombres == ["EMPEZAR", "INTEGRACIÓN", "DESPLIEGUE"]
    for _, paginas in grupos:
        assert all(p["grupo"] is not None for p in paginas)


def test_obtener_pagina_portada_usa_slug_vacio():
    assert dd.obtener_pagina("") is not None
    assert dd.obtener_pagina("no-existe") is None


def test_cifras_de_tools_cuadran_con_el_catalogo_real():
    import mcp_tools as mt

    assert dd.TOTAL_TOOLS == len(mt.TOOLS)
    assert dd.TOOLS_PROPIAS + dd.TOOLS_STACK_COMPARTIDO + dd.TOOLS_TENANT == dd.TOTAL_TOOLS
    # las 7 familias con tenant deben sumar exactamente TOOLS_TENANT
    suma_familias = sum(n for _, _, n in dd._familias_tenant())
    assert suma_familias == dd.TOOLS_TENANT


def test_link_a_documentacion_visible_en_login(cliente):
    resp = cliente.get("/login", follow_redirects=True)
    assert resp.status_code == 200
    assert b'/docs/' in resp.data
