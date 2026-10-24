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
    assert len(f) == 328 + 1581 + 1017 + 823 + len("</T30302026" + "2T0000>")
    assert "<T30301000>" in f and "</T30301000>" in f and "<T30303000>" in f and "</T30303000>" in f
    assert "<AUX>" in f and "</AUX>" in f


def test_se_puede_leer_lo_construido_con_el_mismo_diseno():
    datos = _declaracion_a_cero()
    r = e.descomponer(D, datos)
    assert [p["hoja"] for p in r["paginas"]] == ["DP30301", "DP30303", "DP303DID"]
    assert r["cabecera"][4] == "2026" and r["cabecera"][5] == "2T"
    p1 = r["paginas"][0]["campos"]
    assert p1[6] == "N" and p1[7] == "A12345674" and p1[10] == "2T" and p1[13] == "3"
    assert r["cola"] == "</T30302026" + "2T0000>"


def test_indicadores_segun_el_periodo():
    assert e.indicadores_pagina1("2T")[23] == "0" and e.indicadores_pagina1("2T")[25] == "0" and e.indicadores_pagina1("2T")[17] == "2"
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


def test_la_pagina_did_va_siempre_aunque_este_vacia_y_el_orden_es_el_del_diseno():
    f = e.construir(D, ejercicio=2026, periodo="1T", paginas={"DP30303": {}, "DP30301": {}}).decode("iso-8859-15")
    assert f.index("<T30301000>") < f.index("<T30303000>") < f.index("<T303DID00>")


def test_las_constantes_con_nota_a_continuacion_se_respetan():
    """«Constante "00400". Nota 7» (tipo del 4 %): el simulador de la AEAT rechaza el campo si va a ceros (E010331)."""
    r = e.descomponer(D, e.construir(D, ejercicio=2026, periodo="2T", paginas={"DP30301": {}}))
    p1 = next(p for p in r["paginas"] if p["hoja"] == "DP30301")["campos"]
    c = {x["descripcion"].rstrip().rsplit(" ", 1)[-1]: x["n"] for x in P1["campos"] if x["descripcion"].rstrip().endswith(("[02]", "[05]", "[08]", "[169]"))}
    assert p1[c["[02]"]] == "00400" and p1[c["[05]"]] == "01000" and p1[c["[08]"]] == "02100" and p1[c["[169]"]] == "00050"


# --- Contra el simulador oficial de la AEAT ------------------------------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "aeat"


def _ejemplo_21():
    """La venta de 100,00 € al 21 % con el NIF de PRUEBA A12345674: lo que se subió al simulador y lo que éste exportó de vuelta (24-oct-2026)."""
    b1 = {7: "A12345674", 8: "EMPRESA DE PRUEBA SL", 9: "2026", 10: "2T", **e.indicadores_pagina1("2T")}
    v1 = {6: "I", **b1, "07": Decimal("100.00"), "09": Decimal("21.00"), "27": Decimal("21.00"), "45": Decimal("0"), "46": Decimal("21.00")}
    v3 = {"64": Decimal("21.00"), "65": Decimal("100.00"), "66": Decimal("21.00"), "69": Decimal("21.00"), "71": Decimal("21.00")}
    return e.construir(D, ejercicio=2026, periodo="2T", paginas={"DP30301": v1, "DP30303": v3}, version_programa="", nif_empresa_desarrollo="")


def test_nuestro_fichero_coincide_byte_a_byte_con_el_que_exporta_el_simulador_salvo_campos_de_la_aeat():
    """El simulador importó nuestro fichero SIN errores, calculó el resultado 21,00 y lo exportó de vuelta: mismo tamaño y solo difieren campos que son de la AEAT (reservados) o de la entidad desarrolladora."""
    nuestro = _ejemplo_21()
    assert nuestro == (FIXTURES / "nuestro_303_2026_2T_ejemplo21.303").read_bytes()
    aeat = (FIXTURES / "exportado_por_aeat_simulador_303_2026_2T_ejemplo21.303").read_bytes()
    assert len(nuestro) == len(aeat)
    distintos = {(h, n) for h, n, _d in e.campos_distintos(D, nuestro, aeat)}
    assert distintos == {("DP30300", 8), ("DP30300", 9), ("DP30300", 11), ("DP30303", 37)}     # reservado, versión del programa, NIF de la entidad desarrolladora, reservado de la página 3


def test_el_fichero_de_la_aeat_es_ascii_sin_saltos_de_linea():
    """Evidencia de formato (antes eran suposiciones): una sola «línea», sin CR ni LF, y solo caracteres ASCII."""
    aeat = (FIXTURES / "exportado_por_aeat_simulador_303_2026_2T_ejemplo21.303").read_bytes()
    assert b"\r" not in aeat and b"\n" not in aeat and all(b < 128 for b in aeat)


def test_cuando_no_hay_concurso_la_fecha_del_auto_va_a_ceros_como_hace_la_aeat():
    r = e.descomponer(D, _ejemplo_21())
    assert r["paginas"][0]["campos"][20] == "00000000"


# --- Prueba en línea (opcional): GUILDA_FISCAL_SIMULADOR=1 y Playwright con Chromium ----------------------------------------------------------

import importlib.util  # noqa: E402
import os  # noqa: E402

_ONLINE = os.environ.get("GUILDA_FISCAL_SIMULADOR") == "1" and importlib.util.find_spec("playwright") is not None


@pytest.mark.skipif(not _ONLINE, reason="prueba en línea contra el simulador público de la AEAT: GUILDA_FISCAL_SIMULADOR=1 y Playwright")
def test_el_simulador_acepta_el_ejemplo_y_rechaza_uno_incoherente(tmp_path):
    import importlib.util as iu

    spec = iu.spec_from_file_location("simulador_aeat", Path(__file__).resolve().parent.parent / "scripts" / "fiscal" / "simulador_aeat.py")
    sim = iu.module_from_spec(spec)
    spec.loader.exec_module(sim)
    bueno = tmp_path / "A1234567420262T.303"
    bueno.write_bytes(_ejemplo_21())
    r = sim.probar(bueno)
    codigos = {m["codigo"] for m in r["importacion"]["mensajes"]}
    assert not r["importacion"]["rechazado"] and "00001" in codigos and not any(c.startswith("E") for c in codigos) and r["resultado"] == "21,00"
    malo = bytearray(_ejemplo_21())
    campo = next(c for c in P1["campos"] if c["descripcion"].rstrip().endswith("[27]"))
    ini = 328 + sum(c["lon"] for c in P1["campos"] if c["n"] < campo["n"])
    malo[ini:ini + 17] = b"00000000000002000"                    # la casilla 27 mal a propósito
    f2 = tmp_path / "malo.303"
    f2.write_bytes(bytes(malo))
    codigos = {m["codigo"] for m in sim.probar(f2)["importacion"]["mensajes"]}
    assert "E010671" in codigos


def test_la_entidad_desarrolladora_va_vacia_por_defecto_y_se_puede_informar():
    assert e.NIF_ENTIDAD_DESARROLLADORA == "" and e.VERSION_PROGRAMA == ""
    vacia = e.construir(D, ejercicio=2026, periodo="2T", paginas={}).decode("iso-8859-15")
    con = e.construir(D, ejercicio=2026, periodo="2T", paginas={}, version_programa="1.00", nif_empresa_desarrollo="B16406233").decode("iso-8859-15")
    assert "B16406233" not in vacia and "1.00" not in vacia
    assert "B16406233" in con and "1.00" in con and len(con) == len(vacia)
