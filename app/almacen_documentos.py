"""Almacén único de documentos de clientes y expedientes. TODA escritura y lectura del contenido de un documento pasa por aquí, para poder cifrarlo
con la clave del despacho sin tocar a quien lo guarda o lo lee (PLAN_MAESTRO.md §8.3: la capa única va el Día 3 y el cifrado se enchufa después).

Dos tablas, una sola puerta:
  - `documentos` (nueva): documentos de clientes del núcleo y de expedientes (cualquier módulo de negocio).
  - `cliente_documentos` (anterior): expediente documental de la ficha fiscal de la gestoría. Sus funciones `guardar_de_cliente_fiscal`, etc. delegan en
    `db` y existen para que nadie llame a `db.archivar_documento_cliente` directamente: `tests/test_almacen_documentos.py` lo vigila.

El cifrado es un `Cifrador` que se registra con `fijar_cifrador()`. Sin él (hoy) el contenido se guarda tal cual y `cifrado = 0`. El hash que se guarda es SIEMPRE
el del contenido sin cifrar, para detectar duplicados y comprobar la integridad al leer."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Protocol

from . import acceso, db, nucleo

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


def _abrir(tenant_id: int, fila, usuario_id: int | None = None, via: str = "persona", tabla: str = "documentos") -> bytes:
    if not fila["cifrado"]:
        return bytes(fila["contenido"])
    contenido = _activo().abrir(tenant_id, bytes(fila["contenido"]), fila["sobre"] or "")
    from .cifrado_despacho import canal_actual, registrar_acceso
    registrar_acceso(tenant_id, usuario_id, fila["id"], canal_actual() or via, tabla)
    if hashlib.sha256(contenido).hexdigest() != fila["hash_sha256"]:
        raise RuntimeError("El documento no coincide con su huella: se ha alterado.")
    return contenido


TABLAS_CON_CONTENIDO = ("documentos", "cliente_documentos")


def sellar_pendientes(tenant_id: int) -> int:
    """Sella con el cifrador activo lo que se guardó sin cifrar (al activar el cifrado del despacho), en las dos tablas de documentos. Devuelve cuántos."""
    cifrador = _activo()
    conn = db.get_connection()
    try:
        # Sin esto SQLite deja el contenido en claro en las páginas liberadas por el UPDATE: se pide que las sobrescriba y se vacía el WAL.
        conn.execute("PRAGMA secure_delete = ON")
        hechos = 0
        for tabla in TABLAS_CON_CONTENIDO:
            for f in conn.execute(f"SELECT id, contenido FROM {tabla} WHERE tenant_id = ? AND cifrado = 0", (tenant_id,)).fetchall():
                sellado, sobre = cifrador.sellar(tenant_id, bytes(f["contenido"]))
                if sobre:
                    conn.execute(f"UPDATE {tabla} SET contenido = ?, cifrado = 1, sobre = ? WHERE id = ?", (sellado, sobre, f["id"]))
                    hechos += 1
        conn.commit()
        if hechos:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    finally:
        conn.close()
    if hechos:
        reaplicar_nombres(tenant_id)       # los que acaban de sellarse: su nombre también, si el nivel lo pide
    return hechos


def reaplicar_nombres(tenant_id: int) -> int:
    """Pone los nombres de archivo como pide el nivel actual: sellados (columna vacía) en Medio y Estricto, en claro en Laxo. Sellar no necesita clave privada; devolverlos a claro sí."""
    nivel = _cifrado.nivel_de(tenant_id)
    if nivel is None:
        return 0
    sellar_ahora = _cifrado.nombre_cifrado_en(nivel)
    privada = None if sellar_ahora else _cifrado.privada_disponible(tenant_id)
    conn = db.get_connection()
    try:
        conn.execute("PRAGMA secure_delete = ON")
        hechos = 0
        for tabla in TABLAS_CON_CONTENIDO:
            for f in conn.execute(f"SELECT id, nombre_archivo, nombre_cifrado FROM {tabla} WHERE tenant_id = ? AND cifrado = 1", (tenant_id,)).fetchall():
                if sellar_ahora and not f["nombre_cifrado"]:
                    col, sellado = _cifrado.sellar_nombre(tenant_id, f["nombre_archivo"])
                    conn.execute(f"UPDATE {tabla} SET nombre_archivo = ?, nombre_cifrado = ? WHERE id = ?", (col, sellado, f["id"]))
                    hechos += 1
                elif not sellar_ahora and f["nombre_cifrado"]:
                    nombre = _cifrado.abrir_nombre(tenant_id, f["nombre_cifrado"], privada)
                    if nombre is None:
                        raise _cifrado.DespachoBloqueado("Hay que desbloquear los documentos para devolver sus nombres a claro.")
                    conn.execute(f"UPDATE {tabla} SET nombre_archivo = ?, nombre_cifrado = NULL WHERE id = ?", (nombre, f["id"]))
                    hechos += 1
        conn.commit()
        if hechos:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        return hechos
    finally:
        conn.close()


def resellar(tenant_id: int, abrir_antiguo, sellar_nuevo, en_la_misma_transaccion=None) -> int:
    """Re-cifra TODO el contenido cifrado del despacho: cada fila se abre con `abrir_antiguo(contenido, sobre)` y se vuelve a sellar con `sellar_nuevo(contenido)`.
    Todo en una transacción: o se cambian todas o ninguna. `en_la_misma_transaccion(conn)` se ejecuta antes de confirmar (la rotación guarda ahí la clave nueva, para que
    nunca queden documentos con una clave y la configuración con otra). Lo usa la rotación de la clave del despacho."""
    conn = db.get_connection()
    try:
        conn.execute("PRAGMA secure_delete = ON")
        hechos = 0
        for tabla in TABLAS_CON_CONTENIDO:
            for f in conn.execute(f"SELECT id, contenido, sobre, nombre_cifrado FROM {tabla} WHERE tenant_id = ? AND cifrado = 1", (tenant_id,)).fetchall():
                nuevo, sobre = sellar_nuevo(abrir_antiguo(bytes(f["contenido"]), f["sobre"]))
                nombre = f["nombre_cifrado"]
                if nombre:
                    n = json.loads(nombre)
                    nn, ns = sellar_nuevo(abrir_antiguo(base64.b64decode(n["c"]), n["s"]))
                    nombre = json.dumps({"s": ns, "c": base64.b64encode(nn).decode()})
                conn.execute(f"UPDATE {tabla} SET contenido = ?, sobre = ?, nombre_cifrado = ? WHERE id = ?", (nuevo, sobre, nombre, f["id"]))
                hechos += 1
        if en_la_misma_transaccion is not None:
            en_la_misma_transaccion(conn)
        conn.commit()
        if hechos:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        return hechos
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _nombre_de(tenant_id: int, fila, privada=None) -> str:
    """El nombre real de un documento: el de la columna o, si va sellado (Medio y Estricto), el descifrado; sin clave, un texto que lo explica."""
    n = fila["nombre_archivo"]
    if fila["nombre_cifrado"] if "nombre_cifrado" in fila.keys() else None:
        return _cifrado.abrir_nombre(tenant_id, fila["nombre_cifrado"], privada) or _cifrado.NOMBRE_PROTEGIDO
    return n


def _texto_evento(tenant_id: int, accion: str, nombre: str) -> str:
    """Texto de la línea de tiempo del expediente: con el nombre cifrado (Medio y Estricto) no se copia a un texto que queda en claro."""
    return accion if _cifrado.nombre_cifrado_en(_cifrado.nivel_de(tenant_id)) else f"{accion}: {nombre}"


def _usuario(conn, usuario_id: int):
    return conn.execute("SELECT id, tenant_id, supervisor_tenant FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()


def guardar(usuario_id: int, nombre: str, tipo_mime: str | None, contenido: bytes, *, cliente_id: int | None = None, expediente_id: int | None = None,
            categoria: str | None = None, origen: str = "subida", mensaje_correo_id: int | None = None) -> tuple[str, int | None]:
    """Guarda un documento de un cliente o de un expediente del despacho de quien lo sube. Devuelve (resultado, id): «ok», «duplicado» (id del existente),
    «vacio», «grande», «limite», «cliente» o «expediente» (no existe o no es de su despacho o no puede verlo), «destino» (no se ha dicho dónde) o «clave_privada»
    (el archivo es o contiene una clave privada o un contenedor .p12/.pfx: nunca se guardan)."""
    if cliente_id is None and expediente_id is None:
        return "destino", None
    from . import certificados
    if certificados.contiene_clave_privada(contenido):
        return "clave_privada", None
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
        if not acceso.puede_ver_cliente_nucleo(tenant_id, usuario_id, cliente_id):
            return "cliente" if expediente_id is None else "expediente", None
        repetido = conn.execute(
            "SELECT id FROM documentos WHERE tenant_id = ? AND cliente_id IS ? AND expediente_id IS ? AND hash_sha256 = ? AND papelera_en IS NULL", (tenant_id, cliente_id, expediente_id, huella)).fetchone()
        if repetido:
            return "duplicado", repetido["id"]
        if conn.execute("SELECT COUNT(*) FROM documentos WHERE tenant_id = ? AND cliente_id IS ? AND expediente_id IS ? AND papelera_en IS NULL", (tenant_id, cliente_id, expediente_id)).fetchone()[0] >= db.MAX_DOCUMENTOS_POR_CLIENTE:
            return "limite", None
        guardado, cifrado, sobre = _sellar(tenant_id, contenido)
        nombre_seguro = db._nombre_de_archivo_seguro(nombre)
        nombre_col, nombre_sellado = _cifrado.sellar_nombre(tenant_id, nombre_seguro) if cifrado else (nombre_seguro, None)
        cur = conn.execute(
            "INSERT INTO documentos (tenant_id, cliente_id, expediente_id, nombre_archivo, nombre_cifrado, tipo_mime, tamano_bytes, categoria, contenido, hash_sha256, cifrado, sobre, origen, mensaje_correo_id, subido_por, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, cliente_id, expediente_id, nombre_col, nombre_sellado, (tipo_mime or "application/octet-stream")[:100], len(contenido), (categoria or "").strip()[:60] or None,
             guardado, huella, cifrado, sobre, origen, mensaje_correo_id, usuario_id, db.now_iso()),
        )
        if expediente_id is not None:
            nucleo._evento(conn, expediente_id, "documento", _texto_evento(tenant_id, "Documento añadido", nombre_seguro), usuario_id)
        conn.commit()
        return "ok", cur.lastrowid
    finally:
        conn.close()


def _visible(conn, usuario_id: int, fila) -> bool:
    u = _usuario(conn, usuario_id)
    if fila["cliente_id"] is not None and u is not None and not acceso.puede_ver_cliente_nucleo(u["tenant_id"], usuario_id, fila["cliente_id"]):
        return False                       # el cliente es de una oficina a la que la persona no llega
    if fila["expediente_id"] is None:
        return True
    exp = conn.execute("SELECT * FROM expedientes WHERE id = ?", (fila["expediente_id"],)).fetchone()
    return (exp is not None and u is not None and nucleo.puede_ver_expediente(exp, usuario_id, bool(u["supervisor_tenant"]))
            and acceso.puede_ver_cliente_nucleo(u["tenant_id"], usuario_id, exp["cliente_id"]))


def leer(tenant_id: int, usuario_id: int, documento_id: int, via: str = "persona") -> dict | None:
    """El documento con su contenido ya descifrado, o None si no existe, no es del despacho o no puede verlo."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM documentos WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (documento_id, tenant_id)).fetchone()
        if f is None or not _visible(conn, usuario_id, f):
            return None
    finally:
        conn.close()
    d = {k: f[k] for k in f.keys() if k not in ("contenido", "sobre", "nombre_cifrado")}
    d["contenido"] = _abrir(tenant_id, f, usuario_id, via)
    d["nombre_archivo"] = _nombre_de(tenant_id, f)
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
    d = {k: f[k] for k in f.keys() if k not in ("contenido", "sobre", "nombre_cifrado")}
    d["contenido"] = _abrir(tenant_id, f, None, "enlace")
    d["nombre_archivo"] = _nombre_de(tenant_id, f)
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
            "SELECT d.id, d.cliente_id, d.expediente_id, d.nombre_archivo, d.nombre_cifrado, d.tipo_mime, d.tamano_bytes, d.categoria, d.origen, d.cifrado, d.compartido_cliente, d.subido_por, d.creado_en, "
            "COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS subido_por_nombre FROM documentos d LEFT JOIN usuarios u ON u.id = d.subido_por "
            f"LEFT JOIN usuario_perfil pf ON pf.usuario_id = d.subido_por WHERE {' AND '.join(donde)} ORDER BY d.creado_en DESC, d.id DESC LIMIT ?", [*p, max(1, min(limite, 1000))]).fetchall()
        privada = _cifrado.privada_disponible(tenant_id) if any(f["nombre_cifrado"] for f in filas) else None
        res = []
        for f in filas:
            if not _visible(conn, usuario_id, f):
                continue
            d = dict(f)
            d["nombre_archivo"] = _nombre_de(tenant_id, f, privada)
            d.pop("nombre_cifrado", None)
            res.append(d)
        return res
    finally:
        conn.close()


def compartidos_de_expediente(tenant_id: int, expediente_id: int) -> list[dict]:
    """Los documentos que el despacho enseña al cliente en su enlace de solo lectura (sin comprobar personas: el derecho lo da el enlace). Con el nombre sellado y sin clave, «Documento protegido»."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, nombre_archivo, nombre_cifrado, tamano_bytes, creado_en FROM documentos WHERE expediente_id = ? AND tenant_id = ? AND compartido_cliente = 1 AND papelera_en IS NULL ORDER BY creado_en DESC",
                             (expediente_id, tenant_id)).fetchall()
    finally:
        conn.close()
    privada = _cifrado.privada_disponible(tenant_id) if any(f["nombre_cifrado"] for f in filas) else None
    return [{"id": f["id"], "nombre_archivo": _nombre_de(tenant_id, f, privada), "tamano_bytes": f["tamano_bytes"], "creado_en": f["creado_en"]} for f in filas]


def eliminar(tenant_id: int, usuario_id: int, documento_id: int) -> bool:
    """Lo manda a la papelera quien lo subió o un responsable del despacho."""
    conn = db.get_connection()
    try:
        u = _usuario(conn, usuario_id)
        f = conn.execute("SELECT * FROM documentos WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (documento_id, tenant_id)).fetchone()
        if u is None or f is None or not _visible(conn, usuario_id, f) or not (f["subido_por"] == usuario_id or u["supervisor_tenant"]):
            return False
        if "conservar_hasta" in f.keys() and f["conservar_hasta"] and f["conservar_hasta"] > db.now_iso()[:10]:
            return False                      # política de conservación: no se manda a la papelera antes de «conservar hasta»
        conn.execute("UPDATE documentos SET papelera_en = ? WHERE id = ?", (db._marca_papelera(), documento_id))
        if f["expediente_id"] is not None:
            nucleo._evento(conn, f["expediente_id"], "documento", _texto_evento(tenant_id, "Documento eliminado", f["nombre_archivo"]), usuario_id)
        conn.commit()
        return True
    finally:
        conn.close()


# --- Expediente documental de la ficha fiscal (gestoría): misma puerta, tabla anterior --------------------------------------------------------
def guardar_de_cliente_fiscal(usuario_id: int, cliente_fiscal_id: int, nombre: str, tipo_mime: str | None, contenido: bytes, **kw) -> tuple[str, int | None]:
    from . import certificados
    if certificados.contiene_clave_privada(contenido):
        return "clave_privada", None
    return db.archivar_documento_cliente(usuario_id, cliente_fiscal_id, nombre, tipo_mime, contenido, **kw)


def guardar_de_cliente_fiscal_sin_usuario(tenant_id: int, cliente_fiscal_id: int, nombre: str, tipo_mime: str | None, contenido: bytes, categoria: str | None = None) -> tuple[str, int | None]:
    """Un documento que entrega el propio cliente desde su portal (no hay persona del despacho detrás): mismas comprobaciones, el mismo sellado con la clave del despacho y el mismo reparto en el
    expediente fiscal que `guardar_de_cliente_fiscal`. Devuelve (resultado, id): «ok», «duplicado» (id del existente), «vacio», «grande», «limite», «cliente» o «clave_privada»."""
    from . import certificados
    if certificados.contiene_clave_privada(contenido):
        return "clave_privada", None
    if not contenido:
        return "vacio", None
    if len(contenido) > db.MAX_DOCUMENTO_CLIENTE_BYTES:
        return "grande", None
    huella = hashlib.sha256(contenido).hexdigest()
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_fiscal_id, tenant_id)).fetchone() is None:
            return "cliente", None
        repetido = conn.execute("SELECT id FROM cliente_documentos WHERE cliente_fiscal_id = ? AND hash_sha256 = ?", (cliente_fiscal_id, huella)).fetchone()
        if repetido:
            return "duplicado", repetido["id"]
        if conn.execute("SELECT COUNT(*) FROM cliente_documentos WHERE cliente_fiscal_id = ?", (cliente_fiscal_id,)).fetchone()[0] >= db.MAX_DOCUMENTOS_POR_CLIENTE:
            return "limite", None
        guardado, cifrado, sobre = _sellar(tenant_id, contenido)
        seguro = db._nombre_de_archivo_seguro(nombre)
        nombre_col, nombre_sellado = _cifrado.sellar_nombre(tenant_id, seguro) if cifrado else (seguro, None)
        cur = conn.execute(
            "INSERT INTO cliente_documentos (tenant_id, cliente_fiscal_id, nombre_archivo, nombre_cifrado, tipo_mime, tamano_bytes, contenido, categoria, origen, subido_por, hash_sha256, creado_en, cifrado, sobre) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'subida', NULL, ?, ?, ?, ?)",
            (tenant_id, cliente_fiscal_id, nombre_col, nombre_sellado, (tipo_mime or "application/octet-stream")[:100], len(contenido), guardado, (categoria or "").strip()[:60] or None, huella,
             db.now_iso(), cifrado, sobre))
        conn.commit()
        return "ok", cur.lastrowid
    finally:
        conn.close()


def listar_de_cliente_fiscal(tenant_id: int, cliente_fiscal_id: int, limite: int = 300) -> list[dict]:
    filas = db.listar_documentos_cliente(tenant_id, cliente_fiscal_id, limite)
    privada = _cifrado.privada_disponible(tenant_id) if any(f.get("nombre_cifrado") for f in filas) else None
    res = []
    for f in filas:
        d = dict(f)
        d["nombre_archivo"] = _nombre_de(tenant_id, d, privada)
        d.pop("nombre_cifrado", None)
        res.append(d)
    return res


def leer_de_cliente_fiscal(tenant_id: int, cliente_fiscal_id: int, documento_id: int, usuario_id: int | None = None):
    """El documento del expediente fiscal con su contenido ya descifrado (un diccionario), o None. Lanza `DespachoBloqueado` si está cifrado y no hay clave."""
    f = db.obtener_documento_cliente(tenant_id, cliente_fiscal_id, documento_id)
    if f is None:
        return None
    d = {k: f[k] for k in f.keys() if k not in ("contenido", "sobre", "nombre_cifrado")}
    d["contenido"] = _abrir(tenant_id, f, usuario_id, "persona", "cliente_documentos")
    d["nombre_archivo"] = _nombre_de(tenant_id, f)
    return d


def datos_de_cliente_fiscal(tenant_id: int, cliente_fiscal_id: int, documento_id: int) -> dict | None:
    """Los datos del documento del expediente fiscal SIN su contenido (no se abre ni hace falta la clave): para nombrarlo, por ejemplo, al borrarlo."""
    f = db.obtener_documento_cliente(tenant_id, cliente_fiscal_id, documento_id)
    if f is None:
        return None
    d = {k: f[k] for k in f.keys() if k not in ("contenido", "sobre", "nombre_cifrado")}
    d["nombre_archivo"] = _nombre_de(tenant_id, f)
    return d


def eliminar_de_cliente_fiscal(usuario_id: int, cliente_fiscal_id: int, documento_id: int) -> bool:
    return db.eliminar_documento_cliente(usuario_id, cliente_fiscal_id, documento_id)


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM documentos WHERE tenant_id = ?", (tenant_id,))
    from . import cifrado_despacho
    cifrado_despacho.borrar_datos_de_tenant(conn, tenant_id)
    _rgpd.borrar_datos_de_tenant(conn, tenant_id)
