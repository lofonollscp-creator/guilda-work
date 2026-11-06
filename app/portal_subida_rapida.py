"""Subir facturas y tiquets sin entrar al portal: desde el móvil con un enlace (o su código QR) y, si el despacho lo ha preparado, reenviando el correo con la factura a una dirección propia de cada cliente.

Las dos puertas llevan un secreto largo por cliente (`portal_enlaces_subida`) que el propio cliente puede renovar en «Mi cuenta» y que solo sirve para **subir**: no deja leer nada. Lo subido entra igual que lo que se sube desde
el portal (antivirus, duplicados, límite de pendientes) y avisa al equipo. Por correo: `facturas+<secreto>@despacho.com`; el despacho indica la dirección base en los recordatorios del portal y el correo que llegue a ese buzón se procesa al sincronizarlo."""
from __future__ import annotations

import logging
import re
import secrets
from email.message import Message
from email.utils import getaddresses

from . import db, facturas_contables as fc, verticales

logger = logging.getLogger("guilda")

LARGO_TOKEN = 32                                   # hexadecimal: 128 bits; en minúsculas porque algunos buzones no respetan las mayúsculas de lo que va tras el «+»
_TOKEN = re.compile(r"^[0-9a-f]{32}$")
_EN_DIRECCION = re.compile(r"\+([0-9a-f]{32})@")
TIPOS_ADMITIDOS = ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf")
_EMAIL = re.compile(r"^[^@\s+]+@[^@\s]+\.[^@\s]+$")
CABECERAS_DESTINO = ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To", "X-Envelope-To")


def activa_para(cliente) -> bool:
    return cliente is not None and verticales.esta_activo(cliente["tenant_id"], "contabilizacion")


def token_de(cliente) -> str:
    """El secreto del cliente; se crea la primera vez que se pide."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT token FROM portal_enlaces_subida WHERE tenant_id = ? AND cliente_fiscal_id = ?", (cliente["tenant_id"], cliente["id"])).fetchone()
    finally:
        conn.close()
    return f["token"] if f and _TOKEN.match(f["token"]) else renovar(cliente)


def renovar(cliente) -> str:
    """Un secreto nuevo: el enlace y la dirección de correo anteriores dejan de valer al instante."""
    nuevo = secrets.token_hex(LARGO_TOKEN // 2)
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_enlaces_subida SET token = ?, creado_en = ? WHERE tenant_id = ? AND cliente_fiscal_id = ?", (nuevo, db.now_iso(), cliente["tenant_id"], cliente["id"])).rowcount
        if not n:
            conn.execute("INSERT INTO portal_enlaces_subida (tenant_id, cliente_fiscal_id, token, creado_en) VALUES (?, ?, ?, ?)", (cliente["tenant_id"], cliente["id"], nuevo, db.now_iso()))
        conn.commit()
    finally:
        conn.close()
    return nuevo


def cliente_por_token(token: str):
    if not _TOKEN.match(token or ""):
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT cliente_fiscal_id FROM portal_enlaces_subida WHERE token = ?", (token,)).fetchone()
    finally:
        conn.close()
    return db.obtener_cliente_fiscal_por_id(f["cliente_fiscal_id"]) if f else None


def url(cliente, base: str) -> str:
    return f"{base.rstrip('/')}/portal/subida/{token_de(cliente)}"


# --- Por correo ---------------------------------------------------------------------------------------------------------------------------------------------

def direccion_base(tenant_id: int) -> str:
    """La dirección del despacho que recibe las facturas (por ejemplo facturas@despacho.com), o «» si no la ha indicado."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT correo_facturas FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return (f["correo_facturas"] or "").strip().lower() if f and f["correo_facturas"] else ""


def guardar_direccion_base(tenant_id: int, direccion: str) -> str:
    """Valida y guarda la dirección base. Vacía = desactivar. `ValueError` con un mensaje legible si no vale."""
    d = (direccion or "").strip().lower()
    if d and not _EMAIL.match(d):
        raise ValueError("Escribe una dirección de correo válida, sin «+» (por ejemplo facturas@tudespacho.com).")
    conn = db.get_connection()
    try:
        existe = conn.execute("SELECT 1 FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
        if existe:
            conn.execute("UPDATE portal_recordatorios_config SET correo_facturas = ? WHERE tenant_id = ?", (d or None, tenant_id))
        else:
            cfg = db.CONFIG_RECORDATORIOS_DEFECTO
            conn.execute("INSERT INTO portal_recordatorios_config (tenant_id, dias_antes, dias_despues, avisar_equipo, asunto, cuerpo, actualizado_en, correo_facturas) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, ",".join(str(x) for x in cfg["dias_antes"]), "", int(cfg["avisar_equipo"]), "", "", db.now_iso(), d or None))
        conn.commit()
    finally:
        conn.close()
    return d


def direccion_de(cliente) -> str | None:
    """`facturas+secreto@despacho.com` para este cliente, o None si el despacho no tiene dirección base."""
    base = direccion_base(cliente["tenant_id"])
    if not base or not activa_para(cliente):
        return None
    local, dominio = base.split("@", 1)
    return f"{local}+{token_de(cliente)}@{dominio}"


def token_en(mensaje: Message) -> str | None:
    """El secreto que viaja en alguna de las direcciones de destino del correo (la parte tras el «+»)."""
    for cabecera in CABECERAS_DESTINO:
        for _nombre, direccion in getaddresses(mensaje.get_all(cabecera, [])):
            m = _EN_DIRECCION.search((direccion or "").lower())
            if m:
                return m.group(1)
    return None


def adjuntos_validos(mensaje: Message) -> list[tuple[str, str, bytes]]:
    """Las fotos y PDF del correo (venga como adjunto o incrustado, que es como lo mandan muchos móviles), con tamaño dentro del límite."""
    salida = []
    for i, parte in enumerate(mensaje.walk(), 1):
        tipo = parte.get_content_type()
        if parte.is_multipart() or tipo not in TIPOS_ADMITIDOS:
            continue
        try:
            contenido = parte.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            continue
        if not contenido or len(contenido) > fc.MAX_ADJUNTO_BYTES:
            continue
        nombre = parte.get_filename() or f"adjunto-{i}.{'pdf' if tipo == 'application/pdf' else tipo.split('/')[1].replace('jpeg', 'jpg')}"
        salida.append((nombre[:120], tipo, contenido))
    return salida


def procesar_correo(tenant_id: int, mensaje_id: int, mensaje: Message) -> int:
    """Si el correo recién llegado va a la dirección de un cliente, sube sus fotos y PDF como facturas por leer y lo enlaza con su ficha. Devuelve cuántos archivos entraron (0 si no era para esto).
    Nunca lanza: lo llama la sincronización del correo, que no debe romperse por esto."""
    try:
        token = token_en(mensaje)
        if token is None:
            return 0
        cliente = cliente_por_token(token)
        if cliente is None or cliente["tenant_id"] != tenant_id or not direccion_base(tenant_id) or not activa_para(cliente):
            return 0
        archivos = adjuntos_validos(mensaje)
        db.asignar_cliente_fiscal_correo(tenant_id, mensaje_id, cliente["id"])
        if not archivos:
            return 0
        try:
            ids = fc.subir_desde_portal(cliente["id"], "recibida", archivos, nota="Recibida por correo en la dirección de facturas del cliente, pendiente de leer.")
        except ValueError as e:                                      # demasiadas pendientes, ya enviadas…: el correo queda en la bandeja para que el equipo lo vea
            logger.info("Correo de facturas del cliente %s no procesado: %s", cliente["id"], e)
            return 0
        except Exception:  # noqa: BLE001 -- antivirus caído, etc.
            logger.exception("No se pudieron subir las facturas recibidas por correo del cliente %s", cliente["id"])
            return 0
        from . import auditoria, correo
        auditoria.registrar(tenant_id, None, "portal.subida_correo", "cliente_fiscal", cliente["id"], {"archivos": len(ids)})
        try:
            correo.marcar_leido(mensaje_id, True)
        except Exception:  # noqa: BLE001
            pass
        return len(ids)
    except Exception:  # noqa: BLE001
        logger.exception("Fallo al procesar un correo de facturas")
        return 0
