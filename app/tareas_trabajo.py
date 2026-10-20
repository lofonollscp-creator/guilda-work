"""Cimientos del trabajo con tareas (Fase 1 de docs/guilda-work-implementation-plan.md), todo aditivo sobre `tareas_outlook`.

- **Versión** (`tareas_outlook.version`): un disparador de SQLite la sube en *cada* UPDATE de la tarea, venga de la web, la API, el MCP o la app móvil, sin tocar
  esos escritores. Quien quiera concurrencia optimista llama a `reclamar_version()` antes de escribir: si la versión ya no es la que leyó, hay conflicto (409).
  Quien no manda versión se comporta como siempre.
- **Motivo de bloqueo** (`tareas_outlook.motivo_bloqueo`): «Esperando» pasa a ser «Bloqueada» cuando la persona dice por qué.
- **Varios clientes por tarea** (`tarea_clientes`): un único principal por tarea (índice parcial único). `tareas_outlook.cliente_fiscal_id` sigue siendo el principal,
  así nada de lo existente se rompe. Tarea y cliente tienen que ser del mismo despacho.
- **Vencida** es siempre derivada (`esta_vencida`), nunca un estado guardado."""
from __future__ import annotations

import sqlite3
from datetime import date

from . import auditoria, db

ESTADOS = ("no_iniciada", "en_progreso", "completada", "esperando", "aplazada")
ESTADOS_CERRADOS = ("completada",)
MAX_CLIENTES_POR_TAREA = 50

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tarea_clientes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id),
    principal INTEGER NOT NULL DEFAULT 0 CHECK (principal IN (0, 1)),
    creado_en TEXT NOT NULL,
    UNIQUE (tarea_id, cliente_fiscal_id)
);
CREATE INDEX IF NOT EXISTS idx_tarea_clientes_cliente ON tarea_clientes(tenant_id, cliente_fiscal_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tarea_clientes_principal ON tarea_clientes(tarea_id) WHERE principal = 1;
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_cliente ON tareas_outlook(cliente_fiscal_id);
CREATE INDEX IF NOT EXISTS idx_tareas_outlook_padre ON tareas_outlook(tarea_padre_id);
CREATE TABLE IF NOT EXISTS tarea_adjuntos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    contenido BLOB NOT NULL,
    hash_sha256 TEXT NOT NULL,
    subido_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    papelera_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_tarea_adjuntos_tarea ON tarea_adjuntos(tarea_id);
CREATE TABLE IF NOT EXISTS tarea_revisiones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER,
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    solicitada_por INTEGER NOT NULL REFERENCES usuarios(id),
    revisor_id INTEGER NOT NULL REFERENCES usuarios(id),
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobada', 'cambios', 'cancelada')),
    nota_solicitud TEXT,
    nota_resolucion TEXT,
    solicitada_en TEXT NOT NULL,
    resuelta_en TEXT,
    resuelta_por INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS idx_tarea_revisiones_tarea ON tarea_revisiones(tarea_id);
CREATE INDEX IF NOT EXISTS idx_tarea_revisiones_revisor ON tarea_revisiones(revisor_id, estado);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tarea_revisiones_una_pendiente ON tarea_revisiones(tarea_id) WHERE estado = 'pendiente';
CREATE TRIGGER IF NOT EXISTS tareas_outlook_version AFTER UPDATE ON tareas_outlook
WHEN NEW.version = OLD.version
BEGIN UPDATE tareas_outlook SET version = OLD.version + 1 WHERE id = NEW.id; END;
CREATE TRIGGER IF NOT EXISTS tareas_outlook_cliente_alta AFTER INSERT ON tareas_outlook
WHEN NEW.cliente_fiscal_id IS NOT NULL
BEGIN
  INSERT OR IGNORE INTO tarea_clientes (tenant_id, tarea_id, cliente_fiscal_id, principal, creado_en)
  SELECT tenant_id, NEW.id, id, 1, NEW.creada_en FROM clientes_fiscales WHERE id = NEW.cliente_fiscal_id;
END;
CREATE TRIGGER IF NOT EXISTS tareas_outlook_cliente_cambio AFTER UPDATE OF cliente_fiscal_id ON tareas_outlook
WHEN NEW.cliente_fiscal_id IS NOT OLD.cliente_fiscal_id
BEGIN
  DELETE FROM tarea_clientes WHERE tarea_id = NEW.id AND principal = 1 AND cliente_fiscal_id IS OLD.cliente_fiscal_id;
  UPDATE tarea_clientes SET principal = 0 WHERE tarea_id = NEW.id AND principal = 1 AND cliente_fiscal_id IS NOT NEW.cliente_fiscal_id;
  INSERT OR IGNORE INTO tarea_clientes (tenant_id, tarea_id, cliente_fiscal_id, principal, creado_en)
  SELECT tenant_id, NEW.id, id, 0, COALESCE(NEW.actualizada_en, NEW.creada_en) FROM clientes_fiscales WHERE id = NEW.cliente_fiscal_id;
  UPDATE tarea_clientes SET principal = 1 WHERE tarea_id = NEW.id AND cliente_fiscal_id = NEW.cliente_fiscal_id;
END;
"""


def crear_esquema(conn) -> None:
    """Idempotente: columnas nuevas, tabla de vínculos, disparador de versión y vínculo principal de lo que ya existía."""
    db._asegurar_columna(conn, "tareas_outlook", "version", "INTEGER NOT NULL DEFAULT 1")
    db._asegurar_columna(conn, "tareas_outlook", "motivo_bloqueo", "TEXT")
    db._asegurar_columna(conn, "tareas_outlook", "tarea_padre_id", "INTEGER REFERENCES tareas_outlook(id)")
    db._asegurar_columna(conn, "tareas_outlook", "visible_cliente", "INTEGER NOT NULL DEFAULT 0")
    conn.executescript(ESQUEMA)
    conn.execute(
        """INSERT OR IGNORE INTO tarea_clientes (tenant_id, tarea_id, cliente_fiscal_id, principal, creado_en)
           SELECT cf.tenant_id, t.id, t.cliente_fiscal_id, 1, t.creada_en
           FROM tareas_outlook t JOIN clientes_fiscales cf ON cf.id = t.cliente_fiscal_id
           WHERE t.cliente_fiscal_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM tarea_clientes v WHERE v.tarea_id = t.id)"""
    )


# --- Vencida: derivada -----------------------------------------------------------------------------------------------

def esta_vencida(fecha_vencimiento: str | None, estado: str | None, hoy: date | None = None) -> bool:
    """Vencida = tiene fecha, esa fecha (día) es anterior a hoy y la tarea no está completada. Se compara el día, igual que los contadores del plan de carga, para que
    una obligación «de día» no cambie por la hora ni por la zona."""
    if not fecha_vencimiento or estado in ESTADOS_CERRADOS:
        return False
    return fecha_vencimiento[:10] < (hoy or date.today()).isoformat()


# --- Concurrencia optimista -----------------------------------------------------------------------------------------

class ConflictoDeVersion(Exception):
    def __init__(self, actual: int | None):
        super().__init__("La tarea ha cambiado desde que la abriste.")
        self.actual = actual


def version_de(tarea_id: int) -> int | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT version FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
        return f["version"] if f else None
    finally:
        conn.close()


def version_pedida(valor) -> int | None:
    """None si no se mandó versión (comportamiento de siempre); ValueError si se mandó algo que no es un entero."""
    if valor in (None, ""):
        return None
    if isinstance(valor, bool):
        raise ValueError("version")
    return int(valor)


def reclamar_version(tarea_id: int, version: int | None) -> None:
    """Si se pasó `version`, la «reclama» de forma atómica: el UPDATE solo cuenta si la versión sigue siendo esa, y al hacerlo el disparador la sube, de modo que otra
    escritura con la misma versión vieja ya no pasa. Lanza ConflictoDeVersion si ha cambiado. Sin versión no hace nada."""
    if version is None:
        return
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE tareas_outlook SET actualizada_en = actualizada_en WHERE id = ? AND version = ?", (tarea_id, version))
        conn.commit()
        if cur.rowcount == 0:
            actual = conn.execute("SELECT version FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
            raise ConflictoDeVersion(actual["version"] if actual else None)
    finally:
        conn.close()


# --- Transiciones ---------------------------------------------------------------------------------------------------

class TransicionInvalida(Exception):
    def __init__(self, codigo: str, mensaje: str, campo: str | None = None):
        super().__init__(mensaje)
        self.codigo, self.campo = codigo, campo


def transicionar(usuario_id: int, tarea_id: int, estado: str, motivo: str | None = None, version: int | None = None) -> None:
    """Cambia el estado con las reglas de siempre (permisos, dependencias, completar con cronómetros) más: «esperando» exige un motivo, que se guarda; al salir de
    «esperando» el motivo se borra; y si se manda `version`, solo vale si nadie ha tocado la tarea."""
    if estado not in ESTADOS:
        raise TransicionInvalida("estado_invalido", "El estado no es válido.", "estado")
    if db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if not db.puede_trabajar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para hacer esto con esta tarea.")
    motivo = (motivo or "").strip()[:500]
    if estado == "esperando" and not motivo:
        raise TransicionInvalida("motivo_obligatorio", "Indica por qué la tarea queda bloqueada.", "motivo")
    if estado in ("en_progreso", "completada") and db.tarea_bloqueada(tarea_id):
        raise TransicionInvalida("tarea_bloqueada", "Esta tarea espera a otras que todavía no están completadas.")
    if estado == "completada":
        comprobar_completable(tarea_id)
    reclamar_version(tarea_id, version)
    if not db.cambiar_estado_tarea_outlook(usuario_id, tarea_id, estado):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para hacer esto con esta tarea.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tareas_outlook SET motivo_bloqueo = ? WHERE id = ?", (motivo if estado == "esperando" else None, tarea_id))
        conn.commit()
    finally:
        conn.close()
    if estado == "esperando":
        db.registrar_actividad_tarea(usuario_id, tarea_id, "bloqueada", motivo)


def guardar_motivo(tarea_id: int, estado: str, motivo: str | None) -> None:
    """Para quien cambia el estado por otro camino (formulario de edición): el motivo solo existe mientras la tarea está en «esperando»."""
    motivo = (motivo or "").strip()[:500]
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tareas_outlook SET motivo_bloqueo = ? WHERE id = ? AND COALESCE(motivo_bloqueo, '') != COALESCE(?, '')",
                     (motivo or None if estado == "esperando" else None, tarea_id, motivo or None if estado == "esperando" else None))
        conn.commit()
    finally:
        conn.close()


# --- Clientes de una tarea ------------------------------------------------------------------------------------------

def _tenant_de_usuario(conn: sqlite3.Connection, usuario_id: int) -> int | None:
    f = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return f["tenant_id"] if f else None


def clientes_de_tarea(tarea_id: int) -> list[dict]:
    """Los clientes vinculados (principal primero). Quien llama ya comprobó que ve la tarea."""
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT v.cliente_fiscal_id AS id, c.nombre, c.nif, v.principal FROM tarea_clientes v
               JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
               WHERE v.tarea_id = ? AND c.papelera_en IS NULL ORDER BY v.principal DESC, c.nombre""",
            (tarea_id,),
        ).fetchall()
        return [{"id": f["id"], "nombre": f["nombre"], "nif": f["nif"], "principal": bool(f["principal"])} for f in filas]
    finally:
        conn.close()


def validar_clientes(usuario_id: int, cliente_ids: list, principal_id: int | None = None) -> tuple[list[int], int | None, int | None]:
    """Comprueba una lista de clientes ANTES de tocar nada (también al crear una tarea): enteros, sin repetidos, hasta el máximo, el principal entre ellos y todos del despacho de la persona
    (los demás se rechazan, no se ignoran). Devuelve (ids, principal, tenant); lanza TransicionInvalida si algo no vale."""
    ids: list[int] = []
    for bruto in cliente_ids:
        try:
            i = int(bruto)
        except (TypeError, ValueError):
            raise TransicionInvalida("cliente_invalido", "Hay un cliente que no es válido.", "cliente_ids") from None
        if i not in ids:
            ids.append(i)
    if len(ids) > MAX_CLIENTES_POR_TAREA:
        raise TransicionInvalida("demasiados_clientes", f"Una tarea admite hasta {MAX_CLIENTES_POR_TAREA} clientes.", "cliente_ids")
    if principal_id is not None and int(principal_id) not in ids:
        raise TransicionInvalida("principal_invalido", "El cliente principal tiene que estar entre los vinculados.", "principal_id")
    principal = int(principal_id) if principal_id is not None else (ids[0] if ids else None)
    conn = db.get_connection()
    try:
        tenant = _tenant_de_usuario(conn, usuario_id)
        for i in ids:
            if tenant is None or conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (i, tenant)).fetchone() is None:
                raise TransicionInvalida("cliente_invalido", "Uno de los clientes no existe o no es de tu despacho.", "cliente_ids")
    finally:
        conn.close()
    return ids, principal, tenant


def fijar_clientes(usuario_id: int, tarea_id: int, cliente_ids: list[int], principal_id: int | None = None, version: int | None = None) -> list[dict]:
    """Sustituye los clientes de la tarea. Reglas: quien edita la tarea; todos los clientes del mismo despacho que la persona (los demás se rechazan, no se ignoran);
    sin repetidos; un solo principal (el indicado o, si no, el primero); `tareas_outlook.cliente_fiscal_id` queda igual al principal. Lista vacía = tarea sin cliente."""
    if not db.puede_editar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para cambiar los clientes de esta tarea.")
    ids, principal, tenant = validar_clientes(usuario_id, cliente_ids, principal_id)
    reclamar_version(tarea_id, version)
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM tarea_clientes WHERE tarea_id = ?", (tarea_id,))
        for i in ids:
            conn.execute("INSERT INTO tarea_clientes (tenant_id, tarea_id, cliente_fiscal_id, principal, creado_en) VALUES (?, ?, ?, ?, ?)",
                         (tenant, tarea_id, i, 1 if i == principal else 0, db.now_iso()))
        conn.execute("UPDATE tareas_outlook SET cliente_fiscal_id = ?, actualizada_en = ? WHERE id = ?", (principal, db.now_iso(), tarea_id))
        auditoria.registrar(tenant, usuario_id, "tarea.clientes", "tarea", tarea_id, {"clientes": ids, "principal": principal}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return clientes_de_tarea(tarea_id)


# --- Contadores por cliente -----------------------------------------------------------------------------------------

def contadores_de_cliente(tareas: list, hoy: date | None = None) -> dict:
    """Abiertas, vencidas y completadas sobre la MISMA lista que se enseña (así los números siempre cuadran con lo que hay debajo)."""
    abiertas = [t for t in tareas if t["estado"] != "completada"]
    return {"abiertas": len(abiertas), "vencidas": sum(1 for t in abiertas if esta_vencida(t["fecha_vencimiento"], t["estado"], hoy)),
            "completadas": len(tareas) - len(abiertas), "total": len(tareas)}


# --- Subtareas ------------------------------------------------------------------------------------------------------
# Una subtarea es una tarea de verdad (con su estado, fecha, responsable y comentarios) colgada de otra, a UN solo nivel. Política de cierre, explícita:
#   - la tarea padre no se puede completar mientras tenga subtareas abiertas (las que están en la papelera no cuentan);
#   - al completar la última subtarea el padre NO se completa solo: la persona decide;
#   - si se reabre una subtarea de un padre ya completado, el padre vuelve a «en progreso» (no puede estar completo con trabajo abierto);
#   - mandar el padre a la papelera manda con él las subtareas, y restaurarlo restaura las que se fueron con él.

MENSAJE_SUBTAREAS = "Esta tarea tiene subtareas sin completar."


def subtareas_de(tarea_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT id, asunto, estado, fecha_vencimiento, asignada_a, usuario_id FROM tareas_outlook
               WHERE tarea_padre_id = ? AND papelera_en IS NULL ORDER BY (estado = 'completada'), fecha_vencimiento IS NULL, fecha_vencimiento, id""", (tarea_id,))]
    finally:
        conn.close()


def subtareas_abiertas(tarea_id: int) -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM tareas_outlook WHERE tarea_padre_id = ? AND papelera_en IS NULL AND estado != 'completada'", (tarea_id,)).fetchone()[0]
    finally:
        conn.close()


def progreso_subtareas(subtareas: list[dict]) -> dict:
    hechas = sum(1 for t in subtareas if t["estado"] == "completada")
    return {"total": len(subtareas), "hechas": hechas, "abiertas": len(subtareas) - hechas}


def padre_de(tarea_id: int) -> int | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT tarea_padre_id FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
        return f["tarea_padre_id"] if f else None
    finally:
        conn.close()


def crear_subtarea(usuario_id: int, padre_id: int, asunto: str, fecha_vencimiento: str | None = None, asignada_a: int | None = None) -> int:
    """Quien puede editar la tarea padre añade subtareas. Hereda el cliente principal y el proyecto del padre. Solo un nivel; no sobre una tarea completada."""
    padre = db.obtener_tarea_outlook_visible(usuario_id, padre_id)
    if padre is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if not db.puede_editar_tarea(usuario_id, padre_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para añadir subtareas a esta tarea.")
    asunto = (asunto or "").strip()[:300]
    if not asunto:
        raise TransicionInvalida("asunto_vacio", "El asunto no puede estar vacío.", "asunto")
    if padre["tarea_padre_id"] is not None:
        raise TransicionInvalida("subtarea_de_subtarea", "Una subtarea no puede tener subtareas: solo se permite un nivel.")
    if padre["estado"] == "completada":
        raise TransicionInvalida("padre_completada", "Reabre la tarea antes de añadirle subtareas.")
    nueva = db.crear_tarea_outlook(usuario_id, asunto=asunto, fecha_vencimiento=fecha_vencimiento or None, cliente_fiscal_id=padre["cliente_fiscal_id"],
                                   categoria_id=padre["categoria_id"])
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tareas_outlook SET tarea_padre_id = ? WHERE id = ?", (padre_id, nueva))
        conn.commit()
    finally:
        conn.close()
    if asignada_a and db.asignar_tarea_outlook(usuario_id, nueva, asignada_a):
        pass
    db.registrar_actividad_tarea(usuario_id, padre_id, "subtarea_nueva", asunto)
    return nueva


MENSAJE_REVISION = "Esta tarea tiene una revisión pendiente: primero tiene que resolverla quien revisa."


def impedimento_de_cierre(tarea_id: int) -> tuple[str, str] | None:
    """(código, mensaje) de lo que impide completar la tarea, o None si se puede: subtareas abiertas o una revisión pendiente. Lo usa el núcleo, así que valen todos los caminos."""
    if subtareas_abiertas(tarea_id):
        return "subtareas_abiertas", MENSAJE_SUBTAREAS
    if revision_pendiente(tarea_id) is not None:
        return "revision_pendiente", MENSAJE_REVISION
    return None


def comprobar_completable(tarea_id: int) -> None:
    """Lanza TransicionInvalida si algo impide completar la tarea (ver `impedimento_de_cierre`)."""
    imp = impedimento_de_cierre(tarea_id)
    if imp:
        raise TransicionInvalida(*imp)


def al_cambiar_estado(usuario_id: int, tarea_id: int, antes: str | None, despues: str) -> None:
    """Si una subtarea sale de «completada» y su padre estaba completado, el padre vuelve a «en progreso»."""
    if antes != "completada" or despues == "completada":
        return
    padre_id = padre_de(tarea_id)
    if padre_id is None:
        return
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE tareas_outlook SET estado = 'en_progreso', fecha_completada = NULL, actualizada_en = ? WHERE id = ? AND estado = 'completada' AND papelera_en IS NULL",
                           (db.now_iso(), padre_id))
        conn.commit()
    finally:
        conn.close()
    if cur.rowcount:
        db.registrar_actividad_tarea(usuario_id, padre_id, "reabierta_por_subtarea", db._asunto_tarea(tarea_id))


# --- Adjuntos ---------------------------------------------------------------------------------------------------------
# Archivos de trabajo de la tarea, en la base (mismo criterio que los adjuntos de notas, pero con más tipos y más tamaño). Se sirven siempre como descarga con
# el tipo que decide el servidor (nunca el que dice el navegador) para que un HTML o un SVG subido no se ejecute. Las claves privadas y los .p12/.pfx no se guardan nunca.

TIPOS_ADJUNTO = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "txt": "text/plain", "csv": "text/csv", "md": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text", "ods": "application/vnd.oasis.opendocument.spreadsheet", "odp": "application/vnd.oasis.opendocument.presentation",
}
IMAGENES = ("png", "jpg", "jpeg", "gif", "webp")
MAX_ADJUNTO_BYTES = 15 * 1024 * 1024
MAX_ADJUNTOS_POR_TAREA = 20


def _extension(nombre: str) -> str:
    return nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""


def subir_adjunto(usuario_id: int, tarea_id: int, nombre: str, contenido: bytes) -> int:
    """Quien trabaja la tarea (dueño, asignado o colaborador) adjunta archivos. Devuelve el id; lanza TransicionInvalida con un código estable si no se puede."""
    import hashlib
    if db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if not db.puede_trabajar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para adjuntar archivos a esta tarea.")
    nombre = db._nombre_de_archivo_seguro(nombre or "")[:150]
    ext = _extension(nombre)
    if ext not in TIPOS_ADJUNTO:
        raise TransicionInvalida("tipo_no_admitido", "Tipo de archivo no admitido (PDF, imágenes, texto, CSV y documentos de Office o LibreOffice).", "adjunto")
    if not contenido:
        raise TransicionInvalida("archivo_vacio", "El archivo está vacío.", "adjunto")
    if len(contenido) > MAX_ADJUNTO_BYTES:
        raise TransicionInvalida("archivo_grande", f"El archivo supera los {MAX_ADJUNTO_BYTES // (1024 * 1024)} MB.", "adjunto")
    from . import certificados
    if certificados.contiene_clave_privada(contenido):
        raise TransicionInvalida("clave_privada", "Los certificados con clave privada no se adjuntan nunca.", "adjunto")
    huella = hashlib.sha256(contenido).hexdigest()
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM tarea_adjuntos WHERE tarea_id = ? AND hash_sha256 = ? AND papelera_en IS NULL", (tarea_id, huella)).fetchone():
            raise TransicionInvalida("duplicado", "Ese archivo ya está adjunto a la tarea.", "adjunto")
        if conn.execute("SELECT COUNT(*) FROM tarea_adjuntos WHERE tarea_id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()[0] >= MAX_ADJUNTOS_POR_TAREA:
            raise TransicionInvalida("limite", f"Una tarea admite hasta {MAX_ADJUNTOS_POR_TAREA} archivos.", "adjunto")
        cur = conn.execute(
            "INSERT INTO tarea_adjuntos (tenant_id, tarea_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, hash_sha256, subido_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_tenant_de_usuario(conn, usuario_id), tarea_id, nombre, TIPOS_ADJUNTO[ext], len(contenido), contenido, huella, usuario_id, db.now_iso()))
        conn.commit()
        adjunto_id = cur.lastrowid
    finally:
        conn.close()
    db.registrar_actividad_tarea(usuario_id, tarea_id, "adjunto", nombre)
    return adjunto_id


def listar_adjuntos(tarea_id: int) -> list[dict]:
    """Metadatos, sin el contenido. Quien llama ya comprobó que ve la tarea."""
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT a.id, a.nombre_archivo, a.tipo_mime, a.tamano_bytes, a.subido_por, a.creado_en FROM tarea_adjuntos a
               WHERE a.tarea_id = ? AND a.papelera_en IS NULL ORDER BY a.id""", (tarea_id,))]
    finally:
        conn.close()


def leer_adjunto(usuario_id: int, adjunto_id: int) -> dict | None:
    """El adjunto con su contenido, o None si no existe o la persona no ve la tarea."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM tarea_adjuntos WHERE id = ? AND papelera_en IS NULL", (adjunto_id,)).fetchone()
    finally:
        conn.close()
    if f is None or db.obtener_tarea_outlook_visible(usuario_id, f["tarea_id"]) is None:
        return None
    d = {k: f[k] for k in f.keys() if k != "contenido"}
    d["contenido"] = bytes(f["contenido"])
    d["imagen"] = _extension(f["nombre_archivo"]) in IMAGENES
    return d


def eliminar_adjunto(usuario_id: int, adjunto_id: int) -> bool:
    """A la papelera: quien lo subió o el dueño de la tarea."""
    a = leer_adjunto(usuario_id, adjunto_id)
    if a is None:
        return False
    tarea = db.obtener_tarea_outlook_visible(usuario_id, a["tarea_id"])
    if a["subido_por"] != usuario_id and tarea["usuario_id"] != usuario_id:
        return False
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tarea_adjuntos SET papelera_en = ? WHERE id = ?", (db._marca_papelera(), adjunto_id))
        conn.commit()
    finally:
        conn.close()
    db.registrar_actividad_tarea(usuario_id, a["tarea_id"], "adjunto_eliminado", a["nombre_archivo"])
    return True


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    """Al borrar un despacho entero: sus vínculos tarea-cliente se van con él (referencian a sus clientes) y los adjuntos, que son de la tarea y de la persona, dejan de apuntar a un despacho que ya no existe."""
    conn.execute("DELETE FROM tarea_clientes WHERE tenant_id = ?", (tenant_id,))
    conn.execute("UPDATE tarea_adjuntos SET tenant_id = NULL WHERE tenant_id = ?", (tenant_id,))
    conn.execute("UPDATE tarea_revisiones SET tenant_id = NULL WHERE tenant_id = ?", (tenant_id,))


def desvincular_cliente(conn, tenant_id: int, cliente_fiscal_id: int) -> None:
    """Al borrar un cliente fiscal para siempre: las tareas siguen existiendo, solo dejan de estar vinculadas a él (y si era el principal, cliente_fiscal_id queda vacío)."""
    conn.execute("DELETE FROM tarea_clientes WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))
    conn.execute("UPDATE tareas_outlook SET cliente_fiscal_id = NULL WHERE cliente_fiscal_id = ?", (cliente_fiscal_id,))


# --- Revisión (aprobación) ----------------------------------------------------------------------------------------------
# Quien trabaja la tarea pide que la revise OTRA persona del despacho (nunca uno mismo: dos pares de ojos). Mientras esté pendiente, la tarea no se puede completar. Quien revisa aprueba
# o pide cambios (con nota obligatoria); al pedir cambios la tarea vuelve a «en progreso» y se avisa a quien la pidió. Aprobar no completa la tarea: lo hace quien la lleva.
# Solo puede resolver el revisor designado; quien pidió la revisión o el dueño la pueden cancelar. Todo queda en el historial de la tarea y en la auditoría.

DECISIONES = {"aprobar": "aprobada", "cambios": "cambios"}


def revision_pendiente(tarea_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM tarea_revisiones WHERE tarea_id = ? AND estado = 'pendiente'", (tarea_id,)).fetchone()
        return dict(f) if f else None
    finally:
        conn.close()


def historial_de_revisiones(tarea_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute("SELECT * FROM tarea_revisiones WHERE tarea_id = ? ORDER BY id DESC LIMIT 20", (tarea_id,))]
    finally:
        conn.close()
    for f in filas:
        f["revisor"], f["solicitante"] = db.nombre_mostrado_usuario(f["revisor_id"]), db.nombre_mostrado_usuario(f["solicitada_por"])
    return filas


def _avisar(usuario_id: int, titulo: str, cuerpo: str, tarea_id: int) -> None:
    from . import notificaciones
    notificaciones.crear_y_enviar(usuario_id, "revision_tarea", titulo[:150], cuerpo[:300], url=f"/tareas/{tarea_id}")


def solicitar_revision(usuario_id: int, tarea_id: int, revisor_id: int, nota: str | None = None) -> int:
    tarea = db.obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if tarea is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if not db.puede_trabajar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para pedir la revisión de esta tarea.")
    if tarea["estado"] == "completada":
        raise TransicionInvalida("tarea_completada", "La tarea ya está completada.")
    try:
        revisor_id = int(revisor_id)
    except (TypeError, ValueError):
        raise TransicionInvalida("revisor_invalido", "Elige a quien la revisa.", "revisor_id") from None
    if revisor_id == usuario_id:
        raise TransicionInvalida("revisor_invalido", "La revisión tiene que hacerla otra persona.", "revisor_id")
    conn = db.get_connection()
    try:
        tenant = _tenant_de_usuario(conn, usuario_id)
        if tenant is None or conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (revisor_id, tenant)).fetchone() is None:
            raise TransicionInvalida("revisor_invalido", "Quien revisa tiene que ser de tu despacho.", "revisor_id")
        try:
            cur = conn.execute("INSERT INTO tarea_revisiones (tenant_id, tarea_id, solicitada_por, revisor_id, nota_solicitud, solicitada_en) VALUES (?, ?, ?, ?, ?, ?)",
                               (tenant, tarea_id, usuario_id, revisor_id, (nota or "").strip()[:500] or None, db.now_iso()))
        except sqlite3.IntegrityError:
            raise TransicionInvalida("revision_pendiente", "Esta tarea ya tiene una revisión pendiente.") from None
        if db.obtener_tarea_outlook_visible(revisor_id, tarea_id) is None:       # para poder revisarla tiene que verla: se le comparte como observador
            conn.execute("INSERT OR IGNORE INTO tareas_participantes (tarea_id, usuario_id, rol, compartida_en) VALUES (?, ?, 'observa', ?)", (tarea_id, revisor_id, db.now_iso()))
        auditoria.registrar(tenant, usuario_id, "tarea.revision.solicitar", "tarea", tarea_id, {"revisor": revisor_id}, conn=conn)
        conn.commit()
        revision_id = cur.lastrowid
    finally:
        conn.close()
    db.registrar_actividad_tarea(usuario_id, tarea_id, "revision_solicitada", db.nombre_mostrado_usuario(revisor_id) or "")
    _avisar(revisor_id, f"Te piden revisar: {tarea['asunto']}", (nota or "").strip() or "Revisión pendiente", tarea_id)
    return revision_id


def resolver_revision(usuario_id: int, tarea_id: int, decision: str, nota: str | None = None) -> dict:
    if decision not in DECISIONES:
        raise TransicionInvalida("decision_invalida", "La decisión tiene que ser aprobar o pedir cambios.", "decision")
    nota = (nota or "").strip()[:500]
    if decision == "cambios" and not nota:
        raise TransicionInvalida("nota_obligatoria", "Explica qué hay que cambiar.", "nota")
    rev = revision_pendiente(tarea_id)
    if rev is None or db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        raise TransicionInvalida("no_encontrada", "No hay ninguna revisión pendiente en esta tarea.")
    if rev["revisor_id"] != usuario_id:
        raise TransicionInvalida("sin_permiso", "Solo puede resolverla la persona designada para revisar.")
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE tarea_revisiones SET estado = ?, nota_resolucion = ?, resuelta_en = ?, resuelta_por = ? WHERE id = ? AND estado = 'pendiente'",
                           (DECISIONES[decision], nota or None, db.now_iso(), usuario_id, rev["id"]))
        if cur.rowcount == 0:                                  # otra petición se adelantó
            raise TransicionInvalida("no_encontrada", "No hay ninguna revisión pendiente en esta tarea.")
        if decision == "cambios":
            conn.execute("UPDATE tareas_outlook SET estado = 'en_progreso', fecha_completada = NULL, actualizada_en = ? WHERE id = ? AND estado != 'en_progreso'", (db.now_iso(), tarea_id))
        auditoria.registrar(rev["tenant_id"], usuario_id, "tarea.revision." + decision, "tarea", tarea_id, {"revision": rev["id"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    asunto = db._asunto_tarea(tarea_id)
    db.registrar_actividad_tarea(usuario_id, tarea_id, "revision_aprobada" if decision == "aprobar" else "revision_cambios", nota)
    _avisar(rev["solicitada_por"], (f"Revisión aprobada: {asunto}" if decision == "aprobar" else f"Piden cambios: {asunto}"), nota or "Sin comentarios", tarea_id)
    return {**rev, "estado": DECISIONES[decision], "nota_resolucion": nota or None}


def cancelar_revision(usuario_id: int, tarea_id: int) -> bool:
    """Quien la pidió o el dueño de la tarea retira la revisión pendiente."""
    rev = revision_pendiente(tarea_id)
    tarea = db.obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if rev is None or tarea is None or usuario_id not in (rev["solicitada_por"], tarea["usuario_id"]):
        return False
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE tarea_revisiones SET estado = 'cancelada', resuelta_en = ?, resuelta_por = ? WHERE id = ? AND estado = 'pendiente'", (db.now_iso(), usuario_id, rev["id"]))
        auditoria.registrar(rev["tenant_id"], usuario_id, "tarea.revision.cancelar", "tarea", tarea_id, {"revision": rev["id"]}, conn=conn)
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


# --- Colaboración con el cliente (portal) ------------------------------------------------------------------------------------
# Nada de una tarea sale al portal por defecto. Quien edita la tarea decide, tarea a tarea, enseñársela al cliente al que está vinculada. El cliente ve SOLO el asunto, el estado y la fecha
# límite, de lectura: nunca la descripción, los comentarios, los adjuntos, quién la lleva, el motivo del bloqueo ni las subtareas (a menos que tengan su propia marca).

ESTADOS_PARA_CLIENTE = {"no_iniciada": "Pendiente", "en_progreso": "En curso", "esperando": "En espera", "aplazada": "Aplazada", "completada": "Completada"}


def fijar_visible_cliente(usuario_id: int, tarea_id: int, visible: bool) -> None:
    if db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if not db.puede_editar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para cambiar lo que ve el cliente.")
    if visible and not clientes_de_tarea(tarea_id):
        raise TransicionInvalida("sin_cliente", "La tarea no está vinculada a ningún cliente.")
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE tareas_outlook SET visible_cliente = ? WHERE id = ? AND visible_cliente != ?", (1 if visible else 0, tarea_id, 1 if visible else 0))
        if cur.rowcount:
            auditoria.registrar(_tenant_de_usuario(conn, usuario_id), usuario_id, "tarea.visible_cliente", "tarea", tarea_id, {"visible": bool(visible)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    db.registrar_actividad_tarea(usuario_id, tarea_id, "visible_cliente" if visible else "oculta_cliente")


def tareas_para_cliente(tenant_id: int, cliente_fiscal_id: int) -> list[dict]:
    """Lo que el portal enseña a ese cliente: solo tareas marcadas, de su propio despacho, vinculadas a él, fuera de la papelera. Abiertas primero, por fecha."""
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT t.asunto, t.estado, t.fecha_vencimiento FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id
               WHERE t.visible_cliente = 1 AND t.papelera_en IS NULL AND u.tenant_id = ?
                 AND (t.cliente_fiscal_id = ? OR t.id IN (SELECT tarea_id FROM tarea_clientes WHERE cliente_fiscal_id = ? AND tenant_id = ?))
               ORDER BY (t.estado = 'completada'), t.fecha_vencimiento IS NULL, t.fecha_vencimiento, t.id LIMIT 100""",
            (tenant_id, cliente_fiscal_id, cliente_fiscal_id, tenant_id)).fetchall()
        return [{"asunto": f["asunto"], "estado": f["estado"], "estado_texto": ESTADOS_PARA_CLIENTE.get(f["estado"], f["estado"]),
                 "fecha_vencimiento": f["fecha_vencimiento"][:10] if f["fecha_vencimiento"] else None, "vencida": esta_vencida(f["fecha_vencimiento"], f["estado"])} for f in filas]
    finally:
        conn.close()
