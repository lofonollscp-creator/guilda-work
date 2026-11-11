"""Tema del portal (claro, oscuro o el del sistema): el selector del menú de perfil lo cambia al momento, se recuerda al recargar y «Sistema» sigue al dispositivo. Corre con scripts/probar_navegador.sh."""
from app import db
from tests.e2e.test_capturas_web import _sembrar


def _entrar(servidor, abrir, entrar_como_equipo, chromium, esquema):
    t = db.crear_tenant("Despacho tema portal")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "portal-tema@ejemplo.com", despacho=t, direccion=True)
    ids = _sembrar(uid, t)
    conn = db.get_connection()
    conn.execute("UPDATE clientes_fiscales SET email = ? WHERE id = ?", ("tema@ejemplo.com", ids["cliente"]))
    conn.commit(); conn.close()
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800}, color_scheme=esquema)
    pg = ctx.new_page()
    pg.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(ids['cliente'], '127.0.0.1', email='tema@ejemplo.com')}")
    pg.wait_for_load_state("load")
    return ctx, pg


def _fondo(pg):
    return pg.evaluate("getComputedStyle(document.body).backgroundColor")


def _luz(rgb):
    n = [int(x) for x in rgb.replace("rgba(", "").replace("rgb(", "").replace(")", "").split(",")[:3]]
    return sum(n) / 3


def _elegir(pg, tema):
    if not pg.evaluate("document.querySelector('.pv-perfil').open"):
        pg.click(".pv-perfil > summary")
    pg.click(f'[data-temas] [data-tema="{tema}"]')


def test_el_selector_de_tema_cambia_recuerda_y_sigue_al_sistema(servidor, abrir, entrar_como_equipo, chromium):
    ctx, pg = _entrar(servidor, abrir, entrar_como_equipo, chromium, "light")
    assert _luz(_fondo(pg)) > 200                                              # sistema claro: página clara
    _elegir(pg, "dark")
    assert pg.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
    assert _luz(_fondo(pg)) < 60
    assert pg.evaluate("getComputedStyle(document.documentElement).colorScheme") == "dark"
    pg.reload(wait_until="load")                                                # se recuerda y no hay parpadeo: ya sale oscuro al cargar
    assert pg.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
    if not pg.evaluate("document.querySelector('.pv-perfil').open"):
        pg.click(".pv-perfil > summary")
    assert pg.get_attribute('[data-tema="dark"]', "aria-pressed") == "true"
    assert pg.get_attribute('[data-tema="light"]', "aria-pressed") == "false"
    _elegir(pg, "light")
    assert _luz(_fondo(pg)) > 200
    _elegir(pg, "system")
    assert pg.evaluate("document.documentElement.hasAttribute('data-theme')") is False
    assert _luz(_fondo(pg)) > 200
    ctx.close()


def test_sistema_oscuro_pinta_oscuro_sin_elegir_nada_y_claro_lo_fuerza(servidor, abrir, entrar_como_equipo, chromium):
    ctx, pg = _entrar(servidor, abrir, entrar_como_equipo, chromium, "dark")
    assert _luz(_fondo(pg)) < 60                                               # el dispositivo está en oscuro y no se ha elegido nada
    _elegir(pg, "light")
    assert _luz(_fondo(pg)) > 200                                              # elegir «Claro» gana al dispositivo
    ctx.close()


def test_el_menu_de_perfil_se_cierra_con_escape_y_con_un_clic_fuera_y_devuelve_el_foco(servidor, abrir, entrar_como_equipo, chromium):
    ctx, pg = _entrar(servidor, abrir, entrar_como_equipo, chromium, "light")
    pg.click(".pv-perfil > summary")
    assert pg.evaluate("document.querySelector('.pv-perfil').open") is True
    pg.wait_for_function("document.querySelector('.pv-perfil > summary').getAttribute('aria-expanded') === 'true'")
    pg.keyboard.press("Escape")
    assert pg.evaluate("document.querySelector('.pv-perfil').open") is False
    assert pg.evaluate("document.activeElement.tagName") == "SUMMARY"
    pg.click(".pv-perfil > summary")
    pg.click("h1")
    assert pg.evaluate("document.querySelector('.pv-perfil').open") is False
    ctx.close()


def test_la_pestana_activa_se_ve_aunque_la_fila_haga_scroll_en_el_movil(servidor, abrir, entrar_como_equipo, chromium):
    ctx, pg = _entrar(servidor, abrir, entrar_como_equipo, chromium, "light")
    pg.set_viewport_size({"width": 320, "height": 700})
    pg.goto(f"{servidor.url}/portal/extracto")
    pg.wait_for_load_state("load")
    caja = pg.evaluate("(() => { const a = document.querySelector('.pv-pestanas a[aria-current]').getBoundingClientRect(), f = document.querySelector('.pv-pestanas').getBoundingClientRect(); return [a.left >= f.left - 1, a.right <= f.right + 1]; })()")
    assert caja == [True, True]
    ctx.close()


def test_navegacion_nueva_barra_inferior_en_el_movil_y_cabecera_en_el_pc(servidor, abrir, entrar_como_equipo, chromium):
    ctx, pg = _entrar(servidor, abrir, entrar_como_equipo, chromium, "light")
    pg.set_viewport_size({"width": 390, "height": 800})
    pg.goto(f"{servidor.url}/portal/")
    assert pg.locator(".pv-tabs").is_visible() and pg.locator(".pv-nav").is_hidden()
    assert pg.locator(".pv-tabs").evaluate("e => getComputedStyle(e).position") == "fixed"
    pg.set_viewport_size({"width": 1280, "height": 800})
    assert pg.locator(".pv-tabs").is_hidden() and pg.locator(".pv-nav").is_visible()
    ctx.close()


def test_la_campana_y_el_perfil_no_se_abren_a_la_vez(servidor, abrir, entrar_como_equipo, chromium):
    ctx, pg = _entrar(servidor, abrir, entrar_como_equipo, chromium, "light")
    pg.click(".pv-campana > summary")
    assert pg.evaluate("document.querySelector('.pv-campana').open") is True
    pg.click(".pv-perfil > summary")
    pg.wait_for_function("document.querySelector('.pv-campana').open === false")
    assert pg.evaluate("document.querySelector('.pv-perfil').open") is True
    ctx.close()
