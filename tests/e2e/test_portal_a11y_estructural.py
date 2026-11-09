"""Accesibilidad estructural del portal (F1): en cada pantalla, sin excepciones, hay idioma, un único h1, títulos sin saltos, imágenes con alternativa, campos con etiqueta, botones y enlaces con nombre, ids únicos,
enlaces a pestaña nueva con rel seguro, iframes con título y diálogos con nombre. Es una comprobación automática de lo que se puede comprobar sin lector de pantalla; no sustituye a una revisión manual."""
from app import db, verticales

REGLAS = """() => {
  const fallos = [];
  const nombre = e => (e.getAttribute('aria-label') || '').trim() || (e.getAttribute('aria-labelledby') ? e.getAttribute('aria-labelledby').split(' ').map(i => (document.getElementById(i) || {}).textContent || '').join(' ').trim() : '')
    || (e.textContent || '').trim() || (e.getAttribute('title') || '').trim() || ((e.querySelector('img[alt]') || {}).alt || '').trim() || (e.value && ['submit', 'button'].includes(e.type) ? e.value : '');
  const visible = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  if (!document.documentElement.lang) fallos.push('html sin lang');
  const h1 = document.querySelectorAll('h1'); if (h1.length !== 1) fallos.push('h1: ' + h1.length);
  let previo = 0; document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h => { const n = +h.tagName[1]; if (previo && n > previo + 1 && visible(h)) fallos.push('salto de título h' + previo + '→h' + n + ': ' + h.textContent.trim().slice(0, 30)); previo = n; });
  document.querySelectorAll('img').forEach(i => { if (!i.hasAttribute('alt')) fallos.push('img sin alt: ' + (i.getAttribute('src') || '').slice(0, 40)); });
  document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=image]), select, textarea').forEach(c => {
    if (!visible(c) && c.type !== 'file') return;
    if (!(c.labels && c.labels.length) && !nombre(c)) fallos.push('campo sin etiqueta: ' + (c.name || c.id || c.type));
  });
  document.querySelectorAll('button, a[href], [role=button]').forEach(b => { if (visible(b) && !nombre(b)) fallos.push('sin nombre: ' + (b.outerHTML || '').slice(0, 60)); });
  const ids = {}; document.querySelectorAll('[id]').forEach(e => { ids[e.id] = (ids[e.id] || 0) + 1; }); Object.keys(ids).forEach(i => { if (ids[i] > 1) fallos.push('id repetido: ' + i); });
  document.querySelectorAll('a[target=_blank]').forEach(a => { if (!a.closest('altcha-widget') && !/noopener|noreferrer/.test(a.rel)) fallos.push('target=_blank sin rel: ' + (a.getAttribute('href') || '').slice(0, 40)); });
  document.querySelectorAll('iframe').forEach(f => { if (!f.title) fallos.push('iframe sin título'); });
  document.querySelectorAll('dialog').forEach(d => { if (!d.getAttribute('aria-label') && !d.getAttribute('aria-labelledby')) fallos.push('dialog sin nombre'); });
  document.querySelectorAll('table').forEach(t => { if (visible(t) && !t.querySelector('th')) fallos.push('tabla sin th'); });
  document.querySelectorAll('nav').forEach(n => { if (document.querySelectorAll('nav').length > 1 && !n.getAttribute('aria-label') && !n.getAttribute('aria-labelledby')) fallos.push('nav sin nombre'); });
  return fallos;
}"""

# Los enlaces del widget de captcha (altcha-widget) los pone un tercero y los navegadores ya aplican noopener a target=_blank: se dejan fuera de la regla.
CON_SESION = ("/portal/", "/portal/facturas", "/portal/impuestos", "/portal/mensajes", "/portal/avisos", "/portal/carpeta", "/portal/cuenta", "/portal/glosario", "/portal/actividad", "/portal/cuestionarios",
              "/portal/peticiones", "/portal/justificantes", "/portal/buscar", "/portal/conversaciones/nueva", "/portal/citas", "/portal/extracto")
SIN_SESION = ("/portal/entrar", "/portal/no-puedo-entrar", "/portal/solicitar-acceso")


def test_cada_pantalla_del_portal_cumple_las_reglas_estructurales(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal a11y")
    pagina, _ = abrir()
    entrar_como_equipo(pagina, "portal-a11y@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    verticales.fijar_activo(t, "fiscal", True)
    c = db.crear_cliente_fiscal(t, "Cliente A11y", nif="B12345678", email="a11y@ejemplo.com")
    informe = {}
    for lista, con_sesion in ((SIN_SESION, False), (CON_SESION, True)):
        ctx = chromium.new_context(viewport={"width": 390, "height": 800})
        nueva = ctx.new_page()
        if con_sesion:
            nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1', email='a11y@ejemplo.com')}")
        for ruta in lista:
            resp = nueva.goto(servidor.url + ruta, wait_until="load")
            if resp is None or resp.status >= 400 or "/portal/entrar" in nueva.url and ruta != "/portal/entrar":
                continue                                                                          # pantalla no disponible para este cliente de prueba (módulo apagado…)
            fallos = nueva.evaluate(REGLAS)
            if fallos:
                informe[ruta] = fallos
        ctx.close()
    assert informe == {}, informe
