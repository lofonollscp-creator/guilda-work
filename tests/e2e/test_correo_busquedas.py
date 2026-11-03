"""Bandeja de correo: búsquedas guardadas en el navegador (app/static/correo_busquedas.js)."""
from app import db


def test_guardar_aplicar_y_quitar_una_busqueda(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho búsquedas")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "busquedas-e2e@ejemplo.com", despacho=t, direccion=True)
    cuenta = db.crear_cuenta_correo(uid, "info@despacho.es", "imap", "imap.ejemplo.com", 993, "info@despacho.es")
    db.guardar_mensaje_correo(cuenta, "u1", "Factura de octubre", "ana@ejemplo.com", "info@despacho.es", "2026-10-02T09:00:00", "texto", None)
    db.guardar_mensaje_correo(cuenta, "u2", "Otra cosa", "luis@ejemplo.com", "info@despacho.es", "2026-10-03T09:00:00", "texto", None)

    pagina.goto(f"{servidor.url}/correo/?cuenta_id={cuenta}&q=de:ana")
    pagina.wait_for_load_state("networkidle")
    assert pagina.locator(".correo-fila-check").count() == 1
    pagina.get_by_role("button", name="Búsquedas").click()
    assert pagina.locator(".correo-busquedas-guardar").is_enabled()
    pagina.locator(".correo-busquedas-guardar").click()
    pagina.locator("dialog[open] input").fill("De Ana")
    pagina.locator("dialog[open]").get_by_role("button", name="Aceptar").click()
    assert pagina.locator(".correo-busquedas-ir", has_text="De Ana").count() == 1

    pagina.goto(f"{servidor.url}/correo/?cuenta_id={cuenta}")                              # sin búsqueda: se ven los dos
    pagina.wait_for_load_state("networkidle")
    assert pagina.locator(".correo-fila-check").count() == 2
    pagina.get_by_role("button", name="Búsquedas").click()
    pagina.locator(".correo-busquedas-ir", has_text="De Ana").click()
    pagina.wait_for_url("**q=*")
    pagina.wait_for_load_state("networkidle")
    assert pagina.locator(".correo-fila-check").count() == 1                              # la búsqueda guardada se aplicó

    pagina.get_by_role("button", name="Búsquedas").click()
    pagina.locator(".correo-busquedas-quitar").click()
    assert pagina.locator(".correo-busquedas-ir").count() == 0
    assert not errores
