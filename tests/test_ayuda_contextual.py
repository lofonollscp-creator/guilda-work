"""Ayuda contextual: cada pantalla enlaza con su artículo del centro de ayuda y ninguno apunta a un artículo inexistente."""
import os
import re
from pathlib import Path

import pytest

from app import ayuda, db
from tests.conftest import iniciar_sesion_de_prueba


def test_el_prefijo_mas_largo_gana_y_lo_desconocido_va_a_la_portada():
    assert ayuda.ruta_de("tareas.hoy") == "trabajo-diario/mi-dia"
    assert ayuda.ruta_de("tareas.listar") == "trabajo-diario/tareas"
    assert ayuda.ruta_de("tareas.carga_mover") == "trabajo-diario/tareas-en-equipo"
    assert ayuda.ruta_de("correo.equipo_mensaje") == "trabajo-diario/tareas-en-equipo"
    assert ayuda.ruta_de("correo.bandeja") == "trabajo-diario/correo"
    assert ayuda.ruta_de("fiscal.recordatorios") == "trabajo-diario/recordatorios-a-clientes"
    assert ayuda.ruta_de("ia.ajustes") == "asistente-ia/ajustes-y-limites"
    assert ayuda.ruta_de("ia.asistente_vista") == "asistente-ia/usar-el-asistente"
    assert ayuda.ruta_de("lista_notas") is None and ayuda.ruta_de(None) is None
    assert ayuda.url_de("lista_notas") == ("https://help.guildawork.com/", False)
    assert ayuda.url_de("tareas.hoy") == ("https://help.guildawork.com/trabajo-diario/mi-dia/", True)


def test_la_url_base_se_configura_por_entorno(monkeypatch):
    monkeypatch.setenv("GUILDA_AYUDA_URL", "https://ayuda.ejemplo.com/")
    assert ayuda.url_de("fichaje.panel")[0] == "https://ayuda.ejemplo.com/trabajo-diario/fichaje/"


def test_todo_el_mapa_apunta_a_articulos_que_existen():
    contenido = Path(os.environ.get("GUILDA_AYUDA_CONTENIDO", "/home/guilda/guilda-help/contenido"))
    if not contenido.is_dir():
        pytest.skip("no está el repositorio del centro de ayuda en esta máquina")
    faltan = [r for r in set(ayuda.MAPA.values()) if not (contenido / f"{r}.md").is_file()]
    assert not faltan, faltan


def test_las_pantallas_muestran_su_ayuda(cliente):
    iniciar_sesion_de_prueba(cliente, "ayuda@ejemplo.com", "contrasena123")
    r = cliente.get("/tareas/hoy")
    assert r.status_code == 200
    assert b"https://help.guildawork.com/trabajo-diario/mi-dia/" in r.data
    assert "Ayuda sobre esta pantalla".encode() in r.data
    r = cliente.get("/notas")
    assert b'href="https://help.guildawork.com/"' in r.data
