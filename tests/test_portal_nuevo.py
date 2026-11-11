"""El portal con la navegación nueva (U1-U12): 5 secciones, pestañas, marca del despacho, idioma y menú de perfil; apagado, el portal es el de siempre."""
import re

import pytest

from app import db, marca, portal_diseno, portal_peticiones
from tests.test_portal_personas_avisos import _despacho, _entrar, _html

SECCIONES = ("inicio", "facturas", "documentos", "mensajes", "impuestos")
PAGINAS = {"/portal/": "inicio", "/portal/facturas": "facturas", "/portal/justificantes": "facturas", "/portal/documentos": "documentos", "/portal/carpeta": "documentos", "/portal/peticiones": "documentos",
           "/portal/mensajes": "mensajes", "/portal/avisos": "mensajes", "/portal/gestiones": "mensajes", "/portal/impuestos": "impuestos", "/portal/firmas": "impuestos"}


def _con_portal(cliente, nuevo=True, nombre="Gestoria N"):
    t, u, c = _despacho(nombre, cliente_email="dueno@ejemplo.com", cliente_nombre="Sociedad Uno SL")
    if not nuevo:
        portal_diseno.fijar(t, False)                                      # está encendido por defecto: apagarlo es una decisión del despacho
    _entrar(cliente, c, "dueno@ejemplo.com")
    return t, u, c


def test_apagado_el_portal_es_el_de_siempre(cliente):
    _con_portal(cliente, nuevo=False)
    html = _html(cliente, "/portal/")
    assert 'class="portal-nav"' in html and "pv-cabecera" not in html and "portal_v2.css" not in html and "portal-v2" not in html


def test_encendido_cada_pantalla_cae_en_su_seccion_y_hay_una_sola_marca_activa(cliente):
    _con_portal(cliente)
    for ruta, seccion in PAGINAS.items():
        html = _html(cliente, ruta)
        nav = re.search(r'<nav class="pv-nav".*?</nav>', html, re.S).group(0)
        activas = re.findall(r'<a href="[^"]*"[^>]*aria-current="page"', nav)
        assert len(activas) == 1, (ruta, activas)
        assert f'data-atajo="{ {"inicio": "i", "facturas": "f", "documentos": "d", "mensajes": "m", "impuestos": "t"}[seccion] }" aria-current="page"' in nav, ruta
        assert len(re.findall(r'<nav class="pv-tabs"', html)) == 1 and 'class="portal-nav"' not in html and html.count("<h1>") == 1, ruta


def test_las_pestanas_son_de_la_seccion_y_marcan_la_pantalla_actual(cliente):
    _con_portal(cliente)
    html = _html(cliente, "/portal/avisos")
    pest = re.search(r'<nav class="pv-pestanas".*?</nav>', html, re.S).group(0)
    assert "Conversaciones" in pest and "Pedir algo" in pest and "Mis facturas" not in pest
    assert re.search(r'<a href="/portal/avisos"[^>]*aria-current="page"', pest)
    assert 'class="pv-pestanas"' not in _html(cliente, "/portal/")                              # Inicio no tiene pestañas
    assert "Banco y tiques" in _html(cliente, "/portal/facturas")


def test_el_menu_de_perfil_trae_cuenta_idioma_y_salir(cliente):
    _con_portal(cliente)
    html = _html(cliente, "/portal/")
    perfil = re.search(r'<details class="pv-perfil pv-desplegable">.*?</details>', html, re.S).group(0)
    for esperado in ('href="/portal/cuenta"', 'href="/portal/glosario"', "Català", "English", "Français", "/portal/salir"):
        assert esperado in perfil, esperado


def test_el_idioma_se_elige_con_una_cookie_y_vuelve_a_la_misma_pantalla(cliente):
    _con_portal(cliente)
    r = cliente.post("/portal/idioma/ca", headers={"Referer": "http://127.0.0.1:8000/portal/mensajes"})
    assert r.status_code == 303 and r.headers["Location"].endswith("/portal/mensajes") and "idioma_portal=ca" in r.headers.get("Set-Cookie", "")
    assert 'lang="ca"' in _html(cliente, "/portal/")
    r = cliente.post("/portal/idioma/zz", headers={"Referer": "https://externo.example/portal/x"})
    assert r.status_code == 303 and "/portal/" in r.headers["Location"] and "externo" not in r.headers["Location"] and "idioma_portal" not in r.headers.get("Set-Cookie", "")


def test_la_marca_del_despacho_pone_nombre_color_y_logo(cliente):
    t, u, c = _con_portal(cliente)
    assert "Mi gestoría" in _html(cliente, "/portal/") and cliente.get("/portal/marca/logo").status_code == 404
    marca.guardar(t, nombre="Asesores Lopez", color="#0a7d5a")
    html = _html(cliente, "/portal/")
    assert "Asesores Lopez" in html and "marca/estilo.css" in html
    css = cliente.get("/portal/marca/estilo.css")
    assert css.status_code == 200 and "--pv-accent: #0a7d5a" in css.get_data(as_text=True) and "--pv-on-accent" in css.get_data(as_text=True)
    texto = css.get_data(as_text=True)
    assert "--primary: #0a7d5a" in texto and "--portal-accent:" in texto                       # los botones y enlaces de siempre toman el color del despacho
    assert portal_diseno.css_de_marca("") == "/* sin marca */\n"


def test_el_selector_de_empresas_va_dentro_del_menu_de_perfil(cliente):
    from app.db_fiscal import crear_cliente_fiscal
    t, u, c = _con_portal(cliente)
    crear_cliente_fiscal(t, "Sociedad Dos SL", nif="B87654321", email="dueno@ejemplo.com")
    html = _html(cliente, "/portal/")
    assert "Sociedad Dos SL" in re.search(r'<details class="pv-perfil pv-desplegable">.*?</details>', html, re.S).group(0)


def test_la_portada_pliega_lo_hecho_y_ofrece_subir_una_factura_si_esta_al_dia(cliente):
    _con_portal(cliente)
    html = _html(cliente, "/portal/")
    assert "pv-accion-principal" in html and "Subir una factura" in html


def test_el_interruptor_se_guarda_y_los_grupos_estan_completos():
    t = db.crear_tenant("Interruptor")
    assert portal_diseno.activo(t) is True                                   # por defecto, encendido (también sin configuración guardada)
    portal_diseno.fijar(t, False); assert portal_diseno.activo(t) is False
    portal_diseno.fijar(t, True); assert portal_diseno.activo(t) is True
    assert set(portal_diseno._GRUPO_DE.values()) == set(SECCIONES)
    assert portal_diseno.grupo_de("portal_cliente.cuenta", "cuenta") is None and portal_diseno.grupo_de("portal_cliente.carpeta") == "documentos"


@pytest.mark.parametrize("texto,fondo,minimo", [
    ("#4f6b00", "#ffffff", 4.5),          # acento como texto sobre la tarjeta (claro)
    ("#4f6b00", "#eef5d6", 4.5),          # acento sobre su fondo suave (pestaña/enlace activo)
    ("#ffffff", "#4f6b00", 4.5),          # texto sobre el relleno (avatar, botón Subir)
    ("#c7e85c", "#1e1b14", 4.5),          # tema oscuro: acento sobre la tarjeta
    ("#c7e85c", "#2a2f12", 4.5),          # tema oscuro: acento sobre su fondo suave
    ("#1a1f00", "#c7e85c", 4.5),          # tema oscuro: texto sobre el relleno
])
def test_los_colores_por_defecto_del_portal_nuevo_cumplen_el_contraste(texto, fondo, minimo):
    assert marca._contraste(marca._luminancia(texto), marca._luminancia(fondo)) >= minimo


def test_los_colores_por_defecto_estan_en_la_hoja_de_estilos():
    css = open("app/static/portal_v2.css", encoding="utf-8").read()
    for token in ("--pv-accent: #4f6b00", "--pv-on-accent: #ffffff", "--pv-accent-soft: #eef5d6", "--pv-accent: #c7e85c", "--pv-accent-soft: #2a2f12"):
        assert token in css


def test_ninguna_pantalla_del_portal_nuevo_repite_ids(cliente):
    _con_portal(cliente)
    for ruta in PAGINAS:
        ids = re.findall(r'\sid="([^"]+)"', _html(cliente, ruta))
        repetidos = {i for i in ids if ids.count(i) > 1}
        assert not repetidos, (ruta, repetidos)


def test_las_pestanas_condicionales_solo_salen_cuando_el_cliente_las_tiene(cliente):
    from app import verticales
    t, u, c = _con_portal(cliente)
    assert "Mis ventas" not in _html(cliente, "/portal/facturas") and "Mis trabajadores" not in _html(cliente, "/portal/impuestos")
    assert "Honorarios" not in _html(cliente, "/portal/impuestos") and "Propuestas" not in _html(cliente, "/portal/mensajes") and "Preguntar" not in _html(cliente, "/portal/mensajes")
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET portal_honorarios = 1 WHERE id = ?", (c,)); conn.commit(); conn.close()
    assert "/portal/honorarios" in _html(cliente, "/portal/impuestos")


def test_la_ayuda_de_cada_pantalla_sigue_en_el_menu_de_perfil(cliente):
    _con_portal(cliente)
    html = _html(cliente, "/portal/")
    perfil = re.search(r'<details class="pv-perfil pv-desplegable">.*?</details>', html, re.S).group(0)
    assert "portal-de-cliente/recorrer-el-portal/" in perfil and "/portal/carpeta" not in perfil
    assert "portal-de-cliente/mi-carpeta/" in re.search(r'<details class="pv-perfil pv-desplegable">.*?</details>', _html(cliente, "/portal/carpeta"), re.S).group(0)


def test_cada_modelo_enseña_su_linea_de_tiempo_y_lo_que_falta_de_la_persona(cliente):
    t, u, c = _con_portal(cliente)
    v1 = db.crear_vencimiento_fiscal(t, c, "303", "2026-3T", "2026-10-20", usuario_id=u)
    v2 = db.crear_vencimiento_fiscal(t, c, "111", "2026-3T", "2026-10-20", usuario_id=u)
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET estado = 'presentado' WHERE id = ?", (v1,))
    conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'El extracto del banco' WHERE id = ?", (v2,))
    conn.commit(); conn.close()
    html = _html(cliente, "/portal/impuestos")
    assert html.count('aria-label="Cómo va este modelo"') == 2
    assert "Para seguir necesitamos de ti: El extracto del banco" in html and html.count("Para seguir necesitamos de ti") == 1      # el presentado no pide nada
    from app import portal_linea_tiempo as lt
    assert [p["estado"] for p in lt.de_vencimiento({"estado": "presentado"})] == ["hecha", "hecha", "hecha"]
    assert [p["estado"] for p in lt.de_vencimiento({"estado": "pendiente"})] == ["hecha", "actual", "pendiente"]
    assert [p["estado"] for p in lt.de_vencimiento({"estado": "fuera_plazo"})] == ["hecha", "hecha", "actual"]


def test_la_campana_de_novedades_enseña_lo_ultimo_con_lo_nuevo_marcado(cliente):
    from app import portal_novedades
    t, u, c = _con_portal(cliente)
    ficha = db.obtener_cliente_fiscal_por_id(c)
    html = _html(cliente, "/portal/")
    assert "pv-campana" in html and "No hay novedades por ahora." in html and "pv-campana-n" not in html
    for i in range(7):
        portal_novedades.anotar(ficha, f"Novedad número {i}", "Detalle de la novedad", "/portal/facturas")
    html = _html(cliente, "/portal/impuestos")
    campana = html.split('class="pv-campana', 1)[1].split("</details>", 1)[0]
    assert campana.count('class="pv-novedad nuevo"') == 5 and "Novedad número 6" in campana and "Novedad número 1<" not in campana        # las 5 últimas, la más reciente primero
    assert 'aria-label="Novedades (7)"' in html and 'href="/portal/facturas"' in campana
    assert "Ver todos los avisos" in campana and "Cómo quiero que me avisen" in campana
    _html(cliente, "/portal/avisos")                                                                                                        # abrir el centro de avisos los marca como leídos
    assert 'class="pv-novedad nuevo"' not in _html(cliente, "/portal/").split('class="pv-campana', 1)[1].split("</details>", 1)[0]


def test_la_app_instalada_lleva_el_nombre_y_el_color_del_despacho(cliente):
    t, u, c = _con_portal(cliente)
    antes = cliente.get("/portal/manifest.webmanifest").get_json()
    assert antes["name"] == "Guilda Work" and antes["short_name"] == "Mi gestoría"                   # sin marca, como siempre
    marca.guardar(t, nombre="Asesores Fernández-Villanueva", color="#0a7d5a")
    despues = cliente.get("/portal/manifest.webmanifest").get_json()
    assert despues["name"] == "Asesores Fernández-Villanueva" and despues["short_name"] == "Asesores Fer" and despues["theme_color"] == "#0a7d5a"
    assert [i["sizes"] for i in despues["icons"]][:2] == ["192x192", "512x512"]                        # los iconos que exige la instalación siguen


def test_la_pregunta_sobre_la_navegacion_sale_una_vez_y_no_avisa_al_equipo(cliente):
    from app import portal_valoraciones
    t, u, c = _con_portal(cliente)
    assert "¿Te resulta fácil encontrar lo que buscas en el portal?" in _html(cliente, "/portal/")
    r = cliente.post("/portal/valorar", data={"tipo": "navegacion", "referencia": "v2", "puntos": "2"}, follow_redirects=True)
    assert "¡Gracias por contárnoslo!" in r.get_data(as_text=True)
    assert "¿Te resulta fácil encontrar lo que buscas" not in _html(cliente, "/portal/")                 # una sola vez por persona
    assert portal_valoraciones.resumen(t)["ultimas"][0]["tipo"] == "navegacion"                          # la ve la dirección en la actividad del portal
    assert "Ya has valorado" in cliente.post("/portal/valorar", data={"tipo": "navegacion", "referencia": "v2", "puntos": "5"}, follow_redirects=True).get_data(as_text=True)
    assert "No se puede valorar eso" in cliente.post("/portal/valorar", data={"tipo": "navegacion", "referencia": "otra", "puntos": "5"}, follow_redirects=True).get_data(as_text=True)


def test_con_el_portal_apagado_no_se_pregunta_por_la_navegacion_nueva(cliente):
    _con_portal(cliente, nuevo=False)
    assert "¿Te resulta fácil encontrar lo que buscas" not in _html(cliente, "/portal/")
