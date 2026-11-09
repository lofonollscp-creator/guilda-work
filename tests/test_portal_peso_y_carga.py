"""Peso y carga del portal (Q10): presupuestos para que no engorde sin que nadie lo note, y que nada bloquee el pintado ni deje una imagen sin texto alternativo."""
import re
from pathlib import Path

from tests.test_portal_personas_avisos import _despacho, _entrar, _html, correo  # noqa: F401 -- fixtures

ESTATICOS = Path(__file__).resolve().parent.parent / "app" / "static"
PAGINAS = ("/portal/", "/portal/facturas", "/portal/avisos", "/portal/cuenta", "/portal/cuestionarios", "/portal/mensajes")
MAX_HTML = 90_000                       # bytes de la página ya servida (Caddy la comprime)
MAX_SCRIPTS = 6
MAX_JS_PORTAL = 48_000                  # cada script propio del portal, sin comprimir
MAX_CSS = 400_000


def test_las_paginas_del_portal_caben_en_su_presupuesto_y_no_bloquean_el_pintado(cliente, correo):
    t, u, c = _despacho("Peso portal")
    _entrar(cliente, c, "titular@ejemplo.com")
    for ruta in PAGINAS:
        html = _html(cliente, ruta)
        assert len(html.encode()) <= MAX_HTML, f"{ruta} pesa {len(html.encode())} bytes"
        scripts = re.findall(r"<script\b[^>]*\bsrc=[^>]*>", html)
        assert len(scripts) <= MAX_SCRIPTS, f"{ruta} carga {len(scripts)} scripts"
        cabecera = html.split("</head>", 1)[0]
        for s in re.findall(r"<script\b[^>]*\bsrc=[^>]*>", cabecera):                # solo el del aspecto (evita el parpadeo de tema) puede ir en la cabecera
            assert "portal_aspecto.js" in s or "defer" in s, f"{ruta}: script que bloquea en la cabecera: {s}"
        for img in re.findall(r"<img\b[^>]*>", html):
            assert re.search(r"\balt=", img), f"{ruta}: imagen sin alt: {img}"


def test_los_estaticos_del_portal_no_engordan_sin_avisar():
    assert (ESTATICOS / "style.css").stat().st_size <= MAX_CSS
    for f in ESTATICOS.glob("portal_*.js"):
        assert f.stat().st_size <= MAX_JS_PORTAL, f"{f.name} pesa {f.stat().st_size} bytes"


def test_la_pantalla_sin_conexion_es_publica_igual_para_todos_y_sin_datos_de_nadie(cliente):
    r = cliente.get("/portal/sin-conexion")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "data-cola-offline" in html and 'name="modo" value="archivos"' in html and r.headers["Cache-Control"] == "no-cache"
    assert "csrf" not in html.lower() and "portal_cliente" not in html


def test_el_service_worker_solo_sirve_de_la_cache_la_pantalla_sin_conexion_del_portal():
    codigo = (ESTATICOS / "sw.js").read_text(encoding="utf-8")
    assert 'req.mode === "navigate"' in codigo and "PAGINA_OFFLINE" in codigo and "fetch(req)" in codigo                  # red primero; la caché es solo la pantalla sin datos
    assert "cache.put(req" not in codigo.split("PAGINA_OFFLINE")[1].split("/static/")[0]                               # ninguna página del portal se guarda
