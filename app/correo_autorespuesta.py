"""Respuesta automática («fuera de la oficina») por cuenta de correo.

Mientras está activa y dentro de sus fechas, cada correo NUEVO y SIN LEER que llega a la bandeja de entrada recibe una respuesta, **una sola vez por remitente** y periodo. Para no provocar
bucles ni molestar, no se contesta a: mensajes automáticos (`Auto-Submitted`, `Precedence: bulk/list/junk`, `X-Auto-Response-Suppress`), listas de correo (`List-Id`, `List-Unsubscribe`),
direcciones de sistema (`noreply`, `mailer-daemon`, `postmaster`…), la propia cuenta o mensajes con más de dos días (una sincronización tardía no contesta a correo viejo).
Cambiar la configuración reinicia la lista de remitentes ya contestados."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from . import db

logger = logging.getLogger(__name__)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS correo_autorespuesta (
    cuenta_id INTEGER PRIMARY KEY REFERENCES correo_cuentas(id) ON DELETE CASCADE,
    activa INTEGER NOT NULL DEFAULT 0,
    desde TEXT,
    hasta TEXT,
    asunto TEXT NOT NULL DEFAULT '',
    cuerpo TEXT NOT NULL DEFAULT '',
    actualizada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS correo_autorespuesta_enviadas (
    cuenta_id INTEGER NOT NULL REFERENCES correo_cuentas(id) ON DELETE CASCADE,
    direccion TEXT NOT NULL,
    enviada_en TEXT NOT NULL,
    PRIMARY KEY (cuenta_id, direccion)
);
"""
_REMITENTES_DE_SISTEMA = re.compile(r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster|bounce[s]?|notifications?|alerts?)([+._-].*)?@", re.IGNORECASE)


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def es_automatico(cabeceras) -> bool:
    """True si, por sus cabeceras, el mensaje es automático, de lista o masivo (no se le contesta). `cabeceras` es un objeto con `.get(nombre)`."""
    auto = (cabeceras.get("Auto-Submitted") or "no").strip().lower()
    if auto and auto != "no":
        return True
    if (cabeceras.get("Precedence") or "").strip().lower() in ("bulk", "list", "junk", "auto_reply"):
        return True
    if cabeceras.get("List-Id") or cabeceras.get("List-Unsubscribe") or cabeceras.get("X-Auto-Response-Suppress"):
        return True
    return (cabeceras.get("Return-Path") or "").strip() == "<>"


def direccion_de_sistema(direccion: str) -> bool:
    return bool(_REMITENTES_DE_SISTEMA.match(direccion or ""))


def obtener(cuenta_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM correo_autorespuesta WHERE cuenta_id = ?", (cuenta_id,)).fetchone()
    finally:
        conn.close()
    return dict(f) if f else {"cuenta_id": cuenta_id, "activa": 0, "desde": None, "hasta": None, "asunto": "", "cuerpo": ""}


def _fecha(valor, etiqueta: str) -> str | None:
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError:
        raise ValueError(f"{etiqueta}: fecha no válida.") from None


def guardar(usuario_id: int, cuenta_id: int, *, activa: bool, desde, hasta, asunto: str, cuerpo: str) -> None:
    """Guarda la respuesta automática de una cuenta del usuario. Activa exige asunto y texto; `desde` y `hasta` (opcionales) acotan cuándo."""
    if db.obtener_cuenta_correo(usuario_id, cuenta_id) is None:
        raise ValueError("Esa cuenta no existe.")
    asunto, cuerpo = (asunto or "").strip()[:200], (cuerpo or "").strip()[:5000]
    d, h = _fecha(desde, "Desde"), _fecha(hasta, "Hasta")
    if d and h and h < d:
        raise ValueError("La fecha final no puede ser anterior a la inicial.")
    if activa and (not asunto or not cuerpo):
        raise ValueError("Para activar la respuesta automática escribe el asunto y el mensaje.")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO correo_autorespuesta (cuenta_id, activa, desde, hasta, asunto, cuerpo, actualizada_en) VALUES (?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(cuenta_id) DO UPDATE SET activa = excluded.activa, desde = excluded.desde, hasta = excluded.hasta, asunto = excluded.asunto, cuerpo = excluded.cuerpo, actualizada_en = excluded.actualizada_en",
                     (cuenta_id, int(bool(activa)), d, h, asunto, cuerpo, db.now_iso()))
        conn.execute("DELETE FROM correo_autorespuesta_enviadas WHERE cuenta_id = ?", (cuenta_id,))
        conn.commit()
    finally:
        conn.close()


def vigente(cuenta_id: int, hoy: date | None = None) -> dict | None:
    c = obtener(cuenta_id)
    hoy = (hoy or date.today()).isoformat()
    if not c["activa"] or (c["desde"] and hoy < c["desde"]) or (c["hasta"] and hoy > c["hasta"]):
        return None
    return c


def responder_si_procede(cuenta, mensaje, hoy: date | None = None, ahora: datetime | None = None) -> bool:
    """Contesta a `mensaje` (un `email.message.Message` recién llegado a la bandeja de entrada de `cuenta`) si procede. Devuelve si ha enviado algo."""
    from . import correo
    config = vigente(cuenta["id"], hoy)
    if config is None or es_automatico(mensaje):
        return False
    direccion = (correo.direccion_email(correo._decodificar(mensaje.get("Reply-To")) or correo._decodificar(mensaje.get("From"))) or "").lower()
    propias = correo._direcciones_propias(cuenta)
    if not direccion or direccion in propias or direccion_de_sistema(direccion):
        return False
    try:
        enviado = correo.parsedate_to_datetime(mensaje.get("Date")) if mensaje.get("Date") else None
    except (TypeError, ValueError):
        enviado = None
    ahora = ahora or datetime.now()
    if enviado is not None and (ahora.astimezone() - enviado.astimezone()) > timedelta(days=2):
        return False                      # correo antiguo que llega en una sincronización tardía
    conn = db.get_connection()
    try:
        try:
            conn.execute("INSERT INTO correo_autorespuesta_enviadas (cuenta_id, direccion, enviada_en) VALUES (?, ?, ?)", (cuenta["id"], direccion, db.now_iso()))
            conn.commit()
        except Exception:                 # ya se le contestó en este periodo
            return False
    finally:
        conn.close()
    asunto_original = correo._decodificar(mensaje.get("Subject")) or ""
    try:
        correo.construir_y_enviar(cuenta["usuario_id"], cuenta["id"], direccion, config["asunto"] or f"Re: {asunto_original}", correo.texto_a_html(config["cuerpo"]),
                                  en_respuesta_a=mensaje.get("Message-ID"), cabeceras_extra={"Auto-Submitted": "auto-replied", "X-Auto-Response-Suppress": "All"})
    except Exception:  # noqa: BLE001 -- una respuesta automática fallida no debe romper la sincronización
        logger.exception("No se pudo enviar la respuesta automática de la cuenta %s", cuenta["id"])
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM correo_autorespuesta_enviadas WHERE cuenta_id = ? AND direccion = ?", (cuenta["id"], direccion))
            conn.commit()
        finally:
            conn.close()
        return False
    return True
