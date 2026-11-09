"""Valoración de los clientes: al cerrar un trámite (hoy, una petición de documentos que la gestoría da por revisada) el portal pregunta en una línea «¿qué tal ha ido?» (1 a 5 estrellas y un comentario
opcional). La valoración es de cada persona y de cada trámite (no se repite) y la ve la dirección en la actividad del portal; una nota baja avisa a quien lleva al cliente."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_valoraciones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    tipo TEXT NOT NULL,
    referencia TEXT NOT NULL,
    puntos INTEGER NOT NULL CHECK (puntos BETWEEN 1 AND 5),
    comentario TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_valoraciones ON portal_valoraciones(tenant_id, cliente_fiscal_id, email, tipo, referencia);
"""

TIPOS = ("peticion", "subida")                           # «subida»: ¿te ha resultado fácil subir tus facturas? (referencia = el día de la subida)
NOTA_BAJA = 2
MAX_COMENTARIO = 300


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _email(e: str | None) -> str:
    return (e or "").strip().lower()


def ya_valorada(cliente, email: str, tipo: str, referencia) -> bool:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM portal_valoraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ? AND tipo = ? AND referencia = ?",
                            (cliente["tenant_id"], cliente["id"], _email(email), tipo, str(referencia))).fetchone() is not None
    finally:
        conn.close()


def valorar(cliente, email: str, tipo: str, referencia, puntos, comentario: str = "") -> bool:
    """Guarda la valoración. Devuelve True si es de nota baja (para avisar al equipo). `ValueError` con un mensaje legible si no vale o ya estaba valorada."""
    from . import portal_peticiones
    if tipo not in TIPOS:
        raise ValueError("No se puede valorar eso.")
    try:
        n = int(puntos)
    except (TypeError, ValueError):
        raise ValueError("Elige de 1 a 5 estrellas.") from None
    if not 1 <= n <= 5:
        raise ValueError("Elige de 1 a 5 estrellas.")
    if tipo == "peticion":
        p = portal_peticiones.obtener(cliente, int(referencia))
        if p is None or p["estado"] != "revisada":
            raise ValueError("Solo se puede valorar un trámite ya resuelto.")
    if tipo == "subida":
        from datetime import date
        try:
            dia = date.fromisoformat(str(referencia))
        except ValueError:
            raise ValueError("No se puede valorar eso.") from None
        if not 0 <= (date.today() - dia).days <= 3:
            raise ValueError("No se puede valorar eso.")
    if ya_valorada(cliente, email, tipo, referencia):
        raise ValueError("Ya has valorado este trámite. ¡Gracias!")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO portal_valoraciones (tenant_id, cliente_fiscal_id, email, tipo, referencia, puntos, comentario, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (cliente["tenant_id"], cliente["id"], _email(email), tipo, str(referencia), n, " ".join((comentario or "").split())[:MAX_COMENTARIO], datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    finally:
        conn.close()
    return n <= NOTA_BAJA


def resumen(tenant_id: int, dias: int = 90, ultimas: int = 10) -> dict:
    """{n, media, reparto: {1..5}, ultimas: [{cliente, puntos, comentario, creado_en, tipo}]} de los últimos `dias` días de ese despacho."""
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT v.puntos, v.comentario, v.creado_en, v.tipo, c.nombre AS cliente FROM portal_valoraciones v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id "
                             "WHERE v.tenant_id = ? AND v.creado_en >= ? ORDER BY v.id DESC", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    reparto = {i: 0 for i in range(1, 6)}
    for f in filas:
        reparto[f["puntos"]] += 1
    return {"n": len(filas), "media": round(sum(f["puntos"] for f in filas) / len(filas), 1) if filas else None, "reparto": reparto, "ultimas": [dict(f) for f in filas[:ultimas]]}
