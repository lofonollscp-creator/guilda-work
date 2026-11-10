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


def _n43_movimiento(aammdd: str, clave: str, centimos: int, ref: str, complementario: str = "") -> str:
    r = "22" + "    " + "0001" + aammdd + aammdd + "01" + "001" + clave + f"{centimos:014d}" + "0000000000" + ref.ljust(12)[:12] + "".ljust(16)
    r = r.ljust(80)
    if complementario:
        r += "\n" + ("2301" + complementario.ljust(38)[:38] + "".ljust(38))
    return r


NORMA43 = "\n".join([
    "11" + "2100" + "0001" + "0123456789" + "261101" + "261130" + "2" + f"{100000:014d}" + "978" + "3" + "CLIENTE FORMATOS".ljust(26) + "   ",
    _n43_movimiento("261103", "1", 4550, "REF1", "COMPRA FERRETERIA SOL"),
    _n43_movimiento("261105", "2", 250000, "REF2", "TRANSFERENCIA CLIENTE"),
    "33" + "2100" + "0001" + "0123456789" + "000002" + f"{4550:014d}" + "000001" + f"{250000:014d}" + "2" + f"{345450:014d}" + "978",
    "88" + "9" * 18 + "000006" + "".ljust(52),
])
CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>
<Ntry><Amt Ccy="EUR">121.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-11-03</Dt></BookgDt><NtryDtls><TxDtls><RmtInf><Ustrd>PAPELERIA SOL</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">2500.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-11-07</Dt></BookgDt><AddtlNtryInf>TRANSFERENCIA</AddtlNtryInf></Ntry>
</Stmt></BkToCstmrStmt></Document>"""


def test_lectura_de_cuaderno_43_y_camt_053_y_su_codificacion(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho extracto bancario")
    pagina, _ = abrir()
    entrar_como_equipo(pagina, "portal-extracto3@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Bancario", email="bancario@ejemplo.com")
    ctx = chromium.new_context()
    nueva = ctx.new_page()
    errores = []
    nueva.on("pageerror", lambda e: errores.append(str(e)))
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    nueva.goto(f"{servidor.url}/portal/extracto")
    nueva.wait_for_load_state("networkidle")
    r = nueva.evaluate("(t) => window.__extracto.leer(t)", NORMA43)
    assert r["error"] is None and [(m["f"], m["i"]) for m in r["movimientos"]] == [("2026-11-03", -4550), ("2026-11-05", 250000)], r
    assert "FERRETERIA" in r["movimientos"][0]["c"]
    r = nueva.evaluate("(t) => window.__extracto.leer(t)", CAMT)
    assert r["error"] is None and [(m["f"], m["i"]) for m in r["movimientos"]] == [("2026-11-03", -12100), ("2026-11-07", 250000)], r
    assert "PAPELERIA" in r["movimientos"][0]["c"]
    assert nueva.evaluate("() => window.__extracto.leer('<Document><BkToCstmrStmt><Ntry>').error") == "columnas"
    # un fichero en Latin-1 (habitual en los Cuadernos 43) se lee igual que uno en UTF-8
    nueva.set_input_files("#extracto-archivo", {"name": "extracto.n43", "mimeType": "text/plain", "buffer": NORMA43.replace("FERRETERIA", "FERRETERÍA").encode("latin-1")})
    nueva.wait_for_function("document.getElementById('extracto-estado').innerText.length > 0")
    assert "2 movimientos" in nueva.locator("#extracto-estado").inner_text()
    assert not errores
    ctx.close()


def test_cobros_sin_factura_emitida_y_facturas_sin_pago(servidor, abrir, entrar_como_equipo, chromium):
    t = db.crear_tenant("Despacho extracto cobros")
    pagina, _ = abrir()
    entrar_como_equipo(pagina, "portal-extracto3@ejemplo.com", despacho=t, direccion=True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = db.crear_cliente_fiscal(t, "Cliente Cobros", email="cobros@ejemplo.com")
    conn = db.get_connection()
    for tipo, fecha, numero, total in (("emitida", "2026-10-30", "V-1", 100000), ("recibida", "2026-11-04", "R-9", 33300), ("recibida", "2026-11-03", "R-8", 12100)):
        conn.execute("INSERT INTO facturas_contables (tenant_id, cliente_fiscal_id, tipo, estado, fecha, numero, tercero_nombre, total_centimos, origen, creado_en, actualizado_en) VALUES (?, ?, ?, 'revisada', ?, ?, 'X', ?, 'despacho', '2026-11-01', '2026-11-01')",
                     (t, c, tipo, fecha, numero, total))
    conn.commit(); conn.close()
    ctx = chromium.new_context(viewport={"width": 390, "height": 900})
    errores = []
    nueva = ctx.new_page()
    nueva.on("pageerror", lambda e: errores.append(str(e)))
    nueva.goto(f"{servidor.url}/portal/entrar/{db.crear_acceso_cliente_fiscal(c, '127.0.0.1')}")
    nueva.goto(f"{servidor.url}/portal/extracto")
    nueva.wait_for_load_state("networkidle")
    nueva.set_input_files("#extracto-archivo", {"name": "extracto.csv", "mimeType": "text/csv", "buffer": CSV.encode()})
    nueva.wait_for_function("document.getElementById('extracto-cobros').hidden === false")
    cobros = nueva.locator("#extracto-cobros-lista").inner_text()
    assert "2500,00" in cobros.replace(".", "") and "TRANSFERENCIA CLIENTE" in cobros
    nueva.wait_for_function("document.getElementById('extracto-sin-pago').hidden === false")
    sin_pago = nueva.locator("#extracto-sin-pago-lista").inner_text()
    assert "333,00" in sin_pago and "R-9" in sin_pago and "R-8" not in sin_pago, "R-8 (121,00) sí salió pagada; R-9 no; la emitida no cuenta como pago pendiente"
    assert not errores
    ctx.close()
