"""Aviso de "salida olvidada": si alguien lleva más de GUILDA_FICHAJE_AVISO_HORAS
(10 por defecto, 0 lo desactiva) con la jornada abierta, se le avisa UNA vez
por jornada (notificación en la app + push). No cierra ni toca ningún
fichaje: el registro horario solo lo cambia la propia persona o quien
administra, con corrección."""
import logging
import os
from datetime import datetime, timedelta

from . import db, notificaciones

logger = logging.getLogger("guilda")


def horas_aviso() -> float:
    try:
        return float(os.environ.get("GUILDA_FICHAJE_AVISO_HORAS", "10"))
    except ValueError:
        return 10.0


def procesar_avisos(ahora: datetime | None = None, horas: float | None = None) -> int:
    """Devuelve a cuántas personas se ha avisado en esta pasada."""
    horas = horas_aviso() if horas is None else horas
    if horas <= 0:
        return 0
    ahora = ahora or datetime.now()
    limite = (ahora - timedelta(hours=horas)).isoformat(timespec="seconds")
    avisados = 0
    for jornada in db.jornadas_abiertas_sin_aviso(limite):
        # Se registra ANTES de notificar: ante un fallo del push no se
        # reintenta cada 15 minutos (un aviso perdido es mejor que un spam).
        if not db.registrar_aviso_fichaje(jornada["usuario_id"], jornada["entrada_id"]):
            continue
        entrada = datetime.fromisoformat(jornada["marca_tiempo"])
        transcurridas = (ahora - entrada).total_seconds() / 3600
        try:
            notificaciones.crear_y_enviar(
                jornada["usuario_id"], "fichaje_salida_olvidada", "¿Olvidaste fichar la salida?",
                f"Tu jornada abierta desde las {entrada.strftime('%H:%M')} lleva {transcurridas:.0f} h. "
                "Ficha la salida o pide una corrección.",
                url="/fichaje/", datos={"tipo": "fichaje_salida_olvidada"},
            )
            avisados += 1
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo avisar de la salida olvidada a %s", jornada["usuario_id"])
    return avisados
