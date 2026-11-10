"""Cola de invitaciones al portal: el correo con el enlace de acceso sale solo y de forma escalonada, para poder dar de alta o importar cientos de clientes de una vez sin saturar el servidor de correo ni la bandeja de nadie.

Al dar de alta un cliente con una plantilla que invita (o al pedir «invitar a todos los pendientes» en Adopción del portal) se apunta una invitación; un hilo del servidor manda cada pocos minutos las que toquen,
con un tope por hora y despacho. Cada cliente solo tiene una invitación pendiente a la vez, y se anota cuándo salió para que el panel enseñe cuántas quedan."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta

from . import db

logger = logging.getLogger("guilda")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_invitaciones_cola (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    creado_en TEXT NOT NULL,
    enviada_en TEXT,
    intentos INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_portal_invitaciones_cola ON portal_invitaciones_cola(tenant_id, enviada_en, id);
"""

MAX_POR_HORA = 100          # por despacho
MAX_POR_PASADA = 20
MAX_INTENTOS = 3
INTERVALO_SEGUNDOS = 300


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now()).isoformat(timespec="seconds")


def encolar(tenant_id: int, cliente_fiscal_id: int, ahora: datetime | None = None) -> bool:
    """Apunta una invitación para ese cliente. False si no tiene correo, ya tiene una pendiente o ya la agotó (3 intentos fallidos)."""
    ficha = db.obtener_cliente_fiscal(tenant_id, cliente_fiscal_id)
    if ficha is None or not (ficha["email"] or "").strip():
        return False
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM portal_invitaciones_cola WHERE tenant_id = ? AND cliente_fiscal_id = ? AND enviada_en IS NULL AND intentos < ?", (tenant_id, cliente_fiscal_id, MAX_INTENTOS)).fetchone():
            return False
        conn.execute("INSERT INTO portal_invitaciones_cola (tenant_id, cliente_fiscal_id, creado_en) VALUES (?, ?, ?)", (tenant_id, cliente_fiscal_id, _ahora(ahora)))
        conn.commit()
        return True
    finally:
        conn.close()


def pendientes(tenant_id: int) -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM portal_invitaciones_cola WHERE tenant_id = ? AND enviada_en IS NULL AND intentos < ?", (tenant_id, MAX_INTENTOS)).fetchone()[0]
    finally:
        conn.close()


def _base_publica() -> str:
    from . import portal_recordatorios
    return portal_recordatorios.base_portal()


def procesar(ahora: datetime | None = None, base_url: str | None = None, enviar=None) -> dict:
    """Una pasada: manda las invitaciones que toquen respetando el tope por hora de cada despacho. Devuelve {enviadas, fallidas, aplazadas}. `enviar(cliente, base_url)` se puede sustituir en las pruebas."""
    from . import portal_adopcion
    from .main import app
    ahora = ahora or datetime.now()
    base = (base_url or _base_publica())
    res = {"enviadas": 0, "fallidas": 0, "aplazadas": 0}
    if not base:
        return res
    desde = _ahora(ahora - timedelta(hours=1))
    conn = db.get_connection()
    try:
        despachos = [f[0] for f in conn.execute("SELECT DISTINCT tenant_id FROM portal_invitaciones_cola WHERE enviada_en IS NULL AND intentos < ?", (MAX_INTENTOS,)).fetchall()]
    finally:
        conn.close()
    for tenant_id in despachos:
        conn = db.get_connection()
        try:
            salidas = conn.execute("SELECT COUNT(*) FROM portal_invitaciones_cola WHERE tenant_id = ? AND enviada_en >= ?", (tenant_id, desde)).fetchone()[0]
            cupo = max(0, min(MAX_POR_PASADA, MAX_POR_HORA - salidas))
            filas = conn.execute("SELECT id, cliente_fiscal_id FROM portal_invitaciones_cola WHERE tenant_id = ? AND enviada_en IS NULL AND intentos < ? ORDER BY id LIMIT ?", (tenant_id, MAX_INTENTOS, cupo)).fetchall() if cupo else []
            total = conn.execute("SELECT COUNT(*) FROM portal_invitaciones_cola WHERE tenant_id = ? AND enviada_en IS NULL AND intentos < ?", (tenant_id, MAX_INTENTOS)).fetchone()[0]
        finally:
            conn.close()
        res["aplazadas"] += max(0, total - len(filas))
        for f in filas:
            cliente = db.obtener_cliente_fiscal(tenant_id, f["cliente_fiscal_id"])
            ok, motivo = False, "El cliente ya no existe."
            if cliente is not None:
                try:
                    with app.test_request_context(base_url=base):
                        ok = (enviar or portal_adopcion.invitar)(cliente, base, None)
                    motivo = "" if ok else "No se pudo enviar el correo (¿tiene correo y está configurado el servidor de correo?)."
                except Exception as e:  # noqa: BLE001 -- una invitación rota no frena las demás
                    logger.exception("Invitación al portal del cliente %s fallida", f["cliente_fiscal_id"])
                    motivo = f"{type(e).__name__}"
            conn = db.get_connection()
            try:
                if ok:
                    conn.execute("UPDATE portal_invitaciones_cola SET enviada_en = ? WHERE id = ? AND tenant_id = ?", (_ahora(ahora), f["id"], tenant_id))
                else:
                    conn.execute("UPDATE portal_invitaciones_cola SET intentos = intentos + 1, ultimo_error = ? WHERE id = ? AND tenant_id = ?", (motivo[:200], f["id"], tenant_id))
                conn.commit()
            finally:
                conn.close()
            res["enviadas" if ok else "fallidas"] += 1
    return res


def bucle() -> None:
    """Hilo del servidor: cada pocos minutos manda las invitaciones que toquen. Idempotente: reiniciar el servicio no duplica nada."""
    from . import salud
    from .main import app
    salud.registrar_ok("portal_invitaciones", INTERVALO_SEGUNDOS * 3, "arrancado")
    time.sleep(90)
    while True:
        try:
            with app.app_context():
                r = procesar()
            salud.registrar_ok("portal_invitaciones", INTERVALO_SEGUNDOS * 3, f"{r['enviadas']} enviadas, {r['aplazadas']} esperando su turno")
            if r["fallidas"]:
                salud.registrar_error("portal_invitaciones", INTERVALO_SEGUNDOS * 3, f"{r['fallidas']} invitaciones no se han podido enviar")
        except Exception as e:  # noqa: BLE001
            salud.registrar_error("portal_invitaciones", INTERVALO_SEGUNDOS * 3, f"{type(e).__name__}: {e}")
        time.sleep(INTERVALO_SEGUNDOS)
