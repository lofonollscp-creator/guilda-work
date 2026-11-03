"""Aviso de «Novedades» del centro de ayuda dentro de la app (app/ayuda_novedades.py): lee el feed Atom sin bloquear ni romper nada."""
import time

from app import ayuda_novedades as nov
from tests.conftest import iniciar_sesion_de_prueba

FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Ayuda</title>
<entry><title>Hoy</title><link href="https://help.guildawork.com/trabajo-diario/hoy/"/></entry>
<entry><title>Novedades: privacidad</title><link href="https://help.guildawork.com/novedades/privacidad/"/></entry>
<entry><title>Novedades de noviembre</title><link href="https://help.guildawork.com/novedades/noviembre/"/></entry>
</feed>"""


def test_toma_la_entrada_mas_reciente_de_novedades():
    assert nov.leer_novedad(FEED) == {"id": "https://help.guildawork.com/novedades/privacidad/", "titulo": "Novedades: privacidad", "url": "https://help.guildawork.com/novedades/privacidad/"}


def test_un_feed_roto_o_sin_novedades_no_da_aviso():
    assert nov.leer_novedad(b"esto no es xml") is None
    assert nov.leer_novedad(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Hoy</title><link href="https://x/hoy/"/></entry></feed>') is None
    assert nov.leer_novedad(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>X</title><link href="javascript:/novedades/x"/></entry></feed>') is None


def test_el_feed_es_por_idioma(monkeypatch):
    monkeypatch.setenv("GUILDA_AYUDA_URL", "https://ayuda.ejemplo.com")
    assert nov._url_feed("es") == "https://ayuda.ejemplo.com/feed.xml"
    assert nov._url_feed("ca") == "https://ayuda.ejemplo.com/ca/feed.xml"


def test_si_la_ayuda_falla_no_hay_aviso_ni_error_y_no_se_insiste(monkeypatch):
    nov._cache.clear()
    llamadas = []
    def cae(idioma):
        llamadas.append(idioma)
        raise OSError("sin red")
    monkeypatch.setattr(nov, "_descargar", cae)
    nov._refrescar("es")
    assert nov._cache["es"][1] is None and llamadas == ["es"]
    nov.novedad("es")                                  # dentro del plazo de reintento: no vuelve a pedir
    time.sleep(0.05)
    assert llamadas == ["es"]


def test_conserva_la_ultima_novedad_si_luego_falla(monkeypatch):
    nov._cache.clear()
    valor = {"id": "u", "titulo": "t", "url": "https://x/novedades/u/"}
    nov._cache["es"] = (time.time() - nov.REFRESCO_SEGUNDOS - 1, valor)
    monkeypatch.setattr(nov, "_descargar", lambda idioma: (_ for _ in ()).throw(OSError("sin red")))
    nov._en_curso.add("es")
    nov._refrescar("es")
    assert nov._cache["es"][1] == valor


def test_el_menu_muestra_la_novedad(cliente, monkeypatch):
    nov._cache.clear()
    monkeypatch.setattr(nov, "novedad", lambda idioma: {"id": "https://help.guildawork.com/novedades/privacidad/", "titulo": "Novedades: privacidad", "url": "https://help.guildawork.com/novedades/privacidad/"})
    iniciar_sesion_de_prueba(cliente, "novedad@ejemplo.com", "contrasena123")
    html = cliente.get("/hoy/").get_data(as_text=True)
    assert 'id="ayuda-novedad"' in html and "novedades/privacidad/" in html and "ayuda_novedades.js" in html


def test_sin_novedad_el_menu_no_cambia(cliente, monkeypatch):
    monkeypatch.setattr(nov, "novedad", lambda idioma: None)
    iniciar_sesion_de_prueba(cliente, "sinnovedad@ejemplo.com", "contrasena123")
    html = cliente.get("/hoy/").get_data(as_text=True)
    assert "ayuda-novedad" not in html
