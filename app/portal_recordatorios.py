"""Recordatorios automáticos del portal de cliente: un correo al cliente
cuando un vencimiento pendiente está a 7 y a 2 días. Solo a clientes con email
y con los recordatorios activos (opt-out en su ficha), una vez por vencimiento
y antelación (tabla vencimientos_recordatorios). Necesita el canal PORTAL_SMTP_*;
el enlace al portal sale de GUILDA_URL_PUBLICA (si no está, el correo va sin enlace)."""
import logging
import os
from datetime import datetime, timedelta

from . import db, notificaciones_email

logger = logging.getLogger("guilda")

DIAS_ANTES = (7, 2)


def url_portal() -> str | None:
    base = os.environ.get("GUILDA_URL_PUBLICA", "").strip().rstrip("/")
    return f"{base}/portal/entrar" if base else None


def procesar_recordatorios(hoy: datetime | None = None) -> int:
    """Devuelve cuántos recordatorios se enviaron. Sin SMTP configurado no
    hace nada (y no marca nada: se enviarán cuando lo esté, si aún es a tiempo)."""
    if not notificaciones_email.configurado():
        return 0
    hoy = hoy or datetime.now()
    enviados = 0
    for dias in DIAS_ANTES:
        objetivo = (hoy + timedelta(days=dias)).strftime("%Y-%m-%d")
        for v in db.vencimientos_para_recordatorio_portal(objetivo, dias):
            try:
                notificaciones_email.enviar_recordatorio_vencimiento(
                    v["cliente_email"].strip(), v["cliente_nombre"], v["modelo"], v["periodo"], v["fecha_limite"],
                    dias, url_portal(), v["tenant_nombre"], v["documento_solicitado"],
                )
            except Exception:  # noqa: BLE001 -- un cliente con el buzón roto no debe frenar al resto
                logger.exception("No se pudo enviar el recordatorio del vencimiento %s", v["id"])
                continue
            db.marcar_recordatorio_portal_enviado(v["id"], dias)
            enviados += 1
    return enviados
