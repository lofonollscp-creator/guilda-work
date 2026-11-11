"""«Preguntar al asistente sobre este cliente» (ficha del cliente): /ia/?q=… manda la pregunta al asistente una sola vez y limpia la dirección. Solo se comprueba que la pregunta llega al chat."""
from app import db


def test_la_pregunta_de_la_ficha_llega_al_chat(servidor, abrir, entrar_como_equipo):
    t = db.crear_tenant("Despacho prefill")
    pagina, _ = abrir()
    entrar_como_equipo(pagina, "prefill@ejemplo.com", despacho=t, direccion=True)
    pagina.goto(f"{servidor.url}/ia/?q=Resumen%20de%20Cliente%20Uno%20SL")
    pagina.wait_for_timeout(500)
    assert pagina.url.endswith("/ia/")                                          # la dirección se limpia: recargar no la reenvía
    assert "Resumen de Cliente Uno SL" in pagina.locator(".ia-chat").first.inner_text() or pagina.locator(".ia-chat textarea:visible").first.input_value() == "Resumen de Cliente Uno SL"
