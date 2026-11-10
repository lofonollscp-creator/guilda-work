"""Documentos periódicos (K6): una regla abre la petición del periodo una sola vez, con el periodo anterior en el título."""
from datetime import date

import pytest

from app import db, portal_peticiones as pp, portal_peticiones_recurrentes as ppr
from tests.test_portal_bandeja import _escenario


def test_los_periodos_se_nombran_bien():
    assert ppr.periodo(date(2026, 11, 3), "mensual") == "2026-11" and ppr.periodo(date(2026, 11, 3), "trimestral") == "2026-T4"
    assert ppr.periodo_anterior(date(2026, 11, 3), "mensual") == "octubre 2026" and ppr.periodo_anterior(date(2027, 1, 2), "mensual") == "diciembre 2026"
    assert ppr.periodo_anterior(date(2026, 10, 1), "trimestral") == "3T 2026" and ppr.periodo_anterior(date(2027, 1, 5), "trimestral") == "4T 2026"


def test_valida_la_regla(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    for args in (("ab", "mensual"), ("Extracto", "anual"), ("Extracto", "mensual", 0), ("Extracto", "mensual", 31), ("Extracto", "mensual", "x")):
        with pytest.raises(ValueError):
            ppr.crear(f1, *args)
    for i in range(ppr.MAX_REGLAS):
        ppr.crear(f1, f"Documento {i}", "mensual")
    with pytest.raises(ValueError):
        ppr.crear(f1, "Otro más", "mensual")


def test_genera_una_vez_por_periodo_y_respeta_la_pausa(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    r = ppr.crear(f1, "Extracto bancario", "mensual", 12, por=u)
    q = ppr.crear(f1, "Libro de caja", "trimestral", 15)
    assert ppr.generar(date(2026, 11, 2)) == 1                                              # el trimestral no toca en noviembre
    pet = pp.listar(f1)
    assert [p["titulo"] for p in pet] == ["Extracto bancario · octubre 2026"] and pet[0]["fecha_limite"] == "2026-11-12"
    assert ppr.generar(date(2026, 11, 20)) == 0                                             # mismo periodo: no se repite
    ppr.activar(f1, r, False)
    assert ppr.generar(date(2026, 12, 1)) == 0
    ppr.activar(f1, r, True)
    assert ppr.generar(date(2027, 1, 4)) == 2 and {p["titulo"] for p in pp.listar(f1)} >= {"Libro de caja · 4T 2026", "Extracto bancario · diciembre 2026"}


def test_si_hay_demasiadas_abiertas_reintenta_y_no_pierde_el_periodo(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    for i in range(pp.MAX_ABIERTAS):
        pp.crear(f1, f"Petición {i}", por=u)
    r = ppr.crear(f1, "Extracto bancario", "mensual")
    assert ppr.generar(date(2026, 11, 2)) == 0 and ppr.listar(f1)[0]["ultima_generada"] is None
    conn = db.get_connection(); conn.execute("UPDATE portal_peticiones SET estado = 'cancelada' WHERE tenant_id = ?", (t,)); conn.commit(); conn.close()
    assert ppr.generar(date(2026, 11, 3)) == 1


def test_borrar_solo_afecta_a_ese_cliente(cliente):
    t, u, c, f1, c2, f2 = _escenario()
    r = ppr.crear(f1, "Extracto bancario", "mensual")
    assert ppr.borrar(f2, r) is False and ppr.activar(f2, r, False) is False and len(ppr.listar(f1)) == 1
    assert ppr.borrar(f1, r) is True and ppr.listar(f1) == []
