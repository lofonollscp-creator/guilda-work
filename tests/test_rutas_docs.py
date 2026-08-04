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
    assert nombres == ["EMPEZAR", "INTEGRACIÓN", "CONFIGURACIÓN", "DESPLIEGUE"]
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


# --- Buscador (Ctrl/Cmd+K) --------------------------------------------------

def test_indice_busqueda_incluye_una_entrada_por_pagina():
    indice = dd.indice_busqueda()
    titulos = {e["titulo"] for e in indice}
    for pagina in dd.PAGINAS:
        assert pagina["titulo"] in titulos


def test_indice_busqueda_incluye_secciones_con_href_con_ancla():
    indice = dd.indice_busqueda()
    entradas_asistente_ia = [e for e in indice if e["contexto"] == "Asistente de IA (MCP)"]
    assert entradas_asistente_ia
    assert all("#" in e["href"] for e in entradas_asistente_ia)
    titulos_secciones = {e["titulo"] for e in entradas_asistente_ia}
    assert "Conector remoto — ChatGPT" in titulos_secciones


def test_indice_busqueda_no_deja_etiquetas_html_en_el_texto():
    indice = dd.indice_busqueda()
    for entrada in indice:
        assert "<" not in entrada["texto"]
        assert ">" not in entrada["texto"]


def test_pagina_incluye_el_indice_de_busqueda_embebido(cliente):
    resp = cliente.get("/docs/")
    html = resp.get_data(as_text=True)
    assert 'id="docs-indice-busqueda"' in html
    assert "Autenticación" in html


# --- Catálogo completo de tools (MCP) — no se puede desincronizar de mcp_tools.py

def test_catalogo_tools_mcp_incluye_todas_las_tools_reales(cliente):
    import mcp_tools as mt

    resp = cliente.get("/docs/catalogo-tools-mcp")
    html = resp.get_data(as_text=True)
    faltan = [t.__name__ for t in mt.TOOLS if f">{t.__name__}(" not in html]
    assert faltan == [], f"tools ausentes del catálogo: {faltan}"


def test_catalogo_tools_mcp_muestra_firmas_con_tipos(cliente):
    resp = cliente.get("/docs/catalogo-tools-mcp")
    html = resp.get_data(as_text=True)
    assert "facturas_crear_factura(tenant: str, cliente_codigo: str, lineas: list[dict])" in html


def test_modelos_de_datos_documenta_los_campos_clave(cliente):
    resp = cliente.get("/docs/modelos-de-datos")
    html = resp.get_data(as_text=True)
    for campo in ("duracion_segundos", "outlook_entry_id", "papelera_en", "message_id"):
        assert campo in html


def test_asistente_ia_advierte_que_tareas_duracion_no_tiene_tools_mcp(cliente):
    resp = cliente.get("/docs/asistente-ia")
    html = resp.get_data(as_text=True)
    assert "NO tienen tools de MCP" in html


def test_referencia_api_no_tiene_placeholders_de_ruta_ambiguos(cliente):
    resp = cliente.get("/docs/referencia-api")
    html = resp.get_data(as_text=True)
    assert "{id}/adjuntos/{id}" not in html
    assert "{mensaje_id}/adjuntos/{adjunto_id}" in html


def test_referencia_api_documenta_que_notas_y_tareas_no_tienen_get_de_listado(cliente):
    resp = cliente.get("/docs/referencia-api")
    html = resp.get_data(as_text=True)
    assert "no tienen un endpoint" in html


# --- Webhooks (/docs/webhooks) ----------------------------------------------

def test_webhooks_documenta_los_cuatro_eventos_reales(cliente):
    resp = cliente.get("/docs/webhooks")
    html = resp.get_data(as_text=True)
    for evento in ("tarea.finalizada", "nota.creada", "cita.reservada", "correo.mensaje_nuevo"):
        assert evento in html


def test_webhooks_documenta_la_cabecera_de_firma(cliente):
    resp = cliente.get("/docs/webhooks")
    html = resp.get_data(as_text=True)
    assert "X-Guilda-Signature" in html


def test_referencia_api_enlaza_al_explorador_y_a_webhooks(cliente):
    resp = cliente.get("/docs/referencia-api")
    html = resp.get_data(as_text=True)
    assert "/docs/explorador-api" in html


def test_asistente_ia_documenta_rag_y_enlaza_webhooks(cliente):
    resp = cliente.get("/docs/asistente-ia")
    html = resp.get_data(as_text=True)
    assert "buscar_semantico" in html
    assert "/docs/webhooks" in html


# --- Explorador de API interactivo (/docs/explorador-api) -------------------

def test_explorador_api_renderiza_y_carga_su_script(cliente):
    resp = cliente.get("/docs/explorador-api")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "/static/api_explorer.js" in html


def test_explorador_api_esta_en_el_indice_como_pagina_interactiva():
    datos = dd.obtener_pagina("explorador-api")
    assert datos is not None
    assert datos.get("interactivo") is True


# --- Navegación Anterior/Siguiente -------------------------------------------

def test_pagina_intermedia_incluye_nav_anterior_y_siguiente(cliente):
    resp = cliente.get("/docs/webhooks")
    html = resp.get_data(as_text=True)
    assert "docs-footer-nav-adyacente" in html
