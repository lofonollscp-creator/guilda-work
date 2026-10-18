"""Barra lateral lateral a medida (app/navegacion.py, app/rutas_menu.py) y ficha con una sola fila de pestañas."""
import json

import pytest

from app import db, navegacion, nucleo, verticales
from tests.conftest import iniciar_sesion_de_prueba


def _perfil(texto):
    class P(dict):
        pass
    return P(menu_prefs=texto)


# --- Lógica ------------------------------------------------------------------------------------------------------------------------------------------

def test_leer_tolera_vacios_basura_y_claves_ajenas():
    vacio = {"ocultos": [], "fijados": []}
    assert navegacion.leer(None) == vacio and navegacion.leer(_perfil(None)) == vacio and navegacion.leer(_perfil("")) == vacio
    assert navegacion.leer(_perfil("{no es json")) == vacio and navegacion.leer(_perfil("[1, 2]")) == vacio
    assert navegacion.leer(_perfil(json.dumps({"ocultos": ["notas", "inexistente", "tareas"], "fijados": ["clientes", "inexistente", "clientes"]}))) == {"ocultos": ["notas"], "fijados": ["clientes"]}, \
        "«tareas» no es ocultable y las claves repetidas o desconocidas se descartan"


def test_guardar_valida_y_respeta_el_tope_de_fijados(usuario_id):
    r = navegacion.guardar(usuario_id, ["notas", "tareas", "x"], ["hoy", "tareas", "correo", "clientes", "expedientes", "plazos", "horas", "agenda"])
    assert r["ocultos"] == ["notas"] and len(r["fijados"]) == navegacion.MAX_FIJADOS and r["fijados"][0] == "hoy"
    assert navegacion.leer(db.obtener_perfil_usuario(usuario_id)) == r


def test_lo_fijado_no_puede_estar_oculto(usuario_id):
    r = navegacion.guardar(usuario_id, ["notas", "papelera"], ["notas"])
    assert r == {"ocultos": ["papelera"], "fijados": ["notas"]}


def test_guardar_vacio_borra_la_preferencia(usuario_id):
    navegacion.guardar(usuario_id, ["notas"], [])
    navegacion.guardar(usuario_id, [], [])
    assert db.obtener_perfil_usuario(usuario_id)["menu_prefs"] is None


def test_los_accesos_respetan_si_hay_despacho_y_gestoria(cliente):
    m = navegacion.Menu({"ocultos": [], "fijados": ["hoy", "clientes", "panel_fiscal"]})
    with cliente.application.test_request_context():
        assert [a["clave"] for a in m.accesos(False, False)] == ["hoy"]
        assert [a["clave"] for a in m.accesos(True, False)] == ["hoy", "clientes"]
        assert [a["clave"] for a in m.accesos(True, True)] == ["hoy", "clientes", "panel_fiscal"]
        assert m.visible("notas") and not navegacion.Menu({"ocultos": ["notas"], "fijados": []}).visible("notas")


def test_cada_elemento_del_catalogo_apunta_a_una_ruta_que_existe(cliente):
    rutas = {r.endpoint for r in cliente.application.url_map.iter_rules()}
    assert [k for k, v in navegacion.CATALOGO.items() if v[1] not in rutas] == []


# --- Pantallas -----------------------------------------------------------------------------------------------------------------------------------

def _web(cliente, email="menu@ejemplo.com"):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    return uid, t


def test_por_defecto_se_ve_todo_y_no_hay_accesos_directos(cliente):
    _web(cliente)
    html = cliente.get("/").get_data(as_text=True)
    assert 'title="Notas"' in html and 'title="Papelera"' in html and "Accesos directos" not in html


def test_ocultar_y_fijar_cambia_el_menu_y_solo_el_de_esa_persona(cliente):
    uid, t = _web(cliente, "menu1@ejemplo.com")
    assert "Barra lateral y accesos directos" in cliente.get("/ajustes/menu/").get_data(as_text=True)
    r = cliente.post("/ajustes/menu/", data={"mostrar": [k for k in navegacion.OCULTABLES if k not in ("notas", "papelera")], "fijar": ["clientes", "hoy"]})
    assert r.status_code == 302
    html = cliente.get("/").get_data(as_text=True)
    assert 'title="Notas"' not in html and 'title="Papelera"' not in html and 'title="Tiquets"' in html
    assert "Accesos directos" in html and html.index("Accesos directos") < html.index("Trabajo diario")
    # otra persona del despacho sigue con el menú de serie
    from app.main import app as flask_app
    with flask_app.test_client() as otro:
        u2 = iniciar_sesion_de_prueba(otro, "menu2@ejemplo.com", "contrasena123"); db.asignar_tenant(u2, t)
        h2 = otro.get("/").get_data(as_text=True)
        assert 'title="Notas"' in h2 and "Accesos directos" not in h2
    # lo oculto sigue accesible por su dirección
    assert cliente.get("/notas").status_code in (200, 302)


def test_no_se_puede_ocultar_lo_esencial_ni_inventar_claves(cliente):
    uid, _t = _web(cliente, "menu3@ejemplo.com")
    cliente.post("/ajustes/menu/", data={"mostrar": [], "fijar": ["inexistente"]})
    prefs = navegacion.leer(db.obtener_perfil_usuario(uid))
    assert set(prefs["ocultos"]) == set(navegacion.OCULTABLES) and prefs["fijados"] == []
    html = cliente.get("/").get_data(as_text=True)
    assert 'title="Tareas"' in html and 'title="Hoy"' in html and 'title="Correo' in html


def test_restablecer_deja_el_menu_de_serie(cliente):
    uid, _t = _web(cliente, "menu4@ejemplo.com")
    cliente.post("/ajustes/menu/", data={"mostrar": [], "fijar": ["hoy"]})
    cliente.post("/ajustes/menu/", data={"restablecer": "1"})
    assert navegacion.leer(db.obtener_perfil_usuario(uid)) == {"ocultos": [], "fijados": []}
    assert 'title="Notas"' in cliente.get("/").get_data(as_text=True)


def test_un_acceso_fijado_de_gestoria_no_sale_si_el_despacho_no_la_lleva(cliente):
    uid, t = _web(cliente, "menu5@ejemplo.com")
    verticales.fijar_activo(t, "gestoria", True)
    cliente.post("/ajustes/menu/", data={"mostrar": list(navegacion.OCULTABLES), "fijar": ["panel_fiscal"]})
    assert "Panel fiscal" in cliente.get("/").get_data(as_text=True)
    verticales.fijar_activo(t, "gestoria", False)
    assert navegacion.leer(db.obtener_perfil_usuario(uid))["fijados"] == ["panel_fiscal"], "se conserva la preferencia"
    assert 'Accesos directos' not in cliente.get("/").get_data(as_text=True)


def test_ajustes_enlaza_a_la_pantalla_del_menu(cliente):
    _web(cliente, "menu6@ejemplo.com")
    assert 'href="/ajustes/menu/"' in cliente.get("/ajustes").get_data(as_text=True)


def test_hay_que_iniciar_sesion_para_cambiar_el_menu(cliente):
    assert cliente.get("/ajustes/menu/").status_code in (302, 401)
    assert cliente.post("/ajustes/menu/", data={}).status_code in (302, 401, 400)


def test_las_paginas_sin_sesion_siguen_funcionando(cliente):
    assert cliente.get("/login", follow_redirects=True).status_code == 200


def test_la_ficha_del_cliente_tiene_una_sola_fila_de_pestanas(cliente):
    uid, t = _web(cliente, "menu7@ejemplo.com")
    c = nucleo.crear_cliente(t, "Cliente Ficha")
    html = cliente.get(f"/clientes/{c}").get_data(as_text=True)
    assert html.count('class="tareas-subnav"') == 1 and 'class="ficha-volver"' in html and 'aria-label="Secciones de la ficha"' in html
    lista = cliente.get("/clientes/").get_data(as_text=True)
    assert lista.count('class="tareas-subnav"') == 1 and 'class="ficha-volver"' not in lista, "la lista conserva su navegación del núcleo"


def test_la_ficha_del_expediente_vuelve_a_la_lista(cliente):
    uid, t = _web(cliente, "menu8@ejemplo.com")
    c = nucleo.crear_cliente(t, "Cliente Exp")
    x = nucleo.crear_expediente(t, uid, c, "Expediente de prueba")
    html = cliente.get(f"/expedientes/{x}").get_data(as_text=True)
    assert 'class="ficha-volver"' in html and 'class="tareas-subnav"' not in html
