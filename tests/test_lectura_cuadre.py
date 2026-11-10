"""Cuadre de las líneas leídas (app/lectura_cuadre.py): tipos poco habituales y qué combinación explica un total que no sale de las líneas."""
from app import lectura_cuadre as lc, lectura_evidencias


def _l(base, iva, **kw):
    return {"base": base, "pct_iva": iva, **kw}


def test_un_iva_o_una_retencion_poco_habituales_se_avisan():
    av = lc.tipos_raros([_l("100.00", "19"), _l("100.00", "21", pct_retencion="12")])
    assert len(av) == 2 and "19 %" in av[0] and "12 %" in av[1] and av[0].startswith("Línea 1") and av[1].startswith("Línea 2")


def test_el_recargo_tiene_que_ser_el_de_su_iva():
    assert lc.tipos_raros([_l("100.00", "21", pct_recargo="5.2")]) == []
    av = lc.tipos_raros([_l("100.00", "10", pct_recargo="5.2")])
    assert len(av) == 1 and "recargo" in av[0]


def test_lo_habitual_no_avisa():
    assert lc.tipos_raros([_l("100.00", "21"), _l("50.00", "10"), _l("20.00", "4"), _l("5.00", "0"), _l("100", "21", pct_retencion="15")]) == []


def test_las_comprobaciones_de_la_lectura_incluyen_los_tipos_raros():
    assert any("19 %" in c for c in lectura_evidencias.verificaciones(nif_contraparte="", lineas=[_l("100.00", "19", cuota_iva="19.00")], fecha="2026-01-01"))


def test_total_que_sale_con_otra_retencion():
    msg = lc.explicar_descuadre([_l("1000.00", "21", cuota_iva="210.00")], "", "1060.00")
    assert msg and "21 % de IVA" in msg and "retención del 15 %" in msg


def test_total_que_sale_con_otro_iva():
    msg = lc.explicar_descuadre([_l("1000.00", "21", cuota_iva="210.00")], "", "1100.00")
    assert msg and "10 % de IVA" in msg


def test_total_igual_a_la_base_se_explica_como_total_sin_iva():
    assert "no incluir el IVA" in lc.explicar_descuadre([_l("1000.00", "21", cuota_iva="210.00")], "", "1000.00")


def test_con_varias_bases_prueba_el_recargo_y_la_retencion():
    lineas = [_l("1000.00", "21", cuota_iva="210.00"), _l("100.00", "10", cuota_iva="10.00")]
    msg = lc.explicar_descuadre(lineas, "", "1155.00")               # 1000 + 210 + 100 + 10 - el 15 % de 1100
    assert msg and "retención del 15 %" in msg


def test_si_no_hay_explicacion_clara_calla():
    assert lc.explicar_descuadre([_l("1000.00", "21", cuota_iva="210.00")], "", "1234.56") is None
    assert lc.explicar_descuadre([], "", "10.00") is None
    assert lc.explicar_descuadre([_l("1000.00", "21", cuota_iva="210.00")], "", "") is None
