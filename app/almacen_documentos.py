"""Almacén único de documentos de clientes y expedientes. TODA escritura y lectura del contenido de un documento pasa por aquí, para poder cifrarlo
con la clave del despacho sin tocar a quien lo guarda o lo lee (PLAN_MAESTRO.md §8.3: la capa única va el Día 3 y el cifrado se enchufa después).

Dos tablas, una sola puerta:
  - `documentos` (nueva): documentos de clientes del núcleo y de expedientes (cualquier módulo de negocio).
  - `cliente_documentos` (anterior): expediente documental de la ficha fiscal de la gestoría. Sus funciones `guardar_de_cliente_fiscal`, etc. delegan en
    `db` y existen para que nadie llame a `db.archivar_documento_cliente` directamente: `tests/test_almacen_documentos.py` lo vigila.

El cifrado es un `Cifrador` que se registra con `fijar_cifrador()`. Sin él (hoy) el contenido se guarda tal cual y `cifrado = 0`. El hash que se guarda es SIEMPRE
el del contenido sin cifrar, para detectar duplicados y comprobar la integridad al leer."""
from __future__ import annotations

import hashlib
from typing import Protocol

from . import db, nucleo

ORIGENES = ("subida", "correo", "portal", "generado")

from . import cifrado_despacho as _cifrado
from . import rgpd as _rgpd

ESQUEMA = _cifrado.ESQUEMA + _rgpd.ESQUEMA + """
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    cliente_id INTEGER REFERENCES clientes(id),
    expediente_id INTEGER REFERENCES expedientes(id) ON DELETE CASCADE,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    categoria TEXT,
    contenido BLOB NOT NULL,
    hash_sha256 TEXT NOT NULL,
    cifrado INTEGER NOT NULL DEFAULT 0,
    sobre TEXT,
    origen TEXT NOT NULL DEFAULT 'subida',
    mensaje_correo_id INTEGER,
    subido_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_documentos_cliente ON documentos(tenant_id, cliente_id, papelera_en);
CREATE INDEX IF NOT EXISTS idx_documentos_expediente ON documentos(expediente_id, papelera_en);
"""


class Cifrador(Protocol):
    """Lo que hay que implementar para cifrar documentos (Día 7: clave por despacho). `sellar` devuelve (bytes cifrados, sobre) y `abrir` lo revierte;
    `abrir` debe lanzar una excepción si el contenido se ha manipulado."""

    def sellar(self, tenant_id: int, contenido: bytes) -> tuple[bytes, str]: ...
    def abrir(self, tenant_id: int, contenido: bytes, sobre: str) -> bytes: ...


class _SinCifrado:
    def sellar(self, tenant_id: int, contenido: bytes) -> tuple[bytes, str]:
        return contenido, ""

    def abrir(self, tenant_id: int, contenido: bytes, sobre: str) -> bytes:
        return contenido


_cifrador: Cifrador | None = None


def fijar_cifrador(cifrador: Cifrador | None) -> None:
    global _cifrador
    _cifrador = cifrador


def _activo() -> Cifrador:
    """El cifrador registrado con `fijar_cifrador` o, por defecto, el de la clave del despacho (que no cifra si el despacho no lo ha activado)."""
    if _cifrador is not None:
        return _cifrador
    from .cifrado_despacho import CifradorDespacho
    return CifradorDespacho()


def _sellar(tenant_id: int, contenido: bytes) -> tuple[bytes, int, str | None]:
    cifrado, sobre = _activo().sellar(tenant_id, contenido)
    return (cifrado, 1, sobre) if sobre else (contenido, 0, None)


def _abrir(tenant_id: int, fila, usuario_id: int | None = None, via: str = "persona") -> bytes:
    if not fila["cifrado"]:
        return bytes(fila["contenido"])
    contenido = _activo().abrir(tenant_id, bytes(fila["contenido"]), fila["sobre"] or "")
    from .cifrado_despacho import registrar_acceso
    registrar_acceso(tenant_id, usuario_id, fila["id"], via)
    if hashlib.sha256(contenido).hexdigest() != fila["hash_sha256"]:
        raise RuntimeError("El documento no coincide con su huella: se ha alterado.")
    return contenido


def sellar_pendientes(tenant_id: int) -> int:
    """Sella con el cifrador activo los documentos que se guardaron sin cifrar (al activar el cifrado del despacho). Devuelve cuántos."""
    cifrador = _activo()
    conn = db.get_connection()
    try:
        # Sin esto SQLite deja el contenido en claro en las páginas liberadas por el UPDATE: se pide que las sobrescriba y se vacía el WAL.
        conn.execute("PRAGMA secure_delete = ON")
        filas = conn.execute("SELECT id, contenido FROM documentos WHERE tenant_id = ? AND cifrado = 0", (tenant_id,)).fetchall()
        hechos = 0
        for f in filas:
            sellado, sobre = cifrador.sellar(tenant_id, bytes(f["contenido"]))
            if sobre:
                conn.execute("UPDATE documentos SET contenido = ?, cifrado = 1, sobre = ? WHERE id = ?", (sellado, sobre, f["id"]))
                hechos += 1
        conn.commit()
        if hechos:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        return hechos
    finally:
        conn.close()


def _usuario(conn, usuario_id: int):
    return conn.execute("SELECT id, tenant_id, supervisor_tenant FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()


def guardar(usuario_id: int, nombre: str, tipo_mime: str | None, contenido: bytes, *, cliente_id: int | None = None, expediente_id: int | None = None,
            categoria: str | None = None, origen: str = "subida", mensaje_correo_id: int | None = None) -> tuple[str, int | None]:
    """Guarda un documento de un cliente o de un expediente del despacho de quien lo sube. Devuelve (resultado, id): «ok», «duplicado» (id del existente),
    «vacio», «grande», «limite», «cliente» o «expediente» (no existe o no es de su despacho o no puede verlo) o «destino» (no se ha dicho dónde)."""
    if cliente_id is None and expediente_id is None:
        return "destino", None
    if not contenido:
        return "vacio", None
    if len(contenido) > db.MAX_DOCUMENTO_CLIENTE_BYTES:
        return "grande", None
    if origen not in ORIGENES:
        origen = "subida"
    huella = hashlib.sha256(contenido).hexdigest()
    conn = db.get_connection()
    try:
        u = _usuario(conn, usuario_id)
        if u is None or u["tenant_id"] is None:
            return "cliente", None
        tenant_id = u["tenant_id"]
        if expediente_id is not None:
            exp = conn.execute("SELECT * FROM expedientes WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (expediente_id, tenant_id)).fetchone()
            if exp is None or not nucleo.puede_ver_expediente(exp, usuario_id, bool(u["supervisor_tenant"])):
                return "expediente", None
            cliente_id = cliente_id or exp["cliente_id"]
        if cliente_id is not None and conn.execute("SELECT 1 FROM clientes WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_id, tenant_id)).fetchone() is None:
            return "cliente", None
        repetido = conn.execute(
            "SELECT id FROM documentos WHERE tenant_id = ? AND cliente_id IS ? AND expediente_id IS ? AND hash_sha256 = ? AND papelera_en IS NULL", (tenant_id, cliente_id, expediente_id, huella)).fetchone()
        if repetido:
            return "duplicado", repetido["id"]
        if conn.execute("SELECT COUNT(*) FROM documentos WHERE tenant_id = ? AND cliente_id IS ? AND expediente_id IS ? AND papelera_en IS NULL", (tenant_id, cliente_id, expediente_id)).fetchone()[0] >= db.MAX_DOCUMENTOS_POR_CLIENTE:
            return "limite", None
        guardado, cifrado, sobre = _sellar(tenant_id, contenido)
        cur = conn.execute(
            "INSERT INTO documentos (tenant_id, cliente_id, expediente_id, nombre_archivo, tipo_mime, tamano_bytes, categoria, contenido, hash_sha256, cifrado, sobre, origen, mensaje_correo_id, subido_por, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, cliente_id, expediente_id, db._nombre_de_archivo_seguro(nombre), (tipo_mime or "application/octet-stream")[:100], len(contenido), (categoria or "").strip()[:60] or None,
             guardado, huella, cifrado, sobre, origen, mensaje_correo_id, usuario_id, db.now_iso()),
        )
        if expediente_id is not None:
            nucleo._evento(conn, expediente_id, "documento", f"Documento añadido: {db._nombre_de_archivo_seguro(nombre)}", usuario_id)
        conn.commit()
        return "ok", cur.lastrowid
    finally:
        conn.close()


def _visible(conn, usuario_id: int, fila) -> bool:
    if fila["expediente_id"] is None:
        return True
    u = _usuario(conn, usuario_id)
    exp = conn.execute("SELECT * FROM expedientes WHERE id = ?", (fila["expediente_id"],)).fetchone()
    return exp is not None and u is not None and nucleo.puede_ver_expediente(exp, usuario_id, bool(u["supervisor_tenant"]))


def leer(tenant_id: int, usuario_id: int, documento_id: int, via: str = "persona") -> dict | None:
    """El documento con su contenido ya descifrado, o None si no existe, no es del despacho o no puede verlo."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM documentos WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (documento_id, tenant_id)).fetchone()
        if f is None or not _visible(conn, usuario_id, f):
            return None
    finally:
        conn.close()
    d = {k: f[k] for k in f.keys() if k not in ("contenido", "sobre")}
    d["contenido"] = _abrir(tenant_id, f, usuario_id, via)
    return d


def leer_sin_usuario(tenant_id: int, documento_id: int) -> dict | None:
    """Lectura SIN comprobar permisos de persona: solo para quien ya ha comprobado el derecho de acceso por otra vía (el enlace de solo lectura de un cliente).
    No usar en ninguna ruta que dependa de la sesión de una persona."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM documentos WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (documento_id, tenant_id)).fetchone()
    finally:
        conn.close()
    if f is None:
        return None
    d = {k: f[k] for k in f.keys() if k not in ("contenido", "sobre")}
    d["contenido"] = _abrir(tenant_id, f, None, "enlace")
    return d


def listar(tenant_id: int, usuario_id: int, *, cliente_id: int | None = None, expediente_id: int | None = None, limite: int = 300) -> list[dict]:
    """Metadatos (sin contenido) de los documentos de un cliente o de un expediente que la persona puede ver."""
    donde, p = ["d.tenant_id = ?", "d.papelera_en IS NULL"], [tenant_id]
    if expediente_id is not None:
        donde.append("d.expediente_id = ?"); p.append(expediente_id)
    elif cliente_id is not None:
        donde.append("d.cliente_id = ?"); p.append(cliente_id)
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT d.id, d.cliente_id, d.expediente_id, d.nombre_archivo, d.tipo_mime, d.tamano_bytes, d.categoria, d.origen, d.cifrado, d.compartido_cliente, d.subido_por, d.creado_en, "
            "COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS subido_por_nombre FROM documentos d LEFT JOIN usuarios u ON u.id = d.subido_por "
            f"LEFT JOIN usuario_perfil pf ON pf.usuario_id = d.subido_por WHERE {' AND '.join(donde)} ORDER BY d.creado_en DESC, d.id DESC LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
        return [dict(f) for f in filas if _visible(conn, usuario_id, f)]
    finally:
        conn.close()


def eliminar(tenant_id: int, usuario_id: int, documento_id: int) -> bool:
    """Lo manda a la papelera quien lo subió o un responsable del despacho."""
    conn = db.get_connection()
    try:
        u = _usuario(conn, usuario_id)
        f = conn.execute("SELECT * FROM documentos WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (documento_id, tenant_id)).fetchone()
        if u is None or f is None or not _visible(conn, usuario_id, f) or not (f["subido_por"] == usuario_id or u["supervisor_tenant"]):
            return False
        conn.execute("UPDATE documentos SET papelera_en = ? WHERE id = ?", (db._marca_papelera(), documento_id))
        if f["expediente_id"] is not None:
            nucleo._evento(conn, f["expediente_id"], "documento", f"Documento eliminado: {f['nombre_archivo']}", usuario_id)
        conn.commit()
        return True
    finally:
        conn.close()


# --- Expediente documental de la ficha fiscal (gestoría): misma puerta, tabla anterior --------------------------------------------------------
def guardar_de_cliente_fiscal(usuario_id: int, cliente_fiscal_id: int, nombre: str, tipo_mime: str | None, contenido: bytes, **kw) -> tuple[str, int | None]:
    return db.archivar_documento_cliente(usuario_id, cliente_fiscal_id, nombre, tipo_mime, contenido, **kw)


def listar_de_cliente_fiscal(tenant_id: int, cliente_fiscal_id: int, limite: int = 300) -> list[dict]:
    return db.listar_documentos_cliente(tenant_id, cliente_fiscal_id, limite)


def leer_de_cliente_fiscal(tenant_id: int, cliente_fiscal_id: int, documento_id: int):
    return db.obtener_documento_cliente(tenant_id, cliente_fiscal_id, documento_id)


def eliminar_de_cliente_fiscal(usuario_id: int, cliente_fiscal_id: int, documento_id: int) -> bool:
    return db.eliminar_documento_cliente(usuario_id, cliente_fiscal_id, documento_id)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM documentos WHERE tenant_id = ?", (tenant_id,))
    from . import cifrado_despacho
    cifrado_despacho.borrar_datos_de_tenant(conn, tenant_id)
    _rgpd.borrar_datos_de_tenant(conn, tenant_id)
