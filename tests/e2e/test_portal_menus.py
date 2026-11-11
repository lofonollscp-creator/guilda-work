"""Los menús desplegables de la cabecera (perfil y novedades) abiertos: nada de lo que hay dentro se sale del panel, en ningún ancho ni idioma."""
import pytest

from tests.e2e.test_portal_tema import _entrar

FUERA = """(sel) => { const p = document.querySelector(sel + ' .pv-perfil-panel').getBoundingClientRect(); const o = [];
  for (const e of document.querySelectorAll(sel + ' .pv-perfil-panel *')) { const r = e.getBoundingClientRect(); if (r.width && (r.right > p.right + 1 || r.left < p.left - 1)) o.push(e.tagName.toLowerCase() + '.' + (e.className || '') + ' ' + Math.round(r.left) + '..' + Math.round(r.right) + ' vs ' + Math.round(p.left) + '..' + Math.round(p.right)); }
  return { fuera: o.slice(0, 6), panel_dentro_de_pantalla: p.left >= 0 && p.right <= document.documentElement.clientWidth }; }"""


@pytest.mark.parametrize("ancho", [320, 390, 768, 1280])
@pytest.mark.parametrize("menu", [".pv-perfil", ".pv-campana"])
def test_el_menu_abierto_no_se_desborda(servidor, abrir, entrar_como_equipo, chromium, ancho, menu):
    ctx, pg = _entrar(servidor, abrir, entrar_como_equipo, chromium, "light")
    pg.set_viewport_size({"width": ancho, "height": 800})
    pg.goto(f"{servidor.url}/portal/")
    pg.click(f"{menu} > summary")
    r = pg.evaluate("(m) => { const p = document.querySelector(m + ' .pv-perfil-panel').getBoundingClientRect(); const o = []; for (const e of document.querySelectorAll(m + ' .pv-perfil-panel *')) { const r = e.getBoundingClientRect(); if (r.width && (r.right > p.right + 1 || r.left < p.left - 1)) o.push(e.tagName.toLowerCase() + '.' + (e.className || '') + ' ' + Math.round(r.left) + '..' + Math.round(r.right) + ' vs ' + Math.round(p.left) + '..' + Math.round(p.right)); } return { fuera: o.slice(0, 6), dentro: p.left >= 0 && p.right <= document.documentElement.clientWidth }; }", menu)
    assert r["fuera"] == [] and r["dentro"], (ancho, menu, r)
    ctx.close()
