"""Alta de un buzón de correo del despacho en un solo paso: crea la cuenta `nombre@dominio-del-despacho` en el servidor de correo propio (Stalwart), le genera una contraseña de
aplicación y la conecta a Guilda Work para la persona elegida. Nadie teclea ni ve una contraseña: se guarda cifrada en el llavero del servidor, como el resto de cuentas.

Solo la dirección del despacho (supervisores) y solo si el despacho tiene su dominio de correo aprovisionado (app/stalwart.py:aprovisionar_tenant). Si conectar la cuenta falla
(por ejemplo, el servidor IMAP no responde), el buzón recién creado se borra: no quedan buzones a medias."""
from __future__ import annotations

import logging
import os
import re

from flask_babel import gettext as _

from . import acceso, correo, db, stalwart

logger = logging.getLogger(__name__)

HOST = os.environ.get("GUILDA_CORREO_PROPIO_HOST", "mail.guildawork.com")
PUERTO_IMAP = int(os.environ.get("GUILDA_CORREO_PROPIO_IMAP", "993"))
PUERTO_SMTP = int(os.environ.get("GUILDA_CORREO_PROPIO_SMTP", "465"))
_LOCAL = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")


class ErrorBuzon(Exception):
    """Mensaje legible para mostrar."""


def dominio_del_despacho(usuario_id: int) -> dict | None:
    """Los datos de Stalwart del despacho de la persona, o None si no tiene dominio de correo aprovisionado."""
    t = db.tenant_de_usuario(usuario_id)
    if t is None or not t["stalwart_tenant_id"] or not t["stalwart_domain_id"] or not t["stalwart_domain_name"]:
        return None
    return {"tenant_id": t["id"], "stalwart_tenant_id": t["stalwart_tenant_id"], "domain_id": t["stalwart_domain_id"], "dominio": t["stalwart_domain_name"]}


def personas_del_despacho(usuario_id: int) -> list[dict]:
    """A quién se puede conectar un buzón: uno mismo y sus compañeros."""
    yo = db.obtener_usuario(usuario_id)
    return [{"id": usuario_id, "nombre": _("%(n)s (tú)", n=db.nombre_mostrado_usuario(usuario_id) or yo["email"])}] + [{"id": p["id"], "nombre": p["nombre"]} for p in db.listar_companeros_tenant(usuario_id)]


def alta_buzon(admin_id: int, local: str, persona_id: int | None = None) -> dict:
    """Crea el buzón y lo conecta a la persona (por defecto, quien lo pide). Devuelve {"email", "cuenta_id", "persona_id"}. `ErrorBuzon` con un mensaje legible si no se puede."""
    datos = dominio_del_despacho(admin_id)
    if datos is None:
        raise ErrorBuzon("Tu despacho no tiene un dominio de correo propio configurado.")
    if not acceso.es_directivo(admin_id):
        raise ErrorBuzon("Solo la dirección del despacho puede crear buzones.")
    local = (local or "").strip().lower()
    if not _LOCAL.match(local):
        raise ErrorBuzon("El nombre del buzón solo puede llevar letras, números, punto, guion y guion bajo.")
    persona_id = persona_id or admin_id
    if persona_id != admin_id and persona_id not in {p["id"] for p in personas_del_despacho(admin_id)}:
        raise ErrorBuzon("Esa persona no es de tu despacho.")
    email = f"{local}@{datos['dominio']}"
    try:
        buzon = stalwart.crear_buzon(datos["stalwart_tenant_id"], datos["domain_id"], local, f"Guilda Work — {email}")
    except stalwart.ErrorStalwart as e:
        raise ErrorBuzon(str(e)) from e
    try:
        cuenta_id = correo.guardar_cuenta(persona_id, email, "imap", HOST, PUERTO_IMAP, email, buzon["secreto"], usa_tls=True, smtp_host=HOST, smtp_puerto=PUERTO_SMTP, smtp_tls=True)
    except correo.ErrorCorreo as e:
        stalwart.eliminar_buzon(buzon["account_id"])
        logger.warning("Buzón %s creado pero no se pudo conectar; borrado: %s", email, e)
        raise ErrorBuzon(f"El buzón se creó pero no se pudo conectar ({e}); se ha deshecho.") from e
    return {"email": email, "cuenta_id": cuenta_id, "persona_id": persona_id}
