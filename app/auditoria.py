"""Auditoría unificada de la gestión fiscal (especificación de control fiscal, §10 y §14): una sola tabla de eventos, **solo de anexado** para la aplicación.

- `registrar()` añade un evento (quién, qué, sobre qué, con qué detalle y con qué identificador de petición). Si se le pasa la conexión de la operación, el evento se
  guarda en la **misma transacción** que el cambio auditado: o ocurren los dos o ninguno.
- Dos disparadores de SQLite impiden `UPDATE` y `DELETE` sobre la tabla desde la aplicación. La única excepción es `purgar_tenant()`, que se usa al borrar un despacho entero
  (derecho de supresión) y que queda anotada en el propio registro del sistema. **No es inmutabilidad criptográfica**: quien administre la base de datos puede quitar
  los disparadores. Para eso están las copias separadas (Restic) y los controles de acceso al servidor.
- No guarda contenido de documentos ni secretos: solo identificadores, estados y motivos."""
from __future__ import annotations

import json
from datetime import datetime

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS auditoria_eventos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    usuario_id INTEGER,
    accion TEXT NOT NULL,
    entidad TEXT NOT NULL,
    entidad_id TEXT,
    detalle TEXT,
    correlacion TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auditoria_tenant ON auditoria_eventos(tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON auditoria_eventos(tenant_id, entidad, entidad_id, id);
CREATE TABLE IF NOT EXISTS auditoria_control (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TRIGGER IF NOT EXISTS auditoria_sin_modificar BEFORE UPDATE ON auditoria_eventos
BEGIN SELECT RAISE(ABORT, 'La auditoría es solo de anexado: no se puede modificar.'); END;
CREATE TRIGGER IF NOT EXISTS auditoria_sin_borrar BEFORE DELETE ON auditoria_eventos
WHEN COALESCE((SELECT valor FROM auditoria_control WHERE clave = 'permitir_borrado'), '0') != '1'
BEGIN SELECT RAISE(ABORT, 'La auditoría es solo de anexado: no se puede borrar.'); END;
"""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _correlacion() -> str | None:
    try:
        from . import peticion
        return peticion.id_actual()
    except Exception:  # noqa: BLE001
        return None


def registrar(tenant_id: int | None, usuario_id: int | None, accion: str, entidad: str, entidad_id=None, detalle: dict | str | None = None, *, conn=None) -> int | None:
    """Anota un evento. Con `conn` usa esa conexión (y NO hace commit: lo hará quien la abrió, junto al cambio auditado); sin ella abre la suya y confirma.
    Una auditoría que falla no debe tirar la operación de fondo cuando va por su cuenta, pero en la misma transacción propaga el error: así no hay cambios sin rastro."""
    texto = json.dumps(detalle, ensure_ascii=False, default=str) if isinstance(detalle, (dict, list)) else detalle
    datos = (tenant_id, usuario_id, accion[:80], entidad[:60], str(entidad_id) if entidad_id is not None else None, (texto or None) and texto[:2000], _correlacion(), datetime.now().isoformat(timespec="seconds"))
    sql = "INSERT INTO auditoria_eventos (tenant_id, usuario_id, accion, entidad, entidad_id, detalle, correlacion, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    if conn is not None:
        return conn.execute(sql, datos).lastrowid
    propia = db.get_connection()
    try:
        cur = propia.execute(sql, datos)
        propia.commit()
        return cur.lastrowid
    except Exception:  # noqa: BLE001
        return None
    finally:
        propia.close()


def listar(tenant_id: int, *, entidad: str | None = None, entidad_id=None, usuario_id: int | None = None, accion: str | None = None, desde: str | None = None, hasta: str | None = None,
           antes_de_id: int | None = None, limite: int = 100) -> list[dict]:
    """Eventos del despacho, los más recientes primero. Paginación por cursor: pasa el `id` del último recibido en `antes_de_id`."""
    donde, p = ["a.tenant_id = ?"], [tenant_id]
    for col, val in (("a.entidad", entidad), ("a.entidad_id", str(entidad_id) if entidad_id is not None else None), ("a.usuario_id", usuario_id), ("a.accion", accion)):
        if val is not None and val != "":
            donde.append(f"{col} = ?"); p.append(val)
    if desde:
        donde.append("a.creado_en >= ?"); p.append(desde[:10])
    if hasta:
        donde.append("substr(a.creado_en, 1, 10) <= ?"); p.append(hasta[:10])
    if antes_de_id:
        donde.append("a.id < ?"); p.append(antes_de_id)
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT a.*, COALESCE(NULLIF(pr.nombre_mostrado, ''), u.email) AS actor FROM auditoria_eventos a LEFT JOIN usuarios u ON u.id = a.usuario_id "
            f"LEFT JOIN usuario_perfil pr ON pr.usuario_id = a.usuario_id WHERE {' AND '.join(donde)} ORDER BY a.id DESC LIMIT ?", [*p, max(1, min(limite, 500))]).fetchall()
    finally:
        conn.close()
    res = []
    for f in filas:
        d = dict(f)
        try:
            d["detalle"] = json.loads(d["detalle"]) if d["detalle"] and d["detalle"][:1] in "{[" else d["detalle"]
        except ValueError:
            pass
        res.append(d)
    return res


def purgar_tenant(conn, tenant_id: int) -> int:
    """Borra los eventos de un despacho que se elimina por completo (la única puerta). Se llama dentro de la transacción de `borrar_tenant`; el permiso solo
    existe durante ella: si la transacción se deshace, el permiso también."""
    conn.execute("INSERT INTO auditoria_control (clave, valor) VALUES ('permitir_borrado', '1') ON CONFLICT(clave) DO UPDATE SET valor = '1'")
    try:
        n = conn.execute("DELETE FROM auditoria_eventos WHERE tenant_id = ?", (tenant_id,)).rowcount
    finally:
        conn.execute("UPDATE auditoria_control SET valor = '0' WHERE clave = 'permitir_borrado'")
    return n
