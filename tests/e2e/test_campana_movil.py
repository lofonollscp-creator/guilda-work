"""La insignia de la campana no se desborda ni se recorta con 1, 2 o 3 cifras (escritorio y móvil)."""
import os

import pytest

from app import db


@pytest.mark.parametrize("cuantas", [1, 12, 150])
def test_insignia_de_la_campana_cabe(servidor, abrir, entrar_como_equipo, cuantas):
    t = db.crear_tenant(f"Despacho campana {cuantas}")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, f"campana{cuantas}@ejemplo.com", despacho=t, direccion=True)
    for i in range(cuantas):
        db.crear_notificacion(uid, "tarea", f"Aviso {i}", None, None)
    for ancho in (1440, 390, 360):
        pagina.set_viewport_size({"width": ancho, "height": 800})
        pagina.goto(f"{servidor.url}/hoy/")
        pagina.wait_for_load_state("networkidle")
        insignia = pagina.locator("#notificaciones-toggle .notificaciones-badge")
        assert insignia.count() == 1
        caja, boton = insignia.bounding_box(), pagina.locator("#notificaciones-toggle").bounding_box()
        assert caja["x"] >= 0 and caja["x"] + caja["width"] <= ancho, f"{ancho}px: fuera de pantalla {caja}"
        assert caja["y"] >= 0, f"{ancho}px: recortada por arriba {caja}"
        assert pagina.evaluate("document.documentElement.scrollWidth") <= ancho, f"{ancho}px: scroll horizontal"
        assert caja["width"] <= boton["width"] + 12, f"{ancho}px: insignia mucho mayor que la campana {caja} {boton}"
        carpeta = os.environ.get("GUILDA_CAPTURAS_WEB")
        if carpeta:
            pagina.screenshot(path=f"{carpeta}/campana_{cuantas}_{ancho}.png", clip={"x": max(0, ancho - 260), "y": 0, "width": min(260, ancho), "height": 70})
