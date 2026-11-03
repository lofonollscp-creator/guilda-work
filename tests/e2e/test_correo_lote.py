"""Bandeja de correo: seleccionar todo, rango con Mayús y barra de acciones en lote (app/static/correo_seleccion.js)."""
from app import db


def test_seleccion_en_lote_con_todo_rango_y_posponer(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho lote e2e")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "lote-e2e@ejemplo.com", despacho=t, direccion=True)
    cuenta = db.crear_cuenta_correo(uid, "info@despacho.es", "imap", "imap.ejemplo.com", 993, "info@despacho.es")
    ids = [db.guardar_mensaje_correo(cuenta, f"u{i}", f"Asunto {i}", "cliente@ejemplo.com", "info@despacho.es", f"2026-11-0{i}T09:00:00", "texto", None) for i in range(1, 6)]

    pagina.goto(f"{servidor.url}/correo/?cuenta_id={cuenta}")
    pagina.wait_for_load_state("networkidle")
    casillas = pagina.locator(".correo-fila-check")
    assert casillas.count() == 5 and pagina.locator("#correo-bulkbar").is_hidden()

    casillas.nth(1).click()
    casillas.nth(3).click(modifiers=["Shift"])                                    # Mayús: de la segunda a la cuarta
    assert [casillas.nth(i).is_checked() for i in range(5)] == [False, True, True, True, False]
    assert pagina.locator("#correo-bulkbar").is_visible() and "3" in pagina.locator("#correo-bulkbar-cuenta").inner_text()
    assert pagina.locator("#correo-seleccionar-todo").evaluate("e => e.indeterminate")

    pagina.locator("#correo-seleccionar-todo").check()
    assert all(casillas.nth(i).is_checked() for i in range(5))

    pagina.locator("#correo-seleccionar-todo").uncheck()
    casillas.nth(0).check()
    casillas.nth(2).check()
    pagina.locator("[data-accion-cambio=posponer]").select_option("manana")
    pagina.wait_for_load_state("networkidle")
    pagina.wait_for_timeout(300)
    pospuestos = [i for i in ids if db.obtener_mensaje_correo(i)["pospuesto_hasta"]]
    assert len(pospuestos) == 2 and all(db.obtener_mensaje_correo(i)["pospuesto_hasta"].endswith("T09:00") for i in pospuestos)
    assert pagina.locator(".correo-fila-check").count() == 3                      # los pospuestos salen de la lista
    assert not errores
