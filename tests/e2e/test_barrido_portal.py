"""Barrido del PORTAL DE CLIENTE (entrando con su enlace de un solo uso) y de las pantallas sin sesión (entrar, registro, recuperar contraseña): mismas medidas que `test_barrido_pantallas`. Solo con GUILDA_BARRIDO=<carpeta>; escribe informe-portal.json."""
import json
import os
from pathlib import Path

import pytest

from app import db
from tests.e2e.test_barrido_pantallas import MEDIR
from tests.e2e.test_capturas_web import _sembrar

CARPETA = os.environ.get("GUILDA_BARRIDO")
pytestmark = pytest.mark.skipif(not CARPETA, reason="GUILDA_BARRIDO sin definir")
EXCLUIR = ("salir", "logout", "descargar", "export", "pdf", "csv", "static", "adjunto", "archivo", "borrar", "eliminar", "enviar")


def test_barrido_portal(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal barrido")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "portal-barrido@ejemplo.com", despacho=t, direccion=True)
    ids = _sembrar(uid, t)
    if os.environ.get("GUILDA_TEXTOS_LARGOS"):
        conn = db.get_connection()
        conn.execute("UPDATE clientes_fiscales SET nombre = ?", ("Construcciones y Reformas Hermanos Fernández-Villanueva de la Vera e Hijos Sociedad Limitada Profesional ECLI:ES:TS:2099:12345ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",))
        conn.commit()
        conn.close()
    rutas = sorted({r.rule for r in servidor.app.url_map.iter_rules() if r.rule.startswith("/portal") and "GET" in r.methods and not r.arguments and not any(x in r.rule.lower() for x in EXCLUIR)})
    anonimas = ["/login", "/registro", "/recuperar-contrasena"]
    anchos = [int(a) for a in os.environ.get("GUILDA_ANCHOS", "375,768,1280").split(",")]
    lang = os.environ.get("GUILDA_IDIOMA", "es")
    informe = {}
    actual = {"k": ""}

    def recorrer(pg, lista, etiqueta):
        pg.context.set_extra_http_headers({"Accept-Language": lang})
        pg.on("pageerror", lambda e: informe.setdefault(actual["k"], {}).setdefault("js", []).append(str(e)[:140]))
        for ancho in anchos:
            pg.set_viewport_size({"width": ancho, "height": 800})
            for ruta in lista:
                actual["k"] = f"{etiqueta}{ruta}@{ancho}"
                try:
                    resp = pg.goto(servidor.url + ruta, wait_until="load")
                    pg.wait_for_timeout(120)
                    m = pg.evaluate(MEDIR)
                except Exception as e:
                    informe.setdefault(actual["k"], {})["error"] = str(e).splitlines()[0][:120]
                    continue
                d = informe.setdefault(actual["k"], {})
                d["http"] = resp.status if resp else 0
                d["final"] = pg.url.replace(servidor.url, "")[:60]
                d.update({k: v for k, v in m.items() if v})

    # sin sesión
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800})
    recorrer(ctx.new_page(), anonimas, "anon:")
    ctx.close()
    # cliente del portal con su enlace
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(ids['cliente'], '127.0.0.1')}")
    pg.wait_for_load_state("load")
    informe["entrada"] = {"final": pg.url.replace(servidor.url, "")}
    recorrer(pg, rutas, "portal:")
    ctx.close()
    Path(CARPETA).mkdir(parents=True, exist_ok=True)
    (Path(CARPETA) / "informe-portal.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print("BARRIDO PORTAL:", len(rutas) + len(anonimas), "pantallas x", len(anchos), "anchos")
