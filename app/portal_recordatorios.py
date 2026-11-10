"""Recordatorios automáticos del portal de cliente: un correo al cliente
cuando un vencimiento pendiente llega a los días de aviso de su despacho (por
defecto 7 y 2 antes; configurable, también después del vencimiento, con texto propio
y aviso interno al equipo si el cliente no entrega lo pedido). Solo a clientes con
email y con los recordatorios activos (opt-out en su ficha), una vez por vencimiento
y antelación (tabla vencimientos_recordatorios; los avisos tras el vencimiento
se guardan con días negativos). Necesita el canal PORTAL_SMTP_*;
el enlace al portal sale de GUILDA_URL_PUBLICA (si no está, el correo va sin enlace)."""
import contextlib
import logging
import os
from datetime import datetime, timedelta

from . import db, notificaciones, notificaciones_email, portal_avisos, portal_personas

logger = logging.getLogger("guilda")

DIAS_ANTES = (7, 2)


def con_destino(url: str | None, destino: str | None, cliente_id: int | None = None) -> str | None:
    """El enlace de entrada al portal con la pantalla a la que debe llevar al cliente cuando entre (p. ej. `/portal/facturas?trimestre=2026-T2`). Sin destino o sin enlace, tal cual.
    `cliente_id`: la ficha a la que pertenece ese destino, para quien entra con un mismo email a varias sociedades."""
    if not url or not destino:
        return url
    from urllib.parse import quote
    c = f"&c={int(cliente_id)}" if cliente_id else ""
    return f"{url}{'&' if '?' in url else '?'}siguiente={quote(destino, safe='')}{c}"


def base_portal() -> str:
    """La dirección con la que los clientes entran al portal: `GUILDA_URL_PORTAL` (por ejemplo https://clientes.guildawork.com) o, si no está, la pública de siempre. Los webhooks (Twilio, Stripe) siguen firmándose sobre `GUILDA_URL_PUBLICA`."""
    return (os.environ.get("GUILDA_URL_PORTAL", "").strip() or os.environ.get("GUILDA_URL_PUBLICA", "").strip()).rstrip("/")


def url_portal(destino: str | None = None, cliente_id: int | None = None) -> str | None:
    base = base_portal()
    return con_destino(f"{base}/portal/entrar" if base else None, destino, cliente_id)


def url_preferencias(cliente_id: int, email: str) -> str | None:
    """El enlace del pie de cada correo para cambiar los avisos sin tener que entrar (firmado, vale un año)."""
    from . import portal_personas
    base = base_portal()
    return f"{base}/portal/preferencias/{portal_personas.token_preferencias(cliente_id, email)}" if base else None


def _(mensaje: str, **valores) -> str:
    """Texto traducible al idioma activo (ver `_en_idioma`); sin aplicación, en español."""
    try:
        from flask_babel import gettext

        return gettext(mensaje, **valores)
    except Exception:  # noqa: BLE001
        return mensaje % valores if valores else mensaje


@contextlib.contextmanager
def _en_idioma(idioma: str | None):
    """Contexto de aplicación + idioma del cliente para traducir el correo. Si
    la app no está disponible (tests sin ella), se manda en español."""
    try:
        from flask_babel import force_locale

        from .main import app
    except Exception:  # noqa: BLE001
        yield
        return
    with app.app_context(), force_locale(idioma if idioma in ("es", "ca", "en", "fr") else "es"):
        yield


def _plantilla(config: dict) -> tuple[str, str] | None:
    return (config["asunto"], config["cuerpo"]) if config["asunto"] and config["cuerpo"] else None


def _avisar_equipo(tenant_id: int, dias: int, hoy: datetime) -> int:
    """Cuando llega el último aviso previo, el equipo recibe una notificación por cada vencimiento en que se pidió
    documentación y el cliente no ha subido nada (con o sin recordatorio al cliente: puede no tener email)."""
    objetivo = (hoy + timedelta(days=dias)).strftime("%Y-%m-%d")
    avisos = 0
    for v in db.vencimientos_sin_documentos_del_cliente(tenant_id, objetivo, dias):
        if not db.marcar_vencimiento_escalado(v["id"], dias):
            continue
        for uid in db.destinatarios_aviso_vencimiento(tenant_id, v["usuario_id"]):
            try:
                with _en_idioma(db.idioma_usuario(uid)):
                    titulo = _("%(cliente)s no ha entregado la documentación", cliente=v["cliente_nombre"])
                    cuerpo = _("El modelo %(modelo)s (%(periodo)s) vence el %(fecha)s y sigue pendiente: %(documento)s.",
                               modelo=v["modelo"], periodo=v["periodo"], fecha=v["fecha_limite"][:10], documento=v["documento_solicitado"])
                notificaciones.crear_y_enviar(uid, "portal_sin_documentos", titulo, cuerpo, url=f"/fiscal/vencimientos/{v['id']}/editar",
                                              datos={"tipo": "portal_sin_documentos"})
                avisos += 1
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo avisar al equipo del vencimiento %s", v["id"])
    return avisos


def procesar_recordatorios(hoy: datetime | None = None) -> int:
    """Devuelve cuántos recordatorios se enviaron a clientes. Cada despacho tiene sus días de aviso
    (por defecto 7 y 2 antes; opcionalmente también después del vencimiento) y, si quiere, su propio texto.
    Sin SMTP configurado no envía ni marca nada (se enviarán cuando lo esté, si aún es a tiempo). El aviso
    interno al equipo no necesita SMTP."""
    hoy = hoy or datetime.now()
    smtp = notificaciones_email.configurado()
    enviados = 0
    for tenant in db.listar_tenants():
        config = db.obtener_config_recordatorios(tenant["id"])
        if config["avisar_equipo"] and config["dias_antes"]:
            _avisar_equipo(tenant["id"], min(config["dias_antes"]), hoy)
        if not smtp:
            continue
        plantilla = _plantilla(config)
        for dias in [*config["dias_antes"], *(-d for d in config["dias_despues"])]:
            objetivo = (hoy + timedelta(days=dias)).strftime("%Y-%m-%d")
            for v in db.vencimientos_para_recordatorio_portal(objetivo, dias, tenant["id"]):
                try:
                    cliente = db.obtener_cliente_fiscal_por_id(v["cliente_fiscal_id"])
                    # A quién: cada persona recibe esto según lo que eligió (el aviso de última hora, a 2 días o menos, llega también a quien solo quiere lo urgente).
                    destinatarios = portal_personas.destinatarios(cliente, urgente=dias <= 2, accion="subir") if cliente is not None else [v["cliente_email"].strip()]
                    with _en_idioma(v["cliente_idioma"]):
                        n = portal_avisos.correo_a(cliente, destinatarios, lambda e: notificaciones_email.enviar_recordatorio_vencimiento(
                            e, v["cliente_nombre"], v["modelo"], v["periodo"], v["fecha_limite"],
                            dias, url_portal(f"/portal/vencimientos/{v['id']}/documentos", v["cliente_fiscal_id"]), v["tenant_nombre"], v["documento_solicitado"], plantilla=plantilla, tenant_id=tenant["id"],
                        )) if destinatarios else 0
                    if destinatarios and n == 0:
                        continue                                         # todos los envíos fallaron: se reintenta en la próxima vuelta
                except Exception:  # noqa: BLE001 -- un cliente con el buzón roto no debe frenar al resto
                    logger.exception("No se pudo enviar el recordatorio del vencimiento %s", v["id"])
                    continue
                db.marcar_recordatorio_portal_enviado(v["id"], dias)       # sin destinatarios (todos en «resumen») también se marca: el resumen semanal ya lo recoge
                enviados += n
    return enviados
