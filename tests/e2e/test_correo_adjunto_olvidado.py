"""Redactar: si el texto menciona un adjunto y no hay ninguno, se pregunta antes de enviar (app/static/correo_redactar_extra.js)."""
from app import db


def test_aviso_de_adjunto_olvidado(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho adjunto olvidado")
    pagina, errores = abrir()
    uid = entrar_como_equipo(pagina, "adjunto-e2e@ejemplo.com", despacho=t, direccion=True)
    db.crear_cuenta_correo(uid, "info@despacho.es", "imap", "imap.ejemplo.com", 993, "info@despacho.es", smtp_host="smtp.ejemplo.com", smtp_puerto=587)

    pagina.goto(f"{servidor.url}/correo/redactar")
    pagina.wait_for_load_state("networkidle")
    pagina.fill("input[name=destinatarios]", "cliente@ejemplo.com")
    pagina.fill("input[name=asunto]", "Documentación")
    pagina.click("#correo-editor-cuerpo")
    pagina.keyboard.type("Hola, te adjunto el modelo 303.")
    pagina.get_by_role("button", name="Enviar", exact=True).click()
    dialogo = pagina.locator("dialog[open]")
    dialogo.wait_for()
    assert "adjunto" in dialogo.inner_text().lower()
    dialogo.get_by_role("button", name="Cancelar").click()
    assert pagina.url.endswith("/correo/redactar") and not errores                          # no se envió

    pagina.locator("#correo-editor-cuerpo").fill("Hola, sin nada más que decir.")
    pagina.get_by_role("button", name="Enviar", exact=True).click()
    pagina.wait_for_timeout(400)
    assert pagina.locator("dialog[open]").count() == 0                                      # sin mención: no hay aviso
