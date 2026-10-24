"""BARRIDO DE UX/UI (no forma parte del repositorio): recorre las pantallas con un navegador real, en escritorio y móvil, y mide desbordes, objetivos táctiles, etiquetas y accesibilidad (axe-core)."""
import json
import os
import pathlib
import threading
import time

import pytest

from app import db

SALIDA = pathlib.Path(os.environ["UX_SALIDA"])
AXE = pathlib.Path(os.environ["UX_AXE"]).read_text()

PAGINAS_APP = [
    "/", "/hoy/", "/tareas/", "/tareas/hoy", "/tareas/tablero", "/tareas/calendario", "/tareas/carga", "/tareas/recurrentes", "/tareas/plantillas", "/tareas/automatizaciones", "/tareas/informes",
    "/notas", "/correo/", "/correo/cuentas", "/correo/ajustes", "/correo/redactar", "/correo/programados",
    "/fiscal/panel", "/fiscal/vencimientos", "/fiscal/vencimientos/calendario", "/fiscal/clientes", "/fiscal/avisos", "/fiscal/expedientes", "/fiscal/traspasos", "/fiscal/oficinas", "/fiscal/flujo",
    "/fichaje/", "/fichaje/historial", "/fichaje/ausencias", "/fichaje/turnos", "/fichaje/bolsa", "/fichaje/admin",
    "/clientes/", "/clientes/nuevo", "/expedientes/", "/plazos/", "/tiempo/", "/contactos/", "/citas/",
    "/herramientas", "/ia/", "/ia/ajustes", "/ajustes", "/ajustes/perfil", "/ajustes/cuenta", "/mis-dispositivos", "/seguridad/cifrado", "/seguridad/privacidad",
    "/estadisticas", "/historial", "/papelera", "/importar", "/clientes/importar/", "/tiquets/", "/tiquets/kanban", "/videollamadas/",
    "/certificados/", "/comercial/", "/comercial/reuniones", "/contabilidad/", "/abogados/", "/inmobiliaria/", "/juridico/", "/marca/",
]
PAGINAS_PUBLICAS = ["/login", "/registro", "/recuperar-contrasena", "/portal/solicitar-acceso", "/docs/"]
VISTAS = {"escritorio": {"width": 1366, "height": 800}, "movil": {"width": 390, "height": 844}}

JS_MEDIDAS = """() => {
  const vw = innerWidth;
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const tocables = [...document.querySelectorAll('button, input:not([type=hidden]), select, textarea, [role=button], a.btn, a.boton, nav a, .tabs a')].filter(vis);
  const pequenos = tocables.filter(e => { const r = e.getBoundingClientRect(); return r.width < 40 || r.height < 40; });
  const anchos = [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect(); return r.right > vw + 2 && vis(e) && getComputedStyle(e).position !== 'fixed'; }).slice(0, 4).map(e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\\s+/).slice(0, 2).join('.') : ''));
  const sinAlt = [...document.images].filter(i => !i.hasAttribute('alt')).length;
  const tamanos = [...document.querySelectorAll('p, td, li, label, span, a')].filter(vis).slice(0, 400).map(e => parseFloat(getComputedStyle(e).fontSize));
  return {titulo: document.title, lang: document.documentElement.lang, h1: document.querySelectorAll('h1').length, desborde: document.documentElement.scrollWidth - vw, anchos,
          tocables: tocables.length, pequenos: pequenos.length, ejemplos_pequenos: pequenos.slice(0, 4).map(e => (e.tagName + ' ' + (e.innerText || e.getAttribute('aria-label') || e.name || e.type || '').trim().slice(0, 30))),
          sinAlt, texto_min: tamanos.length ? Math.min(...tamanos) : null, alto: document.body.scrollHeight};
}"""

JS_AXE = """async () => {
  const r = await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']}});
  return r.violations.map(v => ({id: v.id, impacto: v.impact, nodos: v.nodes.length, ayuda: v.help, ejemplo: (v.nodes[0] && v.nodes[0].target || []).join(' ').slice(0, 120), html: (v.nodes[0] && v.nodes[0].html || '').slice(0, 160)}));
}"""


def _recorrer(contexto, base, rutas, etiqueta, resultados, axe=True, prefijo=""):
    pagina = contexto.new_page()
    errores = []
    pagina.on("pageerror", lambda e: errores.append(f"JS: {e}"))
    pagina.on("console", lambda m: errores.append(f"consola: {m.text[:160]}") if m.type == "error" else None)
    for ruta in rutas:
        errores.clear()
        inicio = time.time()
        try:
            resp = pagina.goto(base + ruta, wait_until="load", timeout=20000)
            try:
                pagina.wait_for_load_state("networkidle", timeout=4000)
            except Exception:                                                  # noqa: BLE001
                pass
            estado = resp.status if resp else None
            medidas = pagina.evaluate(JS_MEDIDAS)
            violaciones = []
            if axe:
                pagina.add_script_tag(content=AXE)
                violaciones = pagina.evaluate(JS_AXE)
            nombre = prefijo + (ruta.strip("/").replace("/", "_") or "inicio") + f"__{etiqueta}.jpg"
            pagina.screenshot(path=str(SALIDA / nombre), full_page=True, type="jpeg", quality=45)
            resultados.append({"ruta": ruta, "vista": etiqueta, "estado": estado, "final": pagina.url.replace(base, ""), "ms": int((time.time() - inicio) * 1000), "errores": list(errores), "medidas": medidas, "axe": violaciones, "img": nombre})
        except Exception as e:                                                 # noqa: BLE001
            resultados.append({"ruta": ruta, "vista": etiqueta, "estado": "ERROR", "error": str(e)[:200]})
    pagina.close()


def test_barrido_app(servidor, chromium, entrar_como_equipo):
    SALIDA.mkdir(parents=True, exist_ok=True)
    t = db.crear_tenant("Gestoría Demo")
    ctx0 = chromium.new_context(viewport=VISTAS["escritorio"], bypass_csp=True)
    p0 = ctx0.new_page()
    uid = entrar_como_equipo(p0, "ux-direccion@ejemplo.com", despacho=t, direccion=True)
    otro = db.crear_usuario_vinculado_a_kratos("ux-otro@ejemplo.com", "k-ux-otro")
    db.asignar_tenant(otro, t)
    ahora = time.strftime("%Y-%m-%dT%H:%M:%S")
    dias = lambda n: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + n * 86400))  # noqa: E731
    clientes = [db.crear_cliente_fiscal(t, n, email=f"c{i}@cli.com") for i, n in enumerate(["Talleres Soler SL", "María Pons Vidal", "Construccions Ferrer SA", "Panadería Can Roca", "Clínica Dental Mar", "Asesoría Nord SCP"])]
    conn = db.get_connection()
    cat = conn.execute("INSERT INTO categorias (usuario_id, nombre, color, creada_en) VALUES (?,?,?,?)", (uid, "Cierre trimestral", "#4a6cf7", ahora)).lastrowid
    for k, asunto in enumerate(["Reunir facturas del 3T", "Presentar modelo 303", "Llamar a Talleres Soler", "Revisar nóminas de octubre", "Renovar certificado de María", "Preparar el IVA del cuarto trimestre con todas las facturas pendientes del cliente"]):
        conn.execute("INSERT INTO tareas_outlook (usuario_id, asunto, estado, prioridad, fecha_vencimiento, creada_en, actualizada_en, categoria_id, cliente_fiscal_id) VALUES (?,?,?,?,?,?,?,?,?)",
                     (uid, asunto, ["no_iniciada", "en_progreso", "completada", "esperando"][k % 4], ["baja", "normal", "alta"][k % 3], dias(k - 2), ahora, ahora, cat, clientes[k % len(clientes)]))
    for k, (m, p) in enumerate([("303", "3T"), ("130", "3T"), ("111", "3T"), ("115", "3T"), ("390", "2025"), ("200", "2025")]):
        conn.execute("INSERT INTO vencimientos_fiscales (tenant_id, cliente_fiscal_id, usuario_id, modelo, periodo, fecha_limite, estado, creado_en) VALUES (?,?,?,?,?,?,?,?)",
                     (t, clientes[k % len(clientes)], uid, m, p, dias(k * 6 - 8)[:10], "presentado" if k == 5 else "pendiente", ahora))
    for k in range(4):
        conn.execute("INSERT INTO notas (usuario_id, texto, categoria_id, creada_en, titulo) VALUES (?,?,?,?,?)", (uid, "Recordar pedir el certificado de retenciones. " * (k + 1), cat, dias(-k), f"Nota {k}"))
    conn.commit()
    conn.close()
    resultados = []
    for etiqueta, vista in VISTAS.items():
        ctx = chromium.new_context(viewport=vista, bypass_csp=True, device_scale_factor=1, has_touch=(etiqueta == "movil"), is_mobile=(etiqueta == "movil"))
        ctx.add_cookies(ctx0.cookies())
        _recorrer(ctx, servidor.url, PAGINAS_APP, etiqueta, resultados)
        ctx.close()
        ctxp = chromium.new_context(viewport=vista, bypass_csp=True, has_touch=(etiqueta == "movil"), is_mobile=(etiqueta == "movil"))
        _recorrer(ctxp, servidor.url, PAGINAS_PUBLICAS, etiqueta, resultados)
        ctxp.close()
    ctx0.close()
    (SALIDA / "resultados_app.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=1))
    assert resultados


def test_barrido_backoffice(chromium, tmp_path, monkeypatch):
    from werkzeug.serving import make_server

    from backoffice import auth
    from backoffice.main import create_app
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "backoffice.db")
    monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "bo_secret.key")
    auth.crear_admin("jorge", "una-clave-larga-y-segura-1", "Jorge")
    from backoffice import aprovisionamiento
    monkeypatch.setattr(aprovisionamiento, "aprovisionar_usuario", lambda *a, **k: [])
    t1 = db.crear_tenant("Gestoría Demo")
    db.crear_tenant("Inmobiliaria Costa")
    app_bo = create_app(testing=True)
    servidor = make_server("127.0.0.1", 0, app_bo, threaded=True)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_port}"
    SALIDA.mkdir(parents=True, exist_ok=True)
    resultados = []
    rutas = ["/", "/tenants", f"/tenants/{t1}", "/planes", "/usuarios", "/actividad", "/mapa", "/journey", "/cuenta"]
    for etiqueta, vista in VISTAS.items():
        ctx = chromium.new_context(viewport=vista, bypass_csp=True, has_touch=(etiqueta == "movil"), is_mobile=(etiqueta == "movil"))
        pagina = ctx.new_page()
        pagina.goto(base + "/login")
        pagina.screenshot(path=str(SALIDA / f"bo_login__{etiqueta}.jpg"), full_page=True, type="jpeg", quality=45)
        pagina.fill("input[name=usuario]", "jorge")
        pagina.fill("input[name=contrasena]", "una-clave-larga-y-segura-1")
        pagina.click("button[type=submit]")
        pagina.wait_for_load_state()
        pagina.close()
        pre = []
        _recorrer(ctx, base, rutas, etiqueta, pre, prefijo="bo_")
        for r in pre:
            r["ruta"] = "BO" + r["ruta"]
        resultados += pre
        ctx.close()
    servidor.shutdown()
    (SALIDA / "resultados_bo.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=1))
    assert resultados
