"""Lectura previa de la factura en el portal: al elegir una foto o un PDF, el cliente puede ver qué datos lee la IA (quién la emite, número, fecha, total) antes de enviarla y
darse cuenta de una foto cortada o ilegible. Es opcional y está **apagada** por defecto: la enciende el despacho, porque la lectura se hace con el modelo y la clave de la persona
responsable del cliente (cuenta como una consulta de IA del despacho) y la factura sale hacia ese modelo antes de que nadie del despacho la haya visto. No guarda nada: si el cliente
la envía, entra como siempre, pendiente de que el despacho la lea y la revise."""
from __future__ import annotations

from . import db, lectura_facturas, verticales

TIPOS = ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf")
MAX_BYTES = 8 * 1024 * 1024


def activa(tenant_id: int) -> bool:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT lectura_previa FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return bool(f and f["lectura_previa"])


def fijar(tenant_id: int, activar: bool) -> None:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_recordatorios_config SET lectura_previa = ? WHERE tenant_id = ?", (1 if activar else 0, tenant_id)).rowcount
        if not n:
            cfg = db.CONFIG_RECORDATORIOS_DEFECTO
            conn.execute("INSERT INTO portal_recordatorios_config (tenant_id, dias_antes, dias_despues, avisar_equipo, asunto, cuerpo, actualizado_en, lectura_previa) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, ",".join(str(x) for x in cfg["dias_antes"]), "", int(cfg["avisar_equipo"]), "", "", db.now_iso(), 1 if activar else 0))
        conn.commit()
    finally:
        conn.close()


def lector_de(cliente) -> int | None:
    """La persona del despacho cuya IA hace la lectura: quien lleva al cliente y, si no tiene IA preparada, la primera de coordinación o dirección que sí."""
    candidatos = [cliente["responsable_id"]] if cliente["responsable_id"] else []
    conn = db.get_connection()
    try:
        candidatos += [r["id"] for r in conn.execute("SELECT u.id FROM usuarios u WHERE " + db.sql_supervisor() + " ORDER BY u.id", (cliente["tenant_id"], cliente["tenant_id"])).fetchall()]
    finally:
        conn.close()
    return next((u for u in candidatos if lectura_facturas.configurada(u)), None)


def disponible(cliente) -> bool:
    return bool(cliente is not None and verticales.esta_activo(cliente["tenant_id"], "contabilizacion") and activa(cliente["tenant_id"]) and lector_de(cliente) is not None)


def leer(cliente, contenido: bytes, tipo_mime: str) -> dict:
    """Lo que lee la IA de ese archivo. `ValueError` con un mensaje apto para el cliente si no se puede."""
    if not disponible(cliente):
        raise ValueError("La lectura previa no está disponible.")
    if tipo_mime not in TIPOS or not contenido or len(contenido) > MAX_BYTES:
        raise ValueError("Ese archivo no se puede leer aquí.")
    return lectura_facturas.previsualizar(lector_de(cliente), contenido, tipo_mime)
