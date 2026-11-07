"""Aprender de lo que revisan las personas (R3): al revisar a mano la segunda factura de un proveedor con lo mismo, se crea su regla «aprendida»."""
from app import facturas_contables as fc
from tests.test_facturas_contables import _despacho


def _factura(t, u, c, numero, cuenta="62900000", nif="B87654323", iva="21", base="100,00"):
    return fc.crear(t, u, c, {"tipo": "recibida", "fecha": "2026-08-14", "numero": numero, "tercero_nombre": "Papelería Sol", "tercero_nif": nif},
                    [{"base": base, "pct_iva": iva, "cuenta": cuenta}])


def _regla(t, u, c, nif="B87654323"):
    return next((r for r in fc.listar_reglas(t, u, c) if r["nif"] == nif), None) if hasattr(fc, "listar_reglas") else fc.regla_del_tercero(t, c, "recibida", nif)


def test_con_dos_facturas_revisadas_a_mano_con_lo_mismo_se_aprende_la_regla():
    t, u, c = _despacho()
    a, b = _factura(t, u, c, "1"), _factura(t, u, c, "2")
    fc.cambiar_estado(t, u, a, "revisada")
    assert _regla(t, u, c) is None                                      # una sola no basta
    fc.cambiar_estado(t, u, b, "revisada")
    r = _regla(t, u, c)
    assert r is not None and r["cuenta_linea"] == "62900000" and r["aprendida"] == 1
    d = _factura(t, u, c, "3", cuenta="")
    assert fc.obtener(t, u, d)["lineas"][0]["cuenta"] in ("62900000", None, "")            # la regla se aplicará al exportar


def test_si_las_facturas_no_coinciden_no_se_aprende_la_cuenta_ni_el_iva():
    t, u, c = _despacho()
    a, b = _factura(t, u, c, "1", cuenta="62900000", iva="21"), _factura(t, u, c, "2", cuenta="60000000", iva="10")
    fc.cambiar_estado(t, u, a, "revisada"); fc.cambiar_estado(t, u, b, "revisada")
    assert _regla(t, u, c) is None


def test_las_revisadas_solas_por_la_ia_no_enseñan_y_una_regla_manual_no_se_pisa():
    t, u, c = _despacho()
    a, b = _factura(t, u, c, "1"), _factura(t, u, c, "2")
    fc.cambiar_estado(t, u, a, "revisada", aprender=False); fc.cambiar_estado(t, u, b, "revisada", aprender=False)
    assert _regla(t, u, c) is None
    fc.guardar_regla(t, u, c, "proveedor", {"nif": "B87654323", "nombre": "Papelería Sol", "cuenta_linea": "62700000"})
    e, f = _factura(t, u, c, "5"), _factura(t, u, c, "6")
    fc.cambiar_estado(t, u, e, "revisada"); fc.cambiar_estado(t, u, f, "revisada")
    assert _regla(t, u, c)["cuenta_linea"] == "62700000" and not _regla(t, u, c)["aprendida"]


def test_revisar_nunca_falla_aunque_no_se_pueda_aprender(monkeypatch):
    t, u, c = _despacho()
    a = _factura(t, u, c, "9")

    def roto(*args, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(fc, "aprender_regla", roto)
    fc.cambiar_estado(t, u, a, "revisada")
    assert fc.obtener(t, u, a)["estado"] == "revisada"
