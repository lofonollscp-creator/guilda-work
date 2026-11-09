"""Portal, carpeta del año: filtro sin recargar y vista previa del documento en un cuadro de diálogo (app/static/portal_carpeta.js)."""
from datetime import date

from app import db, verticales

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def test_la_carpeta_filtra_y_abre_la_vista_previa(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal carpeta")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "portal-carpeta@ejemplo.com", despacho=t, direccion=True)
    c = db.crear_cliente_fiscal(t, "Cliente Carpeta", email="carpeta@ejemplo.com")
    v = db.crear_vencimiento_fiscal(t, c, "303", "1T 2026", f"{date.today().year}-04-20", usuario_id=uid)
    db.subir_documento_vencimiento(v, "justificante-303.pdf", "application/pdf", PDF, origen="justificante")
    db.subir_documento_vencimiento(v, "constancia-303.pdf", "application/pdf", PDF + b"2", origen="constancia")
    ctx = chromium.new_context(viewport={"width": 390, "height": 800})
    errores = []
    nueva = ctx.new_page()
    nueva.on("pageerror", lambda e: errores.append(str(e)))
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    nueva.goto(f"{servidor.url}/portal/carpeta")
    nueva.wait_for_load_state("networkidle")
    assert nueva.locator("[data-doc]:visible").count() == 2
    nueva.select_option("[data-filtro-tipo]", "constancia")
    assert nueva.locator("[data-doc]:visible").count() == 1 and "constancia" in nueva.locator("[data-doc]:visible").inner_text()
    nueva.select_option("[data-filtro-tipo]", "")
    nueva.fill("[data-filtro-texto]", "JUSTIFICANTE")
    assert nueva.locator("[data-doc]:visible").count() == 1
    nueva.locator("[data-doc]:visible [data-ver]").click()
    assert nueva.locator("#car-vista").evaluate("d => d.open") is True
    assert nueva.locator("#car-vista-titulo").inner_text() == "justificante-303.pdf"
    nueva.keyboard.press("Escape")
    assert nueva.locator("#car-vista").evaluate("d => d.open") is False
    assert errores == []
