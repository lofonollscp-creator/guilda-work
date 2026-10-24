"""Exportador del fichero importable del 303: formato de campos (Nota 2 del diseño), composición de la envoltura y lectura inversa.

Con NIF y nombres INVENTADOS. Lo que no se puede probar aquí —la aceptación de la AEAT— se prueba con el simulador y queda documentado (docs/fiscal-vias-aeat.md)."""
from decimal import Decimal

import pytest

from app.fiscal_modelos import exportador_303 as e

D = e.cargar_diseno()
P1 = next(p for p in D["paginas"] if p["hoja"] == "DP30301")
P3 = next(p for p in D["paginas"] if p["hoja"] == "DP30303")


def _campo(pagina, casilla):
    return next(c for c in pagina["campos"] if c["descripcion"].rstrip().endswith(f"[{casilla}]"))


def test_importe_positivo_sin_separador_con_ceros_a_la_izquierda():
    assert e.formatear(_campo(P1, "150"), Decimal("1234.56")) == "00000000000123456"
    assert e.formatear(_campo(P1, "150"), 0) == "0" * 17


def test_importe_con_signo_lleva_una_N_en_la_primera_posicion_si_es_negativo():
    c = _campo(P1, "46")                                                # tipo N
    assert c["tipo"].strip() == "N"
    assert e.formatear(c, Decimal("-12.30")) == "N0000000000001230"
    assert len(e.formatear(c, Decimal("-0.01"))) == 17


def test_un_importe_negativo_en_un_campo_sin_signo_se_rechaza():
    c = _campo(P1, "150")                                               # Num
    with pytest.raises(e.ErrorDeFormato, match="SIN signo"):
        e.formatear(c, Decimal("-1"))


def test_un_valor_que_no_cabe_se_rechaza_no_se_recorta():
    with pytest.raises(e.ErrorDeFormato, match="no cabe"):
        e.formatear(_campo(P1, "150"), Decimal("1" + "0" * 16))
    nombre = next(c for c in P1["campos"] if c["descripcion"].endswith("Apellidos y nombre o Razón social"))
    with pytest.raises(e.ErrorDeFormato, match="caben 80"):
        e.formatear(nombre, "X" * 81)


def test_el_texto_va_a_la_izquierda_sin_tildes_en_mayusculas_y_relleno_de_blancos():
    nombre = next(c for c in P1["campos"] if c["descripcion"].endswith("Apellidos y nombre o Razón social"))
    s = e.formatear(nombre, "Peñíscola & Hnos, S.L.")
    assert len(s) == 80 and s.startswith("PENISCOLA   HNOS  S L ") and s.strip() == "PENISCOLA   HNOS  S L"


def test_los_importes_se_redondean_al_centimo_mitad_hacia_arriba():
    c = _campo(P1, "150")
    assert e.formatear(c, Decimal("0.005")) == "0" * 16 + "1"
    assert e.formatear(c, Decimal("0.004")) == "0" * 17


def _declaracion_a_cero(periodo="2T"):
    v1 = {6: "N", 7: "A12345674", 8: "Despacho de prueba SL", 9: "2026", 10: periodo, **e.indicadores_pagina1(periodo)}
    return e.construir(D, ejercicio=2026, periodo=periodo, paginas={"DP30301": v1, "DP30303": {}})


def test_la_envoltura_y_las_paginas_miden_lo_que_dice_el_diseno():
    f = _declaracion_a_cero().decode("iso-8859-15")
    assert f.startswith("<T30302026" + "2T" + "0000><AUX>") and f.endswith("</T30302026" + "2T0000>")
    assert len(f) == 328 + 1581 + 1017 + len("</T30302026" + "2T0000>")
    assert "<T30301000>" in f and "</T30301000>" in f and "<T30303000>" in f and "</T30303000>" in f
    assert "<AUX>" in f and "</AUX>" in f


def test_se_puede_leer_lo_construido_con_el_mismo_diseno():
    datos = _declaracion_a_cero()
    r = e.descomponer(D, datos)
    assert [p["hoja"] for p in r["paginas"]] == ["DP30301", "DP30303"]
    assert r["cabecera"][4] == "2026" and r["cabecera"][5] == "2T"
    p1 = r["paginas"][0]["campos"]
    assert p1[6] == "N" and p1[7] == "A12345674" and p1[10] == "2T" and p1[13] == "3"
    assert r["cola"] == "</T30302026" + "2T0000>"


def test_indicadores_segun_el_periodo():
    assert e.indicadores_pagina1("2T")[23] == "0" and e.indicadores_pagina1("2T")[25] == "0"
    assert e.indicadores_pagina1("4T")[23] == "2" and e.indicadores_pagina1("4T")[17] == "2"
    assert e.indicadores_pagina1("07")[25] == "2"


def test_periodo_o_ejercicio_no_validos_se_rechazan():
    with pytest.raises(e.ErrorDeFormato):
        e.construir(D, ejercicio=2026, periodo="5T", paginas={})
    with pytest.raises(e.ErrorDeFormato):
        e.construir(D, ejercicio=2025, periodo="2T", paginas={})


def test_una_casilla_inexistente_o_un_campo_inexistente_se_rechazan():
    with pytest.raises(e.ErrorDeFormato, match="no existe"):
        e.construir(D, ejercicio=2026, periodo="2T", paginas={"DP30301": {"999": 1}})
    with pytest.raises(e.ErrorDeFormato, match="no existe"):
        e.construir(D, ejercicio=2026, periodo="2T", paginas={"DP30301": {9999: 1}})


def test_valores_por_casilla():
    f = e.construir(D, ejercicio=2026, periodo="2T", paginas={"DP30301": {"150": Decimal("100.00"), "152": Decimal("21.00")}}).decode("iso-8859-15")
    r = e.descomponer(D, f.encode("iso-8859-15"))
    c150, c152 = _campo(P1, "150"), _campo(P1, "152")
    assert r["paginas"][0]["campos"][c150["n"]] == "00000000000010000" and r["paginas"][0]["campos"][c152["n"]] == "00000000000002100"
