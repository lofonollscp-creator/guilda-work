"""Recordatorios por tarea: cada persona pone los suyos (a una hora concreta o
respecto al vencimiento) y elige por dónde le llegan -- centro de avisos de la
app + push del móvil, correo o ntfy. Se pueden posponer en un clic desde la
ficha de la tarea (ver app/rutas_tareas.py). Se procesan cada minuto desde un
hilo del servidor (ver app/main.py:_recordatorios_tareas_servidor)."""
import logging
from datetime import datetime

from . import db, notificaciones, notificaciones_email, ntfy

logger = logging.getLogger("guilda")


def _texto(r: dict) -> tuple[str, str]:
    cuerpo = r["asunto"]
    if r["fecha_vencimiento"]:
        cuerpo += f" (vence {r['fecha_vencimiento'][:16].replace('T', ' ')})"
    return "Recordatorio de tarea", cuerpo


def procesar_recordatorios(ahora: datetime | None = None) -> int:
    """Envía los recordatorios vencidos y devuelve cuántos se han marcado como
    enviados. Se marca ANTES de mandar: ante un fallo no se reintenta cada minuto
    (un aviso perdido es mejor que un spam); cada canal falla por separado."""
    enviados = 0
    for r in db.recordatorios_de_tarea_pendientes_de_aviso(ahora):
        db.marcar_recordatorio_tarea_enviado(r["id"])
        titulo, cuerpo = _texto(r)
        url = f"/tareas/{r['tarea_id']}#recordatorios"
        for canal in r["canales"].split(","):
            try:
                if canal == "app":
                    notificaciones.crear_y_enviar(
                        r["usuario_id"], "tarea_asignada", titulo, cuerpo, url=url,
                        datos={"tipo": "tarea_recordatorio", "tarea_id": r["tarea_id"]},
                    )
                elif canal == "correo" and r["email"] and notificaciones_email.configurado():
                    notificaciones_email._enviar(r["email"], titulo + ": " + r["asunto"], cuerpo + "\n\nGuilda Work")
                elif canal == "ntfy" and r["ntfy_topic"] and r["ntfy_token"]:
                    ntfy.enviar(r["ntfy_topic"], r["ntfy_token"], titulo, cuerpo, prioridad="high")
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo enviar el recordatorio %s por %s", r["id"], canal)
        enviados += 1
    return enviados
