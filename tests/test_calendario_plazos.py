"""Cálculo de plazos (app/calendario_plazos.py): funciones puras con casos concretos."""
from datetime import date

import pytest

from app import calendario_plazos as c


@pytest.mark.parametrize("anio,esperada", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2038, date(2038, 4, 25))])
def test_pascua(anio, esperada):
    assert c.pascua(anio) == esperada


def test_festivos_nacionales_de_ejemplo():
    f = c.festivos_nacionales(2026)
    assert date(2026, 4, 3) in f and f[date(2026, 4, 3)] == "Viernes Santo"
    assert date(2026, 10, 12) in f and date(2026, 12, 25) in f and date(2026, 1, 1) in f
    assert len(f) == 10


def test_es_habil_fines_de_semana_festivos_y_meses_inhabiles():
    cal = c.calendario_procesal([2026])
    assert cal.es_habil(date(2026, 10, 13))                      # martes
    assert not cal.es_habil(date(2026, 10, 10)) and not cal.es_habil(date(2026, 10, 11))      # fin de semana
    assert not cal.es_habil(date(2026, 10, 12))                  # festivo (lunes)
    assert not cal.es_habil(date(2026, 8, 12))                   # agosto inhábil
    assert c.calendario(sabado_habil=True).es_habil(date(2026, 10, 10))
    ex = c.calendario(meses_inhabiles=[8], excepciones_inhabiles=[date(2026, 8, 12)])
    assert ex.es_habil(date(2026, 8, 12)) and not ex.es_habil(date(2026, 8, 13))


def test_sumar_dias_habiles_se_salta_agosto_solo_en_el_calendario_procesal():
    inicio = date(2026, 7, 29)
    assert c.sumar_dias_habiles(inicio, 5, c.calendario_general([2026])) == date(2026, 8, 5)
    assert c.sumar_dias_habiles(inicio, 5, c.calendario_procesal([2026])) == date(2026, 9, 3)


def test_sumar_dias_habiles_cero_y_hacia_atras():
    cal = c.calendario_general([2026])
    assert c.sumar_dias_habiles(date(2026, 10, 10), 0, cal) == date(2026, 10, 13)      # sábado → primer hábil (el 12 es festivo)
    assert c.sumar_dias_habiles(date(2026, 10, 13), -1, cal) == date(2026, 10, 9)      # el lunes 12 es festivo
    assert c.sumar_dias_habiles(date(2026, 10, 13), 1, cal) == date(2026, 10, 14)


def test_dias_habiles_entre():
    cal = c.calendario_general([2026])
    assert c.dias_habiles_entre(date(2026, 10, 9), date(2026, 10, 14), cal) == 2            # 13 y 14 (el 12 es festivo)
    assert c.dias_habiles_entre(date(2026, 10, 14), date(2026, 10, 9), cal) == -2
    assert c.dias_habiles_entre(date(2026, 10, 9), date(2026, 10, 9), cal) == 0


def test_vencimiento_naturales_meses_y_desplazamiento():
    cal = c.calendario_general([2026])
    assert c.vencimiento(date(2026, 10, 1), 10, "naturales", cal) == date(2026, 10, 13)           # el 11 es domingo y el 12 festivo → martes 13
    assert c.vencimiento(date(2026, 10, 1), 10, "naturales", cal, desplazar_si_inhabil=False) == date(2026, 10, 11)
    assert c.vencimiento(date(2026, 1, 31), 1, "meses", cal) == date(2026, 3, 2)                   # 28 feb es sábado → lunes 2 de marzo
    assert c.vencimiento(date(2026, 1, 31), 1, "meses", cal, desplazar_si_inhabil=False) == date(2026, 2, 28)
    assert c.vencimiento(date(2026, 11, 30), 3, "meses", cal, desplazar_si_inhabil=False) == date(2027, 2, 28)
    assert c.vencimiento(date(2026, 12, 15), 2, "meses", cal, desplazar_si_inhabil=False) == date(2027, 2, 15)
    assert c.vencimiento(date(2026, 10, 1), 3, "habiles", cal) == date(2026, 10, 6)
    with pytest.raises(ValueError):
        c.vencimiento(date(2026, 10, 1), 3, "lunares", cal)


def test_fechas_de_aviso():
    cal = c.calendario_general([2026])
    limite = date(2026, 10, 20)
    assert c.fechas_de_aviso(limite) == [date(2026, 10, 13), date(2026, 10, 17), date(2026, 10, 19)]
    # con calendario, el aviso del sábado 17 se adelanta al viernes 16
    assert c.fechas_de_aviso(limite, cal=cal) == [date(2026, 10, 13), date(2026, 10, 16), date(2026, 10, 19)]
    assert c.fechas_de_aviso(limite, (0, 0, 2)) == [date(2026, 10, 18), date(2026, 10, 20)]     # sin repetidas
    assert c.fechas_de_aviso(limite, (-1,)) == []


def test_estado_del_plazo():
    cal = c.calendario_general([2026])
    hoy = date(2026, 10, 13)
    assert c.estado_del_plazo(date(2026, 10, 12), hoy) == "vencido"
    assert c.estado_del_plazo(date(2026, 10, 12), hoy, cumplido=True) == "cumplido"
    assert c.estado_del_plazo(hoy, hoy) == "hoy"
    assert c.estado_del_plazo(date(2026, 10, 15), hoy, cal=cal) == "proximo"
    assert c.estado_del_plazo(date(2026, 10, 30), hoy, cal=cal) == "en_plazo"
    assert c.estado_del_plazo(date(2026, 10, 16), hoy) == "proximo" and c.estado_del_plazo(date(2026, 10, 17), hoy) == "en_plazo"


def test_el_modulo_es_puro():
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent / "app" / "calendario_plazos.py").read_text(encoding="utf-8")
    assert "import flask" not in fuente and "from . import db" not in fuente and "sqlite3" not in fuente
