"""Pasada diaria de las reglas de automatización (app/automatizaciones.py) -- pensado para correr desde el timer systemd
deploy/automatizaciones.timer/.service, mismo patrón que scripts/generar_tareas_recurrentes.py.

Uso:
    .venv/bin/python scripts/ejecutar_automatizaciones.py

Recorre las reglas activas de todos los despachos: atiende lo nuevo y reintenta lo que falló. Idempotente: ejecutarlo varias veces seguidas no duplica nada.
Anota su latido en el panel de salud (nombre «automatizaciones»); si falla, el panel lo enseña en rojo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import automatizaciones, salud  # noqa: E402


def main() -> None:
    try:
        # Primero lo que quedó en la cola de eventos (los que generaron otros procesos, como la creación de tareas recurrentes a las 04:30, o un reinicio a medias), por lotes y con tope.
        eventos = 0
        for _ in range(20):
            lote = automatizaciones.procesar_eventos()
            eventos += lote["eventos"]
            if lote["eventos"] < automatizaciones.MAX_EVENTOS_POR_LOTE:
                break
        r = automatizaciones.ejecutar()
        r["nuevas"] += eventos
    except Exception as e:
        salud.registrar_error("automatizaciones", 24 * 3600, f"{type(e).__name__}: {e}")
        raise
    detalle = f"{r['nuevas']} nueva(s), {r['reintentos']} reintento(s), {r['errores']} error(es), {r['fallidas']} fallida(s)"
    # Un error de una regla concreta ya queda en su ejecución y avisa a la dirección; el latido solo se pone en rojo si la pasada entera se rompe.
    salud.registrar_ok("automatizaciones", 24 * 3600, detalle)
    print(f"Automatizaciones: {detalle}")


if __name__ == "__main__":
    main()
