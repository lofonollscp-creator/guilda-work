"""Enlaces secretos de solo lectura para clientes y propietarios (los usan los módulos Gabinete de abogados e Inmobiliaria). Un enlace da acceso a UN expediente
sin crear cuenta: el token son 32 bytes aleatorios que se enseñan una sola vez y de los que en la base solo queda la huella SHA-256; caduca, se puede revocar,
y deja de valer si el despacho pierde el módulo o el expediente va a la papelera. Cada módulo tiene su tabla (mismas columnas) y decide qué enseña."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from . import db, nucleo, verticales

TABLAS = {"abogados": "abogados_enlaces", "inmobiliaria": "inmobiliaria_enlaces"}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS {tabla} (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expira_en TEXT NOT NULL,
    revocado_en TEXT,
    permite_mensajes INTEGER NOT NULL DEFAULT 0,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL
);
"""


def esquema(conn, vertical_id: str) -> None:
    conn.executescript(ESQUEMA.format(tabla=TABLAS[vertical_id]))
    db._asegurar_columna(conn, TABLAS[vertical_id], "permite_mensajes", "INTEGER NOT NULL DEFAULT 0")      # bases creadas antes de existir los mensajes seguros
    from . import mensajes_enlace
    conn.executescript(mensajes_enlace.ESQUEMA)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def crear(vertical_id: str, tenant_id: int, usuario_id: int, expediente_id: int, dias: int = 30, permite_mensajes: bool = False) -> str:
    """Devuelve el token en claro (solo se muestra ahora). El permiso sobre el expediente lo comprueba quien llama."""
    tabla = TABLAS[vertical_id]
    dias = max(1, min(int(dias), 180))
    token = secrets.token_urlsafe(32)
    conn = db.get_connection()
    try:
        conn.execute(f"INSERT INTO {tabla} (tenant_id, expediente_id, token_hash, expira_en, creado_por, creado_en, permite_mensajes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (tenant_id, expediente_id, _hash(token), (datetime.now() + timedelta(days=dias)).isoformat(timespec="seconds"), usuario_id, db.now_iso(), int(bool(permite_mensajes))))
        nucleo._evento(conn, expediente_id, "enlace", f"Enlace {'con mensajes' if permite_mensajes else 'de solo lectura'} creado (caduca en {dias} días).", usuario_id)
        conn.commit()
    finally:
        conn.close()
    return token


def listar(vertical_id: str, tenant_id: int, expediente_id: int) -> list:
    conn = db.get_connection()
    try:
        return conn.execute(f"SELECT id, expira_en, revocado_en, creado_en, permite_mensajes FROM {TABLAS[vertical_id]} WHERE tenant_id = ? AND expediente_id = ? ORDER BY id DESC", (tenant_id, expediente_id)).fetchall()
    finally:
        conn.close()


def revocar(vertical_id: str, tenant_id: int, expediente_id: int, enlace_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute(f"UPDATE {TABLAS[vertical_id]} SET revocado_en = ? WHERE id = ? AND tenant_id = ? AND expediente_id = ? AND revocado_en IS NULL", (db.now_iso(), enlace_id, tenant_id, expediente_id))
        conn.commit()
    finally:
        conn.close()


def resolver(vertical_id: str, token: str) -> dict | None:
    """El enlace y su expediente si el token es válido (existe, ni revocado ni caducado, módulo activo y expediente fuera de la papelera), o None."""
    if not token or len(token) > 100:
        return None
    conn = db.get_connection()
    try:
        e = conn.execute(f"SELECT * FROM {TABLAS[vertical_id]} WHERE token_hash = ?", (_hash(token),)).fetchone()
        if e is None or e["revocado_en"] or e["expira_en"] < db.now_iso() or not verticales.esta_activo(e["tenant_id"], vertical_id):
            return None
        x = conn.execute("SELECT x.*, c.nombre AS cliente_nombre FROM expedientes x JOIN clientes c ON c.id = x.cliente_id WHERE x.id = ? AND x.papelera_en IS NULL", (e["expediente_id"],)).fetchone()
        return {"enlace": dict(e), "expediente": dict(x)} if x else None
    finally:
        conn.close()


def borrar_datos_de_tenant(conn, vertical_id: str, tenant_id: int) -> None:
    conn.execute("DELETE FROM mensajes_enlace WHERE tenant_id = ? AND vertical_id = ?", (tenant_id, vertical_id))
    conn.execute(f"DELETE FROM {TABLAS[vertical_id]} WHERE tenant_id = ?", (tenant_id,))
