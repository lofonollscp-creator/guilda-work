"""Accesibilidad del portal (L10): enlace para saltar al contenido, tema y tamaño de letra a gusto de cada persona, foco visible y contraste suficiente (WCAG AA) en claro y en oscuro."""
from app import db, verticales

CONTRASTE = """() => {
  const rgb = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); return m ? m[1].split(',').slice(0, 3).map(Number) : [0, 0, 0]; };
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const fondo = e => { while (e) { const c = getComputedStyle(e).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return rgb(c); e = e.parentElement; } return [255, 255, 255]; };
  const razon = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const medir = sel => { const e = document.querySelector(sel); if (!e) return null; const cs = getComputedStyle(e); return Math.round(razon(rgb(cs.color), fondo(e)) * 100) / 100; };
  return {texto: medir('.portal-contenido p'), apagado: medir('.portal-contenido .muted'), enlace: medir('.portal-contenido a:not(.btn)'), boton: medir('.portal-contenido .btn-primary'), nav: medir('.portal-nav a')};
}"""


def _entrar(servidor, abrir, entrar_como_equipo, chromium, nombre, esquema="light"):
    t = db.crear_tenant(nombre)
    pagina, _ = abrir()
    entrar_como_equipo(pagina, f"{nombre.replace(' ', '')}@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Accesible", email="accesible@ejemplo.com")
    ctx = chromium.new_context(viewport={"width": 390, "height": 800}, color_scheme=esquema)
    nueva = ctx.new_page()
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    return ctx, nueva


def test_el_enlace_de_saltar_lleva_al_contenido_y_hay_un_unico_main(servidor, abrir, entrar_como_equipo, chromium):
    ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, "Portal saltar")
    nueva.goto(f"{servidor.url}/portal/cuenta")
    assert nueva.locator("main").count() == 1 and nueva.locator("main#portal-contenido").count() == 1
    nueva.keyboard.press("Tab")
    assert nueva.evaluate("document.activeElement.className") == "portal-saltar" and nueva.locator(".portal-saltar").bounding_box()["y"] >= 0
    nueva.keyboard.press("Enter")
    assert nueva.evaluate("document.activeElement.id") == "portal-contenido"
    ctx.close()


def test_tema_y_tamano_de_letra_se_aplican_y_se_recuerdan(servidor, abrir, entrar_como_equipo, chromium):
    ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, "Portal aspecto")
    nueva.goto(f"{servidor.url}/portal/cuenta")
    assert nueva.evaluate("document.documentElement.getAttribute('data-theme')") is None
    nueva.check("input[name=aspecto-tema][value=dark]")
    nueva.check("input[name=aspecto-letra][value=muy-grande]")
    assert nueva.evaluate("document.documentElement.getAttribute('data-theme')") == "dark" and nueva.evaluate("document.documentElement.getAttribute('data-letra')") == "muy-grande"
    nueva.goto(f"{servidor.url}/portal/")
    assert nueva.evaluate("document.documentElement.getAttribute('data-theme')") == "dark" and nueva.evaluate("getComputedStyle(document.querySelector('.portal-cliente-shell')).zoom") == "1.3"
    nueva.goto(f"{servidor.url}/portal/cuenta")
    assert nueva.is_checked("input[name=aspecto-tema][value=dark]") and nueva.is_checked("input[name=aspecto-letra][value=muy-grande]")
    nueva.check("input[name=aspecto-tema][value=system]")
    nueva.check("input[name=aspecto-letra][value=normal]")
    nueva.goto(f"{servidor.url}/portal/")
    assert nueva.evaluate("document.documentElement.getAttribute('data-theme')") is None and nueva.evaluate("document.documentElement.getAttribute('data-letra')") is None
    ctx.close()


def test_el_contraste_del_texto_cumple_wcag_aa_en_claro_y_en_oscuro(servidor, abrir, entrar_como_equipo, chromium):
    for esquema in ("light", "dark"):
        ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, f"Portal contraste {esquema}", esquema)
        nueva.goto(f"{servidor.url}/portal/cuenta")
        medidas = nueva.evaluate(CONTRASTE)
        for nombre, razon in medidas.items():
            if razon is not None:
                assert razon >= 4.5, (esquema, nombre, razon, medidas)
        ctx.close()


def test_el_foco_del_teclado_se_ve_en_enlaces_y_botones(servidor, abrir, entrar_como_equipo, chromium):
    ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, "Portal foco")
    nueva.goto(f"{servidor.url}/portal/cuenta")
    nueva.focus(".portal-nav a >> nth=1")
    nueva.keyboard.press("Shift+Tab"); nueva.keyboard.press("Tab")
    ancho = nueva.evaluate("parseFloat(getComputedStyle(document.activeElement).outlineWidth)")
    assert ancho >= 2
    ctx.close()
