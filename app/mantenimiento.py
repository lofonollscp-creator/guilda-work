"""Modo mantenimiento: el backoffice cierra la plataforma entera o un despacho con un mensaje; los usuarios
ven una página 503 (y la API un JSON 503) y los administradores globales siguen entrando."""
from __future__ import annotations

import time
from datetime import datetime

from . import db

_TTL = 10.0
_cache: dict[str, tuple[float, list]] = {}


def _ahora() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _invalidar() -> None:
    _cache.clear()


def _vigentes() -> list[dict]:
    clave = str(db.DB_PATH)
    guardado = _cache.get(clave)
    if guardado and time.monotonic() - guardado[0] < _TTL:
        return guardado[1]
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT id, tenant_id, mensaje, hasta FROM mantenimiento WHERE activo = 1 AND (hasta IS NULL OR hasta >= ?)", (_ahora(),)
        ).fetchall()]
    finally:
        conn.close()
    _cache[clave] = (time.monotonic(), filas)
    return filas


def vigente_para(tenant_id: int | None) -> dict | None:
    """El cierre que afecta a este despacho (el global tiene prioridad) o None."""
    filas = _vigentes()
    if not filas:
        return None
    for f in filas:
        if f["tenant_id"] is None:
            return f
    for f in filas:
        if tenant_id is not None and f["tenant_id"] == tenant_id:
            return f
    return None


def activar(tenant_id: int | None, mensaje: str = "", hasta: str | None = None, por: str | None = None) -> int:
    hasta = (hasta or "").strip() or None
    if hasta:
        try:
            hasta = datetime.fromisoformat(hasta).isoformat(timespec="minutes")
        except ValueError:
            raise ValueError("La fecha de fin no es válida.")
        if hasta < _ahora():
            raise ValueError("La fecha de fin ya ha pasado.")
    conn = db.get_connection()
    try:
        if tenant_id is not None and not conn.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,)).fetchone():
            raise ValueError("El despacho no existe.")
        if conn.execute("SELECT 1 FROM mantenimiento WHERE activo = 1 AND tenant_id IS NOT DISTINCT FROM ?", (tenant_id,)).fetchone():
            raise ValueError("Ya hay un mantenimiento activo para ese ámbito.")
        cur = conn.execute(
            "INSERT INTO mantenimiento (tenant_id, mensaje, hasta, activo, creado_en, creado_por) VALUES (?, ?, ?, 1, ?, ?)",
            (tenant_id, (mensaje or "").strip()[:400], hasta, _ahora(), por),
        )
        conn.commit()
        _invalidar()
        return cur.lastrowid
    finally:
        conn.close()


def finalizar(mantenimiento_id: int) -> bool:
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE mantenimiento SET activo = 0 WHERE id = ? AND activo = 1", (mantenimiento_id,))
        conn.commit()
        _invalidar()
        return cur.rowcount > 0
    finally:
        conn.close()


def listar(limite: int = 30) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT m.*, t.nombre AS tenant_nombre FROM mantenimiento m LEFT JOIN tenants t ON t.id = m.tenant_id
               ORDER BY m.activo DESC, m.id DESC LIMIT ?""", (limite,),
        ).fetchall()
    finally:
        conn.close()
    ahora = _ahora()
    return [{**dict(f), "vigente": bool(f["activo"]) and (not f["hasta"] or f["hasta"] >= ahora)} for f in filas]
