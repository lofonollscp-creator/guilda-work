"""Portal como webapp (G): barra inferior en el móvil, invitación a instalar, pantalla sin conexión con cola de envío y service worker que la sirve."""
from app import db, verticales

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _entrar(servidor, abrir, entrar_como_equipo, chromium, nombre, ancho=390):
    t = db.crear_tenant(nombre)
    pagina, _ = abrir()
    entrar_como_equipo(pagina, f"{nombre.replace(' ', '')}@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Webapp", email="webapp@ejemplo.com")
    ctx = chromium.new_context(viewport={"width": ancho, "height": 800})
    nueva = ctx.new_page()
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    return ctx, nueva


def test_en_el_movil_la_navegacion_es_la_barra_inferior_y_en_el_pc_la_de_arriba(servidor, abrir, entrar_como_equipo, chromium):
    ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, "Webapp tabs")
    nueva.goto(f"{servidor.url}/portal/")
    assert nueva.locator(".portal-tabs").is_visible() and nueva.locator(".portal-nav").is_hidden()
    assert nueva.locator(".portal-tabs-subir").is_visible()
    assert nueva.locator(".portal-tabs").evaluate("e => getComputedStyle(e).position") == "fixed"
    nueva.locator(".portal-tabs-mas summary").click()
    assert nueva.locator(".portal-tabs-panel").is_visible()
    nueva.keyboard.press("Escape")
    assert nueva.locator(".portal-tabs-panel").is_hidden()
    nueva.locator(".portal-tabs-mas summary").click()
    nueva.locator(".portal-tabs-panel a", has_text="Carpeta").click()
    nueva.wait_for_url("**/portal/carpeta")
    nueva.set_viewport_size({"width": 1280, "height": 800})
    assert nueva.locator(".portal-tabs").is_hidden() and nueva.locator(".portal-nav").is_visible()
    ctx.close()


def test_la_invitacion_a_instalar_sale_en_la_segunda_visita_y_se_puede_descartar(servidor, abrir, entrar_como_equipo, chromium):
    ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, "Webapp instalar")
    nueva.evaluate("localStorage.clear()")                                                          # la entrada ya contó una visita: se empieza de cero
    nueva.goto(f"{servidor.url}/portal/")
    nueva.evaluate("window.dispatchEvent(Object.assign(new Event('beforeinstallprompt'), { prompt() {}, userChoice: Promise.resolve({ outcome: 'dismissed' }) }))")
    assert nueva.locator("[data-instalar]").is_hidden()                                           # primera visita: no se molesta
    nueva.goto(f"{servidor.url}/portal/carpeta")
    nueva.evaluate("window.dispatchEvent(Object.assign(new Event('beforeinstallprompt'), { prompt() {}, userChoice: Promise.resolve({ outcome: 'dismissed' }) }))")
    assert nueva.locator("[data-instalar]").is_visible() and nueva.locator("[data-instalar-boton]").is_visible()
    nueva.locator("[data-instalar-cerrar]").click()
    nueva.goto(f"{servidor.url}/portal/")
    nueva.evaluate("window.dispatchEvent(Object.assign(new Event('beforeinstallprompt'), { prompt() {}, userChoice: Promise.resolve({ outcome: 'dismissed' }) }))")
    assert nueva.locator("[data-instalar]").is_hidden()                                           # descartada: 30 días sin volver a salir
    ctx.close()


def test_sin_conexion_el_service_worker_enseña_la_pantalla_con_la_cola_de_envio(servidor, abrir, entrar_como_equipo, chromium):
    ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, "Webapp offline")
    nueva.goto(f"{servidor.url}/portal/")
    nueva.wait_for_function("navigator.serviceWorker.ready.then(r => !!r.active)")
    nueva.wait_for_function("caches.open('gw-offline-1').then(c => c.match('/portal/sin-conexion')).then(r => !!r)", timeout=15000)
    nueva.reload()                                                                                  # ya controlada por el service worker
    nueva.wait_for_function("!!navigator.serviceWorker.controller")
    ctx.set_offline(True)
    nueva.goto(f"{servidor.url}/portal/carpeta")
    assert "Sin conexión" in nueva.locator("h1").inner_text()
    nueva.set_input_files("#form-subida input[type=file]", [{"name": "sin-red.pdf", "mimeType": "application/pdf", "buffer": PDF + b"sw"}])
    nueva.get_by_role("button", name="Guardar para enviar").click()
    nueva.wait_for_function("document.getElementById('cola-offline').innerText.includes('Sin conexión')")
    assert nueva.evaluate("async () => (await window.__colaOffline.todos()).length") == 1
    ctx.set_offline(False)
    nueva.wait_for_function("document.getElementById('cola-offline').innerText.includes('Ya se ha enviado')", timeout=25000)
    ctx.close()


def test_el_manifiesto_trae_accesos_directos_y_el_icono_recibe_la_insignia(servidor, abrir, entrar_como_equipo, chromium):
    ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, "Webapp manifiesto")
    m = nueva.evaluate("fetch('/portal/manifest.webmanifest').then(r => r.json())")
    assert [a["url"] for a in m["shortcuts"]][:2] == ["/portal/facturas#form-subida", "/portal/"] and m["id"] == "/portal/" and m["scope"] == "/portal/"
    nueva.goto(f"{servidor.url}/portal/")
    assert nueva.locator("meta[name=portal-insignia]").get_attribute("content") == "0"
    ctx.close()


def test_en_el_pc_la_portada_va_a_dos_columnas_se_arrastra_y_pega_y_hay_atajos(servidor, abrir, entrar_como_equipo, chromium):
    ctx, nueva = _entrar(servidor, abrir, entrar_como_equipo, chromium, "Webapp pc", ancho=1280)
    errores = []
    nueva.on("pageerror", lambda e: errores.append(str(e)))
    nueva.goto(f"{servidor.url}/portal/")
    a, b = nueva.locator(".portal-col-principal").bounding_box(), nueva.locator(".portal-col-lateral").bounding_box()
    assert a["x"] + a["width"] <= b["x"] + 1 and nueva.locator(".portal-tabs").is_hidden()
    # atajos: «g f» va a Facturas, «?» abre la lista y Esc la cierra
    nueva.keyboard.press("g")
    nueva.keyboard.press("f")
    nueva.wait_for_url("**/portal/facturas")
    nueva.keyboard.press("?")
    assert nueva.locator("#portal-atajos").evaluate("d => d.open") is True
    nueva.keyboard.press("Escape")
    assert nueva.locator("#portal-atajos").evaluate("d => d.open") is False
    # arrastrar y pegar sobre el formulario de subida
    nueva.evaluate("""() => {
      const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array(3000)], 'arrastrada.pdf', { type: 'application/pdf' }));
      document.getElementById('form-subida').dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
    }""")
    nombres = nueva.evaluate("Array.from(document.querySelector('#form-subida input[type=file]').files).map(f => f.name)")
    assert nombres == ["arrastrada.pdf"]
    nueva.evaluate("""() => {
      const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array(3000)], 'image.png', { type: 'image/png' }));
      document.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
    }""")
    nombres = nueva.evaluate("Array.from(document.querySelector('#form-subida input[type=file]').files).map(f => f.name)")
    assert nombres[0] == "arrastrada.pdf" and len(nombres) == 2 and nombres[1].startswith("captura-")
    assert errores == []
    ctx.close()
