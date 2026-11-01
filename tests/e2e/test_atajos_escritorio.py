"""Atajos de una tecla y navegación por listas de la versión de escritorio (app/static/ux_v2.js)."""
from datetime import date

from app import db


def test_g_h_navega_y_j_x_recorren_y_completan_tareas(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho atajos")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "atajos@ejemplo.com", despacho=t, direccion=True)
    a = db.crear_tarea_outlook(uid, asunto="Primera tarea", fecha_vencimiento=date.today().isoformat())
    db.crear_tarea_outlook(uid, asunto="Segunda tarea", fecha_vencimiento=date.today().isoformat())

    pagina.goto(f"{servidor.url}/tareas/")
    pagina.wait_for_load_state("networkidle")
    pagina.keyboard.press("j")
    assert pagina.locator(".tarea-fila.fila-foco").count() == 1
    pagina.keyboard.press("j")
    assert "Segunda" in pagina.locator(".tarea-fila.fila-foco").inner_text()
    pagina.keyboard.press("k")
    assert "Primera" in pagina.locator(".tarea-fila.fila-foco").inner_text()

    pagina.keyboard.press("g")
    pagina.keyboard.press("h")
    pagina.wait_for_url("**/hoy/")

    pagina.goto(f"{servidor.url}/tareas/")
    pagina.wait_for_load_state("networkidle")
    pagina.keyboard.press("n")
    pagina.wait_for_url("**/tareas/?nueva=1")
    assert not [e for e in errores if "TypeError" in e or "ReferenceError" in e]


def test_paleta_ctrl_k_ofrece_ir_a_y_acciones(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho paleta")
    pagina, errores = abrir()
    entrar_como_equipo(pagina, "paleta@ejemplo.com", despacho=t, direccion=True)
    pagina.goto(f"{servidor.url}/hoy/")
    pagina.wait_for_load_state("networkidle")

    pagina.keyboard.press("Control+k")
    pagina.wait_for_selector("#busqueda-resultados .busqueda-comando")
    assert pagina.locator("#busqueda-resultados .busqueda-grupo").count() == 2
    assert "tarea" in pagina.locator("#busqueda-resultados").inner_text().lower()

    pagina.fill("#busqueda-input", "ir a notas")
    pagina.wait_for_selector("#busqueda-resultados .busqueda-comando")
    pagina.keyboard.press("ArrowDown")
    pagina.keyboard.press("Enter")
    pagina.wait_for_url("**/notas**")

    pagina.keyboard.press("Control+k")
    pagina.fill("#busqueda-input", "tema")
    pagina.wait_for_selector('[data-accion="tema"]')
    pagina.click('[data-accion="tema"]')
    assert pagina.evaluate("localStorage.getItem('guilda-work-tema')") == "light"
    assert not [e for e in errores if "TypeError" in e or "ReferenceError" in e]
