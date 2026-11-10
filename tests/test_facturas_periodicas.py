"""Facturas periódicas que faltan este mes (app/facturas_periodicas.py)."""
from datetime import date

from app import facturas_contables as fc, facturas_periodicas as fp, panel_cierre
from tests.test_facturas_contables import LINEA, _datos, _despacho

LUZ, ALQUILER = "A58818501", "B12345674"


def _facturas(t, u, c, nif, nombre, *meses, **kw):
    for i, mes in enumerate(meses):
        fc.crear(t, u, c, _datos(numero=f"{nif[:3]}-{mes}-{i}", fecha=f"{mes}-05", tercero_nif=nif, tercero_nombre=nombre, **kw), [LINEA])


def test_un_proveedor_periodico_sin_factura_este_mes_se_avisa():
    t, u, c = _despacho()
    _facturas(t, u, c, LUZ, "Eléctrica Norte", "2026-05", "2026-07", "2026-08", "2026-09")
    r = fp.que_faltan(t, c, date(2026, 10, 15))
    assert [(x["nif"], x["nombre"], x["meses"], x["ultima"]) for x in r] == [(LUZ, "Eléctrica Norte", 4, "2026-09")]
    assert fp.que_faltan(t, c, date(2026, 10, 9)) == []                                     # a principios de mes aún es pronto


def test_no_avisa_si_ya_llego_si_no_es_periodico_ni_si_ya_no_se_usa():
    t, u, c = _despacho()
    _facturas(t, u, c, LUZ, "Eléctrica Norte", "2026-07", "2026-08", "2026-09", "2026-10")             # ya llegó la de octubre
    _facturas(t, u, c, ALQUILER, "Alquileres SL", "2026-08", "2026-09")                                # solo dos meses
    _facturas(t, u, c, "B99999999", "Antiguo", "2026-03", "2026-04", "2026-05", "2026-06")              # última de hace 4 meses
    assert fp.que_faltan(t, c, date(2026, 10, 20)) == []


def test_los_abonos_y_las_emitidas_no_cuentan_y_se_ve_en_el_panel():
    t, u, c = _despacho()
    _facturas(t, u, c, LUZ, "Eléctrica Norte", "2026-07", "2026-08", "2026-09")
    _facturas(t, u, c, ALQUILER, "Cliente final", "2026-07", "2026-08", "2026-09", tipo="emitida")
    assert [x["nif"] for x in fp.que_faltan(t, c, date(2026, 10, 15))] == [LUZ]
    cl = panel_cierre.panel(t, u, "2026-T3", hoy=date(2026, 10, 15))["clientes"][0]
    assert cl["periodicas_que_faltan"] == 1


def test_la_lectura_copia_el_concepto_de_la_ultima_factura_revisada_a_mano():
    from app import lectura_historial as lh
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(numero="K-1", tercero_nif=LUZ, concepto="Suministro eléctrico"), [LINEA])
    fc.cambiar_estado(t, u, fid, "revisada")
    nuevos = {"tercero_nombre": "Eléctrica Norte", "tercero_nif": LUZ, "concepto": ""}
    avisos = lh.completar(t, u, c, "recibida", nuevos, [{"base": "10.00", "pct_iva": "21"}], "imagen")
    assert nuevos["concepto"] == "Suministro eléctrico" and any("concepto" in a for a in avisos)
