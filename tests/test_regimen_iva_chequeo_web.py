"""Régimen de IVA: lo que comprueba el pre-chequeo del fichero y lo que se ve en la web."""
from app import db, enlace_a3 as a3, enlace_a3_chequeo as chq, facturas_contables as fc, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.conftest import iniciar_sesion_de_prueba


def _rec(**kw):
    return {"tipo": "recibida", "fecha": "2026-09-30", "fecha_operacion": "2026-09-30", "numero": "A-1", "concepto": "x", "nif": "B12345678", "nombre": "Prov", "cuenta_tercero": "40000001",
            "total_centimos": 12100, "lineas": [{"cuenta": "62900000", "subtipo": "01", "base_centimos": 10000, "pct_iva": 2100, "cuota_iva": 2100, "cuenta_iva": "47200000", **kw}]}


def _emitida(**kw):
    f = _rec()
    return {**f, "tipo": "emitida", "cuenta_tercero": "43000001", "lineas": [{**f["lineas"][0], "cuenta_iva": "47700000", **kw}]}


def _mod(contenido, registro, pos, texto):
    t = contenido.decode("latin-1"); ini = (registro - 1) * 512 + pos - 1
    return (t[:ini] + texto + t[ini + len(texto):]).encode("latin-1")


def test_el_prechequeo_valida_subtipo_impreso_y_caja():
    base = a3.generar([_rec()], empresa=1)
    assert chq.chequear(base)["ok"]
    assert any("subtipo" in e["mensaje"] for e in chq.chequear(_mod(base, 2, 100, "05"))["errores"]), "el 05 solo vale en emitidas"
    assert any("impreso" in e["mensaje"] for e in chq.chequear(_mod(base, 2, 173, "ab"))["errores"])
    assert any("criterio de caja" in e["mensaje"] for e in chq.chequear(_mod(base, 2, 177, "X"))["errores"])
    emitida = _mod(a3.generar([_emitida()], empresa=1), 2, 177, "S")
    assert any("solo se tiene en cuenta en facturas recibidas" in a["mensaje"] for a in chq.chequear(emitida)["avisos"])


def test_el_prechequeo_avisa_de_incoherencias_de_iva_y_de_349():
    cero = a3.generar([_rec(pct_iva=0, cuota_iva=0)], empresa=1)
    assert any("IVA al 0 %" in a["mensaje"] for a in chq.chequear(cero)["avisos"])
    intra = a3.generar([_rec(subtipo="03", pct_iva=0, cuota_iva=0)], empresa=1)
    assert any("modelo 349" in a["mensaje"] for a in chq.chequear(intra)["avisos"]), "sin impreso 349"
    bien = a3.generar([_rec(subtipo="03", pct_iva=0, cuota_iva=0, impreso="02")], empresa=1)
    assert not any("349" in a["mensaje"] for a in chq.chequear(bien)["avisos"])
    exenta_con_iva = a3.generar([_emitida(subtipo="02")], empresa=1)
    assert any("exenta" in a["mensaje"] for a in chq.chequear(exenta_con_iva)["avisos"])


def test_la_web_permite_elegir_regimen_tipo_de_operacion_y_caja(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "regimenweb@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho regimen web"); db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Web", nif="B12345678")
    url = f"/contabilidad/cliente/{c}/configuracion"
    html = cliente.get(url).get_data(as_text=True)
    assert "Régimen de IVA del cliente" in html and "Recargo de equivalencia" in html and "Retención de IRPF por defecto" in html
    r = cliente.post(url, data={"a3_empresa": "5", "digitos": "8", "regimen_iva": "recargo", "retencion_emitidas": "15"})
    assert r.status_code == 302 and fc.configuracion(t, c)["regimen_iva"] == "recargo"
    assert 'value="15"' in cliente.get(url).get_data(as_text=True)
    assert "elige un régimen" in cliente.post(url, data={"a3_empresa": "5", "digitos": "8", "regimen_iva": "x"}).get_data(as_text=True).lower()
    r = cliente.post("/contabilidad/ajustes", data={"accion": "despacho", "digitos": "8", "regimen_iva": "exento", "retencion_emitidas": "7,5"})
    assert fc.configuracion_despacho(t)["retencion_emitidas"] == 750 and "Régimen de IVA del cliente" in r.get_data(as_text=True)
    nueva = cliente.get(f"/contabilidad/nueva?cliente_id={c}&tipo=recibida").get_data(as_text=True)
    assert "Tipo de operación" in nueva and "04 · Inversión del sujeto pasivo" in nueva and "El proveedor aplica el criterio de caja" in nueva and "Según el régimen del cliente" in nueva
    emitida = cliente.get(f"/contabilidad/nueva?cliente_id={c}&tipo=emitida").get_data(as_text=True)
    assert "03 · Entrega intracomunitaria" in emitida and "criterio de caja" not in emitida
    r = cliente.post("/contabilidad/nueva", data={"cliente_id": c, "tipo": "recibida", "fecha": "2026-08-20", "numero": "W-1", "tercero_nombre": "Prov", "tercero_nif": "B22222222",
                                                  "base_0": "100,00", "pct_iva_0": "21", "subtipo_0": "", "criterio_caja": "1"})
    fid = int(r.headers["Location"].rsplit("/", 1)[1])
    f = fc.obtener(t, uid, fid)
    assert f["criterio_caja"] == 1 and f["lineas"][0]["subtipo"] == "01" and f["lineas"][0]["pct_recargo"] == 520
    ver = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert 'name="criterio_caja" value="1" checked' in ver and '<option value="01" selected>' in ver
