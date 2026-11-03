"""Barrido de pantallas del BACKOFFICE (app aparte): mismo recorrido y mismas medidas que `test_barrido_pantallas`, con datos ficticios y textos largos. Solo corre con GUILDA_BARRIDO=<carpeta>; escribe informe-backoffice.json."""
import json
import os
import re
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app import db
from tests.e2e.test_barrido_pantallas import MEDIR

CARPETA = os.environ.get("GUILDA_BARRIDO")
pytestmark = pytest.mark.skipif(not CARPETA, reason="GUILDA_BARRIDO sin definir")
CLAVE = "una-clave-larga-y-segura-1"
EXCLUIR = ("logout", "salir", "descargar", "export", "csv", "pdf", "static", "healthz", "login", "webhook", "oauth", "callback", "sincronizar", "enviar", "borrar", "eliminar")


def test_barrido_backoffice(cliente, chromium, tmp_path, monkeypatch):
    from backoffice import auth
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "backoffice.db")
    monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "bo_secret.key")
    auth.crear_admin("jorge", CLAVE, "Jorge")
    from backoffice import aprovisionamiento
    monkeypatch.setattr(aprovisionamiento, "aprovisionar_usuario", lambda *a, **k: [])
    from backoffice.main import create_app
    app = create_app(testing=True)
    largo = "Construcciones y Reformas Hermanos Fernández-Villanueva de la Vera e Hijos Sociedad Limitada Profesional"
    for i in range(6):
        t = db.crear_tenant(f"{largo} {i}" if i % 2 else f"Despacho {i}")
        db.crear_usuario(f"usuario-con-un-correo-muy-largo-{i}-para-probar-desbordes@dominio-de-ejemplo-extenso.com", "contrasena123")
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    rutas = sorted({r.rule for r in app.url_map.iter_rules() if "GET" in r.methods and not r.arguments and not any(x in r.rule.lower() for x in EXCLUIR)})
    anchos = [int(a) for a in os.environ.get("GUILDA_ANCHOS", "375,768,1280").split(",")]
    informe = {}
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    actual = {"k": ""}
    pg.on("pageerror", lambda e: informe.setdefault(actual["k"], {}).setdefault("js", []).append(str(e)[:140]))
    pg.on("response", lambda r: informe.setdefault(actual["k"], {}).setdefault("recursos", []).append(f"{r.status} {r.url.replace(base, '')[:90]}") if r.status >= 400 and r.url != base + actual["k"].split("@")[0] else None)
    pg.goto(base + "/login")
    pg.fill("input[name=usuario]", "jorge")
    pg.fill("input[name=contrasena]", CLAVE)
    pg.click("button[type=submit]")
    pg.wait_for_load_state("load")
    for ancho in anchos:
        pg.set_viewport_size({"width": ancho, "height": 800})
        for ruta in rutas:
            actual["k"] = f"{ruta}@{ancho}"
            try:
                resp = pg.goto(base + ruta, wait_until="load")
                pg.wait_for_timeout(100)
                m = pg.evaluate(MEDIR)
                if os.environ.get("GUILDA_BARRIDO_CAPTURAS"):
                    Path(os.environ["GUILDA_BARRIDO_CAPTURAS"]).mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(Path(os.environ["GUILDA_BARRIDO_CAPTURAS"]) / ((ruta.strip('/').replace('/', '_') or 'inicio') + f'_{ancho}.png')))
            except Exception as e:
                informe.setdefault(actual["k"], {})["error"] = str(e).splitlines()[0][:120]
                continue
            d = informe.setdefault(actual["k"], {})
            d["http"] = resp.status if resp else 0
            d.update({k: v for k, v in m.items() if v})
    ctx.close()
    srv.shutdown()
    Path(CARPETA).mkdir(parents=True, exist_ok=True)
    (Path(CARPETA) / "informe-backoffice.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print("BARRIDO BACKOFFICE:", len(rutas), "pantallas x", len(anchos), "anchos")
