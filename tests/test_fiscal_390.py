"""Modelo 390: el motor anual y su cuadre con los cuatro 303; las casillas existen en el diseño oficial; el fichero respeta el diseño."""
from datetime import date

import pytest

from app.fiscal_modelos import motor_303, motor_390 as m
from app.fiscal_modelos.apuntes import Apunte

E, R = "E", "R"


def _ap(libro, fecha, base, tipo=2100, **kw):
    cuota = kw.pop("cuota", base * tipo // 10000)
    return Apunte(libro=libro, tipo_factura=kw.pop("tipo_factura", "F1"), fecha_expedicion=fecha, numero=kw.pop("numero", f"{libro}{fecha.month}{base}"), base=base, tipo_iva=tipo, cuota=cuota, **kw)


def _anio():
    return [
        _ap(E, date(2026, 2, 10), 100000),                                  # 21 % en 1T
        _ap(E, date(2026, 5, 10), 50000, 400),                              # 4 % en 2T
        _ap(E, date(2026, 5, 20), 30000, 0, cuota=0, calificacion="S1", exenta="E1", numero="X1"),      # exenta sin derecho a deducción
        _ap(E, date(2026, 8, 1), 20000, 1000),                              # 10 % en 3T
        _ap(R, date(2026, 8, 5), 40000),                                    # corriente 21 %
        _ap(R, date(2026, 11, 3), 100000, bien_inversion=True),             # inversión 21 %
        _ap(R, date(2026, 11, 9), 10000, 1000),                             # corriente 10 %
    ]


def test_todas_las_casillas_que_usa_el_motor_existen_en_el_diseno():
    for t in m.TIPOS_DEVENGO:
        assert all(m._devengo_ordinario(t))
    for bloque in (m.DED_INTERIOR_CORRIENTE, m.DED_INTERIOR_INVERSION, m.DED_IMPORT_CORRIENTE, m.DED_IMPORT_INVERSION):
        for t in m.TIPOS_DEDUCIBLE:
            assert all(m._deducible(bloque, t))
        assert all(m._par_total(bloque[0], m._TOTAL_DEDUCIBLE[bloque]))
    r = m.calcular(_anio(), ejercicio=2026)          # no lanza: todas las casillas de volumen y resultado se resuelven
    assert r.calculable, r.bloqueos


def test_el_390_cuadra_con_la_suma_de_los_cuatro_303():
    ap = _anio()
    r = m.calcular(ap, ejercicio=2026)
    s27 = sum(motor_303.calcular(ap, ejercicio=2026, periodo=t).casillas["27"] for t in m.TRIMESTRES)
    s45 = sum(motor_303.calcular(ap, ejercicio=2026, periodo=t).casillas["45"] for t in m.TRIMESTRES)
    c = r.casillas
    assert c[m.casilla("Pág. 2", "Total bases y cuotas IVA", final="Cuota")] == s27 == 21000 + 2000 + 2000
    assert c[m.casilla("Pág. 4", "Suma de deducciones")] == s45 == 8400 + 21000 + 1000
    assert c[m.casilla("Pág. 4", "Resultado régimen general")] == s27 - s45
    assert not [a for a in r.avisos if "no coincide" in a]
    # desglose por tipo
    assert c[m._devengo_ordinario(2100)[0]] == 100000 and c[m._devengo_ordinario(400)[1]] == 2000 and c[m._devengo_ordinario(1000)[1]] == 2000
    assert c[m._deducible(m.DED_INTERIOR_CORRIENTE, 2100)[1]] == 8400 and c[m._deducible(m.DED_INTERIOR_INVERSION, 2100)[1]] == 21000 and c[m._deducible(m.DED_INTERIOR_CORRIENTE, 1000)[1]] == 1000


def test_volumen_de_operaciones_y_resultado_anual():
    r = m.calcular(_anio(), ejercicio=2026)
    c = r.casillas
    assert c["99"] == 100000 + 50000 + 20000 and c["105"] == 30000 and c["108"] == 200000
    assert any("106 y 107" in a for a in r.avisos)
    assert c["84"] == c["86"] == 25000 - 30400 and c["87"] == 10000 and c["92"] == c["94"] == -5400
    assert c["95"] == 21000 + 2000                                  # solo los 303 con resultado a ingresar (el 3T sale negativo)
    assert "97" in c and "98" not in c                               # el 4T sale a compensar (destino por defecto)


def test_lo_no_soportado_se_bloquea():
    ap = _anio() + [_ap(R, date(2026, 3, 3), 5000, clave="09")]
    r = m.calcular(ap, ejercicio=2026)
    assert not r.calculable and any("intracomunitarias" in b for b in r.bloqueos)
    assert not m.calcular(_anio(), ejercicio=2026, prorrata=True).calculable
    raro = m.calcular([_ap(R, date(2026, 3, 3), 1000, 700, cuota=70)], ejercicio=2026)
    assert any("no desglosa el tipo" in b for b in raro.bloqueos)


def test_una_declaracion_del_303_ya_revisada_manda_sobre_el_calculo():
    ap = _anio()
    r = m.calcular(ap, ejercicio=2026, declaraciones_303={"1T": {"casillas": {"27": 21000, "45": 0, "71": 21000, "66": 21000}, "tipo_declaracion": "I"}})
    assert not any("1T" in a for a in r.avisos if "Sin declaración" in a) and any("2T" in a for a in r.avisos if "Sin declaración" in a)


def test_el_fichero_390_respeta_el_diseno_y_devuelve_lo_calculado():
    from app.fiscal_modelos import fichero_390 as f
    r = m.calcular(_anio(), ejercicio=2026)
    diseno = f.cargar_diseno()
    datos = f.generar(r, nif="B12345674", nombre="Empresa Web SL")
    texto = datos.decode("iso-8859-15")
    esperado = 328 + sum(p["total_posiciones"] for p in diseno["paginas"] if p["hoja"] in f.PAGINAS) + len("</T390020260A0000>")
    assert len(texto) == esperado
    assert texto.startswith("<T390020260A0000><AUX>") and texto.endswith("</T390020260A0000>") and "<T39001000>" in texto and "</T39006000>" in texto
    assert f.leer_casillas(diseno, datos) == {k: v for k, v in r.casillas.items() if v}
    assert "B12345674" in texto and "EMPRESA WEB SL" in texto


def test_el_fichero_390_no_se_genera_si_el_calculo_esta_bloqueado_o_el_nombre_no_cabe():
    from app.fiscal_modelos import fichero_390 as f
    bloqueado = m.calcular(_anio(), ejercicio=2026, criterio_caja=True)
    with pytest.raises(f.FicheroNoGenerable):
        f.generar(bloqueado, nif="B12345674", nombre="X")
    with pytest.raises(f.FicheroNoGenerable):
        f.generar(m.calcular(_anio(), ejercicio=2026), nif="B12345674", nombre="X" * 61)


def test_303_del_ultimo_periodo_sin_exoneracion_y_con_ella():
    import json
    from app.fiscal_modelos import exportador_303 as ex, fichero_303 as f303
    ap = _anio()
    r4 = motor_303.calcular(ap, ejercicio=2026, periodo="4T")
    diseno = json.loads(ex.DISENO_303_2026.read_text(encoding="utf-8"))
    normal = f303.generar(r4, nif="B12345674", nombre="EMPRESA WEB SL")
    d = ex.descomponer(diseno, normal)
    assert "DP30304" not in [p["hoja"] for p in d["paginas"]]
    p1 = next(p for p in d["paginas"] if p["hoja"] == "DP30301")["campos"]
    assert (p1[23], p1[24]) == ("2", "0")                           # no exonerado del 390: «2» y el volumen anual no se declara (Nota 3: «0»)
    # exonerado: lleva la página 4 con el volumen de operaciones del año y el territorio común al 100 %
    with pytest.raises(f303.FicheroNoGenerable):
        f303.generar(r4, nif="B12345674", nombre="X", exonerado_390=True)
    volumen = m.volumen_anual(ap, 2026)
    conexo = f303.generar(r4, nif="B12345674", nombre="EMPRESA WEB SL", exonerado_390=True, volumen=volumen)
    d = ex.descomponer(diseno, conexo)
    assert "DP30304" in [p["hoja"] for p in d["paginas"]]
    p1 = next(p for p in d["paginas"] if p["hoja"] == "DP30301")["campos"]
    assert (p1[23], p1[24]) == ("1", "1")
    p4 = next(p for p in d["paginas"] if p["hoja"] == "DP30304")["campos"]
    assert int(p4[23]) == 10000 and int(p4[24]) == 170000 and int(p4[28]) == 30000 and int(p4[41]) == 200000
    assert ex.leer_casillas(diseno, conexo)["45"] == r4.casillas["45"]       # las casillas del 303 del último periodo siguen siendo las del motor


def test_el_volumen_del_303_y_el_del_390_son_los_mismos_conceptos_en_los_dos_disenos():
    import json
    from app.fiscal_modelos import exportador_303 as ex, fichero_303 as f303
    d303 = json.loads(ex.DISENO_303_2026.read_text(encoding="utf-8"))
    p4 = next(p for p in d303["paginas"] if p["hoja"] == "DP30304")["campos"]
    palabras = {24: "régimen general", 26: "intracomunitarias", 27: "Exportaciones", 28: "exentas sin derecho", 29: "no sujetas por reglas de localización", 30: "inversión del sujeto pasivo", 41: "Total volumen"}
    for n, c390 in f303.VOLUMEN_PAGINA_4.items():
        campo = next(c for c in p4 if c["n"] == n)
        d390 = next(t for h, c, t in m._descripciones() if h == "Pág. 6" and c == c390)
        assert palabras[n].lower() in campo["descripcion"].lower() and palabras[n].lower() in d390.lower(), (n, c390, campo["descripcion"], d390)
