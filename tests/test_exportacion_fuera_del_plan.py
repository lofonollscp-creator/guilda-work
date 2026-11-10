"""El pre-chequeo avisa de las subcuentas de terceros que no figuran en el plan de a3 importado (J7)."""
from app import db, facturas_contables as fc
from tests.test_facturas_contables import LINEA, _datos, _despacho


def _plan(t, c, *filas):
    conn = db.get_connection()
    try:
        for cuenta, nif in filas:
            conn.execute("INSERT INTO contabilidad_plan (tenant_id, cliente_fiscal_id, cuenta, nombre, nif, tipo, importado_en) VALUES (?, ?, ?, 'X', ?, 'proveedor', ?)", (t, c, cuenta, nif, db.now_iso()))
        conn.commit()
    finally:
        conn.close()


def _revisada(t, u, c, **kw):
    fid = fc.crear(t, u, c, _datos(**{"tercero_nif": "A58818501", **kw}), [LINEA])
    fc.cambiar_estado(t, u, fid, "revisada", confirmar_duplicado=True)
    return fid


def _mensajes(t, u, c):
    return [a["mensaje"] for a in fc.comprobar_exportacion(t, u, c)["avisos"]]


def test_sin_plan_importado_no_avisa():
    t, u, c = _despacho()
    _revisada(t, u, c, tercero_cuenta="40001234")
    assert not [m for m in _mensajes(t, u, c) if "plan de cuentas" in m]


def test_una_subcuenta_escrita_a_mano_que_no_esta_en_el_plan_se_avisa():
    t, u, c = _despacho()
    _plan(t, c, ("40000555", "B11111111"))
    _revisada(t, u, c, tercero_cuenta="40001234")
    assert any("40001234" in m and "no figura en el plan" in m for m in _mensajes(t, u, c))


def test_una_que_esta_en_el_plan_o_es_la_generica_no_se_avisa():
    t, u, c = _despacho()
    _plan(t, c, ("40000555", "A58818501"))
    _revisada(t, u, c)                                                          # sale la del plan por su NIF
    _revisada(t, u, c, numero="F-9", tercero_nif="B99999999")
    assert not [m for m in _mensajes(t, u, c) if "plan de cuentas" in m]
