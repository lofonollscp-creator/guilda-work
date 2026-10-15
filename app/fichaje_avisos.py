"""Avisos de "salida olvidada". Dos, ambos UNA vez por jornada (notificación en la app + push) y sin cerrar ni tocar ningún fichaje: el registro horario solo lo cambia la propia
persona o quien administra, con corrección.

- **Por horas**: alguien lleva más de GUILDA_FICHAJE_AVISO_HORAS (10 por defecto, 0 lo desactiva) con la jornada abierta.
- **Por turno** (`procesar_avisos_turno`): la persona tiene un turno asignado en el cuadrante (app/turnos.py) que ya terminó hace más de GUILDA_FICHAJE_AVISO_TURNO_MARGEN_HORAS
  (1 por defecto, negativo lo desactiva) y sigue con la jornada abierta. Sin turno ese día, no hace nada."""
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


def margen_turno_horas() -> float:
    try:
        return float(os.environ.get("GUILDA_FICHAJE_AVISO_TURNO_MARGEN_HORAS", "1"))
    except ValueError:
        return 1.0


def _turno_de_la_jornada(tenant_id: int, usuario_id: int, entrada: datetime):
    """`(nombre, inicio, fin)` del turno al que corresponde una entrada: el de su día o, si entró de madrugada, el de la noche anterior que cruzaba la medianoche. None si no hay turno."""
    from . import turnos
    for dia in (entrada.date(), entrada.date() - timedelta(days=1)):
        for t in turnos.mis_turnos(tenant_id, usuario_id, dia.isoformat()):
            ini = datetime.fromisoformat(f"{dia.isoformat()}T{t['inicio']}:00")
            fin = ini + timedelta(hours=t["horas"])
            if dia == entrada.date() or fin > entrada:         # el de ayer solo vale si todavía no había terminado cuando entró
                return t["nombre"], ini, fin
    return None


def procesar_avisos_turno(ahora: datetime | None = None, margen_horas: float | None = None) -> int:
    """Avisa a quien sigue con la jornada abierta cuando su turno ya terminó hace más de `margen_horas`. Devuelve a cuántas personas se ha avisado."""
    margen = margen_turno_horas() if margen_horas is None else margen_horas
    if margen < 0:
        return 0
    ahora = ahora or datetime.now()
    avisados = 0
    for jornada in db.jornadas_abiertas_desde((ahora - timedelta(hours=36)).isoformat(timespec="seconds")):
        entrada = datetime.fromisoformat(jornada["marca_tiempo"])
        t = _turno_de_la_jornada(jornada["tenant_id"], jornada["usuario_id"], entrada) if jornada["tenant_id"] is not None else None
        if t is None or ahora < t[2] + timedelta(hours=margen):
            continue
        if not db.registrar_aviso_turno(jornada["usuario_id"], jornada["entrada_id"]):
            continue
        tarde = (ahora - t[2]).total_seconds() / 3600
        try:
            notificaciones.crear_y_enviar(
                jornada["usuario_id"], "fichaje_salida_olvidada", "Tu turno ya ha terminado",
                f"Tu turno «{t[0]}» acabó a las {t[2].strftime('%H:%M')} (hace {tarde:.1f} h) y tu jornada sigue abierta. Ficha la salida o pide una corrección.",
                url="/fichaje/", datos={"tipo": "fichaje_salida_olvidada"},
            )
            avisados += 1
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo avisar del fin de turno a %s", jornada["usuario_id"])
    return avisados
