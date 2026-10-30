"""Plantillas recurrentes de Guilda Fiscal (app/fiscal_recurrentes.py): crea los apuntes que tocan -- pensado para correr a diario vía el timer systemd
deploy/apuntes-recurrentes.timer/.service, mismo patrón que scripts/generar_tareas_recurrentes.py.

Uso:
    .venv/bin/python scripts/generar_apuntes_recurrentes.py

No necesita parámetros: recorre las plantillas activas de TODOS los despachos y pone al día las fechas ya llegadas. Idempotente: ejecutarlo varias veces seguidas no duplica nada."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fiscal_recurrentes, salud  # noqa: E402


def main() -> None:
    try:
        r = fiscal_recurrentes.generar()
    except Exception as e:
        salud.registrar_error("apuntes_recurrentes", 24 * 3600, f"{type(e).__name__}: {e}")
        raise
    salud.registrar_ok("apuntes_recurrentes", 24 * 3600, f"{r['creados']} apunte(s) en {r['plantillas']} plantilla(s), {r['errores']} con error")
    print(f"Apuntes recurrentes creados: {r['creados']}; ya existían: {r['ya_existian']}; plantillas con error: {r['errores']}")


if __name__ == "__main__":
    main()
