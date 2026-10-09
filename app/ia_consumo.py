"""Consumo de IA por despacho y mes, con tope opcional. Cada consulta al modelo (turno del chat o acción de IA del
correo) cuenta 1. `tenants.ia_limite_mensual`: NULL = ilimitado, 0 = IA desactivada, N = tope mensual. El consumo se
registra siempre, también sin tope, para que el backoffice vea quién gasta. Usuarios sin despacho: sin tope."""
from __future__ import annotations

from datetime import datetime

from . import db


class LimiteIA(Exception):
    """El despacho ha agotado su tope mensual (el mensaje se muestra al usuario)."""


def _mes(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now()).strftime("%Y-%m")


def reservar(usuario_id: int, ahora: datetime | None = None) -> None:
    """Cuenta una consulta o lanza LimiteIA. Atómico: dos consultas simultáneas no pueden pasarse del tope."""
    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute(
            "SELECT t.id, t.ia_limite_mensual FROM usuarios u JOIN tenants t ON t.id = u.tenant_id WHERE u.id = ?", (usuario_id,)
        ).fetchone()
        if fila is None:
            conn.rollback()
            return
        tenant_id, limite, mes = fila["id"], fila["ia_limite_mensual"], _mes(ahora)
        usadas = (conn.execute("SELECT usadas FROM ia_consumo WHERE tenant_id = ? AND mes = ?", (tenant_id, mes)).fetchone() or {"usadas": 0})["usadas"]
        if limite is not None and usadas >= limite:
            conn.rollback()
            if limite == 0:
                raise LimiteIA("El asistente de IA no está activado para tu despacho. Contacta con soporte.")
            raise LimiteIA(f"Tu despacho ha agotado su límite mensual de IA ({limite} consultas). Se renueva el día 1 del mes que viene, o contacta con soporte para ampliarlo.")
        conn.execute(
            "INSERT INTO ia_consumo (tenant_id, mes, usadas) VALUES (?, ?, 1) ON CONFLICT(tenant_id, mes) DO UPDATE SET usadas = usadas + 1",
            (tenant_id, mes),
        )
        conn.commit()
    finally:
        conn.close()


def estado(tenant_id: int, ahora: datetime | None = None) -> dict:
    mes = _mes(ahora)
    conn = db.get_connection()
    try:
        t = conn.execute("SELECT ia_limite_mensual FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        f = conn.execute("SELECT usadas FROM ia_consumo WHERE tenant_id = ? AND mes = ?", (tenant_id, mes)).fetchone()
    finally:
        conn.close()
    limite = t["ia_limite_mensual"] if t else None
    usadas = f["usadas"] if f else 0
    pct = None if not limite else min(100, usadas * 100 // limite)
    return {
        "mes": mes, "usadas": usadas, "limite": limite, "ilimitado": limite is None,
        "restantes": None if limite is None else max(0, limite - usadas),
        "pct": pct, "agotado": limite is not None and usadas >= limite, "cerca": pct is not None and pct >= 80,
    }


def historial(tenant_id: int, meses: int = 6) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT mes, usadas FROM ia_consumo WHERE tenant_id = ? ORDER BY mes DESC LIMIT ?", (tenant_id, meses)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def fijar_limite(tenant_id: int, limite: int | None) -> None:
    """None = ilimitado. 0 desactiva la IA del despacho."""
    if limite is not None and (not isinstance(limite, int) or limite < 0 or limite > 1_000_000):
        raise ValueError("El límite debe ser un número entre 0 y 1.000.000, o ilimitado.")
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE tenants SET ia_limite_mensual = ? WHERE id = ?", (limite, tenant_id))
        if cur.rowcount == 0:
            raise ValueError("El despacho no existe.")
        conn.commit()
    finally:
        conn.close()


def resumen_global(ahora: datetime | None = None) -> list[dict]:
    """Consumo del mes de todos los despachos con uso o con tope, de más a menos gasto (para el backoffice)."""
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT t.id, t.nombre, t.ia_limite_mensual AS limite, COALESCE(c.usadas, 0) AS usadas
               FROM tenants t LEFT JOIN ia_consumo c ON c.tenant_id = t.id AND c.mes = ?
               WHERE COALESCE(c.usadas, 0) > 0 OR t.ia_limite_mensual IS NOT NULL
               ORDER BY usadas DESC, t.nombre COLLATE NOCASE""", (_mes(ahora),),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for f in filas:
        pct = None if not f["limite"] else min(100, f["usadas"] * 100 // f["limite"])
        out.append({**dict(f), "pct": pct, "ilimitado": f["limite"] is None})
    return out
