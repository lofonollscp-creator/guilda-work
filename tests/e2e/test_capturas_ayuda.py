"""Capturas de pantalla para el centro de ayuda (repo `guilda-help`), en los 4 idiomas y con los datos FICTICIOS de `test_capturas_web._sembrar` (despacho «Despacho capturas»: nunca datos reales).

Solo corre si se pide: GUILDA_CAPTURAS_AYUDA=<carpeta de salida>. La lista de pantallas sale de `capturas.yaml` del repo de ayuda (GUILDA_CAPTURAS_MANIFIESTO, por defecto /home/guilda/guilda-help/capturas.yaml) y cada
imagen se guarda como <carpeta>/<idioma>/<nombre>.png. Lo lanza `guilda-help/capturas.sh`; no comprueba nada más que cada pantalla cargue (las que fallan se listan al final)."""
import os
from pathlib import Path

import pytest
import yaml

from app import db
from tests.e2e.test_capturas_web import _sembrar

CARPETA = os.environ.get("GUILDA_CAPTURAS_AYUDA")
MANIFIESTO = Path(os.environ.get("GUILDA_CAPTURAS_MANIFIESTO", "/home/guilda/guilda-help/capturas.yaml"))
pytestmark = pytest.mark.skipif(not CARPETA, reason="GUILDA_CAPTURAS_AYUDA sin definir")
IDIOMAS = ("es", "ca", "en", "fr")


def test_capturas_ayuda(servidor, abrir, entrar_como_equipo):
    pantallas = yaml.safe_load(MANIFIESTO.read_text(encoding="utf-8"))["capturas"]
    t = db.crear_tenant("Despacho capturas")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "capturas@ejemplo.com", despacho=t, direccion=True)
    ids = _sembrar(uid, t)
    fallos = []
    for lang in IDIOMAS:
        pagina.context.set_extra_http_headers({"Accept-Language": lang})
        destino = Path(CARPETA) / lang
        destino.mkdir(parents=True, exist_ok=True)
        for p in pantallas:
            pagina.set_viewport_size({"width": p.get("ancho", 1200), "height": p.get("alto", 720)})
            respuesta = pagina.goto(f"{servidor.url}{p['ruta'].format(**ids)}")
            if respuesta is None or respuesta.status >= 400:
                fallos.append(f"{lang}/{p['nombre']}: HTTP {respuesta.status if respuesta else '?'} en {p['ruta']}")
                continue
            pagina.wait_for_load_state("networkidle")
            pagina.evaluate("() => document.documentElement.setAttribute('data-theme', 'light')")
            for accion in p.get("antes", []):                      # clics previos (abrir un panel...)
                pagina.click(accion)
            pagina.wait_for_timeout(200)
            (pagina.locator(p["elemento"]).first if p.get("elemento") else pagina).screenshot(path=str(destino / f"{p['nombre']}.png"))
    print("CAPTURAS:", len(pantallas) * len(IDIOMAS) - len(fallos), "hechas;", len(fallos), "con fallo")
    print("\n".join(fallos))
