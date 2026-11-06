"""Portal, subida de facturas: avisos al elegir archivos (repetido, borrosa, no válido) y trimestre cerrado al escribir la fecha (app/static/portal_facturas_subida.js)."""
import struct
import zlib

from app import db, facturas_contables as fc, facturas_portal, verticales

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _png(ancho: int, alto: int, pixel) -> bytes:
    filas = b"".join(b"\x00" + bytes(v for x in range(ancho) for v in (pixel(x, y),) * 3) for y in range(alto))

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)) + trozo(b"IDAT", zlib.compress(filas)) + trozo(b"IEND", b"")


def test_avisos_al_elegir_facturas(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal avisos")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "portal-avisos@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Avisos", email="avisos@ejemplo.com")
    fc.subir_desde_portal(c, "recibida", [("antes.pdf", "application/pdf", PDF)])
    fc.cerrar_periodo(t, uid, c, "2026-T2")
    ctx = chromium.new_context(viewport={"width": 390, "height": 800})
    errores = []
    nueva = ctx.new_page()
    nueva.on("pageerror", lambda e: errores.append(str(e)))
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    nueva.goto(f"{servidor.url}/portal/facturas")
    nueva.wait_for_load_state("networkidle")

    nitida = _png(120, 120, lambda x, y: 255 if (x // 3 + y // 3) % 2 else 0)
    borrosa = _png(120, 120, lambda x, y: 200)
    nueva.set_input_files("#form-subida input[type=file]", [
        {"name": "antes.pdf", "mimeType": "application/pdf", "buffer": PDF},
        {"name": "borrosa.png", "mimeType": "image/png", "buffer": borrosa},
        {"name": "nitida.png", "mimeType": "image/png", "buffer": nitida},
        {"name": "notas.txt", "mimeType": "text/plain", "buffer": b"hola"},
    ])
    nueva.wait_for_function("document.querySelectorAll('#avisos-subida li').length >= 3")
    avisos = nueva.locator("#avisos-subida").inner_text()
    assert "antes.pdf" in avisos and "ya la enviaste" in avisos.lower()
    assert "borrosa.png" in avisos and "borrosa" in avisos.lower()
    assert "notas.txt" in avisos and "nitida.png" not in avisos

    nueva.locator("details.portal-anotar summary").click()
    nueva.fill("#fecha-factura", "2026-05-10")
    nueva.dispatch_event("#fecha-factura", "change")
    assert nueva.locator("#aviso-cierre").is_visible() and "cerrado" in nueva.locator("#aviso-cierre").inner_text().lower()
    nueva.fill("#fecha-factura", "2026-08-10")
    nueva.dispatch_event("#fecha-factura", "change")
    assert not nueva.locator("#aviso-cierre").is_visible()
    assert not errores
    ctx.close()


def test_la_foto_se_recorta_y_se_aligera_antes_de_subirla(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal recorte")
    pagina, _ = abrir()
    entrar_como_equipo(pagina, "portal-recorte@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Recorte", email="recorte@ejemplo.com")
    ctx = chromium.new_context(viewport={"width": 390, "height": 800})
    errores = []
    nueva = ctx.new_page()
    nueva.on("pageerror", lambda e: errores.append(str(e)))
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    nueva.goto(f"{servidor.url}/portal/facturas")
    nueva.wait_for_load_state("networkidle")

    def pagina_sobre_mesa(x, y):
        if 150 <= x < 650 and 100 <= y < 500:
            return 20 if (y % 20 < 4 and 180 < x < 620) else 245
        return 80
    foto = _png(800, 600, pagina_sobre_mesa)
    nueva.set_input_files("#form-subida input[type=file]", [{"name": "ticket.png", "mimeType": "image/png", "buffer": foto}])
    nueva.wait_for_function("document.getElementById('avisos-subida').innerText.includes('recortado')")
    datos = nueva.evaluate("""async () => { const f = document.querySelector('#form-subida input[type=file]').files[0]; const b = await createImageBitmap(f); return {tipo: f.type, nombre: f.name, ancho: b.width, alto: b.height, bytes: f.size}; }""")
    assert datos["tipo"] == "image/jpeg" and datos["nombre"] == "ticket.jpg"
    assert datos["ancho"] < 600 and datos["alto"] < 480 and datos["ancho"] > 480, datos          # recortada a la hoja (500x400) más un pequeño margen
    assert nueva.locator("#usar-originales").is_visible()
    nueva.check("#usar-originales")
    nueva.wait_for_function("document.querySelector('#form-subida input[type=file]').files[0].type === 'image/png'")
    assert not errores
    ctx.close()
