"""Comunicados del backoffice a la plataforma: avisos (mantenimiento, novedades, incidencias) que la app
muestra como banner. Se publican para todos los despachos o para uno; el usuario puede cerrar los
informativos y los de aviso, no los críticos."""
from __future__ import annotations

import time
from datetime import datetime

from . import db

NIVELES = ("info", "aviso", "critico")

# El banner se pinta en TODAS las páginas: se recuerda 20 s si existe algún comunicado que pueda estar vigente
# (la mayor parte del tiempo no hay ninguno y así no cuesta ni una consulta). El backoffice es otro proceso,
# por eso la caducidad corta; las escrituras de este proceso la invalidan al momento.
_TTL_HAY = 20.0
_hay: dict[str, tuple[float, bool]] = {}


def _invalidar() -> None:
    _hay.clear()


def _hay_alguno(ahora: str) -> bool:
    clave = str(db.DB_PATH)
    guardado = _hay.get(clave)
    if guardado and time.monotonic() - guardado[0] < _TTL_HAY:
        return guardado[1]
    conn = db.get_connection()
    try:
        hay = conn.execute("SELECT 1 FROM comunicados WHERE activo = 1 AND (hasta IS NULL OR hasta >= ?) LIMIT 1", (ahora,)).fetchone() is not None
    finally:
        conn.close()
    _hay[clave] = (time.monotonic(), hay)
    return hay


def _ahora() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _fecha(valor: str | None) -> str | None:
    """'2026-10-09T08:00' / '2026-10-09' -> ISO a minutos; vacío o inválido -> None."""
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor).isoformat(timespec="minutes")
    except ValueError:
        return None


def crear(titulo: str, texto: str = "", nivel: str = "info", tenant_id: int | None = None, desde: str | None = None, hasta: str | None = None) -> int:
    titulo = (titulo or "").strip()[:120]
    if not titulo:
        raise ValueError("El comunicado necesita un título.")
    if nivel not in NIVELES:
        raise ValueError("Nivel no válido.")
    desde, hasta = _fecha(desde), _fecha(hasta)
    if desde and hasta and hasta < desde:
        raise ValueError("La fecha de fin es anterior a la de inicio.")
    conn = db.get_connection()
    try:
        if tenant_id is not None and not conn.execute("SELECT 1 FROM tenants WHERE id = ?", (tenant_id,)).fetchone():
            raise ValueError("El despacho no existe.")
        cur = conn.execute(
            "INSERT INTO comunicados (titulo, texto, nivel, tenant_id, desde, hasta, activo, creado_en) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (titulo, (texto or "").strip()[:600], nivel, tenant_id, desde, hasta, _ahora()),
        )
        conn.commit()
        _invalidar()
        return cur.lastrowid
    finally:
        conn.close()


def estado_de(fila, ahora: str | None = None) -> str:
    """'activo' | 'programado' | 'caducado' | 'pausado'."""
    ahora = ahora or _ahora()
    if not fila["activo"]:
        return "pausado"
    if fila["desde"] and fila["desde"] > ahora:
        return "programado"
    if fila["hasta"] and fila["hasta"] < ahora:
        return "caducado"
    return "activo"


def listar() -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT c.*, t.nombre AS tenant_nombre,
                      (SELECT COUNT(*) FROM comunicados_cerrados x WHERE x.comunicado_id = c.id) AS cerrados
               FROM comunicados c LEFT JOIN tenants t ON t.id = c.tenant_id ORDER BY c.id DESC"""
        ).fetchall()
    finally:
        conn.close()
    ahora = _ahora()
    return [{**dict(f), "estado": estado_de(f, ahora)} for f in filas]


def cambiar_activo(comunicado_id: int, activo: bool) -> bool:
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE comunicados SET activo = ? WHERE id = ?", (1 if activo else 0, comunicado_id))
        conn.commit()
        _invalidar()
        return cur.rowcount > 0
    finally:
        conn.close()


def eliminar(comunicado_id: int) -> bool:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM comunicados_cerrados WHERE comunicado_id = ?", (comunicado_id,))
        cur = conn.execute("DELETE FROM comunicados WHERE id = ?", (comunicado_id,))
        conn.commit()
        _invalidar()
        return cur.rowcount > 0
    finally:
        conn.close()


def activos_para(usuario_id: int, tenant_id: int | None, ahora: str | None = None) -> list[dict]:
    """Comunicados vigentes que debe ver este usuario: los críticos primero, sin los que ya cerró."""
    ahora = ahora or _ahora()
    if not _hay_alguno(ahora):
        return []
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT c.id, c.titulo, c.texto, c.nivel FROM comunicados c
               WHERE c.activo = 1 AND (c.desde IS NULL OR c.desde <= ?) AND (c.hasta IS NULL OR c.hasta >= ?)
                 AND (c.tenant_id IS NULL OR c.tenant_id = ?)
                 AND (c.nivel = 'critico' OR NOT EXISTS
                      (SELECT 1 FROM comunicados_cerrados x WHERE x.comunicado_id = c.id AND x.usuario_id = ?))
               ORDER BY CASE c.nivel WHEN 'critico' THEN 0 WHEN 'aviso' THEN 1 ELSE 2 END, c.id DESC LIMIT 3""",
            (ahora, ahora, tenant_id, usuario_id),
        ).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def cerrar(usuario_id: int, comunicado_id: int) -> bool:
    """El usuario descarta un comunicado. Los críticos no se pueden cerrar."""
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT nivel FROM comunicados WHERE id = ?", (comunicado_id,)).fetchone()
        if fila is None or fila["nivel"] == "critico":
            return False
        conn.execute("INSERT OR IGNORE INTO comunicados_cerrados (usuario_id, comunicado_id) VALUES (?, ?)", (usuario_id, comunicado_id))
        conn.commit()
        return True
    finally:
        conn.close()
