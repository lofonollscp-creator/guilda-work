"""«No molestar» de los avisos del móvil: una franja horaria en la que una persona no quiere notificaciones (por defecto, ninguna).

Solo afecta a las notificaciones al móvil o al navegador: el correo no suena y el aviso queda siempre anotado en el centro de avisos del portal, así que nada se pierde, solo se ve más tarde. La franja puede cruzar la
medianoche (de 22:00 a 08:00). Es por persona y por ficha de cliente."""
from __future__ import annotations

import re
from datetime import datetime

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_silencios (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    desde TEXT NOT NULL,
    hasta TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (tenant_id, cliente_fiscal_id, email)
);
"""
_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _email(e: str | None) -> str:
    return (e or "").strip().lower()


def obtener(cliente, email: str | None) -> dict | None:
    """{desde, hasta} de esta persona, o None si no tiene franja."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT desde, hasta FROM portal_silencios WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], _email(email))).fetchone()
    finally:
        conn.close()
    return {"desde": f["desde"], "hasta": f["hasta"]} if f else None


def guardar(cliente, email: str | None, desde: str, hasta: str) -> None:
    """Fija la franja (HH:MM a HH:MM). Con las dos vacías, la quita. `ValueError` con un mensaje legible si no es una franja válida."""
    desde, hasta = (desde or "").strip(), (hasta or "").strip()
    conn = db.get_connection()
    try:
        if not desde and not hasta:
            conn.execute("DELETE FROM portal_silencios WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], _email(email)))
        else:
            if not (_HORA.match(desde) and _HORA.match(hasta)):
                raise ValueError("Escribe las dos horas, por ejemplo de 22:00 a 08:00.")
            if desde == hasta:
                raise ValueError("La hora de inicio y la de fin no pueden ser la misma.")
            ahora = datetime.now().isoformat(timespec="seconds")
            n = conn.execute("UPDATE portal_silencios SET desde = ?, hasta = ?, actualizado_en = ? WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (desde, hasta, ahora, cliente["tenant_id"], cliente["id"], _email(email))).rowcount
            if not n:
                conn.execute("INSERT INTO portal_silencios (tenant_id, cliente_fiscal_id, email, desde, hasta, actualizado_en) VALUES (?, ?, ?, ?, ?, ?)", (cliente["tenant_id"], cliente["id"], _email(email), desde, hasta, ahora))
        conn.commit()
    finally:
        conn.close()


def dentro(franja: dict | None, ahora: datetime | None = None) -> bool:
    """¿Cae `ahora` dentro de la franja? (admite que cruce la medianoche)"""
    if not franja:
        return False
    h = (ahora or datetime.now()).strftime("%H:%M")
    d, a = franja["desde"], franja["hasta"]
    return d <= h < a if d < a else (h >= d or h < a)


def en_silencio(cliente, email: str | None, ahora: datetime | None = None) -> bool:
    return dentro(obtener(cliente, email), ahora)
