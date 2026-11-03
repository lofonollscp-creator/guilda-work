"""Barrido de pantallas: recorre todas las rutas GET sin parámetros (más las de `/docs/`) con datos FICTICIOS y mide, en cada ancho, lo que una persona notaría: desbordes horizontales, errores de JavaScript, recursos que
fallan (con su URL y la pantalla que los pide), botones y campos sin nombre accesible, imágenes sin `alt` y objetivos táctiles demasiado pequeños en móvil.

Solo corre si se pide: GUILDA_BARRIDO=<carpeta de salida> (deja ahí informe.json y lo resume por pantalla). GUILDA_ANCHOS (por defecto 375,768,1280), GUILDA_IDIOMA (por defecto es), GUILDA_TEMA (light|dark).
No guarda capturas ni comprueba nada: es una herramienta de revisión, no un test de regresión."""
import json
import os
from pathlib import Path

import pytest

from app import db
from tests.e2e.test_capturas_web import EXCLUIR, _sembrar

CARPETA = os.environ.get("GUILDA_BARRIDO")
pytestmark = pytest.mark.skipif(not CARPETA, reason="GUILDA_BARRIDO sin definir")

MEDIR = """() => {
  const de = document.documentElement, W = de.clientWidth, o = {desborde: [], sin_nombre: [], sin_alt: 0, pequenos: [], pagina: de.scrollWidth > W + 1 ? de.scrollWidth : 0};
  const visible = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && !e.closest('[hidden],dialog:not([open]),details:not([open])>*:not(summary)'); };
  const nombre = e => (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.getAttribute('title') || (e.textContent || '').trim() || (e.querySelector('img[alt]:not([alt=""])') ? 'x' : '') || (e.labels && e.labels.length ? 'x' : '') || e.getAttribute('placeholder') || '');
  const desc = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  for (const e of document.querySelectorAll('body *')) {
    if (!visible(e) || getComputedStyle(e).position === 'fixed') continue;
    const r = e.getBoundingClientRect();
    let a = e.parentElement, recortado = false;
    while (a && a !== document.body) { if (getComputedStyle(a).overflowX !== 'visible') { recortado = true; break; } a = a.parentElement; }
    if (!recortado && r.right > 0 && (r.right > W + 1 || r.left < -1)) o.desborde.push(desc(e) + '@' + Math.round(r.left) + '..' + Math.round(r.right) + ' «' + (e.textContent || '').trim().slice(0, 24) + '»');
  }
  for (const e of document.querySelectorAll('button, [role=button], a[href], input:not([type=hidden]), select, textarea')) {
    if (!visible(e)) continue;
    if (!nombre(e)) o.sin_nombre.push(desc(e));
    const r = e.getBoundingClientRect();
    if (W <= 480 && (r.height < 32 || r.width < 32) && e.tagName !== 'INPUT' && !(e.tagName === 'A' && e.closest('p, li, td, span, .md, .prosa') && e.textContent.trim().length > 3)) o.pequenos.push(desc(e) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' «' + (e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 20) + '»');
  }
  o.fuera_de_caja = [];
  for (const c of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(c);
    if (!['grid', 'flex', 'inline-flex'].includes(cs.display) || cs.overflowX !== 'visible' || !visible(c)) continue;
    const rc = c.getBoundingClientRect();
    for (const h of c.children) {
      if (!visible(h) || ['absolute', 'fixed'].includes(getComputedStyle(h).position)) continue;
      const rh = h.getBoundingClientRect();
      if (rh.width > 4 && rc.width > 4 && (rh.left < rc.left - 2 || rh.right > rc.right + 2) && o.fuera_de_caja.length < 8) { o.fuera_de_caja.push(desc(c) + ' > ' + desc(h) + ' (' + Math.round(rh.left - rc.left) + ',' + Math.round(rh.right - rc.right) + ')'); break; }
    }
  }
  o.fuera_de_caja = [...new Set(o.fuera_de_caja)].slice(0, 6);
  o.solapes = [];
  for (const c of document.querySelectorAll('body *')) {
    const d = getComputedStyle(c).display;
    if ((d !== 'grid' && d !== 'flex' && d !== 'inline-flex') || !visible(c)) continue;
    const hijos = [...c.children].filter(h => visible(h) && !['absolute', 'fixed', 'sticky'].includes(getComputedStyle(h).position) && h.getBoundingClientRect().width > 4 && h.getBoundingClientRect().height > 4);
    for (let i = 0; i < hijos.length && o.solapes.length < 6; i++) for (let j = i + 1; j < hijos.length; j++) {
      const a = hijos[i].getBoundingClientRect(), b = hijos[j].getBoundingClientRect();
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left), h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 3 && h > 3) { o.solapes.push(desc(c) + ' > ' + desc(hijos[i]) + ' x ' + desc(hijos[j]) + ' ' + Math.round(w) + 'x' + Math.round(h)); break; }
    }
  }
  o.solapes = [...new Set(o.solapes)].slice(0, 5);
  o.sin_alt = [...document.images].filter(i => visible(i) && !i.hasAttribute('alt')).length;
  o.titulo = document.title; o.h1 = document.querySelectorAll('h1').length;
  for (const k of ['desborde', 'sin_nombre', 'pequenos']) o[k] = [...new Set(o[k])].slice(0, 8);
  return o;
}"""


def _rutas(app, ids):
    rutas = []
    for r in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if "GET" not in r.methods or any(x in r.rule.lower() for x in EXCLUIR):
            continue
        if r.arguments:
            continue
        rutas.append(r.rule)
    return rutas


def test_barrido(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho barrido")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "barrido@ejemplo.com", despacho=t, direccion=True)
    ids = _sembrar(uid, t)
    from app import verticales
    for v in list(verticales.VERTICALES):                                     # que ninguna pantalla se quede en un 404 por tener el módulo apagado
        try:
            verticales.fijar_activo(t, v, True)
        except Exception:
            pass
    if os.environ.get("GUILDA_TEXTOS_LARGOS"):                                # estrés: nombres y títulos kilométricos, con y sin espacios, como los de la vida real
        conn = db.get_connection()
        largo = "Construcciones y Reformas Hermanos Fernández-Villanueva de la Vera e Hijos Sociedad Limitada Profesional"
        sin_espacios = "ECLI:ES:TS:2099:12345ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for tabla, in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for _, col, tipo, *_ in conn.execute(f"PRAGMA table_info({tabla})").fetchall():
                if col in ("asunto", "nombre", "titulo", "razon_social", "contraparte_nombre", "nombre_visible", "cuerpo_texto", "texto"):
                    try:
                        conn.execute(f"UPDATE {tabla} SET {col} = ? WHERE {col} IS NOT NULL AND length({col}) < 60", (largo + " " + sin_espacios,))
                    except Exception:
                        pass
        conn.commit()
        conn.close()
    lang = os.environ.get("GUILDA_IDIOMA", "es")
    pagina.context.set_extra_http_headers({"Accept-Language": lang})
    anchos = [int(a) for a in os.environ.get("GUILDA_ANCHOS", "375,768,1280").split(",")]
    tema = os.environ.get("GUILDA_TEMA", "light")
    pagina.goto(f"{servidor.url}/docs/")
    docs = pagina.evaluate("() => [...new Set([...document.querySelectorAll('.docs-sidebar a')].map(a => a.getAttribute('href')))]")
    rutas = _rutas(servidor.app, ids) + [d for d in docs if d and d.startswith("/")]
    rutas += [f"/clientes/{ids['cliente']}", f"/tareas/{ids['tarea']}", f"/correo/?cuenta_id={ids['cuenta']}&mensaje_id={ids['mensaje']}", f"/proyectos/{ids['proyecto']}"]
    informe = {}
    fallos = {"actual": ""}
    pagina.on("response", lambda r: informe.setdefault(fallos["actual"], {}).setdefault("recursos", []).append(f"{r.status} {r.url.replace(servidor.url, '')[:90]}") if r.status >= 400 and not r.url.endswith(fallos["actual"].split("@")[0]) else None)
    pagina.on("pageerror", lambda e: informe.setdefault(fallos["actual"], {}).setdefault("js", []).append(str(e)[:140]))
    for ancho in anchos:
        pagina.set_viewport_size({"width": ancho, "height": 800})
        for ruta in rutas:
            fallos["actual"] = f"{ruta}@{ancho}"
            try:
                resp = pagina.goto(f"{servidor.url}{ruta}", wait_until="load")
                pagina.wait_for_timeout(120)
                pagina.evaluate("t => document.documentElement.setAttribute('data-theme', t)", tema)
                m = pagina.evaluate(MEDIR)
                for fila in (".tarea-fila", ".fiscal-fila", ".cliente-fila", ".correo-fila"):         # estados al pasar el ratón (los controles de fila aparecen al hover)
                    if pagina.locator(fila).count():
                        pagina.locator(fila).first.hover()
                        pagina.wait_for_timeout(120)
                        extra = pagina.evaluate(MEDIR)
                        m["solapes"] = list(dict.fromkeys((m.get("solapes") or []) + extra.get("solapes", [])))[:5]
                        m["fuera_de_caja"] = list(dict.fromkeys((m.get("fuera_de_caja") or []) + extra.get("fuera_de_caja", [])))[:6]
                        m["desborde"] = list(dict.fromkeys((m.get("desborde") or []) + extra.get("desborde", [])))[:8]
            except Exception as e:                                                  # una pantalla que no carga no para el barrido
                informe.setdefault(fallos["actual"], {})["error"] = str(e).splitlines()[0][:120]
                continue
            d = informe.setdefault(fallos["actual"], {})
            d["http"] = resp.status if resp else 0
            d.update({k: v for k, v in m.items() if v})
    Path(CARPETA).mkdir(parents=True, exist_ok=True)
    (Path(CARPETA) / "informe.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print("BARRIDO:", len(rutas), "pantallas x", len(anchos), "anchos")
