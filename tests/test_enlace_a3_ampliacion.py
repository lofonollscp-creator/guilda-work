"""Datos de ampliación de a3 de una factura, impresos y formato del fichero (J15, J16, J17, J22): del formulario al fichero."""
import pytest

from app import enlace_a3_chequeo as chequeo, facturas_contables as fc
from tests.test_facturas_contables import LINEA, _datos, _despacho

NIF = "A58818501"


def _crear(t, u, c, numero="Z-1", lineas=None, **kw):
    return fc.crear(t, u, c, _datos(numero=numero, tercero_nif=NIF, **kw), lineas or [LINEA])


def _exportar(t, u, c, fid):
    fc.cambiar_estado(t, u, fid, "revisada", confirmar_duplicado=True)
    return fc.exportar(t, u, c)["contenido"]


def test_el_formato_del_fichero_se_elige_y_se_valida():
    t, u, c = _despacho()
    assert fc.configuracion(t, c)["formato_enlace"] == "512"
    assert fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "256"})["formato_enlace"] == "256"
    with pytest.raises(ValueError, match="formato"):
        fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "128"})


def test_los_datos_de_ampliacion_se_validan_y_se_guardan():
    t, u, c = _despacho()
    fid = _crear(t, u, c, datos_a3={"bien_inversion": "1", "clave_340": "3", "dua": "DUA-1", "nif_representante": "12345678z", "autofactura": "AF-1", "metalico": "total", "inmuebles": "1.500,00"})
    assert fc.obtener(t, u, fid)["a3"] == {"bien_inversion": True, "dua": "DUA-1", "clave_340": "3", "nif_representante": "12345678Z", "autofactura": "AF-1", "metalico": "total", "inmuebles": 150000}
    for malos in ({"bien_inversion": "1", "tipo": "emitida"}, {"clave_340": "9"}, {"inmuebles": "abc"}):
        with pytest.raises(ValueError):
            fc.datos_a3_validados(malos, malos.pop("tipo", "recibida"))
    assert fc.obtener(t, u, _crear(t, u, c, numero="Z-2"))["a3"] == {}


def test_una_lectura_con_ia_no_borra_los_datos_que_puso_una_persona():
    t, u, c = _despacho()
    fid = _crear(t, u, c, datos_a3={"clave_340": "1"})
    f = fc.obtener(t, u, fid)
    fc.actualizar(t, u, fid, {"tipo": "recibida", "fecha": f["fecha"], "numero": "Z-9", "tercero_nombre": f["tercero_nombre"], "tercero_nif": NIF}, [LINEA])     # sin claves de a3
    assert fc.obtener(t, u, fid)["a3"] == {"clave_340": "1"}
    fc.actualizar(t, u, fid, {"tipo": "recibida", "fecha": f["fecha"], "numero": "Z-9", "tercero_nombre": f["tercero_nombre"], "tercero_nif": NIF, "clave_340": ""}, [LINEA])
    assert fc.obtener(t, u, fid)["a3"] == {}


def test_un_bien_de_inversion_sale_con_tipo_de_factura_3_en_el_fichero():
    t, u, c = _despacho()
    contenido = _exportar(t, u, c, _crear(t, u, c, datos_a3={"bien_inversion": True})).decode("latin-1")
    assert contenido[57] == "3" and chequeo.chequear(contenido.encode("latin-1"), 8)["ok"]


def test_en_256_la_ampliacion_sale_en_el_registro_4_y_el_chequeo_lo_da_por_bueno():
    t, u, c = _despacho()
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "256"})
    contenido = _exportar(t, u, c, _crear(t, u, c, datos_a3={"clave_340": "1", "metalico": "total"}))
    registros = [contenido[i:i + 256].decode("latin-1") for i in range(0, len(contenido), 256)]
    assert [r[14] for r in registros] == ["1", "9", "4"] and registros[2][106] == "1" and registros[2][131] == "S" and all(r[0] == "4" for r in registros)
    assert chequeo.chequear(contenido, 8)["ok"]


def test_la_importacion_necesita_formato_256_y_dua():
    t, u, c = _despacho()
    linea = {**LINEA, "subtipo": "06"}
    f = fc.obtener(t, u, _crear(t, u, c, numero="I-1", lineas=[linea]))
    assert any("formato clásico" in p for p in f["problemas"])
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "256"})
    f = fc.obtener(t, u, f["id"])
    assert any("DUA" in p for p in f["problemas"])
    fc.actualizar(t, u, f["id"], {"tipo": "recibida", "fecha": f["fecha"], "numero": "I-1", "tercero_nombre": f["tercero_nombre"], "tercero_nif": NIF, "dua": "26ES0001"}, [linea])
    assert not any("DUA" in p or "formato" in p for p in fc.obtener(t, u, f["id"])["problemas"])


def test_el_impreso_de_una_compra_con_retencion_sale_segun_su_porcentaje_y_se_puede_elegir_a_mano():
    assert fc.impreso_de_linea("recibida", {"cuota_retencion": 100, "pct_retencion": 1900}) == "03"
    assert fc.impreso_de_linea("recibida", {"cuota_retencion": 100, "pct_retencion": 1500}) == "05"
    assert fc.impreso_de_linea("recibida", {"cuota_retencion": 100, "pct_retencion": 2400}) is None            # no se adivina
    assert fc.impreso_de_linea("emitida", {"cuota_retencion": 100, "pct_retencion": 1500}) is None
    assert fc.impreso_de_linea("recibida", {"cuota_retencion": 100, "pct_retencion": 1500, "impreso": "01"}) == "01"
    assert fc.impreso_de_linea("recibida", {"subtipo": "03"}) == "02" and fc.impreso_de_linea("recibida", {"subtipo": "08"}) == "11"
    t, u, c = _despacho()
    fid = _crear(t, u, c, lineas=[{**LINEA, "pct_retencion": "15"}, {**LINEA, "pct_iva": "10", "impreso": "01"}])
    contenido = _exportar(t, u, c, fid).decode("latin-1").split("\r\n")
    assert contenido[1][172:174] == "05" and contenido[2][172:174] == "01"


def test_la_operacion_07_de_las_emitidas_se_ofrece():
    assert "07" in fc.operaciones_validas("emitida") and "06" in fc.operaciones_validas("recibida")


def test_la_ficha_guarda_el_impreso_y_los_datos_de_ampliacion(cliente):
    from tests.test_facturas_contables import _web
    uid, t, c = _web(cliente, "ampliaciona3@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    fid = fc.crear(t, uid, c, _datos(numero="W-1", tercero_nif=NIF), [LINEA])
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "Datos para los modelos 340 y 347" in html and 'name="impreso_0"' in html and 'name="dua"' in html
    r = cliente.post(f"/contabilidad/{fid}", data={"tipo": "recibida", "fecha": "2026-08-15", "numero": "W-1", "tercero_nombre": "Papelería Sol", "tercero_nif": NIF, "base_0": "100,00", "pct_iva_0": "21",
                                                  "impreso_0": "05", "pct_retencion_0": "15", "bien_inversion": "1", "clave_340": "3", "metalico": "total"})
    assert r.status_code == 302
    f = fc.obtener(t, uid, fid)
    assert f["a3"] == {"bien_inversion": True, "clave_340": "3", "metalico": "total"} and f["lineas"][0]["impreso"] == "05"
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert 'value="05" selected' in html and "checked" in html


def test_el_formato_se_elige_en_la_configuracion_del_cliente(cliente):
    from tests.test_facturas_contables import _web
    uid, t, c = _web(cliente, "formatoa3@ejemplo.com")
    assert "Formato del fichero para a3" in cliente.get(f"/contabilidad/cliente/{c}/configuracion").get_data(as_text=True)
    r = cliente.post(f"/contabilidad/cliente/{c}/configuracion", data={"a3_empresa": "12", "digitos": "8", "formato_enlace": "256", "regimen_iva": "general"})
    assert r.status_code == 302 and fc.configuracion(t, c)["formato_enlace"] == "256"


def test_el_iban_se_valida_con_su_digito_de_control():
    assert fc.iban_valido("ES91 2100 0418 4502 0005 1332") and fc.iban_valido("GB82WEST12345698765432")
    assert not fc.iban_valido("ES91 2100 0418 4502 0005 1333") and not fc.iban_valido("ES9121000418450200051") and not fc.iban_valido("") and not fc.iban_valido("1234")


def test_vencimiento_forma_de_pago_e_iban_se_validan_y_salen_en_256():
    t, u, c = _despacho()
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "256"})
    fid = _crear(t, u, c, datos_a3={"iban": "es91 2100 0418 4502 0005 1332", "vencimiento": "2026-10-30", "forma_pago": "tr"})
    assert fc.obtener(t, u, fid)["a3"] == {"iban": "ES9121000418450200051332", "vencimiento": "2026-10-30", "forma_pago": "TR"}
    for malo in ({"iban": "ES00"}, {"forma_pago": "XX"}, {"vencimiento": "mañana"}):
        with pytest.raises(ValueError):
            fc.datos_a3_validados(malo, "recibida")
    contenido = _exportar(t, u, c, fid)
    registros = [contenido[i:i + 256].decode("latin-1") for i in range(0, len(contenido), 256)]
    assert [r[14] for r in registros] == ["1", "9", "V", "V"] and registros[2][6:14] == "20261030" and registros[3][93:113] == "21000418450200051332" and registros[3][58:60] == "TR"
    assert chequeo.chequear(contenido, 8)["ok"]


def test_una_lectura_suma_sus_datos_a_los_que_puso_una_persona():
    t, u, c = _despacho()
    fid = _crear(t, u, c, datos_a3={"bien_inversion": True})
    f = fc.obtener(t, u, fid)
    base = {"tipo": "recibida", "fecha": f["fecha"], "numero": "Z-1", "tercero_nombre": f["tercero_nombre"], "tercero_nif": NIF}
    fc.actualizar(t, u, fid, {**base, "datos_a3": {"vencimiento": "2026-10-30"}}, [LINEA])
    assert fc.obtener(t, u, fid)["a3"] == {"bien_inversion": True, "vencimiento": "2026-10-30"}
    fc.actualizar(t, u, fid, {**base, "bien_inversion": "", "vencimiento": "", "iban": "", "forma_pago": ""}, [LINEA])             # el formulario manda y vacía
    assert fc.obtener(t, u, fid)["a3"] == {}


def test_la_lectura_guarda_iban_vencimiento_y_forma_de_pago_validos():
    from app import lectura_facturas as lf
    f = {"tipo": "recibida", "tercero_nombre": "X", "tercero_nif": "", "numero": "1", "fecha": "2026-08-15"}
    base = {"emisor_nif": "A58818501", "receptor_nif": "", "numero": "7", "fecha": "2026-08-15", "total": 12.10, "lineas": [{"base": 10, "pct_iva": 21, "cuota_iva": 2.1}]}
    _, nuevos, _, avisos = lf._a_factura({**base, "iban": "ES91 2100 0418 4502 0005 1332", "vencimiento": "2026-09-14", "forma_pago": "Transferencia"}, f, "", "")
    assert nuevos["datos_a3"] == {"iban": "ES9121000418450200051332", "vencimiento": "2026-09-14", "forma_pago": "TR"}
    _, nuevos, _, avisos = lf._a_factura({**base, "iban": "ES00 0000", "vencimiento": "2026-08-01", "forma_pago": "bizum"}, f, "", "")
    assert "datos_a3" not in nuevos and any("IBAN leído" in a for a in avisos)               # IBAN inválido, vencimiento anterior a la factura y forma desconocida: nada se guarda
