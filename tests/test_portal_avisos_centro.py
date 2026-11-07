"""Centro de avisos del portal (Q4): todo lo que se avisa queda anotado, con lo nuevo por persona."""
from datetime import datetime, timedelta

from app import db, portal_conversaciones as pc, portal_novedades as pn, portal_peticiones as pp
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def test_anotar_listar_y_marcar_leidas_por_persona():
    t, u, c = _despacho("Avisos persona")
    ficha = _ficha(c)
    pn.anotar(ficha, "Tu gestoría te ha escrito", "Mira el mensaje", "/portal/mensajes", ahora=datetime(2026, 11, 1, 10, 0))
    pn.anotar(ficha, "Te piden un documento", "", "/portal/peticiones/3", ahora=datetime(2026, 11, 2, 10, 0))
    pn.anotar(ficha, "   ", "vacío: no se anota")
    lista = pn.listar(ficha, "titular@ejemplo.com")
    assert [a["titulo"] for a in lista] == ["Te piden un documento", "Tu gestoría te ha escrito"] and all(a["nuevo"] for a in lista)
    assert pn.sin_leer(ficha, "titular@ejemplo.com") == 2 and pn.sin_leer(ficha, "administrativa@ejemplo.com") == 2
    pn.marcar_leidas(ficha, "Titular@Ejemplo.com", ahora=datetime(2026, 11, 3, 9, 0))
    assert pn.sin_leer(ficha, "titular@ejemplo.com") == 0 and pn.sin_leer(ficha, "administrativa@ejemplo.com") == 2          # la otra persona sigue con lo suyo
    pn.anotar(ficha, "Nuevo de después", "", "", ahora=datetime(2026, 11, 4, 9, 0))
    assert pn.sin_leer(ficha, "titular@ejemplo.com") == 1 and pn.listar(ficha, "titular@ejemplo.com")[0]["nuevo"]


def test_las_urls_ajenas_al_portal_no_se_guardan_y_lo_viejo_se_borra():
    t, u, c = _despacho("Avisos urls")
    ficha = _ficha(c)
    pn.anotar(ficha, "Con enlace raro", "", "https://evil.com/x", ahora=datetime(2026, 11, 1))
    assert pn.listar(ficha, "x@y.z")[0]["url"] == ""
    pn.anotar(ficha, "Antiguo", ahora=datetime(2026, 1, 1))
    pn.anotar(ficha, "Reciente", ahora=datetime(2026, 11, 1))
    assert [a["titulo"] for a in pn.listar(ficha, "x@y.z")] == ["Reciente", "Con enlace raro"]               # pasados 120 días, se borra


def test_los_avisos_de_otro_cliente_no_se_mezclan():
    t, u, c = _despacho("Avisos uno")
    t2, u2, c2 = _despacho("Avisos dos", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    pn.anotar(_ficha(c), "Solo del primero")
    assert pn.listar(_ficha(c2), "otro@ejemplo.com") == []


def test_lo_que_se_avisa_por_el_portal_queda_en_el_centro(cliente, correo):
    t, u, c = _despacho("Avisos flujo")
    uid = iniciar_sesion_de_prueba(cliente, "eq-avisos@ejemplo.com", "contrasena123")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    cliente.post(f"/fiscal/clientes/{c}/peticiones", data={"titulo": "Libro de facturas", "avisar": "1"})
    cliente.post(f"/fiscal/clientes/{c}/conversaciones", data={"asunto": "Una duda", "texto": "¿Nos lo mandas?", "avisar": "1"})
    titulos = [a["titulo"] for a in pn.listar(_ficha(c), "titular@ejemplo.com")]
    assert "Tu gestoría te pide un documento" in titulos and "Tu gestoría te ha escrito" in titulos


def test_la_pagina_enseña_lo_nuevo_marcado_y_despues_ya_no_lo_esta(cliente, correo):
    t, u, c = _despacho("Avisos pagina")
    pn.anotar(_ficha(c), "Aviso de prueba", "Con su resumen", "/portal/peticiones")
    _entrar(cliente, c, "titular@ejemplo.com")
    inicio = _html(cliente, "/portal/")
    assert "portal-nav-insignia" in inicio and "Avisos nuevos" in inicio
    html = _html(cliente, "/portal/avisos")
    assert "Aviso de prueba" in html and "Con su resumen" in html and 'href="/portal/peticiones"' in html and "Nuevo" in html and "Cambiar mis avisos" in html
    assert "Avisos nuevos" not in _html(cliente, "/portal/")                                                      # abrir el centro marca lo visto como leído
    assert "Nuevo</span>" not in _html(cliente, "/portal/avisos")


def test_sin_avisos_dice_que_todavia_no_hay(cliente, correo):
    t, u, c = _despacho("Avisos vacio")
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Todavía no hay avisos" in _html(cliente, "/portal/avisos")
