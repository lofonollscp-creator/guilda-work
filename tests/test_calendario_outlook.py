"""Tests de la lógica pura de rango/navegación del calendario de tareas
(app/rutas_tareas.py: _rango_para_vista, _mover_ancla, color_categoria).
"""
from datetime import date

from app.rutas_tareas import _mover_ancla, _rango_para_vista, color_categoria


def test_rango_dia():
    assert _rango_para_vista("dia", date(2026, 7, 15)) == (date(2026, 7, 15), date(2026, 7, 15))


def test_rango_semana_laboral():
    # 2026-07-15 es miércoles
    inicio, fin = _rango_para_vista("semana_laboral", date(2026, 7, 15))
    assert inicio == date(2026, 7, 13)  # lunes
    assert fin == date(2026, 7, 17)     # viernes


def test_rango_semana():
    inicio, fin = _rango_para_vista("semana", date(2026, 7, 15))
    assert inicio == date(2026, 7, 13)  # lunes
    assert fin == date(2026, 7, 19)     # domingo


def test_rango_mes_cubre_semanas_completas():
    # Julio de 2026 empieza en miércoles y termina en viernes.
    inicio, fin = _rango_para_vista("mes", date(2026, 7, 15))
    assert inicio.weekday() == 0  # lunes
    assert fin.weekday() == 6     # domingo
    assert inicio <= date(2026, 7, 1)
    assert fin >= date(2026, 7, 31)


def test_mover_ancla_dia():
    assert _mover_ancla("dia", date(2026, 7, 15), 1) == date(2026, 7, 16)
    assert _mover_ancla("dia", date(2026, 7, 15), -1) == date(2026, 7, 14)


def test_mover_ancla_semana():
    assert _mover_ancla("semana", date(2026, 7, 15), 1) == date(2026, 7, 22)
    assert _mover_ancla("semana_laboral", date(2026, 7, 15), -1) == date(2026, 7, 8)


def test_mover_ancla_mes_cruza_anio():
    assert _mover_ancla("mes", date(2026, 12, 10), 1) == date(2027, 1, 10)
    assert _mover_ancla("mes", date(2026, 1, 10), -1) == date(2025, 12, 10)


def test_mover_ancla_mes_ajusta_dia_invalido():
    # 31 de enero + 1 mes -> febrero no tiene 31, debe caer en el último día válido.
    assert _mover_ancla("mes", date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_color_categoria_estable_y_por_defecto():
    assert color_categoria("Trabajo") == color_categoria("Trabajo")
    assert color_categoria(None) == "#7c8ba1"
    assert color_categoria("") == "#7c8ba1"
