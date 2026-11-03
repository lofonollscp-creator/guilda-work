"""El manifest de la webapp apunta a ficheros que existen y con el tamaño declarado."""
import json
import os

from PIL import Image

RAIZ = os.path.join(os.path.dirname(__file__), "..", "app")


def _manifest():
    with open(os.path.join(RAIZ, "static", "manifest.webmanifest"), encoding="utf-8") as f:
        return json.load(f)


def test_iconos_y_capturas_existen_con_su_tamano():
    m = _manifest()
    for entrada in m["icons"] + m["screenshots"]:
        assert entrada["src"].startswith("/static/")
        with Image.open(os.path.join(RAIZ, entrada["src"].lstrip("/"))) as im:
            assert "%dx%d" % im.size == entrada["sizes"], entrada["src"]


def test_hay_iconos_any_y_maskable_y_capturas_de_ambos_formatos():
    m = _manifest()
    assert {"any", "maskable"} <= {i["purpose"] for i in m["icons"]}
    assert {"wide", "narrow"} <= {s["form_factor"] for s in m["screenshots"]}
    assert all(s.get("label") for s in m["screenshots"])
