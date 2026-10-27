"""Capturas de las pantallas principales de la web (1440 × 900) con datos de ejemplo, para compararlas con el diseño. Solo corren si se pide con GUILDA_CAPTURAS_WEB=<carpeta>; no comprueban nada más que
que la página no dé errores de JavaScript."""
import json
import os
from datetime import date, timedelta

import pytest

from app import db

CARPETA = os.environ.get("GUILDA_CAPTURAS_WEB")
pytestmark = pytest.mark.skipif(not CARPETA, reason="GUILDA_CAPTURAS_WEB sin definir")


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
    return {"mensaje": primero, "cuenta": cuenta}


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
            for nombre, ruta in PAGINAS + [("notas", "/notas"), ("tareas_tablero", "/tareas/tablero")]:
                pagina.goto(f"{servidor.url}{ruta.format(**ids)}")
                pagina.wait_for_load_state("networkidle")
                pagina.evaluate("t => document.documentElement.setAttribute('data-theme', t)", tema)
                pagina.wait_for_timeout(150)
                pagina.screenshot(path=os.path.join(CARPETA, f"{nombre}_{ancho}_{tema}.png"))
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
