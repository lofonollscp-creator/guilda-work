"""Autocompletado del alta rápida de tareas (app/static/alta_rapida.js): @personas, #proyectos y !prioridad, con teclado."""
from app import db


def test_el_alta_rapida_autocompleta_personas_proyectos_y_prioridad(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho autocompletado")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "autoc-e2e@ejemplo.com", despacho=t, direccion=True)
    luis = db.crear_usuario("luis.e2e@ejemplo.com", "contrasena123")
    db.asignar_tenant(luis, t)
    db.crear_categoria(uid, "Cierre trimestral")

    pagina.goto(f"{servidor.url}/tareas/")
    pagina.wait_for_load_state("networkidle")
    campo = pagina.locator("#tarea-alta-asunto")
    campo.click()
    campo.type("llamar @lu", delay=30)
    pagina.wait_for_selector(".alta-sugerencias:not([hidden]) .alta-sugerencia")
    assert pagina.locator(".alta-sugerencia").count() >= 1 and campo.get_attribute("aria-expanded") == "true"
    pagina.keyboard.press("Enter")
    assert campo.input_value().startswith("llamar @") and campo.input_value().endswith(" ")
    assert pagina.locator(".alta-sugerencias").is_hidden() and not campo.input_value().startswith("llamar @lu ")

    campo.type("#cier", delay=30)
    pagina.wait_for_selector(".alta-sugerencia")
    pagina.keyboard.press("ArrowDown")
    pagina.keyboard.press("Enter")
    assert '#"Cierre trimestral" ' in campo.input_value()

    campo.type("!a", delay=30)
    pagina.wait_for_selector(".alta-sugerencia")
    pagina.keyboard.press("Tab")
    assert campo.input_value().endswith("!alta ")

    campo.type("@zz", delay=30)                                              # sin coincidencias: no se queda un desplegable vacío
    pagina.wait_for_timeout(200)
    assert pagina.locator(".alta-sugerencias").is_hidden()
    pagina.keyboard.press("Escape")
    assert not errores


def test_cambiar_la_prioridad_y_la_fecha_en_la_propia_fila(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho edición en fila")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "enfila-e2e@ejemplo.com", despacho=t, direccion=True)
    tid = db.crear_tarea_outlook(uid, "Revisar extractos")

    pagina.goto(f"{servidor.url}/tareas/")
    pagina.wait_for_load_state("networkidle")
    fila = pagina.locator(f".tarea-fila[data-tarea-id='{tid}']")
    fila.hover()
    fila.locator("[data-edita=prioridad]").click()
    fila.locator("select.tarea-en-fila-control").select_option("alta")
    pagina.wait_for_function("(id) => document.querySelector(`.tarea-fila[data-tarea-id='${id}'] [data-edita=prioridad]`).textContent.trim() === 'Alta'", arg=tid)
    assert db.obtener_tarea_outlook(uid, tid)["prioridad"] == "alta"

    fila.locator("[data-edita=fecha_vencimiento]").click()
    fila.locator("input.tarea-en-fila-control").fill("2099-05-04")
    pagina.wait_for_function("(id) => /mayo|may/i.test(document.querySelector(`.tarea-fila[data-tarea-id='${id}'] [data-edita=fecha_vencimiento]`).textContent)", arg=tid)
    assert db.obtener_tarea_outlook(uid, tid)["fecha_vencimiento"].startswith("2099-05-04") and not errores
