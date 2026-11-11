"""Bandeja de propuestas (W3): la IA y las reglas del sistema **proponen**, la persona aprueba o rechaza. Nada se ejecuta solo.

Una propuesta es «crear esta tarea», con su porqué y de dónde sale (`origen`: las alertas de clientes de app/anomalias.py hoy; el asistente y las demás funciones de IA pueden proponer con `proponer`).
Aprobar ejecuta el manejador de su `tipo` con quien aprueba (hoy: `tarea`); rechazar la silencia: la misma propuesta (misma `clave`) no vuelve a salir en `DIAS_SILENCIO` días, así la bandeja aprende
de lo que se descarta y no insiste. Cada aprobación y rechazo queda en la auditoría."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Callable

from . import auditoria, db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ia_propuestas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    clave TEXT NOT NULL,
    tipo TEXT NOT NULL,
    origen TEXT NOT NULL DEFAULT '',
    titulo TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    datos TEXT NOT NULL DEFAULT '{}',
    cliente_fiscal_id INTEGER,
    prioridad TEXT NOT NULL DEFAULT 'normal',
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobada', 'rechazada')),
    creada_en TEXT NOT NULL,
    resuelta_en TEXT,
    resuelta_por INTEGER,
    resultado TEXT
);
CREATE INDEX IF NOT EXISTS idx_ia_propuestas_tenant ON ia_propuestas(tenant_id, estado, creada_en);
CREATE INDEX IF NOT EXISTS idx_ia_propuestas_clave ON ia_propuestas(tenant_id, clave);
"""

DIAS_SILENCIO = 30
MANEJADORES: dict[str, Callable[[dict, int], str]] = {}


class ErrorPropuesta(ValueError):
    """Mensaje apto para enseñarlo."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def manejador(tipo: str):
    def registrar(f):
        MANEJADORES[tipo] = f
        return f
    return registrar


@manejador("tarea")
def _crear_tarea(p: dict, usuario_id: int) -> str:
    d = p["datos"]
    tid = db.crear_tarea_outlook(usuario_id, asunto=p["titulo"], cuerpo=p["detalle"] or None, prioridad=p["prioridad"], cliente_fiscal_id=p["cliente_fiscal_id"])
    return f"tarea:{tid}"


def proponer(tenant_id: int, *, clave: str, tipo: str, titulo: str, detalle: str = "", origen: str = "", datos: dict | None = None, cliente_fiscal_id: int | None = None, prioridad: str = "normal") -> int | None:
    """Deja una propuesta en la bandeja. Devuelve su id, o None si no hace falta: ya hay una igual pendiente o se aprobó o rechazó hace menos de `DIAS_SILENCIO` días."""
    if tipo not in MANEJADORES:
        raise ErrorPropuesta("No sé ejecutar ese tipo de propuesta.")
    desde = (datetime.now() - timedelta(days=DIAS_SILENCIO)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM ia_propuestas WHERE tenant_id = ? AND clave = ? AND (estado = 'pendiente' OR creada_en >= ?)", (tenant_id, clave, desde)).fetchone():
            return None
        cur = conn.execute("INSERT INTO ia_propuestas (tenant_id, clave, tipo, origen, titulo, detalle, datos, cliente_fiscal_id, prioridad, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, clave[:200], tipo, origen[:40], titulo[:200], detalle[:600], json.dumps(datos or {}, ensure_ascii=False), cliente_fiscal_id, prioridad, _ahora()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _fila(f) -> dict:
    d = dict(f)
    d["datos"] = json.loads(d.get("datos") or "{}")
    return d


def obtener(tenant_id: int, propuesta_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM ia_propuestas WHERE tenant_id = ? AND id = ?", (tenant_id, propuesta_id)).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def pendientes(tenant_id: int, cliente_fiscal_id: int | None = None) -> list[dict]:
    """Las pendientes, las urgentes primero y dentro de cada prioridad las más antiguas."""
    sql, args = "SELECT * FROM ia_propuestas WHERE tenant_id = ? AND estado = 'pendiente'", [tenant_id]
    if cliente_fiscal_id is not None:
        sql += " AND cliente_fiscal_id = ?"; args.append(cliente_fiscal_id)
    conn = db.get_connection()
    try:
        filas = [_fila(f) for f in conn.execute(sql + " ORDER BY id", args).fetchall()]
    finally:
        conn.close()
    return sorted(filas, key=lambda p: (0 if p["prioridad"] == "alta" else 1, p["id"]))


def contar(tenant_id: int) -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM ia_propuestas WHERE tenant_id = ? AND estado = 'pendiente'", (tenant_id,)).fetchone()[0]
    finally:
        conn.close()


def resueltas(tenant_id: int, dias: int = 30, limite: int = 30) -> list[dict]:
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        return [_fila(f) for f in conn.execute("SELECT * FROM ia_propuestas WHERE tenant_id = ? AND estado <> 'pendiente' AND resuelta_en >= ? ORDER BY resuelta_en DESC, id DESC LIMIT ?", (tenant_id, desde, limite)).fetchall()]
    finally:
        conn.close()


def _resolver(tenant_id: int, usuario_id: int, propuesta_id: int, estado: str, resultado: str = "") -> bool:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE ia_propuestas SET estado = ?, resuelta_en = ?, resuelta_por = ?, resultado = ? WHERE tenant_id = ? AND id = ? AND estado = 'pendiente'",
                         (estado, _ahora(), usuario_id, resultado[:200], tenant_id, propuesta_id)).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def aprobar(tenant_id: int, usuario_id: int, propuesta_id: int) -> str:
    """Ejecuta la propuesta como quien la aprueba y la cierra. Dos personas pulsando a la vez no la ejecutan dos veces. Devuelve lo que se hizo (p. ej. `tarea:12`)."""
    p = obtener(tenant_id, propuesta_id)
    if p is None:
        raise ErrorPropuesta("Esa propuesta no existe.")
    if p["estado"] != "pendiente":
        raise ErrorPropuesta("Esa propuesta ya estaba resuelta.")
    if not _resolver(tenant_id, usuario_id, propuesta_id, "aprobada"):          # se «reclama» antes de ejecutar: la segunda persona se queda sin nada que hacer
        raise ErrorPropuesta("Esa propuesta ya estaba resuelta.")
    try:
        resultado = MANEJADORES[p["tipo"]](p, usuario_id)
    except Exception:
        conn = db.get_connection()
        try:
            conn.execute("UPDATE ia_propuestas SET estado = 'pendiente', resuelta_en = NULL, resuelta_por = NULL WHERE tenant_id = ? AND id = ?", (tenant_id, propuesta_id))
            conn.commit()
        finally:
            conn.close()
        raise
    conn = db.get_connection()
    try:
        conn.execute("UPDATE ia_propuestas SET resultado = ? WHERE tenant_id = ? AND id = ?", (resultado[:200], tenant_id, propuesta_id))
        conn.commit()
    finally:
        conn.close()
    auditoria.registrar(tenant_id, usuario_id, "ia.propuesta_aprobada", "ia_propuesta", propuesta_id, {"tipo": p["tipo"], "origen": p["origen"], "resultado": resultado})
    return resultado


def rechazar(tenant_id: int, usuario_id: int, propuesta_id: int) -> None:
    if not _resolver(tenant_id, usuario_id, propuesta_id, "rechazada"):
        raise ErrorPropuesta("Esa propuesta ya estaba resuelta.")
    auditoria.registrar(tenant_id, usuario_id, "ia.propuesta_rechazada", "ia_propuesta", propuesta_id, {})


def generar_desde_alertas(tenant_id: int, hoy=None) -> int:
    """Deja en la bandeja una propuesta «crear tarea» por cada alerta de clientes (app/anomalias.py) que todavía no tenga una reciente. Idempotente. Devuelve cuántas nuevas."""
    from . import anomalias
    nuevas = 0
    for a in anomalias.detectar(tenant_id, hoy):
        titulo, detalle = anomalias.texto(a)
        if proponer(tenant_id, clave=f"alerta:{anomalias.clave(a)}", tipo="tarea", titulo=titulo, detalle=detalle, origen="alerta", cliente_fiscal_id=a["cliente_id"], prioridad="alta" if a["severidad"] == "alta" else "normal", datos={"alerta": a["tipo"]}):
            nuevas += 1
    return nuevas


_ULTIMA_GENERACION: dict[int, datetime] = {}


def generar_si_toca(tenant_id: int, minutos: int = 60) -> int:
    """Como `generar_desde_alertas`, pero como mucho una vez cada `minutos` por despacho en este proceso: la ficha de cada cliente la llama y calcular las alertas de todo el despacho no es gratis."""
    ahora = datetime.now()
    ultima = _ULTIMA_GENERACION.get(tenant_id)
    if ultima and ahora - ultima < timedelta(minutes=minutos):
        return 0
    _ULTIMA_GENERACION[tenant_id] = ahora
    return generar_desde_alertas(tenant_id)
