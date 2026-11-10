"""Proveedor ya conocido: lo decidido en su última factura revisada a mano se aprovecha en la lectura siguiente (app/lectura_historial.py)."""
from app import db, facturas_contables as fc, lectura_historial as lh
from tests.test_facturas_contables import _datos, _despacho

NIF = "A58818501"


def _anterior(t, u, c, *, nombre="Papelería Sol S.L.", cuenta="62200001", subtipo="01", revisar=True, **kw):
    fid = fc.crear(t, u, c, _datos(numero="P-1", tercero_nombre=nombre, tercero_nif=NIF, **kw), [{"base": "100,00", "pct_iva": "21", "cuenta": cuenta, "subtipo": subtipo}])
    if revisar:
        fc.cambiar_estado(t, u, fid, "revisada")
    return fid


def _nueva(nombre="PAPELERIA SOL", **linea):
    return {"tercero_nombre": nombre, "tercero_nif": NIF}, [{"base": "50.00", "pct_iva": "21", **linea}]


def test_pone_el_nombre_con_el_que_ya_figura_y_copia_la_cuenta():
    t, u, c = _despacho()
    _anterior(t, u, c)
    nuevos, lineas = _nueva()
    avisos = lh.completar(t, u, c, "recibida", nuevos, lineas, "imagen")
    assert nuevos["tercero_nombre"] == "Papelería Sol S.L." and lineas[0]["cuenta"] == "62200001"
    assert any("nombre" in a for a in avisos) and any("cuenta 62200001" in a and "P-1" in a for a in avisos)


def test_no_pisa_lo_que_la_lectura_ya_trae_ni_un_xml():
    t, u, c = _despacho()
    _anterior(t, u, c)
    nuevos, lineas = _nueva(nombre="Otro nombre XML", cuenta="60000000")
    nuevos["tercero_nombre"] = "Papelería Sol"                                   # comparte palabra, pero es un XML: el nombre es exacto
    lh.completar(t, u, c, "recibida", nuevos, lineas, "xml")
    assert nuevos["tercero_nombre"] == "Papelería Sol" and lineas[0]["cuenta"] == "60000000"


def test_si_el_nombre_no_se_parece_avisa_en_vez_de_cambiarlo():
    t, u, c = _despacho()
    _anterior(t, u, c)
    nuevos, lineas = _nueva(nombre="Talleres Mecánicos Ruiz")
    avisos = lh.completar(t, u, c, "recibida", nuevos, lineas, "imagen")
    assert nuevos["tercero_nombre"] == "Talleres Mecánicos Ruiz" and any("comprueba el NIF" in a for a in avisos)


def test_copia_el_tipo_de_operacion_solo_si_no_es_la_corriente_y_por_tipo_de_iva():
    t, u, c = _despacho()
    _anterior(t, u, c, subtipo="03")
    nuevos, lineas = _nueva()
    nuevos2, lineas2 = _nueva()
    lineas2.append({"base": "10.00", "pct_iva": "10"})                          # un tipo de IVA que la anterior no tenía: no se toca
    lh.completar(t, u, c, "recibida", nuevos, lineas, "imagen")
    lh.completar(t, u, c, "recibida", nuevos2, lineas2, "imagen")
    assert lineas[0]["subtipo"] == "03" and lineas2[0]["subtipo"] == "03" and "cuenta" not in lineas2[1] and "subtipo" not in lineas2[1]


def test_las_revisadas_por_la_ia_sola_o_pendientes_no_sirven_de_ejemplo():
    t, u, c = _despacho()
    _anterior(t, u, c, revisar=False)                                           # pendiente
    nuevos, lineas = _nueva()
    assert lh.completar(t, u, c, "recibida", nuevos, lineas, "imagen") == [] and "cuenta" not in lineas[0]
    fid = _anterior(t, u, c)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET revision_auto = 1 WHERE id = ?", (fid,)); conn.commit()
    finally:
        conn.close()
    assert lh.factura_anterior(t, c, "recibida", NIF) is None


def test_con_regla_del_proveedor_manda_la_regla_y_no_se_copia_la_cuenta():
    t, u, c = _despacho()
    _anterior(t, u, c)
    fc.guardar_regla(t, u, c, "proveedor", {"nif": NIF, "nombre": "Papelería Sol S.L.", "cuenta_linea": "62900009", "pct_iva": None, "pct_retencion": None, "subtipo": None})
    nuevos, lineas = _nueva()
    lh.completar(t, u, c, "recibida", nuevos, lineas, "imagen")
    assert "cuenta" not in lineas[0]                                            # la pondrá la regla al guardar


def test_no_mezcla_clientes_ni_clases():
    t, u, c = _despacho()
    _anterior(t, u, c)
    nuevos, lineas = _nueva()
    assert lh.completar(t, u, c, "emitida", nuevos, lineas, "imagen") == []
