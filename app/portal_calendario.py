"""Calendario de plazos del cliente para su móvil o su agenda: un enlace secreto (`webcal://…`) con sus vencimientos fiscales sin presentar y las peticiones de documentos con fecha límite, que Google
Calendar, Apple Calendar u Outlook se descargan y mantienen al día solos. No hay sesión (las agendas no la tienen): el enlace va firmado con un secreto del cliente y solo enseña modelos, periodos y fechas.
El secreto sale del mismo que el del enlace de subida desde el móvil, así que «Renovar enlace» en Mi cuenta invalida los dos."""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date, datetime, timedelta

from . import db, portal_peticiones, portal_subida_rapida

HORIZONTE_DIAS = 400
LARGO_TOKEN = 32
_TOKEN = re.compile(r"^[0-9a-f]{32}$")
PRODID = "-//Guilda Work//Plazos del cliente//ES"


def _derivar(cliente_id: int, secreto: str) -> str:
    return hmac.new(secreto.encode(), f"calendario:{cliente_id}".encode(), hashlib.sha256).hexdigest()[:LARGO_TOKEN]


def token_de(cliente) -> str:
    """El secreto del calendario de ese cliente (se crea el del enlace de subida si aún no existía)."""
    return _derivar(cliente["id"], portal_subida_rapida.token_de(cliente))


def cliente_por_token(token: str, cliente_id: int):
    """El cliente si el token es el suyo (se compara en tiempo constante); None si no. El id va en el enlace para no tener que buscar entre todos."""
    if not _TOKEN.match(token or ""):
        return None
    cliente = db.obtener_cliente_fiscal_por_id(cliente_id)
    if cliente is None:
        return None
    return cliente if hmac.compare_digest(token_de(cliente), token) else None


def _escapar(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _plegar(linea: str) -> list[str]:
    """Líneas de máximo 75 octetos (RFC 5545 §3.1), sin partir un carácter multibyte; las siguientes empiezan por un espacio."""
    datos, partes, actual = linea.encode(), [], b""
    for carácter in linea:
        b = carácter.encode()
        if len(actual) + len(b) > (75 if not partes else 74):
            partes.append(actual.decode())
            actual = b
        else:
            actual += b
    partes.append(actual.decode())
    return [partes[0]] + [" " + p for p in partes[1:]]


def _evento(uid: str, dia: date, resumen: str, descripcion: str, marca: str) -> list[str]:
    return ["BEGIN:VEVENT", f"UID:{uid}@guildawork", f"DTSTAMP:{marca}", f"DTSTART;VALUE=DATE:{dia.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(dia + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_escapar(resumen)}", f"DESCRIPTION:{_escapar(descripcion)}", "TRANSP:TRANSPARENT",
            "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escapar(resumen)}", "TRIGGER:-P2D", "END:VALARM", "END:VEVENT"]


def contenido(cliente, ahora: datetime | None = None) -> str:
    """El texto del calendario (.ics) de ese cliente."""
    ahora = ahora or datetime.utcnow()
    hoy, marca = ahora.date(), ahora.strftime("%Y%m%dT%H%M%SZ")
    limite = hoy + timedelta(days=HORIZONTE_DIAS)
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_escapar('Plazos · ' + cliente['nombre'])}", "X-WR-TIMEZONE:Europe/Madrid",
              "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H"]
    for v in db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"], sin_internos=True):
        if v["estado"] == "presentado":
            continue
        try:
            dia = datetime.strptime((v["fecha_limite"] or "")[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if dia > limite:
            continue
        lineas += _evento(f"venc-{v['id']}", dia, f"Modelo {v['modelo']} · {v['periodo']}", f"Fecha límite de presentación del modelo {v['modelo']} ({v['periodo']}).", marca)
    for p in portal_peticiones.pendientes_del_cliente(cliente["id"]):
        if p["fecha_limite"]:
            lineas += _evento(f"peticion-{p['id']}", date.fromisoformat(p["fecha_limite"]), f"Subir: {p['titulo']}", f"Tu gestoría necesita este documento: {p['titulo']}.", marca)
    lineas.append("END:VCALENDAR")
    return "\r\n".join(parte for linea in lineas for parte in _plegar(linea)) + "\r\n"
