"""Portal, subida de facturas: la foto torcida recibe la propuesta de la enderezada, con vista previa, y el cliente decide (app/static/portal_facturas_subida.js)."""
import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from app import db, facturas_contables as fc, verticales
from tests.test_enderezar_documento import _foto


def test_la_foto_torcida_ofrece_la_enderezada_y_se_puede_usar_o_dejar(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal enderezar")
    pagina, _ = abrir()
    entrar_como_equipo(pagina, "portal-enderezar@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Enderezar", email="enderezar@ejemplo.com")
    ctx = chromium.new_context(viewport={"width": 390, "height": 800})
    errores = []
    nueva = ctx.new_page()
    nueva.on("pageerror", lambda e: errores.append(str(e)))
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    nueva.goto(f"{servidor.url}/portal/facturas")
    nueva.wait_for_load_state("networkidle")
    foto = _foto()
    nueva.set_input_files("#form-subida input[type=file]", [{"name": "ticket.jpg", "mimeType": "image/jpeg", "buffer": foto}])
    nueva.wait_for_selector(".portal-enderezar", timeout=15000)
    assert nueva.locator(".portal-enderezar img").get_attribute("alt") == "" and "enderezada" in nueva.locator(".portal-enderezar").inner_text().lower()
    antes = nueva.evaluate("document.querySelector('#form-subida input[type=file]').files[0].size")
    nueva.get_by_role("button", name="Usar la enderezada").click()
    nueva.wait_for_function("document.querySelector('.portal-enderezar') && document.querySelector('.portal-enderezar').textContent.indexOf('Hecho') >= 0")
    despues = nueva.evaluate("[document.querySelector('#form-subida input[type=file]').files.length, document.querySelector('#form-subida input[type=file]').files[0].name]")
    assert despues[0] == 1 and despues[1] == "ticket.jpg"
    nueva.set_input_files("#form-subida input[type=file]", [{"name": "otra.jpg", "mimeType": "image/jpeg", "buffer": foto}])
    nueva.wait_for_selector(".portal-enderezar button.btn-ghost", timeout=15000)
    nueva.locator(".portal-enderezar button.btn-ghost").click()
    assert nueva.locator(".portal-enderezar").count() == 0
    assert errores == []
