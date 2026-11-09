"""Salud del portal vista desde el navegador de los clientes: cuánto tarda en cargar cada pantalla y qué errores de JavaScript ocurren, para detectar un problema antes de que alguien llame.

Es **opcional y está apagada por defecto**: cada despacho la enciende si la quiere. Solo guarda contadores por día y pantalla («/portal/facturas»: 40 cargas, 620 ms de media, 1 error de tal tipo): nada de quién es la persona, ni su cliente, ni su
navegador, ni su IP, ni lo que hay en la página. Las rutas se normalizan (los números y los códigos largos se sustituyen) y los mensajes de error se recortan y se les quitan los números, para que no cuelen datos."""
from __future__ import annotations

import re
import time
from datetime import date, timedelta

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_telemetria_diaria (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    dia TEXT NOT NULL,
    ruta TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('carga', 'error')),
    detalle TEXT NOT NULL DEFAULT '',
    n INTEGER NOT NULL DEFAULT 0,
    suma_ms INTEGER NOT NULL DEFAULT 0,
    max_ms INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, dia, ruta, tipo, detalle)
);
"""
RETENCION_DIAS = 30
MAX_MS = 60000
_CACHE: dict[int, tuple[float, bool]] = {}
TTL = 30


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def activa(tenant_id: int) -> bool:
    """¿Tiene este despacho encendida la medición? (con una caché de 30 s: se consulta en cada página del portal)."""
    c = _CACHE.get(tenant_id)
    if c and time.monotonic() - c[0] < TTL:
        return c[1]
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT telemetria FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    v = bool(f and f["telemetria"])
    _CACHE[tenant_id] = (time.monotonic(), v)
    return v


def fijar(tenant_id: int, activar: bool) -> None:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_recordatorios_config SET telemetria = ? WHERE tenant_id = ?", (1 if activar else 0, tenant_id)).rowcount
        if not n:
            cfg = db.CONFIG_RECORDATORIOS_DEFECTO
            conn.execute("INSERT INTO portal_recordatorios_config (tenant_id, dias_antes, dias_despues, avisar_equipo, asunto, cuerpo, actualizado_en, telemetria) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, ",".join(str(x) for x in cfg["dias_antes"]), "", int(cfg["avisar_equipo"]), "", "", db.now_iso(), 1 if activar else 0))
        conn.commit()
    finally:
        conn.close()
    _CACHE.pop(tenant_id, None)


def ruta_normalizada(ruta: str) -> str:
    """Solo el camino, sin consulta, con los números y los códigos largos sustituidos: «/portal/facturas/123» → «/portal/facturas/:id»."""
    camino = (ruta or "").split("?")[0].split("#")[0][:120]
    partes = []
    for p in camino.split("/"):
        if re.fullmatch(r"\d+", p):
            p = ":id"
        elif len(p) >= 16 and re.fullmatch(r"[A-Za-z0-9_\-]+", p):
            p = ":codigo"
        partes.append(p)
    r = "/".join(partes)
    return r if r.startswith("/portal") else ""


def _mensaje_limpio(m: str) -> str:
    m = re.sub(r"https?://\S+", "", str(m or ""))
    m = re.sub(r"\d+", "#", m)
    return " ".join(m.split())[:100]


def registrar(tenant_id: int, evento: dict, dia: date | None = None) -> bool:
    """Suma un evento {tipo: carga|error, ruta, ms | mensaje} al contador del día. False si no se admite (apagada, tipo o ruta que no valen)."""
    if not activa(tenant_id) or not isinstance(evento, dict):
        return False
    tipo, ruta = evento.get("tipo"), ruta_normalizada(str(evento.get("ruta") or ""))
    if tipo not in ("carga", "error") or not ruta:
        return False
    ms = 0
    detalle = ""
    if tipo == "carga":
        try:
            ms = max(0, min(MAX_MS, int(float(evento.get("ms")))))
        except (TypeError, ValueError):
            return False
    else:
        detalle = _mensaje_limpio(evento.get("mensaje"))
    d = (dia or date.today()).isoformat()
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_telemetria_diaria SET n = n + 1, suma_ms = suma_ms + ?, max_ms = CASE WHEN ? > max_ms THEN ? ELSE max_ms END WHERE tenant_id = ? AND dia = ? AND ruta = ? AND tipo = ? AND detalle = ?",
                         (ms, ms, ms, tenant_id, d, ruta, tipo, detalle)).rowcount
        if not n:
            conn.execute("INSERT INTO portal_telemetria_diaria (tenant_id, dia, ruta, tipo, detalle, n, suma_ms, max_ms) VALUES (?, ?, ?, ?, ?, 1, ?, ?)", (tenant_id, d, ruta, tipo, detalle, ms, ms))
        conn.execute("DELETE FROM portal_telemetria_diaria WHERE tenant_id = ? AND dia < ?", (tenant_id, (date.today() - timedelta(days=RETENCION_DIAS)).isoformat()))
        conn.commit()
    finally:
        conn.close()
    return True


def resumen(tenant_id: int, dias: int = 14, hoy: date | None = None) -> dict:
    """{pantallas: [{ruta, cargas, media_ms, max_ms}] de la más lenta a la más rápida, errores: [{ruta, mensaje, n}] de más a menos frecuentes} de los últimos `dias` días."""
    desde = ((hoy or date.today()) - timedelta(days=dias)).isoformat()
    conn = db.get_connection()
    try:
        cargas = conn.execute("SELECT ruta, SUM(n) AS n, SUM(suma_ms) AS ms, MAX(max_ms) AS mx FROM portal_telemetria_diaria WHERE tenant_id = ? AND tipo = 'carga' AND dia >= ? GROUP BY ruta", (tenant_id, desde)).fetchall()
        errores = conn.execute("SELECT ruta, detalle, SUM(n) AS n FROM portal_telemetria_diaria WHERE tenant_id = ? AND tipo = 'error' AND dia >= ? GROUP BY ruta, detalle ORDER BY n DESC LIMIT 15", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    pantallas = sorted(({"ruta": c["ruta"], "cargas": c["n"], "media_ms": round(c["ms"] / c["n"]) if c["n"] else 0, "max_ms": c["mx"]} for c in cargas), key=lambda x: -x["media_ms"])
    return {"pantallas": pantallas, "errores": [{"ruta": e["ruta"], "mensaje": e["detalle"], "n": e["n"]} for e in errores]}
