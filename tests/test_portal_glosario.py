"""Glosario del portal (B1) y ayuda contextual en cada pantalla (B4)."""
from datetime import date, timedelta

from app import db, portal_glosario as pg
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def test_por_modelo_entiende_las_formas_habituales_de_nombrarlo():
    for texto in ("303", "Modelo 303", "303 1T", "  303 "):
        assert pg.por_modelo(texto)["modelo"] == "303"
    assert pg.por_modelo("037")["modelo"] == "036" or pg.por_modelo("037")["nombre"] == pg.por_modelo("036")["nombre"]
    assert pg.por_modelo("999") is None and pg.por_modelo(None) is None and pg.por_modelo("") is None


def test_todo_modelo_tiene_sus_tres_textos_y_la_busqueda_ignora_tildes_y_mayusculas():
    for clave in pg.MODELOS:
        m = pg.por_modelo(clave)
        assert all(str(m[c]).strip() for c in ("nombre", "que_es", "que_hace_falta", "cuando")), clave
    assert [m["modelo"] for m in pg.todo("RETENCIÓN")["modelos"]] and any(c["clave"] == "retencion" for c in pg.todo("retencion")["conceptos"])
    assert pg.todo("zzzzqq") == {"modelos": [], "conceptos": []}


def test_la_pagina_del_glosario_lista_y_busca_y_ofrece_preguntar_si_no_hay_nada(cliente, correo):
    t, u, c = _despacho("Glosario web")
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/glosario")
    assert "Modelo 303" in html and "IVA repercutido" in html and 'id="modelo-130"' in html
    assert "Modelo 130" not in _html(cliente, "/portal/glosario?q=retenciones") and "Modelo 111" in _html(cliente, "/portal/glosario?q=retenciones")
    vacio = _html(cliente, "/portal/glosario?q=zzzzqq")
    assert "No hay nada con esa búsqueda" in vacio and "/portal/conversaciones/nueva" in vacio


def test_cada_vencimiento_lleva_su_que_es_en_impuestos(cliente, correo):
    t, u, c = _despacho("Glosario impuestos")
    hoy = date.today()
    db.crear_vencimiento_fiscal(t, c, "303", f"{hoy.year}-T1", (hoy + timedelta(days=5)).isoformat(), usuario_id=u)
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/impuestos")
    assert "¿Qué es el modelo 303?" in html and "IVA que has cobrado" in html


def test_cada_pantalla_del_portal_enlaza_su_guia_de_ayuda(cliente, correo, portal_antiguo):
    t, u, c = _despacho("Glosario ayuda")
    _entrar(cliente, c, "titular@ejemplo.com")
    inicio = _html(cliente, "/portal/")
    assert 'class="portal-nav-ayuda"' in inicio and "portal-de-cliente/recorrer-el-portal/" in inicio
    assert "portal-de-cliente/mi-carpeta/" in _html(cliente, "/portal/carpeta")
    assert "portal-de-cliente/avisos-del-portal/" in _html(cliente, "/portal/avisos")


def test_no_puedo_entrar_es_publica_ofrece_los_cuatro_casos_y_se_enlaza_desde_la_entrada(cliente):
    html = cliente.get("/portal/no-puedo-entrar").get_data(as_text=True)
    for caso in ("No me llega el correo", "He cambiado de correo", "He perdido o cambiado de móvil", "aplicación de códigos"):
        assert caso in html
    assert "/portal/no-puedo-entrar" in cliente.get("/portal/entrar").get_data(as_text=True)
    cambio = cliente.get("/portal/solicitar-acceso?motivo=cambio_correo").get_data(as_text=True)
    assert "Si has cambiado de correo" in cambio and "Mi correo anterior era" in cambio
    assert "Si todavía no tienes acceso" in cliente.get("/portal/solicitar-acceso").get_data(as_text=True)
