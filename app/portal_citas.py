"""Citas con la gestoría desde el portal: el cliente pide una llamada, una videollamada o una visita diciendo para qué y cuándo le viene bien, y el despacho la **confirma** con día y hora (o la rechaza con una
nota). La confirmada aparece en el calendario de plazos del cliente. No enseña la agenda del despacho: el cliente propone y el despacho decide.

Estados: `solicitada` (espera al despacho), `confirmada`, `rechazada` y `cancelada` (por el cliente, antes de que pase)."""
from __future__ import annotations

from datetime import datetime

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_citas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    canal TEXT NOT NULL CHECK (canal IN ('llamada', 'videollamada', 'visita')),
    motivo TEXT NOT NULL,
    preferencias TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'solicitada' CHECK (estado IN ('solicitada', 'confirmada', 'rechazada', 'cancelada')),
    fecha_hora TEXT,
    nota TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL,
    resuelta_en TEXT,
    resuelta_por INTEGER
);
CREATE INDEX IF NOT EXISTS idx_portal_citas_cliente ON portal_citas(tenant_id, cliente_fiscal_id, estado);
"""

CANALES = ("llamada", "videollamada", "visita")
MAX_ABIERTAS = 3
MAX_MOTIVO, MAX_PREFERENCIAS, MAX_NOTA = 200, 200, 300


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _limpio(texto: str | None, largo: int) -> str:
    return " ".join((texto or "").split())[:largo]


def solicitar(cliente, email: str, canal: str, motivo: str, preferencias: str = "") -> int:
    """El cliente pide una cita. `ValueError` con un mensaje legible si falta algo o ya tiene demasiadas pendientes."""
    if canal not in CANALES:
        raise ValueError("Elige cómo quieres la cita.")
    motivo = _limpio(motivo, MAX_MOTIVO)
    if len(motivo) < 5:
        raise ValueError("Cuéntanos para qué es la cita (mínimo 5 caracteres).")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM portal_citas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'solicitada'", (cliente["tenant_id"], cliente["id"])).fetchone()[0] >= MAX_ABIERTAS:
            raise ValueError("Ya tienes varias citas pidiéndose: espera a que tu gestoría las confirme.")
        cur = conn.execute("INSERT INTO portal_citas (tenant_id, cliente_fiscal_id, email, canal, motivo, preferencias, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], (email or "").strip().lower(), canal, motivo, _limpio(preferencias, MAX_PREFERENCIAS), _ahora()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar(cliente) -> list[dict]:
    """Las citas de ese cliente: primero las que esperan o están por llegar y luego el histórico."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM portal_citas WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY id DESC", (cliente["tenant_id"], cliente["id"])).fetchall()
    finally:
        conn.close()
    ahora = _ahora()
    orden = lambda c: (0 if c["estado"] == "solicitada" else (1 if c["estado"] == "confirmada" and (c["fecha_hora"] or "") >= ahora else 2), c["fecha_hora"] or "", -c["id"])
    return sorted((dict(f) for f in filas), key=orden)


def del_despacho(tenant_id: int) -> list[dict]:
    """Las citas por atender de todo el despacho (pedidas) y las confirmadas que aún no han pasado, con el nombre del cliente."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT p.*, c.nombre AS cliente FROM portal_citas p JOIN clientes_fiscales c ON c.id = p.cliente_fiscal_id WHERE p.tenant_id = ? AND "
                             "(p.estado = 'solicitada' OR (p.estado = 'confirmada' AND p.fecha_hora >= ?)) ORDER BY CASE p.estado WHEN 'solicitada' THEN 0 ELSE 1 END, COALESCE(p.fecha_hora, p.creado_en), p.id",
                             (tenant_id, _ahora())).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def obtener(tenant_id: int, cita_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM portal_citas WHERE id = ? AND tenant_id = ?", (cita_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return dict(f) if f else None


def confirmar(tenant_id: int, cita_id: int, fecha_hora: str, nota: str, por: int | None) -> dict:
    """El despacho confirma la cita con día y hora (AAAA-MM-DDTHH:MM) y, si quiere, una nota (dónde, con quién, enlace de la videollamada). Devuelve la cita. `ValueError` si la fecha no vale o ya no se puede."""
    try:
        cuando = datetime.fromisoformat((fecha_hora or "").strip()[:16])
    except ValueError:
        raise ValueError("Indica el día y la hora de la cita.") from None
    if cuando < datetime.now():
        raise ValueError("La cita no puede ser en el pasado.")
    return _resolver(tenant_id, cita_id, ("solicitada",), "confirmada", por, nota, cuando.isoformat(timespec="minutes"))


def rechazar(tenant_id: int, cita_id: int, nota: str, por: int | None) -> dict:
    if len(_limpio(nota, MAX_NOTA)) < 5:
        raise ValueError("Explica el motivo (mínimo 5 caracteres): lo verá el cliente.")
    return _resolver(tenant_id, cita_id, ("solicitada", "confirmada"), "rechazada", por, nota, None)


def _resolver(tenant_id: int, cita_id: int, desde: tuple[str, ...], estado: str, por: int | None, nota: str, fecha_hora: str | None) -> dict:
    conn = db.get_connection()
    try:
        marcadores = ",".join("?" * len(desde))
        n = conn.execute(f"UPDATE portal_citas SET estado = ?, nota = ?, fecha_hora = COALESCE(?, fecha_hora), resuelta_en = ?, resuelta_por = ? WHERE id = ? AND tenant_id = ? AND estado IN ({marcadores})",
                         (estado, _limpio(nota, MAX_NOTA), fecha_hora, _ahora(), por, cita_id, tenant_id, *desde)).rowcount
        conn.commit()
    finally:
        conn.close()
    if not n:
        raise ValueError("Esa cita ya no admite este cambio.")
    return obtener(tenant_id, cita_id)


def cancelar(cliente, email: str, cita_id: int) -> bool:
    """El cliente cancela una cita suya, pedida o confirmada, que aún no ha pasado."""
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_citas SET estado = 'cancelada', resuelta_en = ? WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('solicitada', 'confirmada') "
                         "AND (fecha_hora IS NULL OR fecha_hora >= ?)", (_ahora(), cita_id, cliente["tenant_id"], cliente["id"], _ahora())).rowcount
        conn.commit()
    finally:
        conn.close()
    return bool(n)


def confirmadas_futuras(cliente) -> list[dict]:
    return [c for c in listar(cliente) if c["estado"] == "confirmada" and (c["fecha_hora"] or "") >= _ahora()]
