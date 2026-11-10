"""Documentos que se piden cada mes o cada trimestre (K6): «extracto bancario», «nóminas», «tiques de caja». El despacho lo define una vez por cliente y el portal abre solo la petición del periodo.

Cada regla genera una petición normal (app/portal_peticiones.py) el primer día de cada periodo, con el periodo anterior en el título («Extracto bancario · octubre 2026») y la fecha límite del día
elegido; el cliente la ve en su portada y recibe los avisos de siempre. Una regla no genera dos veces el mismo periodo (`ultima_generada`) y, si el cliente ya tiene demasiadas peticiones abiertas,
reintenta en la siguiente pasada en lugar de perder el periodo. Pausar una regla no borra las peticiones ya abiertas."""
from __future__ import annotations

import logging
from datetime import date

from . import db, portal_peticiones

logger = logging.getLogger("guilda")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_peticiones_recurrentes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    periodicidad TEXT NOT NULL CHECK (periodicidad IN ('mensual', 'trimestral')),
    dia_limite INTEGER NOT NULL DEFAULT 10,
    activa INTEGER NOT NULL DEFAULT 1,
    ultima_generada TEXT,
    creado_por INTEGER,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portal_pet_recurrentes ON portal_peticiones_recurrentes(tenant_id, cliente_fiscal_id);
"""

PERIODICIDADES = ("mensual", "trimestral")
MAX_REGLAS = 12                                    # por cliente
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def periodo(hoy: date, periodicidad: str) -> str:
    """La clave del periodo en curso: `2026-11` (mensual) o `2026-T4` (trimestral)."""
    return f"{hoy.year}-{hoy.month:02d}" if periodicidad == "mensual" else f"{hoy.year}-T{(hoy.month - 1) // 3 + 1}"


def periodo_anterior(hoy: date, periodicidad: str) -> str:
    """El periodo del que se piden los documentos, en palabras: «octubre 2026» o «3T 2026»."""
    if periodicidad == "mensual":
        m, a = (hoy.month - 1, hoy.year) if hoy.month > 1 else (12, hoy.year - 1)
        return f"{MESES[m - 1]} {a}"
    q, a = ((hoy.month - 1) // 3, hoy.year) if hoy.month > 3 else (4, hoy.year - 1)
    return f"{q}T {a}"


def _toca(hoy: date, periodicidad: str) -> bool:
    return periodicidad == "mensual" or hoy.month in (1, 4, 7, 10)


def crear(cliente, titulo: str, periodicidad: str, dia_limite=10, descripcion: str = "", por: int | None = None) -> int:
    """`ValueError` con un mensaje legible si el título, la periodicidad o el día no valen, o si el cliente ya tiene demasiadas reglas."""
    titulo = " ".join((titulo or "").split())[:80]
    if len(titulo) < 3:
        raise ValueError("Escribe qué documento hay que pedir (mínimo 3 caracteres).")
    if periodicidad not in PERIODICIDADES:
        raise ValueError("Elige si se pide cada mes o cada trimestre.")
    try:
        dia = int(dia_limite)
    except (TypeError, ValueError):
        raise ValueError("El día límite debe ser un número del 1 al 28.") from None
    if not 1 <= dia <= 28:
        raise ValueError("El día límite debe ser un número del 1 al 28.")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM portal_peticiones_recurrentes WHERE tenant_id = ? AND cliente_fiscal_id = ?", (cliente["tenant_id"], cliente["id"])).fetchone()[0] >= MAX_REGLAS:
            raise ValueError("Este cliente ya tiene demasiados documentos periódicos.")
        cur = conn.execute("INSERT INTO portal_peticiones_recurrentes (tenant_id, cliente_fiscal_id, titulo, descripcion, periodicidad, dia_limite, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], titulo, " ".join((descripcion or "").split())[:300], periodicidad, dia, por, db.now_iso()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar(cliente) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM portal_peticiones_recurrentes WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY id", (cliente["tenant_id"], cliente["id"]))]
    finally:
        conn.close()


def activar(cliente, regla_id: int, activa: bool) -> bool:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_peticiones_recurrentes SET activa = ? WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (1 if activa else 0, regla_id, cliente["tenant_id"], cliente["id"])).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def borrar(cliente, regla_id: int) -> bool:
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM portal_peticiones_recurrentes WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (regla_id, cliente["tenant_id"], cliente["id"])).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def _avisar(cliente, peticion_id: int, titulo: str) -> None:
    """El correo (y el aviso al móvil) de que hay un documento nuevo que subir. Nunca rompe la generación."""
    try:
        from flask_babel import gettext as _
        from . import notificaciones_email as ne, portal_avisos, portal_recordatorios
        enlace = portal_recordatorios.url_portal(f"/portal/peticiones/{peticion_id}", cliente["id"])
        if enlace and ne.configurado():
            with portal_recordatorios._en_idioma(portal_avisos._idioma(cliente)):
                portal_avisos.correo_directo(cliente, lambda e: ne.enviar_solicitud_documento(e, titulo[:120], enlace, tenant_id=cliente["tenant_id"]), accion="subir",
                                             push=(_("Tu gestoría te pide un documento"), titulo[:100], f"/portal/peticiones/{peticion_id}"))
    except Exception:  # noqa: BLE001 -- el aviso es un extra: la petición ya existe y sale en la portada del cliente
        logger.exception("No se pudo avisar de la petición periódica %s", peticion_id)


def generar(hoy: date | None = None) -> int:
    """Abre las peticiones del periodo que toca para cada regla activa que aún no lo ha hecho. Devuelve cuántas abrió."""
    hoy = hoy or date.today()
    conn = db.get_connection()
    try:
        reglas = [dict(f) for f in conn.execute("SELECT * FROM portal_peticiones_recurrentes WHERE activa = 1")]
    finally:
        conn.close()
    abiertas = 0
    for r in reglas:
        clave = periodo(hoy, r["periodicidad"])
        if r["ultima_generada"] == clave or not _toca(hoy, r["periodicidad"]):
            continue
        try:
            cliente = db.obtener_cliente_fiscal_por_id(r["cliente_fiscal_id"])
            if cliente is None or cliente["tenant_id"] != r["tenant_id"]:
                continue
            limite = date(hoy.year, hoy.month, r["dia_limite"])
            titulo = f"{r['titulo']} · {periodo_anterior(hoy, r['periodicidad'])}"
            pid = portal_peticiones.crear(cliente, titulo, r["descripcion"], limite.isoformat() if limite >= hoy else None, por=r["creado_por"])
        except ValueError:
            continue                                                                    # demasiadas abiertas: se reintenta en la siguiente pasada
        except Exception:  # noqa: BLE001 -- una regla rota no debe frenar a las demás
            logger.exception("No se pudo abrir la petición periódica %s", r["id"])
            continue
        conn = db.get_connection()
        try:
            conn.execute("UPDATE portal_peticiones_recurrentes SET ultima_generada = ? WHERE id = ? AND tenant_id = ?", (clave, r["id"], r["tenant_id"]))
            conn.commit()
        finally:
            conn.close()
        abiertas += 1
        if cliente["recordatorios_portal"] != 0:
            _avisar(cliente, pid, titulo)
    return abiertas
