"""Enlaces temporales para compartir un documento de la carpeta con un tercero (el banco, un proveedor, un asesor) sin darle acceso al portal.

Solo se pueden compartir documentos que ya están en la carpeta del cliente (justificantes y constancias) y solo lo hace una persona con perfil completo. El enlace lleva un secreto largo que nunca se guarda en claro (solo su
huella SHA-256), caduca a las 24 horas, a los 7 o a los 30 días, tiene un tope de descargas y se puede anular en cualquier momento. Abrir el enlace enseña una página con el nombre del documento y un botón: la descarga
se cuenta al pulsarlo, no al abrir (así un antivirus o la vista previa de un chat no gastan las descargas). Cada descarga queda anotada en el registro del despacho."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from . import db, portal_carpeta

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_enlaces_compartidos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    vencimiento_id INTEGER NOT NULL,
    documento_id INTEGER NOT NULL,
    huella TEXT NOT NULL,
    creado_por TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL,
    caduca_en TEXT NOT NULL,
    max_descargas INTEGER NOT NULL DEFAULT 5,
    descargas INTEGER NOT NULL DEFAULT 0,
    ultima_descarga TEXT,
    anulado_en TEXT,
    UNIQUE (tenant_id, huella)
);
CREATE INDEX IF NOT EXISTS idx_portal_enlaces_compartidos_huella ON portal_enlaces_compartidos(huella);
CREATE INDEX IF NOT EXISTS idx_portal_enlaces_compartidos_cliente ON portal_enlaces_compartidos(tenant_id, cliente_fiscal_id, creado_en);
"""

DURACIONES = {"1": 1, "7": 7, "30": 30}              # días
MAX_DESCARGAS = (1, 5, 20)
MAX_ACTIVOS = 20


class ErrorEnlace(ValueError):
    """Mensaje legible para quien crea el enlace."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _huella(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ahora(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now()).isoformat(timespec="seconds")


def crear(cliente, vencimiento_id: int, documento_id: int, dias: str, max_descargas: int, quien: str, ahora: datetime | None = None) -> str:
    """Crea el enlace y devuelve el SECRETO (solo se ve una vez). `ErrorEnlace` si el documento no se puede compartir o hay demasiados enlaces activos."""
    if dias not in DURACIONES or max_descargas not in MAX_DESCARGAS:
        raise ErrorEnlace("Elige cuánto tiempo y cuántas descargas.")
    anios = portal_carpeta.anios_disponibles(cliente)
    documento = next((d for a in anios for d in portal_carpeta.contenido(cliente, a)["documentos"] if d["id"] == documento_id and d["vencimiento_id"] == vencimiento_id), None)
    if documento is None:
        raise ErrorEnlace("Ese documento no se puede compartir.")
    if len(activos(cliente, ahora)) >= MAX_ACTIVOS:
        raise ErrorEnlace("Ya tienes muchos enlaces activos: anula alguno antes de crear otro.")
    token = secrets.token_urlsafe(32)
    ahora_dt = ahora or datetime.now()
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO portal_enlaces_compartidos (tenant_id, cliente_fiscal_id, vencimiento_id, documento_id, huella, creado_por, creado_en, caduca_en, max_descargas) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (cliente["tenant_id"], cliente["id"], vencimiento_id, documento_id, _huella(token), (quien or "")[:120], _ahora(ahora_dt), _ahora(ahora_dt + timedelta(days=DURACIONES[dias])), max_descargas))
        conn.commit()
    finally:
        conn.close()
    return token


def activos(cliente, ahora: datetime | None = None) -> list[dict]:
    """Los enlaces vigentes de este cliente (sin anular, sin caducar y con descargas por gastar), con el nombre del documento."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT e.id, e.vencimiento_id, e.documento_id, e.creado_por, e.creado_en, e.caduca_en, e.max_descargas, e.descargas, e.ultima_descarga, d.nombre_archivo FROM portal_enlaces_compartidos e "
                             "LEFT JOIN vencimientos_fiscales_documentos d ON d.id = e.documento_id WHERE e.tenant_id = ? AND e.cliente_fiscal_id = ? AND e.anulado_en IS NULL AND e.caduca_en > ? AND e.descargas < e.max_descargas "
                             "ORDER BY e.id DESC", (cliente["tenant_id"], cliente["id"], _ahora(ahora))).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def anular(cliente, enlace_id: int, ahora: datetime | None = None) -> bool:
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_enlaces_compartidos SET anulado_en = ? WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND anulado_en IS NULL", (_ahora(ahora), enlace_id, cliente["tenant_id"], cliente["id"])).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def _buscar(token: str, ahora: datetime | None = None):
    """La fila vigente de ese secreto o None (no existe, caducó, se anuló o gastó sus descargas): quien lo abre no puede distinguir los casos."""
    if not token or len(token) > 100:
        return None
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM portal_enlaces_compartidos WHERE huella = ? AND anulado_en IS NULL AND caduca_en > ? AND descargas < max_descargas", (_huella(token), _ahora(ahora))).fetchone()
    finally:
        conn.close()


def ver(token: str, ahora: datetime | None = None) -> dict | None:
    """{nombre, cliente, caduca_en, quedan} para la página pública, sin contar ninguna descarga."""
    f = _buscar(token, ahora)
    if f is None:
        return None
    documento = db.obtener_documento_vencimiento(f["documento_id"])
    cliente = db.obtener_cliente_fiscal_por_id(f["cliente_fiscal_id"])
    if documento is None or cliente is None:
        return None
    return {"nombre": documento["nombre_archivo"], "cliente": cliente["nombre"], "caduca_en": f["caduca_en"], "quedan": f["max_descargas"] - f["descargas"]}


def descargar(token: str, ahora: datetime | None = None) -> tuple[bytes, str, str] | None:
    """(contenido, tipo MIME, nombre) y cuenta una descarga; None si el enlace ya no vale. La cuenta se hace con una sola sentencia para que dos descargas a la vez no se salten el tope."""
    f = _buscar(token, ahora)
    if f is None:
        return None
    documento = db.obtener_documento_vencimiento(f["documento_id"])
    if documento is None or documento["vencimiento_id"] != f["vencimiento_id"]:
        return None
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_enlaces_compartidos SET descargas = descargas + 1, ultima_descarga = ? WHERE id = ? AND tenant_id = ? AND anulado_en IS NULL AND descargas < max_descargas",
                         (_ahora(ahora), f["id"], f["tenant_id"])).rowcount
        conn.commit()
    finally:
        conn.close()
    if not n:
        return None
    try:
        contenido = db.contenido_documento_vencimiento(documento)
    except Exception:  # noqa: BLE001 -- almacenamiento externo caído: se devuelve la descarga al enlace
        conn = db.get_connection()
        try:
            conn.execute("UPDATE portal_enlaces_compartidos SET descargas = descargas - 1 WHERE id = ? AND tenant_id = ?", (f["id"], f["tenant_id"]))
            conn.commit()
        finally:
            conn.close()
        return None
    from . import auditoria
    auditoria.registrar(f["tenant_id"], None, "portal.enlace_compartido_descargado", "cliente_fiscal", f["cliente_fiscal_id"], {"enlace": f["id"], "documento": f["documento_id"]})
    return bytes(contenido), documento["tipo_mime"], documento["nombre_archivo"]
