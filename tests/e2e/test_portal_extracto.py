"""Portal, «Revisar mi extracto» (L4): el CSV se lee y se compara en el navegador; solo se envía lo que el cliente anota."""
from app import db, facturas_contables as fc, verticales

CSV = """Banco Ejemplo;Extracto de movimientos
Titular: Cliente Extracto
Fecha operación;Fecha valor;Concepto;Importe;Saldo
03/11/2026;03/11/2026;PAGO PAPELERIA SOL;-121,00;1.879,00
05/11/2026;05/11/2026;COMPRA FERRETERIA;-45,50;1.833,50
07/11/2026;07/11/2026;TRANSFERENCIA CLIENTE;2.500,00;4.333,50
09/11/2026;09/11/2026;PARKING CENTRO;-8,20;4.325,30
"""


def test_el_extracto_se_compara_en_el_navegador_y_se_anota_un_tiquet(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho portal extracto")
    pagina, _ = abrir()
    uid = entrar_como_equipo(pagina, "portal-extracto@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Extracto", email="extracto@ejemplo.com")
    conn = db.get_connection()
    conn.execute("INSERT INTO facturas_contables (tenant_id, cliente_fiscal_id, tipo, estado, fecha, numero, tercero_nombre, total_centimos, origen, creado_en, actualizado_en) VALUES (?, ?, 'recibida', 'revisada', '2026-10-30', 'F-1', 'Papeleria Sol', 12100, 'portal', ?, ?)", (t, c, db.now_iso(), db.now_iso()))
    conn.commit(); conn.close()
    ctx = chromium.new_context(viewport={"width": 390, "height": 900})
    errores = []
    nueva = ctx.new_page()
    nueva.on("pageerror", lambda e: errores.append(str(e)))
    peticiones_extracto = []
    nueva.on("request", lambda r: peticiones_extracto.append(r.url) if "extracto" in r.url and r.method == "POST" else None)
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    nueva.goto(f"{servidor.url}/portal/extracto")
    nueva.wait_for_load_state("networkidle")
    nueva.set_input_files("#extracto-archivo", {"name": "extracto.csv", "mimeType": "text/csv", "buffer": CSV.encode()})
    nueva.wait_for_function("document.querySelectorAll('#extracto-lista li').length >= 1")
    texto = nueva.locator("#extracto-estado").inner_text()
    assert "4 movimientos" in texto and "2 son pagos sin factura" in texto, texto
    lista = nueva.locator("#extracto-lista").inner_text()
    assert "45,50" in lista and "FERRETERIA" in lista and "8,20" in lista and "121,00" not in lista and "2.500" not in lista and "2500" not in lista
    assert not peticiones_extracto, "el extracto no se envía a ningún sitio"
    nueva.locator("#extracto-lista li", has_text="FERRETERIA").locator("button").click()
    nueva.wait_for_load_state("networkidle")
    assert "/portal/justificantes" in nueva.url
    fila = db.get_connection().execute("SELECT fecha, importe_centimos, concepto, estado, origen FROM justificantes_pendientes WHERE cliente_fiscal_id = ?", (c,)).fetchone()
    assert (fila["fecha"], fila["importe_centimos"], fila["concepto"], fila["estado"], fila["origen"]) == ("2026-11-05", -4550, "COMPRA FERRETERIA", "tiquet", "cliente")
    # el tiquet ya anotado deja de salir como pendiente
    nueva.goto(f"{servidor.url}/portal/extracto")
    nueva.set_input_files("#extracto-archivo", {"name": "extracto.csv", "mimeType": "text/csv", "buffer": CSV.encode()})
    nueva.wait_for_function("document.getElementById('extracto-estado').innerText.includes('1 son pagos')")
    assert not errores
    ctx.close()


def test_lectura_de_formatos_de_csv_habituales(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho extracto formatos")
    pagina, _ = abrir()
    entrar_como_equipo(pagina, "portal-extracto2@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Formatos", email="formatos@ejemplo.com")
    ctx = chromium.new_context()
    nueva = ctx.new_page()
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    nueva.goto(f"{servidor.url}/portal/extracto")
    nueva.wait_for_load_state("networkidle")
    casos = {
        "coma_y_comillas": ('"Fecha","Descripción","Importe"\n"2026-11-03","Pago, con coma","-1,234.50"\n', [("2026-11-03", -123450)]),
        "cargo_abono": ("Fecha;Concepto;Cargo;Abono\n03/11/2026;Pago luz;50,00;\n04/11/2026;Nómina;;1.200,00\n", [("2026-11-03", -5000), ("2026-11-04", 120000)]),
        "sin_cabecera": ("03/11/2026;Cafetería;-3,50\n04/11/2026;Taxi;-12,00\n", [("2026-11-03", -350), ("2026-11-04", -1200)]),
        "parentesis_y_anio_corto": ("Fecha;Concepto;Importe\n03/11/26;Seguro;(99,99)\n", [("2026-11-03", -9999)]),
    }
    for nombre, (texto, esperado) in casos.items():
        r = nueva.evaluate("(t) => window.__extracto.leer(t)", texto)
        assert r["error"] is None, (nombre, r)
        assert [(m["f"], m["i"]) for m in r["movimientos"]] == esperado, (nombre, r)
    assert nueva.evaluate("() => window.__extracto.leer('Hola;mundo\\nsin;datos').error") == "columnas"
    assert nueva.evaluate("() => window.__extracto.leer('').error") == "vacio"
    ctx.close()
