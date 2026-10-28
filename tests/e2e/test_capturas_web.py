"""Capturas de las pantallas principales de la web (1440 × 900) con datos de ejemplo, para compararlas con el diseño. Solo corren si se pide con GUILDA_CAPTURAS_WEB=<carpeta>; no comprueban nada más que
que la página no dé errores de JavaScript."""
import json
import os
from datetime import date, timedelta

import pytest

from app import db

CARPETA = os.environ.get("GUILDA_CAPTURAS_WEB")
pytestmark = pytest.mark.skipif(not CARPETA, reason="GUILDA_CAPTURAS_WEB sin definir")


CONTRASTE = """() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = ({r, g, b}) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const mezcla = (f, b) => ({r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1});
  const fondo = el => { const capas = []; for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.backgroundImage !== 'none' && !cs.backgroundImage.startsWith('linear-gradient(rgba')) return null; const c = parse(cs.backgroundColor); if (c && c.a > 0) { capas.push(c); if (c.a >= 1) break; } }
    let base = {r: 255, g: 255, b: 255, a: 1}; for (let i = capas.length - 1; i >= 0; i--) base = mezcla(capas[i], base); return base; };
  const out = [], vistos = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) {
    if (!n.textContent.trim()) continue; const el = n.parentElement; if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'OPTION'].includes(el.tagName)) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.3) continue;
    const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight) continue;
    const fg = parse(cs.color); const bg = fondo(el); if (!fg || !bg) continue;
    const f = mezcla(fg, bg), l1 = lum(f), l2 = lum(bg), ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const grande = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.66 && parseInt(cs.fontWeight) >= 700);
    if (ratio < (grande ? 3 : 4.5)) { const k = (el.className || el.tagName) + '|' + cs.color + '|' + ratio.toFixed(1); if (!vistos.has(k)) { vistos.add(k); out.push(ratio.toFixed(1) + ' ' + (el.className || el.tagName).toString().slice(0, 50) + ' «' + n.textContent.trim().slice(0, 28) + '»'); } }
  }
  return out.slice(0, 12);
}"""

DESBORDES = """() => {
  const W = document.documentElement.clientWidth, out = [];
  if (document.documentElement.scrollWidth > W + 1) out.push('PAGINA ' + document.documentElement.scrollWidth);
  for (const e of document.querySelectorAll('body *')) {
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const cs = getComputedStyle(e);
    if (cs.position === 'fixed' || cs.visibility === 'hidden') continue;
    let a = e.parentElement, recortado = false;
    while (a && a !== document.body) { const o = getComputedStyle(a).overflowX; if (o !== 'visible') { recortado = true; break; } a = a.parentElement; }
    if (recortado) continue;
    if (r.right > W + 1 && !e.closest('[hidden],dialog:not([open]),details:not([open])>*:not(summary)')) out.push((e.className || e.tagName).toString().slice(0, 40) + '@' + Math.round(r.right));
    else if (e.scrollWidth > e.clientWidth + 2 && false) out.push('TXT ' + (e.className || e.tagName).toString().slice(0, 40));
  }
  return out.slice(0, 8);
}"""


def _extra():
    """Rutas adicionales: GUILDA_RUTAS=/clientes,/tiquets (el nombre del fichero sale de la ruta)."""
    return [(r.strip("/").replace("/", "_") or "raiz", r) for r in os.environ.get("GUILDA_RUTAS", "").split(",") if r]


def _dia(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _sembrar(uid: int, tenant: int) -> dict:
    c1 = db.crear_cliente_fiscal(tenant, "Construcciones Vidal", email="vidal@ejemplo.com")
    c2 = db.crear_cliente_fiscal(tenant, "Acme SL", email="acme@ejemplo.com")
    c3 = db.crear_cliente_fiscal(tenant, "Beta SA", email="beta@ejemplo.com")
    db.crear_tarea_outlook(uid, asunto="Presentar el modelo 303 · Construcciones Vidal", estado="en_progreso", prioridad="alta", fecha_vencimiento=_dia(0), cliente_fiscal_id=c1)
    db.crear_tarea_outlook(uid, asunto="Enviar factura de octubre a Hotel Mirador", prioridad="alta", fecha_vencimiento=_dia(-2))
    db.crear_tarea_outlook(uid, asunto="Llamar a la gestoría sobre la nómina", fecha_vencimiento=_dia(0))
    db.crear_tarea_outlook(uid, asunto="Revisar borrador de contrato", estado="en_progreso", prioridad="baja", fecha_vencimiento=_dia(0))
    db.crear_tarea_outlook(uid, asunto="Declaración de la renta de Beta SA", estado="esperando", fecha_vencimiento=_dia(12), cliente_fiscal_id=c3)
    db.crear_tarea_outlook(uid, asunto="Conciliar el banco de octubre", estado="en_progreso", fecha_vencimiento=_dia(3))
    db.crear_vencimiento_fiscal(tenant, c2, "303", "3T", _dia(-2), usuario_id=uid)
    db.crear_vencimiento_fiscal(tenant, c1, "303", "3T", _dia(0), usuario_id=uid)
    db.crear_vencimiento_fiscal(tenant, c3, "111", "3T", _dia(3), usuario_id=uid)
    db.crear_vencimiento_fiscal(tenant, c3, "115", "3T", _dia(3), usuario_id=uid)
    db.crear_vencimiento_fiscal(tenant, c1, "390", "2025", _dia(24), usuario_id=uid)
    db.agregar_mensaje_ia(uid, "user", "¿Qué me queda de Vidal esta semana y cuánto IVA les toca?")
    db.agregar_mensaje_ia(uid, "assistant", "Tienes **2 tareas abiertas** de Vidal; la urgente vence hoy a las 14:00. El 303 del trimestre sale a **1.284,50 € a ingresar**.",
                          fuentes_json=json.dumps([{"tipo": "tarea", "titulo": "Presentar modelo 303", "url": "/tareas/1"}, {"tipo": "vencimiento", "titulo": "303 · 3T · Vidal", "url": "/fiscal/vencimientos"}]))
    db.agregar_mensaje_ia(uid, "user", "Recuérdame llamar a Vidal mañana a las 10")
    cuenta = db.crear_cuenta_correo(uid, "info@despacho.es", "imap", "imap.ejemplo.com", 993, "info@despacho.es")
    for i, (de, asunto, texto, leido) in enumerate([
        ("Marta Ruiz <marta@ejemplo.com>", "Consulta sobre la renta", "Hola, quería preguntaros por la deducción de la vivienda habitual. Hasta 2022 vivíamos de alquiler y en 2023 compramos el piso. ¿Podemos aplicarla este año?", False),
        ("Hacienda <no-reply@aeat.es>", "Notificación electrónica pendiente", "Tiene una notificación pendiente de lectura en la sede electrónica.", False),
        ("Luis Mora <luis@ejemplo.com>", "Facturas de septiembre", "Adjunto las facturas del mes para que las contabilicéis.", True),
        ("Banco Norte <avisos@banco.example>", "Resumen de movimientos", "Su resumen mensual ya está disponible en la banca online.", True),
    ]):
        mid = db.guardar_mensaje_correo(cuenta, f"uid{i}", asunto, de, "info@despacho.es", f"2026-10-2{4 - i // 2}T0{9 - i}:30:00", texto, None, leido=leido)
        if i == 0:
            primero = mid
    p1 = db.crear_categoria(uid, "Cierre de trimestre", "#a6e600")
    p2 = db.crear_categoria(uid, "Auditoría Acme", "#6c63ff")
    db.crear_nota(uid, "Revisar con Marta la deducción por vivienda habitual.\n\n- Pedir escritura de compra\n- Comprobar si hay **alquiler** hasta 2022\n- Calcular el importe con el 303", categoria_id=p1, titulo="Consulta de Marta Ruiz", fijada=True)
    db.crear_nota(uid, "Llamar al banco para el certificado de saldos a 31 de diciembre.", categoria_id=p2, titulo="Certificado de saldos")
    db.crear_nota(uid, "Ideas para la reunión del lunes: plantillas de recordatorio, calendario compartido y avisos por WhatsApp.", titulo="Reunión del lunes")
    db.crear_tiquet(uid, "error", "El calendario fiscal no muestra el 115", "Al filtrar por cliente desaparece.")
    db.crear_tiquet(uid, "sugerencia", "Poder duplicar un vencimiento", None)
    for asunto, estado in (("Recoger extractos bancarios", "completada"), ("Conciliar IVA soportado", "en_progreso"), ("Preparar el 303", "no_iniciada"), ("Enviar borrador al cliente", "no_iniciada")):
        db.crear_tarea_outlook(uid, asunto=asunto, estado=estado, categoria_id=p1, fecha_vencimiento=_dia(2))
    try:
        from app import facturas_contables as fc, verticales
        verticales.fijar_activo(tenant, "contabilizacion", True)
        for tipo, n, quien, base in (("recibida", "F-2026-114", "Suministros Ríos SL", "1200"), ("emitida", "A-0031", "Construcciones Vidal", "3400"), ("recibida", "F-2026-121", "Gráficas Norte SA", "260,50")):
            fc.crear(tenant, uid, c1, {"tipo": tipo, "fecha": _dia(-3), "numero": n, "tercero_nombre": quien, "tercero_nif": "B12345678"}, [{"base": base, "pct_iva": "21"}])
    except Exception as e:                                            # solo es decorado de la captura
        print("SIN FACTURAS", e)
    db.guardar_fichaje_datos(uid, "Jorge Capturas", "12345678Z")
    db.fichar(uid, tenant, "entrada")
    return {"mensaje": primero, "cuenta": cuenta, "proyecto": p1}


PAGINAS = [
    ("hoy", "/hoy/"),
    ("tareas", "/tareas/"),
    ("correo", "/correo/"),
    ("correo_mensaje", "/correo/?cuenta_id={cuenta}&mensaje_id={mensaje}"),
    ("asistente", "/ia/"),
    ("fiscal_vencimientos", "/fiscal/vencimientos"),
]


def test_capturas(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho capturas")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "capturas@ejemplo.com", despacho=t, direccion=True)
    ids = _sembrar(uid, t)
    os.makedirs(CARPETA, exist_ok=True)
    pagina.set_viewport_size({"width": 1440, "height": 900})
    anchos = [int(a) for a in os.environ.get("GUILDA_ANCHOS", "1440").split(",")]
    temas = os.environ.get("GUILDA_TEMAS", "light").split(",")
    for ancho in anchos:
        pagina.set_viewport_size({"width": ancho, "height": 900})
        for tema in temas:
            for nombre, ruta in PAGINAS + [("notas", "/notas"), ("tareas_tablero", "/tareas/tablero")] + _extra():
                pagina.goto(f"{servidor.url}{ruta.format(**ids)}")
                pagina.wait_for_load_state("networkidle")
                if tema.startswith("sistema"):
                    pagina.emulate_media(color_scheme="dark" if tema.endswith("oscuro") else "light")
                    pagina.evaluate("() => document.documentElement.removeAttribute('data-theme')")
                else:
                    pagina.evaluate("t => document.documentElement.setAttribute('data-theme', t)", tema)
                pagina.wait_for_timeout(150)
                pagina.screenshot(path=os.path.join(CARPETA, f"{nombre}_{ancho}_{tema}.png"))
                if os.environ.get("GUILDA_CONTRASTE"):
                    for f in pagina.evaluate(CONTRASTE):
                        print(f"CONTRASTE {nombre} {ancho} {tema}: {f}")
                bordes = pagina.evaluate(DESBORDES)
                if bordes:
                    print(f"DESBORDE {nombre} {ancho}: {bordes}")
    if os.environ.get("GUILDA_DEPURAR_JS"):
        pagina.goto(f"{servidor.url}/correo/")
        print("DEPURAR", pagina.evaluate(os.environ["GUILDA_DEPURAR_JS"]))
    # Búsqueda global (Ctrl K)
    pagina.goto(f"{servidor.url}/hoy/")
    pagina.keyboard.press("Control+K")
    pagina.wait_for_timeout(300)
    pagina.keyboard.type("vidal")
    pagina.wait_for_timeout(1200)
    pagina.screenshot(path=os.path.join(CARPETA, "buscar.png"))
    print("\n".join(errores))
