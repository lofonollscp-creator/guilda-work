"""El centro de avisos del portal: la lista de todo lo que ha pasado para esta persona (la gestoría te ha escrito, te devuelve una factura, te pide un documento, confirma tu cita…), con lo nuevo marcado.

Cada aviso que el portal manda por correo o al móvil queda anotado aquí con su título, un resumen y el enlace a donde lleva (se anota en `portal_push.enviar`, por donde pasan todos), de modo que quien no
abrió el correo ni vio la notificación lo encuentra igualmente. Lo «nuevo» es por persona: cada una tiene su propia marca de «leído hasta» (`portal_novedades_lectura`), así que la titular
leyendo sus avisos no se los quita a su administrativa. Se conservan 120 días."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_novedades (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    detalle TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portal_novedades_cliente ON portal_novedades(tenant_id, cliente_fiscal_id, creado_en);

CREATE TABLE IF NOT EXISTS portal_novedades_lectura (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    leidas_hasta TEXT NOT NULL,
    PRIMARY KEY (tenant_id, cliente_fiscal_id, email)
);
"""

CONSERVAR_DIAS = 120
MAX_TITULO, MAX_DETALLE = 160, 300
LIMITE_LISTA = 80


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def anotar(cliente, titulo: str, detalle: str = "", url: str = "", ahora: datetime | None = None) -> None:
    """Apunta un aviso para este cliente. Nunca lanza: apuntarlo no puede romper lo que lo provoca."""
    titulo = " ".join((titulo or "").split())[:MAX_TITULO]
    if not titulo:
        return
    url = url if (url or "").startswith("/portal/") else ""
    ahora = ahora or datetime.now()
    try:
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO portal_novedades (tenant_id, cliente_fiscal_id, titulo, detalle, url, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
                         (cliente["tenant_id"], cliente["id"], titulo, " ".join((detalle or "").split())[:MAX_DETALLE], url, _iso(ahora)))
            conn.execute("DELETE FROM portal_novedades WHERE tenant_id = ? AND cliente_fiscal_id = ? AND creado_en < ?", (cliente["tenant_id"], cliente["id"], _iso(ahora - timedelta(days=CONSERVAR_DIAS))))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("guilda").warning("No se pudo anotar el aviso del portal", exc_info=True)


def _leidas_hasta(conn, cliente, email: str) -> str:
    f = conn.execute("SELECT leidas_hasta FROM portal_novedades_lectura WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], (email or "").lower())).fetchone()
    return f["leidas_hasta"] if f else ""


def listar(cliente, email: str, limite: int = LIMITE_LISTA) -> list[dict]:
    """Los avisos más recientes primero, cada uno con `nuevo` (llegó después de la última vez que esta persona los marcó como leídos)."""
    conn = db.get_connection()
    try:
        marca = _leidas_hasta(conn, cliente, email)
        filas = [dict(f) for f in conn.execute("SELECT id, titulo, detalle, url, creado_en FROM portal_novedades WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY creado_en DESC, id DESC LIMIT ?",
                                               (cliente["tenant_id"], cliente["id"], limite)).fetchall()]
    finally:
        conn.close()
    for f in filas:
        f["nuevo"] = f["creado_en"] > marca
    return filas


def sin_leer(cliente, email: str) -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM portal_novedades WHERE tenant_id = ? AND cliente_fiscal_id = ? AND creado_en > ?", (cliente["tenant_id"], cliente["id"], _leidas_hasta(conn, cliente, email))).fetchone()[0]
    finally:
        conn.close()


def marcar_leidas(cliente, email: str, ahora: datetime | None = None) -> None:
    """Todo lo anotado hasta ahora pasa a estar leído para esta persona."""
    marca = _iso((ahora or datetime.now()) + timedelta(seconds=1))
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO portal_novedades_lectura (tenant_id, cliente_fiscal_id, email, leidas_hasta) VALUES (?, ?, ?, ?) ON CONFLICT (tenant_id, cliente_fiscal_id, email) DO UPDATE SET leidas_hasta = excluded.leidas_hasta",
                     (cliente["tenant_id"], cliente["id"], (email or "").lower(), marca))
        conn.commit()
    finally:
        conn.close()
