"""Barrido del PORTAL DE CLIENTE (entrando con su enlace de un solo uso) y de las pantallas sin sesión (entrar, registro, recuperar contraseña): mismas medidas que `test_barrido_pantallas`. Solo con GUILDA_BARRIDO=<carpeta>; escribe informe-portal.json."""
import json
import os
from pathlib import Path

import pytest

from app import db
from tests.e2e.test_barrido_pantallas import MEDIR
from tests.e2e.test_capturas_web import _sembrar

CARPETA = os.environ.get("GUILDA_BARRIDO")
# Contraste AA (4,5:1; 3:1 en texto grande) de cada texto visible contra el fondo real que tiene detrás: sube por los ascendientes componiendo los fondos translúcidos. Devuelve los peores (máx. 6) con su selector.
CONTRASTE = """() => {
  const rgba = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const comp = (f, b) => [f[0] * f[3] + b[0] * (1 - f[3]), f[1] * f[3] + b[1] * (1 - f[3]), f[2] * f[3] + b[2] * (1 - f[3]), 1];
  const lum = (c) => { const v = c.slice(0, 3).map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const fondo = (el) => { let capas = []; for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e); if (s.backgroundImage !== 'none') return null; const c = rgba(s.backgroundColor); if (c && c[3] > 0) { capas.push(c); if (c[3] >= 1) break; } } let base = [255, 255, 255, 1]; if (capas.length && capas[capas.length - 1][3] < 1) capas.push(getComputedStyle(document.documentElement).colorScheme === 'dark' ? [10, 10, 12, 1] : [255, 255, 255, 1]); let r = capas.pop() || base; while (capas.length) r = comp(capas.pop(), r); return r; };
  const malos = [], visto = new Set();
  const it = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = it.nextNode());) {
    if (!n.nodeValue.trim()) continue; const el = n.parentElement; if (!el || visto.has(el)) continue; visto.add(el);
    const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) continue;
    const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1 || r.right <= 0 || r.bottom <= 0) continue;                // lo que está fuera de pantalla (enlace «Saltar al contenido») no cuenta hasta que recibe el foco
    if (el.closest('[hidden], [inert], dialog:not([open]), details:not([open]) > :not(summary)')) continue;
    const f = fondo(el); if (!f) continue; const t = rgba(s.color); if (!t) continue; const tc = comp(t, f);
    const l1 = lum(tc), l2 = lum(f), ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const grande = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && +s.fontWeight >= 700);
    if (ratio < (grande ? 3 : 4.5)) malos.push({ r: Math.round(ratio * 100) / 100, s: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/)[0] : ''), t: n.nodeValue.trim().slice(0, 24), c: s.color, f: f.slice(0, 3).map(Math.round).join(',') });
  }
  malos.sort((a, b) => a.r - b.r); return malos.slice(0, 6);
}"""
# Huella de estilos: por cada elemento de la página, su ruta y los estilos calculados que más se notan. Dos huellas iguales = la página se ve igual (sirve para mover CSS de sitio sin romper nada: GUILDA_HUELLA=<fichero.json>).
HUELLA = """() => Array.from(document.body.querySelectorAll('*')).map((e) => { const s = getComputedStyle(e); const r = e.getBoundingClientRect(); const ruta = e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\\s+/).join('.') : ''); return [ruta, s.color, s.backgroundColor, s.fontSize, s.fontWeight, s.display, s.position, s.margin, s.padding, s.border, s.borderRadius, s.boxShadow, s.gap, s.textAlign, s.opacity, Math.round(r.width), Math.round(r.height)].join('|'); })"""
pytestmark = pytest.mark.skipif(not CARPETA, reason="GUILDA_BARRIDO sin definir")
EXCLUIR = ("salir", "logout", "descargar", "export", "pdf", "csv", "static", "adjunto", "archivo", "borrar", "eliminar", "enviar", "manifest", "push", "comprobar")


def test_barrido_portal(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal barrido")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "portal-barrido@ejemplo.com", despacho=t, direccion=True)
    ids = _sembrar(uid, t)
    from datetime import date
    from app import facturas_contables as fc, facturas_portal, verticales
    verticales.fijar_activo(t, "contabilizacion", True)                       # el portal enseña sus facturas, la barra de secciones y el tablero
    hoy = date.today().isoformat()
    trimestre = fc.trimestre_de(hoy)
    v303 = db.crear_vencimiento_fiscal(t, ids["cliente"], "303", trimestre, hoy[:8] + "28", usuario_id=uid)
    db.crear_mensaje_vencimiento(v303, "empleado", "¿Nos mandas el extracto del banco del trimestre?", usuario_id=uid)
    nombres = ("Ferretería Paco", "Suministros Industriales del Levante, Sociedad Anónima", "ECLI:ES:TS:2099:12345ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    fids = [fc.crear_desde_portal(ids["cliente"], {"tipo": "recibida", "fecha": hoy, "numero": f"B-{i}", "tercero_nombre": n, "tercero_nif": "B11111111", "total": "121,00", "pct_iva": "21"}) for i, n in enumerate(nombres)]
    facturas_portal.devolver(t, uid, fids[1], "La foto sale movida y no se lee el NIF del proveedor; vuelve a hacerla con más luz y sin reflejos, por favor")
    facturas_portal.devolver(t, uid, fids[2], "No es de tu empresa")
    facturas_portal.escribir_como_cliente(ids["cliente"], fids[0], "¿Os hace falta algo más de esta factura? " * 6)
    facturas_portal.escribir_como_despacho(t, uid, fids[0], "Todo recibido, gracias; en cuanto la revisemos te avisamos desde aquí mismo.")
    from app import conformidad_declaracion, fiscal_nucleo as fn, fiscal_perfiles as fp
    from tests.escenarios_303 import ESCENARIOS
    verticales.fijar_activo(t, "fiscal", True)                                 # el portal enseña el modelo 303 que el despacho pide revisar
    try:
        fp.guardar_perfil(t, uid, ids["cliente"], {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    except fp.ErrorFiscal:                                                     # la siembra común puede haberlo creado ya
        pass
    for ap in ESCENARIOS["basico"][0]:
        try:
            fn.aprobar_apunte(t, uid, ids["cliente"], ap)
        except fp.ErrorFiscal:
            pass
    decl = fn.calcular_declaracion(t, uid, fn.crear_instantanea(t, uid, ids["cliente"], ejercicio=2026, periodo="2T")["id"])["id"]
    fn.revisar_declaracion(t, uid, decl)
    conformidad_declaracion.pedir(t, uid, decl)
    from app import justificantes
    justificantes.pedir(t, uid, ids["cliente"], [{"fecha": hoy, "importe": -31240, "concepto": "PAGO TARJETA FERRETERIA HERMANOS FERNANDEZ-VILLANUEVA DE LA VERA SOCIEDAD LIMITADA PROFESIONAL"}, {"fecha": hoy, "importe": 150000, "concepto": "TRANSFERENCIA CLIENTE X"}])
    j0 = justificantes.pendientes_del_cliente(ids["cliente"])[0]["id"]
    justificantes.responder(ids["cliente"], j0, "no_se", "No recuerdo qué era esto, lo miro y te cuento con más calma la semana que viene, gracias")
    conn = db.get_connection()
    conn.execute("UPDATE clientes_fiscales SET portal_honorarios = 1 WHERE id = ?", (ids["cliente"],))
    conn.execute("INSERT INTO honorarios_aplicados (tenant_id, vencimiento_id, cliente_fiscal_id, regla_nombre, concepto, importe_centimos, estado, confirmado_en) VALUES (?, ?, ?, 'Fija', 'Honorarios 303', 4500, 'confirmado', ?)",
                 (t, v303, ids["cliente"], db.now_iso()))
    conn.execute("UPDATE vencimientos_fiscales SET documenso_documento_id = 'env_barrido' WHERE id = ?", (v303,))
    conn.commit(); conn.close()
    db.subir_documento_vencimiento(v303, "justificante-presentacion-303-con-un-nombre-muy-largo-de-archivo.pdf", "application/pdf", b"%PDF-1.4\n%%EOF", origen="justificante")
    from app import portal_personas, portal_subida_rapida
    ficha = db.obtener_cliente_fiscal_por_id(ids["cliente"])
    conn = db.get_connection()
    conn.execute("UPDATE clientes_fiscales SET email = ? WHERE id = ?", ("titular-barrido@ejemplo.com", ids["cliente"]))
    conn.commit(); conn.close()
    ficha = db.obtener_cliente_fiscal_por_id(ids["cliente"])
    portal_personas.anadir(ficha, "administracion-con-un-nombre-de-correo-larguisimo@despacho-de-ejemplo-muy-largo.com", "Ana María Fernández-Villanueva de la Vera y Soto", "administracion")
    portal_personas.anadir(ficha, "asesor@ejemplo.com", "Asesor externo", "consulta")
    from app.db_fiscal import crear_cliente_fiscal
    crear_cliente_fiscal(t, "Segunda sociedad del mismo dueño, Sociedad Limitada Profesional", nif="B87654321", email="titular-barrido@ejemplo.com")
    token_subida = portal_subida_rapida.token_de(ficha)
    portal_subida_rapida.guardar_direccion_base(t, "facturas@despacho-de-ejemplo-muy-largo.com")
    token_preferencias = portal_personas.token_preferencias(ids["cliente"], "titular-barrido@ejemplo.com")
    for i, (fecha, tipo, total) in enumerate((("2026-02-10", "recibida", "121,00"), ("2026-03-10", "emitida", "242,00"), ("2025-08-10", "recibida", "60,50"), (hoy, "emitida", "363,00"))):
        fid = fc.crear_desde_portal(ids["cliente"], {"tipo": tipo, "fecha": fecha, "numero": f"S-{i}", "tercero_nombre": "Proveedor de la situación", "tercero_nif": "B11111111", "total": total, "pct_iva": "21"})
        conn = db.get_connection(); conn.execute("UPDATE facturas_contables SET estado = 'revisada' WHERE id = ?", (fid,)); conn.commit(); conn.close()
    conn = db.get_connection()
    conn.execute("UPDATE vencimientos_fiscales SET documento_solicitado = 'Extracto bancario completo del trimestre con todos los movimientos' WHERE id = ?", (v303,))
    conn.execute("INSERT INTO tareas_outlook (usuario_id, asunto, estado, porcentaje_completado, creada_en, actualizada_en, cliente_fiscal_id, visible_cliente, comentarios_cliente) VALUES (?, 'Preparar la declaración de la renta con un asunto bastante largo para ver cómo se parte', 'esperando', 40, '2026-10-01T10:00:00', '2026-11-03T09:00:00', ?, 1, 1)", (uid, ids["cliente"]))
    conn.commit(); conn.close()
    from app import portal_citas, portal_peticiones, portal_valoraciones
    from datetime import datetime, timedelta
    ficha_p = db.obtener_cliente_fiscal_por_id(ids["cliente"])
    pet_abierta = portal_peticiones.crear(ficha_p, "Extracto bancario completo del trimestre con todos los movimientos de todas las cuentas de la sociedad", "Necesitamos el de la cuenta principal y el de la de impuestos, en PDF o en CSV, con todos los movimientos del trimestre", (date.today() + timedelta(days=5)).isoformat(), por=uid)
    pet_cerrada = portal_peticiones.crear(ficha_p, "Escritura de constitución", por=uid)
    portal_peticiones.revisar(ficha_p, pet_cerrada, uid)
    portal_peticiones.reabrir(ficha_p, pet_cerrada, uid, "Falta la última página con las firmas de todos los socios, por favor súbela completa")
    portal_peticiones.revisar(ficha_p, pet_cerrada, uid)
    cita = portal_citas.solicitar(ficha_p, "titular-barrido@ejemplo.com", "videollamada", "Planificar el cierre del ejercicio y revisar las deducciones pendientes de la sociedad", "Martes o jueves por la mañana, mejor temprano")
    cita2 = portal_citas.solicitar(ficha_p, "titular-barrido@ejemplo.com", "visita", "Firmar unos documentos")
    portal_citas.confirmar(t, cita2, (datetime.now() + timedelta(days=4)).replace(hour=10, minute=0).isoformat(timespec="minutes"), "En la oficina de la calle Mayor, planta 2", uid)
    from app import portal_conversaciones
    conv = portal_conversaciones.iniciar(ficha_p, "Cambio de domicilio fiscal de la sociedad con efectos desde el próximo trimestre", "Nos mudamos a unas oficinas nuevas y necesitamos saber qué documentos hay que presentar y en qué plazo para no perder ninguna notificación", "cliente", "titular-barrido@ejemplo.com", peticion_id=pet_abierta)
    portal_conversaciones.responder(ficha_p, conv, "Hola. Hay que presentar el modelo 036 en el plazo de un mes desde el cambio. Si nos mandas la escritura o el contrato de alquiler de las nuevas oficinas lo preparamos nosotros", "despacho", "equipo@despacho.com")
    conv_cerrada = portal_conversaciones.iniciar(ficha_p, "Duda resuelta sobre el IVA", "¿Puedo deducir la factura del restaurante?", "despacho", "equipo@despacho.com")
    portal_conversaciones.cambiar_estado(ficha_p, conv_cerrada, abierta=False, por=uid)
    from app import portal_cuestionarios
    cuest = portal_cuestionarios.desde_plantilla(ficha_p, sorted(portal_cuestionarios.PLANTILLAS)[0], por=uid, fecha_limite=(date.today() + timedelta(days=5)).isoformat())
    cuest_largo = portal_cuestionarios.crear(ficha_p, "Cuestionario con un título larguísimo sobre el cambio de domicilio fiscal y de actividad de la sociedad", portal_cuestionarios.preguntas_desde_texto("¿Cuál es el nuevo domicilio completo de la sociedad, con calle, número, piso, código postal y municipio?\n¿Desde qué fecha exacta tiene efecto el cambio?"), por=uid)
    if os.environ.get("GUILDA_TEXTOS_LARGOS"):
        conn = db.get_connection()
        conn.execute("UPDATE clientes_fiscales SET nombre = ?", ("Construcciones y Reformas Hermanos Fernández-Villanueva de la Vera e Hijos Sociedad Limitada Profesional ECLI:ES:TS:2099:12345ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",))
        conn.commit()
        conn.close()
    if os.environ.get("GUILDA_PORTAL_NUEVO"):                                  # el mismo barrido con la navegación nueva y la marca del despacho
        from app import marca, portal_diseno
        portal_diseno.fijar(t, True)
        marca.guardar(t, nombre="Asesores Fernández-Villanueva y Asociados", color="#0a7d5a")
    rutas = sorted({r.rule for r in servidor.app.url_map.iter_rules() if r.rule.startswith("/portal") and "GET" in r.methods and not r.arguments and not any(x in r.rule.lower() for x in EXCLUIR)})
    rutas += [f"/portal/cuestionarios/{cuest}", f"/portal/cuestionarios/{cuest_largo}", f"/portal/conversaciones/nueva?peticion={pet_abierta}", f"/portal/conversaciones/{conv}", f"/portal/conversaciones/{conv_cerrada}", f"/portal/peticiones/{pet_abierta}", f"/portal/peticiones/{pet_cerrada}", f"/portal/facturas?trimestre={trimestre}", f"/portal/vencimientos/{v303}/documentos", f"/portal/vencimientos/{v303}/mensajes", f"/portal/facturas/{fids[0]}", f"/portal/facturas/{fids[1]}", f"/portal/declaraciones/{decl}", f"/portal/vencimientos/{v303}/firma", "/portal/justificantes", "/portal/buscar?q=ferreteria", "/portal/buscar?q=zzzz", f"/portal/preferencias/{token_preferencias}", f"/portal/subida/{token_subida}"]
    tema = os.environ.get("GUILDA_TEMA", "")                                   # claro | oscuro | sistema-oscuro | sistema-claro (vacío: como estaba)
    anonimas = ["/login", "/registro", "/recuperar-contrasena"]
    anchos = [int(a) for a in os.environ.get("GUILDA_ANCHOS", "375,768,1280").split(",")]
    lang = os.environ.get("GUILDA_IDIOMA", "es")
    informe = {}
    huellas = {}
    actual = {"k": ""}

    def recorrer(pg, lista, etiqueta):
        pg.context.set_extra_http_headers({"Accept-Language": lang})
        if tema in ("claro", "oscuro"):                                        # lo que guarda el selector de tema del portal (portal_aspecto.js)
            pg.context.add_init_script("try { localStorage.setItem('guilda-work-tema', '%s') } catch (e) {}" % ("dark" if tema == "oscuro" else "light"))
        pg.on("pageerror", lambda e: informe.setdefault(actual["k"], {}).setdefault("js", []).append(str(e)[:140]))
        for ancho in anchos:
            pg.set_viewport_size({"width": ancho, "height": 800})
            for ruta in lista:
                actual["k"] = f"{etiqueta}{ruta}@{ancho}"
                try:
                    resp = pg.goto(servidor.url + ruta, wait_until="load")
                    pg.wait_for_timeout(120)
                    m = pg.evaluate(MEDIR)
                except Exception as e:
                    informe.setdefault(actual["k"], {})["error"] = str(e).splitlines()[0][:120]
                    continue
                d = informe.setdefault(actual["k"], {})
                d["http"] = resp.status if resp else 0
                d["final"] = pg.url.replace(servidor.url, "")[:60]
                d.update({k: v for k, v in m.items() if v})
                if os.environ.get("GUILDA_HUELLA"):
                    huellas[actual["k"]] = pg.evaluate(HUELLA)
                if tema:
                    c = pg.evaluate(CONTRASTE)
                    if c:
                        d["contraste"] = c
                if os.environ.get("GUILDA_CAPTURAS") and etiqueta == "portal:" and ruta in ("/portal/", "/portal/facturas", "/portal/mensajes", "/portal/documentos", "/portal/impuestos"):
                    Path(os.environ["GUILDA_CAPTURAS"]).mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(Path(os.environ["GUILDA_CAPTURAS"]) / f"{ruta.strip('/').replace('/', '_') or 'portal'}-{ancho}.png"), full_page=bool(os.environ.get("GUILDA_CAPTURA_COMPLETA")))

    # sin sesión
    esquema = "dark" if tema in ("oscuro", "sistema-oscuro") else "light"
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800}, color_scheme=esquema)
    recorrer(ctx.new_page(), anonimas, "anon:")
    ctx.close()
    # cliente del portal con su enlace
    ctx = chromium.new_context(viewport={"width": 1280, "height": 800}, color_scheme=esquema)
    pg = ctx.new_page()
    pg.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(ids['cliente'], '127.0.0.1', email='titular-barrido@ejemplo.com')}")
    pg.wait_for_load_state("load")
    informe["entrada"] = {"final": pg.url.replace(servidor.url, "")}
    recorrer(pg, rutas, "portal:")
    ctx.close()
    Path(CARPETA).mkdir(parents=True, exist_ok=True)
    (Path(CARPETA) / "informe-portal.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    if os.environ.get("GUILDA_HUELLA"):
        Path(os.environ["GUILDA_HUELLA"]).write_text(json.dumps(huellas), encoding="utf-8")
    print("BARRIDO PORTAL:", len(rutas) + len(anonimas), "pantallas x", len(anchos), "anchos")
