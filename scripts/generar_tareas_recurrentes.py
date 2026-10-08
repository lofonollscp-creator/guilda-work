"""Recurrencia automática de tareas (semanal/mensual, ver
app/db.py:generar_tareas_recurrentes) -- pensado para correr a diario vía
el timer systemd deploy/tareas-recurrentes.timer/.service, mismo patrón
exacto que scripts/generar_vencimientos_fiscales.py.

Uso:
    .venv/bin/python scripts/generar_tareas_recurrentes.py

No necesita ningún parámetro: recorre TODAS las reglas activas de TODOS
los usuarios y genera lo que falte del periodo en curso. Idempotente --
ejecutarlo varias veces seguidas el mismo día no duplica nada."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, salud  # noqa: E402


def main() -> None:
    try:
        creadas = db.generar_tareas_recurrentes()
        por_vencimiento = db.generar_tareas_por_vencimiento()
    except Exception as e:
        salud.registrar_error("tareas_recurrentes", 24 * 3600, f"{type(e).__name__}: {e}")
        raise
    salud.registrar_ok("tareas_recurrentes", 24 * 3600, f"{creadas} creada(s), {por_vencimiento} por vencimiento")
    print(f"Tareas recurrentes generadas: {creadas}; por vencimiento fiscal: {por_vencimiento}")


if __name__ == "__main__":
    main()
