"""El service worker solo guarda recursos de /static/: ni páginas ni API ni nada con sesión."""
from app import db


def test_service_worker_solo_cachea_estaticos(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho sw")
    pagina, errores = abrir()
    entrar_como_equipo(pagina, "sw@ejemplo.com", despacho=t, direccion=True)
    r = pagina.request.get(f"{servidor.url}/sw.js")
    assert r.status == 200 and "javascript" in r.headers["content-type"]
    assert r.headers.get("service-worker-allowed") == "/"

    pagina.goto(f"{servidor.url}/hoy/")
    pagina.wait_for_load_state("networkidle")
    pagina.evaluate("navigator.serviceWorker.ready")
    pagina.reload()
    pagina.wait_for_load_state("networkidle")
    assert pagina.evaluate("!!navigator.serviceWorker.controller")

    urls = pagina.evaluate("""async () => {
      const c = await caches.open('gw-estaticos-1');
      return (await c.keys()).map(k => new URL(k.url).pathname);
    }""")
    assert urls and all(u.startswith("/static/") for u in urls), urls
    assert any(u.endswith("web_v2.css") for u in urls), urls
    assert not any("/hoy" in u or "/api" in u for u in urls)
    assert not [e for e in errores if "TypeError" in e or "ReferenceError" in e]
