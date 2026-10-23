"""Libreta de contactos compartida del despacho: personas con nombre, correo y teléfono que no son (todavía) clientes, o que son contacto de uno.

Es del **despacho** (todo el equipo la ve y la usa) y alimenta el autocompletado de Correo junto a los clientes y sus contactos, que no se copian: se buscan donde viven. Un contacto puede
enlazarse a un cliente; entonces solo lo ven quienes ven a ese cliente (oficinas, app/acceso.py), se incluye en la exportación RGPD del cliente y su borrado va a la papelera, que se vacía con
el resto (app/rgpd.py). Los **grupos** («Proveedores», «Junta») sirven para escribir a varias personas de golpe: en el redactor, el grupo sale como una sola sugerencia con todas sus direcciones.

Los trabajadores de los clientes (app/laboral.py) no tienen correo guardado a propósito —son datos personales de terceros—, así que no entran aquí."""
from __future__ import annotations

import re
import sqlite3
from email.utils import getaddresses

from .bd.errores import ErrorIntegridad
from . import acceso, db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS contactos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    email TEXT,
    telefono TEXT,
    empresa TEXT,
    notas TEXT,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
    creado_por INTEGER,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT,
    papelera_en TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_contactos_email ON contactos(tenant_id, LOWER(email)) WHERE email IS NOT NULL AND papelera_en IS NULL;
CREATE INDEX IF NOT EXISTS idx_contactos_tenant ON contactos(tenant_id, papelera_en, nombre);
CREATE TABLE IF NOT EXISTS contacto_grupos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_contacto_grupos_nombre ON contacto_grupos(tenant_id, LOWER(nombre));
CREATE TABLE IF NOT EXISTS contacto_grupo_miembros (
    grupo_id INTEGER NOT NULL REFERENCES contacto_grupos(id) ON DELETE CASCADE,
    contacto_id INTEGER NOT NULL REFERENCES contactos(id) ON DELETE CASCADE,
    PRIMARY KEY (grupo_id, contacto_id)
);
"""
_EMAIL = re.compile(r"[^@\s<>\",;]+@[^@\s<>\",;]+\.[^@\s<>\",;]+")


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)


def _texto(v, maximo: int) -> str | None:
    return " ".join((v or "").split())[:maximo] or None


def _limpiar(datos: dict) -> dict:
    res: dict = {}
    if "nombre" in datos:
        res["nombre"] = _texto(datos["nombre"], 150)
        if not res["nombre"]:
            raise ValueError("Indica el nombre del contacto.")
    if "email" in datos:
        email = (datos["email"] or "").strip().lower()
        if email and not _EMAIL.fullmatch(email):
            raise ValueError("El correo no es válido.")
        res["email"] = email or None
    if "telefono" in datos:
        res["telefono"] = _texto(datos["telefono"], 40)
    if "empresa" in datos:
        res["empresa"] = _texto(datos["empresa"], 150)
    if "notas" in datos:
        res["notas"] = (datos["notas"] or "").strip()[:2000] or None
    return res


def _cliente_valido(conn, tenant_id: int, usuario_id: int, cliente_id) -> int | None:
    if not cliente_id:
        return None
    if conn.execute("SELECT 1 FROM clientes WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_id, tenant_id)).fetchone() is None or not acceso.puede_ver_cliente_nucleo(tenant_id, usuario_id, cliente_id):
        raise ValueError("Cliente no encontrado.")
    return int(cliente_id)


def _visible(tenant_id: int, usuario_id: int, columna: str = "ct.cliente_id") -> tuple[str, list]:
    """Condición SQL (con `AND` inicial) para no enseñar los contactos de clientes que la persona no ve."""
    sql, params = acceso.condicion_nucleo(tenant_id, usuario_id, columna)
    return (f" AND ({columna} IS NULL OR {sql})", params) if sql else ("", [])


def crear(tenant_id: int, usuario_id: int, **datos) -> int:
    campos = _limpiar({"nombre": datos.get("nombre"), **{k: datos.get(k) for k in ("email", "telefono", "empresa", "notas")}})
    conn = db.get_connection()
    try:
        cliente_id = _cliente_valido(conn, tenant_id, usuario_id, datos.get("cliente_id"))
        try:
            cur = conn.execute("INSERT INTO contactos (tenant_id, nombre, email, telefono, empresa, notas, cliente_id, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (tenant_id, campos["nombre"], campos["email"], campos["telefono"], campos["empresa"], campos["notas"], cliente_id, usuario_id, db.now_iso()))
        except ErrorIntegridad:
            raise ValueError("Ya hay un contacto con ese correo.") from None
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener(tenant_id: int, usuario_id: int, contacto_id: int):
    extra, pe = _visible(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        return conn.execute(f"SELECT ct.* FROM contactos ct WHERE ct.id = ? AND ct.tenant_id = ? AND ct.papelera_en IS NULL{extra}", (contacto_id, tenant_id, *pe)).fetchone()
    finally:
        conn.close()


def editar(tenant_id: int, usuario_id: int, contacto_id: int, **datos) -> None:
    if obtener(tenant_id, usuario_id, contacto_id) is None:
        raise ValueError("Contacto no encontrado.")
    campos = _limpiar({k: datos[k] for k in ("nombre", "email", "telefono", "empresa", "notas") if k in datos})
    conn = db.get_connection()
    try:
        if "cliente_id" in datos:
            campos["cliente_id"] = _cliente_valido(conn, tenant_id, usuario_id, datos["cliente_id"])
        if not campos:
            return
        try:
            conn.execute(f"UPDATE contactos SET {', '.join(f'{c} = ?' for c in campos)}, actualizado_en = ? WHERE id = ? AND tenant_id = ?", (*campos.values(), db.now_iso(), contacto_id, tenant_id))
        except ErrorIntegridad:
            raise ValueError("Ya hay un contacto con ese correo.") from None
        conn.commit()
    finally:
        conn.close()


def eliminar(tenant_id: int, usuario_id: int, contacto_id: int) -> bool:
    """A la papelera (se vacía con el resto, app/rgpd.py); sale de sus grupos."""
    if obtener(tenant_id, usuario_id, contacto_id) is None:
        return False
    conn = db.get_connection()
    try:
        conn.execute("UPDATE contactos SET papelera_en = ? WHERE id = ? AND tenant_id = ?", (db._marca_papelera(), contacto_id, tenant_id))
        conn.execute("DELETE FROM contacto_grupo_miembros WHERE contacto_id = ?", (contacto_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def listar(tenant_id: int, usuario_id: int, q: str | None = None, grupo_id: int | None = None, limite: int = 300) -> list[dict]:
    extra, pe = _visible(tenant_id, usuario_id)
    cond, params = ["ct.tenant_id = ?", "ct.papelera_en IS NULL"], [tenant_id]
    if q and q.strip():
        patron = f"%{q.strip().lower()}%"
        cond.append("(LOWER(ct.nombre) LIKE ? OR LOWER(COALESCE(ct.email, '')) LIKE ? OR LOWER(COALESCE(ct.empresa, '')) LIKE ?)")
        params += [patron, patron, patron]
    if grupo_id:
        cond.append("ct.id IN (SELECT contacto_id FROM contacto_grupo_miembros WHERE grupo_id = ?)")
        params.append(grupo_id)
    conn = db.get_connection()
    try:
        filas = conn.execute(f"SELECT ct.*, c.nombre AS cliente_nombre FROM contactos ct LEFT JOIN clientes c ON c.id = ct.cliente_id WHERE {' AND '.join(cond)}{extra} ORDER BY LOWER(ct.nombre) LIMIT ?",
                             (*params, *pe, limite)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


# --- Grupos ----------------------------------------------------------------------------------------------------------------------------------------

def crear_grupo(tenant_id: int, nombre: str) -> int:
    nombre = _texto(nombre, 80)
    if not nombre:
        raise ValueError("Indica el nombre del grupo.")
    conn = db.get_connection()
    try:
        try:
            cur = conn.execute("INSERT INTO contacto_grupos (tenant_id, nombre, creado_en) VALUES (?, ?, ?)", (tenant_id, nombre, db.now_iso()))
        except ErrorIntegridad:
            raise ValueError("Ya hay un grupo con ese nombre.") from None
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def eliminar_grupo(tenant_id: int, grupo_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM contacto_grupos WHERE id = ? AND tenant_id = ?", (grupo_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def listar_grupos(tenant_id: int, usuario_id: int) -> list[dict]:
    extra, pe = _visible(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filas = conn.execute(
            f"""SELECT g.id, g.nombre, (SELECT COUNT(*) FROM contacto_grupo_miembros m JOIN contactos ct ON ct.id = m.contacto_id
                                         WHERE m.grupo_id = g.id AND ct.papelera_en IS NULL{extra}) AS n
                FROM contacto_grupos g WHERE g.tenant_id = ? ORDER BY LOWER(g.nombre)""", (*pe, tenant_id)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]


def _grupo_del_despacho(conn, tenant_id: int, grupo_id: int) -> None:
    if conn.execute("SELECT 1 FROM contacto_grupos WHERE id = ? AND tenant_id = ?", (grupo_id, tenant_id)).fetchone() is None:
        raise ValueError("Grupo no encontrado.")


def poner_en_grupo(tenant_id: int, usuario_id: int, grupo_id: int, contacto_id: int, dentro: bool = True) -> None:
    if obtener(tenant_id, usuario_id, contacto_id) is None:
        raise ValueError("Contacto no encontrado.")
    conn = db.get_connection()
    try:
        _grupo_del_despacho(conn, tenant_id, grupo_id)
        if dentro:
            conn.execute("INSERT INTO contacto_grupo_miembros (grupo_id, contacto_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (grupo_id, contacto_id))
        else:
            conn.execute("DELETE FROM contacto_grupo_miembros WHERE grupo_id = ? AND contacto_id = ?", (grupo_id, contacto_id))
        conn.commit()
    finally:
        conn.close()


def grupos_de(tenant_id: int, contacto_id: int) -> list[int]:
    conn = db.get_connection()
    try:
        return [f["grupo_id"] for f in conn.execute("SELECT m.grupo_id FROM contacto_grupo_miembros m JOIN contacto_grupos g ON g.id = m.grupo_id WHERE m.contacto_id = ? AND g.tenant_id = ?", (contacto_id, tenant_id))]
    finally:
        conn.close()


# --- Uso desde Correo ----------------------------------------------------------------------------------------------------------------------------

def sugerencias(tenant_id: int, usuario_id: int, q: str, limite: int = 8) -> list[dict]:
    """Para el autocompletado de Correo: contactos con correo que coinciden con `q`, y los grupos cuyo nombre coincide (un grupo es una sola sugerencia con todas las direcciones de sus miembros)."""
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    res = [{"direccion": c["email"], "nombre_mostrado": c["nombre"] + (f" ({c['empresa']})" if c["empresa"] else "")} for c in listar(tenant_id, usuario_id, q, limite=limite) if c["email"]]
    extra, pe = _visible(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        for g in conn.execute("SELECT id, nombre FROM contacto_grupos WHERE tenant_id = ? AND LOWER(nombre) LIKE ? ORDER BY LOWER(nombre) LIMIT 3", (tenant_id, f"%{q}%")).fetchall():
            correos = [f["email"] for f in conn.execute(
                f"SELECT ct.email FROM contacto_grupo_miembros m JOIN contactos ct ON ct.id = m.contacto_id WHERE m.grupo_id = ? AND ct.papelera_en IS NULL AND ct.email IS NOT NULL{extra} ORDER BY LOWER(ct.nombre)",
                (g["id"], *pe))]
            if correos:
                res.insert(0, {"direccion": ", ".join(correos), "nombre_mostrado": f"Grupo: {g['nombre']} ({len(correos)})"})
    finally:
        conn.close()
    return res[:limite]


def guardar_desde_correo(tenant_id: int, usuario_id: int, remitente_crudo: str | None) -> int:
    """Guarda en la libreta a quien envía un correo (nombre y dirección de la cabecera From). Si ya está, devuelve su id sin duplicarlo. `ValueError` si no hay una dirección válida."""
    nombre, direccion = (getaddresses([remitente_crudo or ""]) or [("", "")])[0]
    direccion = direccion.strip().lower()
    if not _EMAIL.fullmatch(direccion):
        raise ValueError("Este mensaje no tiene una dirección de remitente válida.")
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id FROM contactos WHERE tenant_id = ? AND LOWER(email) = ? AND papelera_en IS NULL", (tenant_id, direccion)).fetchone()
    finally:
        conn.close()
    if f is not None:
        return f["id"]
    return crear(tenant_id, usuario_id, nombre=nombre.strip() or direccion.split("@")[0], email=direccion)


def exportar_de_cliente(tenant_id: int, cliente_id: int) -> list[dict]:
    """Los contactos de la libreta enlazados a un cliente, para su exportación RGPD."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT nombre, email, telefono, empresa, notas, creado_en FROM contactos WHERE tenant_id = ? AND cliente_id = ? AND papelera_en IS NULL ORDER BY nombre", (tenant_id, cliente_id)).fetchall()
    finally:
        conn.close()
    return [dict(f) for f in filas]
