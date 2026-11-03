"""Genera las capturas del manifest de la webapp (GUILDA_CAPTURAS_MANIFEST=carpeta). Con datos de demostración; no comprueba nada."""
import os

import pytest

from app import db
from tests.e2e.test_capturas_web import _sembrar

CARPETA = os.environ.get("GUILDA_CAPTURAS_MANIFEST")
ESCRITORIO = (("hoy", "/hoy/"), ("tareas", "/tareas/"), ("correo", "/correo/"))
MOVIL = (("hoy", "/hoy/"), ("tareas", "/tareas/"), ("correo", "/correo/"))


@pytest.mark.skipif(not CARPETA, reason="GUILDA_CAPTURAS_MANIFEST sin definir")
def test_capturas_del_manifest(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho demo")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "demo@ejemplo.com", despacho=t, direccion=True)
    _sembrar(uid, t)
    os.makedirs(CARPETA, exist_ok=True)
    for ancho, alto, destino, rutas in ((1280, 800, "escritorio", ESCRITORIO), (390, 800, "movil", MOVIL)):
        pagina.set_viewport_size({"width": ancho, "height": alto})
        for nombre, ruta in rutas:
            pagina.goto(f"{servidor.url}{ruta}")
            pagina.wait_for_load_state("networkidle")
            pagina.screenshot(path=f"{CARPETA}/{destino}-{nombre}.png")
