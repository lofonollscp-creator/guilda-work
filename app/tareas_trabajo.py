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
from datetime import date, datetime, timedelta

from . import bd as _bd
from .bd.errores import ErrorIntegridad
from . import antivirus, auditoria, db

ESTADOS = ("no_iniciada", "en_progreso", "completada", "esperando", "aplazada", "en_revision")
ESTADOS_CERRADOS = ("completada",)
MENSAJE_EN_REVISION = "La tarea está en revisión: resuélvela o retira la petición antes de cambiar su estado."
MENSAJE_SOLO_POR_REVISION = "El estado «en revisión» se pone pidiendo la revisión de la tarea, no a mano."
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
CREATE TABLE IF NOT EXISTS tarea_comentarios_cliente (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL REFERENCES clientes_fiscales(id),
    autor TEXT NOT NULL CHECK (autor IN ('cliente', 'despacho')),
    usuario_id INTEGER REFERENCES usuarios(id),
    texto TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    leido_en TEXT,
    oculto_en TEXT,
    oculto_por INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS idx_tarea_coment_cliente_tarea ON tarea_comentarios_cliente(tarea_id, cliente_fiscal_id, id);
CREATE TABLE IF NOT EXISTS tarea_comentarios_cliente_adjuntos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    comentario_id INTEGER NOT NULL REFERENCES tarea_comentarios_cliente(id) ON DELETE CASCADE,
    tarea_id INTEGER NOT NULL,
    cliente_fiscal_id INTEGER NOT NULL,
    nombre_archivo TEXT NOT NULL,
    tipo_mime TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    contenido BLOB NOT NULL,
    hash_sha256 TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tarea_coment_adj_comentario ON tarea_comentarios_cliente_adjuntos(comentario_id);
CREATE TABLE IF NOT EXISTS tarea_avisos_correo (
    usuario_id INTEGER NOT NULL,
    tarea_id INTEGER NOT NULL REFERENCES tareas_outlook(id) ON DELETE CASCADE,
    enviado_en TEXT NOT NULL,
    PRIMARY KEY (usuario_id, tarea_id)
);
CREATE TABLE IF NOT EXISTS informes_tareas_suscripciones (
    usuario_id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    activa INTEGER NOT NULL DEFAULT 1,
    ultimo_envio TEXT,
    creada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tarea_revision_votos (
    id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES tarea_revisiones(id) ON DELETE CASCADE,
    revisor_id INTEGER NOT NULL REFERENCES usuarios(id),
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobado', 'cambios')),
    nota TEXT,
    votado_en TEXT,
    UNIQUE (revision_id, revisor_id)
);
CREATE INDEX IF NOT EXISTS idx_tarea_revision_votos_revisor ON tarea_revision_votos(revisor_id, estado);
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

# «En revisión» es un estado real de la tarea, pero solo se entra y se sale por el flujo de revisión. Estos dos disparadores lo garantizan para CUALQUIER camino (web, API, importación…): no se puede poner
# «en revisión» sin una revisión pendiente, ni sacar la tarea de ahí mientras siga pendiente. El flujo (solicitar/resolver/cancelar) cambia primero la revisión y después la tarea, así que los cumple.
DISPARADORES_EN_REVISION = """
DROP TRIGGER IF EXISTS tareas_outlook_en_revision_entrada;
CREATE TRIGGER tareas_outlook_en_revision_entrada BEFORE UPDATE OF estado ON tareas_outlook
WHEN NEW.estado = 'en_revision' AND OLD.estado != 'en_revision'
  AND NOT EXISTS (SELECT 1 FROM tarea_revisiones r WHERE r.tarea_id = NEW.id AND r.estado = 'pendiente')
BEGIN SELECT RAISE(ABORT, 'solo_por_revision'); END;
DROP TRIGGER IF EXISTS tareas_outlook_en_revision_salida;
CREATE TRIGGER tareas_outlook_en_revision_salida BEFORE UPDATE OF estado ON tareas_outlook
WHEN OLD.estado = 'en_revision' AND NEW.estado != 'en_revision'
  AND EXISTS (SELECT 1 FROM tarea_revisiones r WHERE r.tarea_id = NEW.id AND r.estado = 'pendiente')
BEGIN SELECT RAISE(ABORT, 'revision_pendiente'); END;
"""


def _permitir_estado_en_revision(conn) -> None:
    """Añade «en_revision» al CHECK del estado de `tareas_outlook`. SQLite no deja alterar un CHECK, y reconstruir la tabla con las claves foráneas activas es arriesgado; para AMPLIAR (nunca restringir)
    un CHECK, la documentación de SQLite admite reescribir su definición (`writable_schema` + `schema_version`), sin tocar ni mover ningún dato. Idempotente: si ya lo admite, no hace nada."""
    if _bd.MOTOR != "sqlite":          # reconstruye tablas de bases SQLite antiguas; en PostgreSQL el esquema nace ya con el diseño final
        return
    import re
    fila = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tareas_outlook'").fetchone()
    if fila is None or "en_revision" in fila[0]:
        return
    nuevo = re.sub(r"'aplazada'\s*\)\s*\)", "'aplazada','en_revision'))", fila[0], count=1)
    if nuevo == fila[0]:
        raise RuntimeError("No se reconoce la definición del estado de tareas_outlook: no se puede añadir «en_revision».")
    conn.commit()
    version = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.execute("PRAGMA writable_schema = ON")
    try:
        conn.execute("UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = 'tareas_outlook'", (nuevo,))
        conn.execute(f"PRAGMA schema_version = {int(version) + 1}")
    finally:
        conn.execute("PRAGMA writable_schema = OFF")
    conn.commit()
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("La comprobación de integridad falló tras ampliar el estado de tareas_outlook.")


def crear_esquema(conn) -> None:
    """Idempotente: columnas nuevas, tabla de vínculos, disparador de versión y vínculo principal de lo que ya existía."""
    db._asegurar_columna(conn, "usuario_perfil", "avisos_cliente_por_correo", "INTEGER NOT NULL DEFAULT 0")      # opt-in: correo al equipo cuando un cliente comenta
    db._asegurar_columna(conn, "tareas_outlook", "version", "INTEGER NOT NULL DEFAULT 1")
    db._asegurar_columna(conn, "tareas_outlook", "motivo_bloqueo", "TEXT")
    db._asegurar_columna(conn, "tareas_outlook", "tarea_padre_id", "INTEGER REFERENCES tareas_outlook(id)")
    db._asegurar_columna(conn, "tareas_outlook", "visible_cliente", "INTEGER NOT NULL DEFAULT 0")
    db._asegurar_columna(conn, "tareas_outlook", "comentarios_cliente", "INTEGER NOT NULL DEFAULT 0")
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "tarea_revisiones", "modo", "TEXT NOT NULL DEFAULT 'todos'")
    db._asegurar_columna(conn, "tarea_revisiones", "estado_previo", "TEXT")            # el estado que tenía la tarea al pedir la revisión, para devolvérselo al resolverla o retirarla
    _permitir_estado_en_revision(conn)
    conn.executescript(DISPARADORES_EN_REVISION)
    # Las revisiones que ya estaban pendientes pasan a verse «en revisión» (y guardan el estado del que venían); una tarea «en revisión» sin revisión pendiente vuelve a «en progreso».
    conn.execute("""UPDATE tarea_revisiones SET estado_previo = (SELECT t.estado FROM tareas_outlook t WHERE t.id = tarea_revisiones.tarea_id)
                    WHERE estado = 'pendiente' AND estado_previo IS NULL""")
    conn.execute("""UPDATE tareas_outlook SET estado = 'en_revision' WHERE estado NOT IN ('completada', 'en_revision') AND papelera_en IS NULL
                    AND EXISTS (SELECT 1 FROM tarea_revisiones r WHERE r.tarea_id = tareas_outlook.id AND r.estado = 'pendiente')""")
    conn.execute("""UPDATE tareas_outlook SET estado = 'en_progreso' WHERE estado = 'en_revision'
                    AND NOT EXISTS (SELECT 1 FROM tarea_revisiones r WHERE r.tarea_id = tareas_outlook.id AND r.estado = 'pendiente')""")
    conn.execute(                    # las revisiones de antes tenían un solo revisor: pasan a tener su voto (pendiente, aprobado o con cambios según cómo acabaron)
        """INSERT INTO tarea_revision_votos (revision_id, revisor_id, estado, nota, votado_en)
           SELECT r.id, r.revisor_id, CASE r.estado WHEN 'aprobada' THEN 'aprobado' WHEN 'cambios' THEN 'cambios' ELSE 'pendiente' END,
                  CASE WHEN r.estado IN ('aprobada', 'cambios') THEN r.nota_resolucion END, CASE WHEN r.estado IN ('aprobada', 'cambios') THEN r.resuelta_en END
           FROM tarea_revisiones r WHERE r.estado != 'cancelada' AND NOT EXISTS (SELECT 1 FROM tarea_revision_votos v WHERE v.revision_id = r.id) ON CONFLICT DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO tarea_clientes (tenant_id, tarea_id, cliente_fiscal_id, principal, creado_en)
           SELECT cf.tenant_id, t.id, t.cliente_fiscal_id, 1, t.creada_en
           FROM tareas_outlook t JOIN clientes_fiscales cf ON cf.id = t.cliente_fiscal_id
           WHERE t.cliente_fiscal_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM tarea_clientes v WHERE v.tarea_id = t.id) ON CONFLICT DO NOTHING"""
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
    actual = db.obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if actual is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if estado == "en_revision" and actual["estado"] != "en_revision":
        raise TransicionInvalida("solo_por_revision", MENSAJE_SOLO_POR_REVISION, "estado")
    if actual["estado"] == "en_revision" and estado not in ("en_revision", "completada"):          # completar tiene su propio aviso (comprobar_completable: revisión pendiente)
        raise TransicionInvalida("revision_pendiente", MENSAJE_EN_REVISION, "estado")
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
        db._emitir_evento(usuario_id, "tarea.estado_cambiado", {"tarea_id": padre_id, "de": "completada", "a": "en_progreso"})


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
    if not _bd.es_postgres(conn):                      # en PostgreSQL la fila no puede cambiar de despacho: se borra con él (tenant.borrar_filas_de_tenant)
        conn.execute("UPDATE tarea_adjuntos SET tenant_id = NULL WHERE tenant_id = ?", (tenant_id,))
        conn.execute("UPDATE tarea_revisiones SET tenant_id = NULL WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM informes_tareas_suscripciones WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM tarea_comentarios_cliente_adjuntos WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM tarea_comentarios_cliente WHERE tenant_id = ?", (tenant_id,))             # son conversaciones con clientes de ese despacho: se van con él


def desvincular_cliente(conn, tenant_id: int, cliente_fiscal_id: int) -> None:
    """Al borrar un cliente fiscal para siempre: las tareas siguen existiendo, solo dejan de estar vinculadas a él (y si era el principal, cliente_fiscal_id queda vacío)."""
    conn.execute("DELETE FROM tarea_clientes WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))
    conn.execute("DELETE FROM tarea_comentarios_cliente_adjuntos WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))
    conn.execute("DELETE FROM tarea_comentarios_cliente WHERE cliente_fiscal_id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id))
    conn.execute("UPDATE tareas_outlook SET cliente_fiscal_id = NULL WHERE cliente_fiscal_id = ?", (cliente_fiscal_id,))


# --- Revisión (aprobación) ----------------------------------------------------------------------------------------------
# Quien trabaja la tarea pide que la revise OTRA persona del despacho —o varias, hasta cinco— (nunca uno mismo: dos pares de ojos). Mientras esté pendiente, la tarea no se puede completar.
# Política, explícita:
#   - modo «todos» (por defecto): hace falta que aprueben todos los revisores; modo «cualquiera»: basta con que apruebe uno, y el primer voto decide;
#   - modo «cadena»: aprueban uno tras otro, en el orden en que se eligieron. Solo vota quien tiene el turno (los demás aún no pueden, y no se les avisa hasta que les toque); al aprobar uno, se avisa al
#     siguiente; la revisión se aprueba cuando aprueba el último;
#   - UNA petición de cambios, de quien sea, detiene la revisión: la tarea vuelve a «en progreso» y se avisa a quien la pidió (con la nota obligatoria). Los demás ya no tienen que votar;
#   - cada revisor vota una sola vez; solo vota quien está designado; aprobar no completa la tarea: lo hace quien la lleva;
#   - quien pidió la revisión o el dueño de la tarea la pueden retirar. Todo queda en el historial de la tarea y en la auditoría.

DECISIONES = {"aprobar": "aprobada", "cambios": "cambios"}
MODOS_REVISION = {"todos": "Tienen que aprobarla todos", "cualquiera": "Basta con que la apruebe uno", "cadena": "Aprueban uno tras otro, en el orden elegido"}
MAX_REVISORES = 5


def _con_votos(conn, rev: dict) -> dict:
    votos = [dict(v) for v in conn.execute("SELECT revisor_id, estado, nota, votado_en FROM tarea_revision_votos WHERE revision_id = ? ORDER BY id", (rev["id"],))]
    for v in votos:
        v["revisor"] = db.nombre_mostrado_usuario(v["revisor_id"])
    rev["votos"] = votos
    rev["revisores"] = [v["revisor_id"] for v in votos]
    rev["pendientes"] = [v["revisor_id"] for v in votos if v["estado"] == "pendiente"]
    rev["aprobados"] = sum(1 for v in votos if v["estado"] == "aprobado")
    rev["revisor"] = ", ".join(v["revisor"] or "" for v in votos)
    # Quién puede votar ahora: en cadena, solo el primero que falta (el orden de los votos es el orden elegido); en los demás modos, todos los que faltan.
    rev["turno"] = rev["pendientes"][0] if rev.get("modo") == "cadena" and rev["pendientes"] else None
    rev["pueden_votar"] = [rev["turno"]] if rev["turno"] is not None else (rev["pendientes"] if rev.get("modo") != "cadena" else [])
    return rev


def revision_pendiente(tarea_id: int) -> dict | None:
    """La revisión pendiente con sus votos (`votos`, `revisores`, `pendientes`, `aprobados`). `revisor_id` sigue siendo el primer revisor, por compatibilidad."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM tarea_revisiones WHERE tarea_id = ? AND estado = 'pendiente'", (tarea_id,)).fetchone()
        return _con_votos(conn, dict(f)) if f else None
    finally:
        conn.close()


def historial_de_revisiones(tarea_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = [_con_votos(conn, dict(f)) for f in conn.execute("SELECT * FROM tarea_revisiones WHERE tarea_id = ? ORDER BY id DESC LIMIT 20", (tarea_id,))]
    finally:
        conn.close()
    for f in filas:
        f["solicitante"] = db.nombre_mostrado_usuario(f["solicitada_por"])
    return filas


def tiene_voto_pendiente(usuario_id: int, revision: dict | None) -> bool:
    return bool(revision and usuario_id in revision["pueden_votar"])


def _avisar(usuario_id: int, titulo: str, cuerpo: str, tarea_id: int) -> None:
    from . import notificaciones
    notificaciones.crear_y_enviar(usuario_id, "revision_tarea", titulo[:150], cuerpo[:300], url=f"/tareas/{tarea_id}")


def _lista_de_revisores(revisores) -> list[int]:
    if revisores in (None, ""):
        raise TransicionInvalida("revisor_invalido", "Elige a quien la revisa.", "revisor_ids")
    bruto = list(revisores) if isinstance(revisores, (list, tuple, set)) else [revisores]
    ids: list[int] = []
    for x in bruto:
        try:
            i = int(x)
        except (TypeError, ValueError):
            raise TransicionInvalida("revisor_invalido", "Elige a quien la revisa.", "revisor_ids") from None
        if i not in ids:
            ids.append(i)
    if not ids:
        raise TransicionInvalida("revisor_invalido", "Elige a quien la revisa.", "revisor_ids")
    if len(ids) > MAX_REVISORES:
        raise TransicionInvalida("demasiados_revisores", f"Una revisión admite hasta {MAX_REVISORES} revisores.", "revisor_ids")
    return ids


def solicitar_revision(usuario_id: int, tarea_id: int, revisores, nota: str | None = None, modo: str = "todos") -> int:
    """`revisores`: una persona (un entero, como siempre) o una lista de hasta cinco. `modo`: «todos», «cualquiera» o «cadena» (uno tras otro, en el orden de la lista)."""
    tarea = db.obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if tarea is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if not db.puede_trabajar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para pedir la revisión de esta tarea.")
    if tarea["estado"] == "completada":
        raise TransicionInvalida("tarea_completada", "La tarea ya está completada.")
    if (modo or "todos") not in MODOS_REVISION:
        raise TransicionInvalida("modo_invalido", "El modo tiene que ser «todos», «cualquiera» o «cadena».", "modo")
    modo = modo or "todos"
    ids = _lista_de_revisores(revisores)
    if usuario_id in ids:
        raise TransicionInvalida("revisor_invalido", "La revisión tiene que hacerla otra persona.", "revisor_ids")
    conn = db.get_connection()
    try:
        tenant = _tenant_de_usuario(conn, usuario_id)
        for r in ids:
            if tenant is None or conn.execute("SELECT 1 FROM usuarios WHERE id = ? AND tenant_id = ?", (r, tenant)).fetchone() is None:
                raise TransicionInvalida("revisor_invalido", "Quien revisa tiene que ser de tu despacho.", "revisor_ids")
        try:
            cur = conn.execute("INSERT INTO tarea_revisiones (tenant_id, tarea_id, solicitada_por, revisor_id, nota_solicitud, solicitada_en, modo) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (tenant, tarea_id, usuario_id, ids[0], (nota or "").strip()[:500] or None, db.now_iso(), modo))
        except ErrorIntegridad:
            raise TransicionInvalida("revision_pendiente", "Esta tarea ya tiene una revisión pendiente.") from None
        revision_id = cur.lastrowid
        previo = tarea["estado"]
        conn.execute("UPDATE tarea_revisiones SET estado_previo = ? WHERE id = ?", (previo, revision_id))
        conn.execute("UPDATE tareas_outlook SET estado = 'en_revision', actualizada_en = ? WHERE id = ?", (db.now_iso(), tarea_id))        # la revisión ya está pendiente: el disparador lo admite
        for r in ids:
            conn.execute("INSERT INTO tarea_revision_votos (revision_id, revisor_id) VALUES (?, ?)", (revision_id, r))
            if db.obtener_tarea_outlook_visible(r, tarea_id) is None:            # para poder revisarla tiene que verla: se le comparte como observador
                conn.execute("INSERT INTO tareas_participantes (tarea_id, usuario_id, rol, compartida_en) VALUES (?, ?, 'observa', ?) ON CONFLICT DO NOTHING", (tarea_id, r, db.now_iso()))
        auditoria.registrar(tenant, usuario_id, "tarea.revision.solicitar", "tarea", tarea_id, {"revisores": ids, "modo": modo}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    db.registrar_actividad_tarea(usuario_id, tarea_id, "revision_solicitada", ", ".join(db.nombre_mostrado_usuario(r) or "" for r in ids))
    db._emitir_evento(usuario_id, "tarea.estado_cambiado", {"tarea_id": tarea_id, "de": previo, "a": "en_revision"})
    for r in (ids[:1] if modo == "cadena" else ids):               # en cadena solo se avisa a quien tiene el turno
        _avisar(r, f"Te piden revisar: {tarea['asunto']}", (nota or "").strip() or "Revisión pendiente", tarea_id)
    return revision_id


def resolver_revision(usuario_id: int, tarea_id: int, decision: str, nota: str | None = None) -> dict:
    """El voto de un revisor. Devuelve la revisión: si ese voto la cierra, con su estado final; si faltan votos, sigue `pendiente` con quién falta."""
    if decision not in DECISIONES:
        raise TransicionInvalida("decision_invalida", "La decisión tiene que ser aprobar o pedir cambios.", "decision")
    nota = (nota or "").strip()[:500]
    if decision == "cambios" and not nota:
        raise TransicionInvalida("nota_obligatoria", "Explica qué hay que cambiar.", "nota")
    rev = revision_pendiente(tarea_id)
    if rev is None or db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        raise TransicionInvalida("no_encontrada", "No hay ninguna revisión pendiente en esta tarea.")
    if usuario_id not in rev["revisores"]:
        raise TransicionInvalida("sin_permiso", "Solo puede resolverla la persona designada para revisar.")
    if usuario_id not in rev["pendientes"]:
        raise TransicionInvalida("ya_has_votado", "Ya has votado en esta revisión.")
    if usuario_id not in rev["pueden_votar"]:
        raise TransicionInvalida("no_es_tu_turno", f"Todavía no es tu turno: revisa antes {db.nombre_mostrado_usuario(rev['turno']) or 'la persona anterior'}.")
    voto = "aprobado" if decision == "aprobar" else "cambios"
    conn = db.get_connection()
    previo = None
    destino = "en_progreso"
    try:
        cur = conn.execute("UPDATE tarea_revision_votos SET estado = ?, nota = ?, votado_en = ? WHERE revision_id = ? AND revisor_id = ? AND estado = 'pendiente'",
                           (voto, nota or None, db.now_iso(), rev["id"], usuario_id))
        if cur.rowcount == 0:                                  # otra petición se adelantó
            raise TransicionInvalida("ya_has_votado", "Ya has votado en esta revisión.")
        restantes = conn.execute("SELECT COUNT(*) FROM tarea_revision_votos WHERE revision_id = ? AND estado = 'pendiente'", (rev["id"],)).fetchone()[0]
        final = None
        if decision == "cambios":
            final = "cambios"
        elif rev["modo"] == "cualquiera" or restantes == 0:
            final = "aprobada"
        if final:
            cur = conn.execute("UPDATE tarea_revisiones SET estado = ?, nota_resolucion = ?, resuelta_en = ?, resuelta_por = ? WHERE id = ? AND estado = 'pendiente'",
                               (final, nota or None, db.now_iso(), usuario_id, rev["id"]))
            if cur.rowcount == 0:                              # otro voto la cerró un instante antes (p. ej. unos cambios): este voto queda anotado, la revisión ya está resuelta
                final = None
            elif final == "cambios":
                previo = conn.execute("SELECT estado FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
                conn.execute("UPDATE tareas_outlook SET estado = 'en_progreso', fecha_completada = NULL, actualizada_en = ? WHERE id = ? AND estado != 'en_progreso'", (db.now_iso(), tarea_id))
            elif final == "aprobada":                         # aprobada: la tarea vuelve al estado del que venía (aprobar no la completa; lo hace quien la lleva)
                previo = conn.execute("SELECT estado FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
                destino = _estado_al_salir_de_revision(conn, rev["id"])
                conn.execute("UPDATE tareas_outlook SET estado = ?, actualizada_en = ? WHERE id = ? AND estado = 'en_revision'", (destino, db.now_iso(), tarea_id))
        auditoria.registrar(rev["tenant_id"], usuario_id, "tarea.revision.voto", "tarea", tarea_id, {"revision": rev["id"], "voto": voto}, conn=conn)
        if final:
            auditoria.registrar(rev["tenant_id"], usuario_id, "tarea.revision." + decision, "tarea", tarea_id, {"revision": rev["id"], "modo": rev["modo"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    asunto = db._asunto_tarea(tarea_id)
    quien = db.nombre_mostrado_usuario(usuario_id) or ""
    if final is None:
        db.registrar_actividad_tarea(usuario_id, tarea_id, "revision_voto", f"{quien} aprobó ({rev['aprobados'] + 1} de {len(rev['revisores'])})" if voto == "aprobado" else f"{quien} pidió cambios")
        pendientes = [p for p in rev["pendientes"] if p != usuario_id]
        if rev["modo"] == "cadena" and pendientes:                      # le toca al siguiente de la cadena
            _avisar(pendientes[0], f"Te toca revisar: {asunto}", f"{quien} ya la ha aprobado", tarea_id)
        return {**rev, "estado": "pendiente", "pendientes": pendientes, "turno": pendientes[0] if rev["modo"] == "cadena" and pendientes else None, "nota_resolucion": None}
    if final in ("cambios", "aprobada") and previo is not None and previo["estado"] != destino:
        db._emitir_evento(usuario_id, "tarea.estado_cambiado", {"tarea_id": tarea_id, "de": previo["estado"], "a": destino})
    db.registrar_actividad_tarea(usuario_id, tarea_id, "revision_aprobada" if final == "aprobada" else "revision_cambios", f"{quien}: {nota}" if nota else quien)
    _avisar(rev["solicitada_por"], (f"Revisión aprobada: {asunto}" if final == "aprobada" else f"Piden cambios: {asunto}"), (f"{quien}: " if len(rev["revisores"]) > 1 else "") + (nota or "Sin comentarios"), tarea_id)
    return {**rev, "estado": final, "nota_resolucion": nota or None, "pendientes": []}


def _estado_al_salir_de_revision(conn, revision_id: int) -> str:
    """El estado que tenía la tarea al pedir la revisión; «en progreso» si no consta o ya no vale (completada o la propia revisión)."""
    f = conn.execute("SELECT estado_previo FROM tarea_revisiones WHERE id = ?", (revision_id,)).fetchone()
    previo = f["estado_previo"] if f else None
    return previo if previo in ESTADOS and previo not in ("en_revision", "completada") else "en_progreso"


def cancelar_revision(usuario_id: int, tarea_id: int) -> bool:
    """Quien la pidió o el dueño de la tarea retira la revisión pendiente."""
    rev = revision_pendiente(tarea_id)
    tarea = db.obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if rev is None or tarea is None or usuario_id not in (rev["solicitada_por"], tarea["usuario_id"]):
        return False
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE tarea_revisiones SET estado = 'cancelada', resuelta_en = ?, resuelta_por = ? WHERE id = ? AND estado = 'pendiente'", (db.now_iso(), usuario_id, rev["id"]))
        devuelta = None
        if cur.rowcount:                                      # retirada: la tarea vuelve al estado del que venía
            destino = _estado_al_salir_de_revision(conn, rev["id"])
            if conn.execute("UPDATE tareas_outlook SET estado = ?, actualizada_en = ? WHERE id = ? AND estado = 'en_revision'", (destino, db.now_iso(), tarea_id)).rowcount:
                devuelta = destino
        auditoria.registrar(rev["tenant_id"], usuario_id, "tarea.revision.cancelar", "tarea", tarea_id, {"revision": rev["id"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    if devuelta:
        db._emitir_evento(usuario_id, "tarea.estado_cambiado", {"tarea_id": tarea_id, "de": "en_revision", "a": devuelta})
    return bool(cur.rowcount)


# --- Colaboración con el cliente (portal) ------------------------------------------------------------------------------------
# Nada de una tarea sale al portal por defecto. Quien edita la tarea decide, tarea a tarea, enseñársela al cliente al que está vinculada. El cliente ve SOLO el asunto, el estado y la fecha
# límite: nunca la descripción, los comentarios internos, los adjuntos, quién la lleva, el motivo del bloqueo ni las subtareas (a menos que tengan su propia marca).
# Comentarios del cliente (segundo permiso, también por tarea y apagado por defecto): el cliente puede escribir en las tareas ABIERTAS que se le enseñan y el equipo le contesta desde la
# ficha. Es una conversación aparte (`tarea_comentarios_cliente`), nunca mezclada con los comentarios internos. Política, explícita:
#   - solo texto, hasta 1.000 caracteres; como mucho 10 comentarios por hora por tarea y 40 al día en total por cliente (lo demás se rechaza con un aviso, no se guarda);
#   - cada cliente ve solo su propia conversación (lo que escribió y lo que se le contestó a él), aunque la tarea esté vinculada a varios;
#   - el equipo puede ocultar un comentario (queda en la base, auditado, pero ya no se ve en el portal ni cuenta); contestar al cliente le manda un correo con un enlace al portal;
#   - si la tarea se completa, se borra o se deja de enseñar, el cliente deja de poder comentar y de verla (la conversación se conserva para el equipo).

ESTADOS_PARA_CLIENTE = {"no_iniciada": "Pendiente", "en_progreso": "En curso", "esperando": "En espera", "aplazada": "Aplazada", "completada": "Completada", "en_revision": "En curso"}      # la revisión interna no se le cuenta al cliente
MAX_CARACTERES_COMENTARIO = 1000
MAX_COMENTARIOS_POR_HORA_Y_TAREA = 10
MAX_COMENTARIOS_POR_DIA = 40


class ComentarioInvalido(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo


def fijar_visible_cliente(usuario_id: int, tarea_id: int, visible: bool, comentarios: bool | None = None) -> None:
    """`visible`: enseñar la tarea al cliente. `comentarios`: dejar que además escriba en ella (solo con `visible`; si se deja de enseñar, se apaga también). None = no cambia."""
    if db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if not db.puede_editar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para cambiar lo que ve el cliente.")
    if visible and not clientes_de_tarea(tarea_id):
        raise TransicionInvalida("sin_cliente", "La tarea no está vinculada a ningún cliente.")
    if comentarios and not visible:
        raise TransicionInvalida("comentarios_sin_visible", "Para que el cliente pueda comentar, primero hay que enseñarle la tarea.")
    if not visible:
        comentarios = False
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE tareas_outlook SET visible_cliente = ? WHERE id = ? AND visible_cliente != ?", (1 if visible else 0, tarea_id, 1 if visible else 0))
        if cur.rowcount:
            auditoria.registrar(_tenant_de_usuario(conn, usuario_id), usuario_id, "tarea.visible_cliente", "tarea", tarea_id, {"visible": bool(visible)}, conn=conn)
        if comentarios is not None:
            cur = conn.execute("UPDATE tareas_outlook SET comentarios_cliente = ? WHERE id = ? AND comentarios_cliente != ?", (1 if comentarios else 0, tarea_id, 1 if comentarios else 0))
            if cur.rowcount:
                auditoria.registrar(_tenant_de_usuario(conn, usuario_id), usuario_id, "tarea.comentarios_cliente", "tarea", tarea_id, {"permitidos": bool(comentarios)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    db.registrar_actividad_tarea(usuario_id, tarea_id, "visible_cliente" if visible else "oculta_cliente")


_VISIBLE_PARA_CLIENTE = """t.visible_cliente = 1 AND t.papelera_en IS NULL AND u.tenant_id = ?
                 AND (t.cliente_fiscal_id = ? OR t.id IN (SELECT tarea_id FROM tarea_clientes WHERE cliente_fiscal_id = ? AND tenant_id = ?))"""


def tareas_para_cliente(tenant_id: int, cliente_fiscal_id: int) -> list[dict]:
    """Lo que el portal enseña a ese cliente: solo tareas marcadas, de su propio despacho, vinculadas a él, fuera de la papelera. Abiertas primero, por fecha. Cada una lleva su conversación
    (lo que él escribió y se le contestó) y si puede comentar ahora."""
    conn = db.get_connection()
    try:
        filas = conn.execute(
            f"""SELECT t.id, t.asunto, t.estado, t.fecha_vencimiento, t.comentarios_cliente FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id
                WHERE {_VISIBLE_PARA_CLIENTE}
                ORDER BY (t.estado = 'completada'), t.fecha_vencimiento IS NULL, t.fecha_vencimiento, t.id LIMIT 100""",
            (tenant_id, cliente_fiscal_id, cliente_fiscal_id, tenant_id)).fetchall()
        ids = [f["id"] for f in filas]
        hilos: dict[int, list[dict]] = {}
        if ids:
            filas_c = conn.execute(f"SELECT id, tarea_id, autor, texto, creado_en FROM tarea_comentarios_cliente WHERE cliente_fiscal_id = ? AND oculto_en IS NULL AND tarea_id IN ({','.join('?' * len(ids))}) ORDER BY id",
                                   (cliente_fiscal_id, *ids)).fetchall()
            adj = _adjuntos_por_comentario(conn, [c["id"] for c in filas_c])
            for c in filas_c:
                hilos.setdefault(c["tarea_id"], []).append({"autor": c["autor"], "texto": c["texto"], "creado_en": c["creado_en"], "adjuntos": adj.get(c["id"], [])})
        return [{"id": f["id"], "asunto": f["asunto"], "estado": f["estado"], "estado_texto": ESTADOS_PARA_CLIENTE.get(f["estado"], f["estado"]),
                 "fecha_vencimiento": f["fecha_vencimiento"][:10] if f["fecha_vencimiento"] else None, "vencida": esta_vencida(f["fecha_vencimiento"], f["estado"]),
                 "puede_comentar": bool(f["comentarios_cliente"]) and f["estado"] != "completada", "comentarios": hilos.get(f["id"], [])} for f in filas]
    finally:
        conn.close()


# Archivos del cliente en sus comentarios. Es contenido de un tercero y se trata como tal: solo PDF e imágenes, comprobados por su contenido (no por lo que diga el nombre o el navegador),
# hasta 3 por comentario y 5 MB cada uno, 15 por tarea y 30 al día por cliente; nada con claves privadas. Viven en su propia tabla (nunca mezclados con los adjuntos del equipo), cada cliente
# solo descarga los suyos, se sirven siempre como descarga y sin ejecutar nada, y un comentario oculto se lleva sus archivos (no se ven ni en el portal ni en la ficha). No se analizan con antivirus.
TIPOS_ADJUNTO_CLIENTE = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
MAX_ADJUNTO_CLIENTE_BYTES = 5 * 1024 * 1024
MAX_ADJUNTOS_POR_COMENTARIO = 3
MAX_ADJUNTOS_CLIENTE_POR_TAREA = 15
MAX_ADJUNTOS_CLIENTE_POR_DIA = 30


def _firma_valida(ext: str, contenido: bytes) -> bool:
    cabecera = contenido[:16]
    if ext == "pdf":
        return cabecera.startswith(b"%PDF-")
    if ext == "png":
        return cabecera.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return cabecera.startswith(b"\xff\xd8\xff")
    if ext == "gif":
        return cabecera.startswith((b"GIF87a", b"GIF89a"))
    if ext == "webp":
        return cabecera.startswith(b"RIFF") and cabecera[8:12] == b"WEBP"
    return False


def _validar_adjuntos_cliente(archivos, tenant_id: int | None = None, cliente_fiscal_id: int | None = None) -> list[tuple[str, str, bytes]]:
    """[(nombre seguro, tipo que decide el servidor, contenido)] o ComentarioInvalido. `archivos`: lista de (nombre, bytes); los vacíos (sin nombre) se ignoran."""
    import hashlib
    from . import certificados
    validos, vistos = [], set()
    for nombre, contenido in [a for a in (archivos or []) if a and a[0]]:
        if len(validos) >= MAX_ADJUNTOS_POR_COMENTARIO:
            raise ComentarioInvalido("demasiados_archivos", f"Puedes adjuntar hasta {MAX_ADJUNTOS_POR_COMENTARIO} archivos por comentario.")
        nombre = db._nombre_de_archivo_seguro(nombre or "")[:150]
        ext = _extension(nombre)
        if ext not in TIPOS_ADJUNTO_CLIENTE:
            raise ComentarioInvalido("tipo_no_admitido", "Solo se admiten PDF e imágenes (PNG, JPG, WEBP o GIF).")
        if not contenido:
            raise ComentarioInvalido("archivo_vacio", "Uno de los archivos está vacío.")
        if len(contenido) > MAX_ADJUNTO_CLIENTE_BYTES:
            raise ComentarioInvalido("archivo_grande", f"Cada archivo puede pesar como máximo {MAX_ADJUNTO_CLIENTE_BYTES // (1024 * 1024)} MB.")
        if not _firma_valida(ext, contenido) or certificados.contiene_clave_privada(contenido):
            raise ComentarioInvalido("tipo_no_admitido", "Solo se admiten PDF e imágenes (PNG, JPG, WEBP o GIF).")
        huella = hashlib.sha256(contenido).hexdigest()
        if huella in vistos:
            continue
        vistos.add(huella)
        try:
            antivirus.exigir_limpio(nombre, contenido, tenant_id, cliente_fiscal_id)           # apagado por defecto (ver app/antivirus.py)
        except antivirus.ArchivoRechazado as e:
            raise ComentarioInvalido(e.codigo, str(e)) from None
        validos.append((nombre, TIPOS_ADJUNTO_CLIENTE[ext], contenido))
    return validos


def comentar_como_cliente(tenant_id: int, cliente_fiscal_id: int, tarea_id: int, texto: str, archivos=None) -> dict:
    """El cliente escribe en una tarea que se le enseña y en la que se le deja comentar, con hasta 3 archivos (`archivos`: lista de (nombre, bytes)). Todo o nada: si algo no vale, no se guarda ni el texto.
    Devuelve {"id", "tarea", "destinatarios", "adjuntos"} (a quién avisar). Lanza ComentarioInvalido con un código estable."""
    texto = (texto or "").strip()
    if not texto:
        raise ComentarioInvalido("vacio", "Escribe algo antes de enviar.")
    if len(texto) > MAX_CARACTERES_COMENTARIO:
        raise ComentarioInvalido("largo", f"El comentario admite como máximo {MAX_CARACTERES_COMENTARIO} caracteres.")
    texto = "".join(c for c in texto if c == "\n" or c >= " ")                       # fuera caracteres de control
    adjuntos = _validar_adjuntos_cliente(archivos, tenant_id, cliente_fiscal_id)
    conn = db.get_connection()
    try:
        t = conn.execute(
            f"""SELECT t.id, t.asunto, t.estado, t.comentarios_cliente, t.usuario_id, t.asignada_a FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id
                WHERE t.id = ? AND {_VISIBLE_PARA_CLIENTE}""", (tarea_id, tenant_id, cliente_fiscal_id, cliente_fiscal_id, tenant_id)).fetchone()
        if t is None or not t["comentarios_cliente"]:
            raise ComentarioInvalido("no_encontrada", "No se puede comentar en esta tarea.")
        if t["estado"] == "completada":
            raise ComentarioInvalido("cerrada", "Esta tarea ya está completada.")
        ahora = datetime.now()
        hace_una_hora = (ahora - timedelta(hours=1)).isoformat(timespec="seconds")
        hace_un_dia = (ahora - timedelta(days=1)).isoformat(timespec="seconds")
        if conn.execute("SELECT COUNT(*) FROM tarea_comentarios_cliente WHERE tarea_id = ? AND cliente_fiscal_id = ? AND autor = 'cliente' AND creado_en >= ?", (tarea_id, cliente_fiscal_id, hace_una_hora)).fetchone()[0] >= MAX_COMENTARIOS_POR_HORA_Y_TAREA \
                or conn.execute("SELECT COUNT(*) FROM tarea_comentarios_cliente WHERE cliente_fiscal_id = ? AND autor = 'cliente' AND creado_en >= ?", (cliente_fiscal_id, hace_un_dia)).fetchone()[0] >= MAX_COMENTARIOS_POR_DIA:
            raise ComentarioInvalido("limite", "Has enviado muchos comentarios seguidos. Espera un rato y vuelve a intentarlo.")
        if adjuntos:
            if conn.execute("SELECT COUNT(*) FROM tarea_comentarios_cliente_adjuntos WHERE tarea_id = ? AND cliente_fiscal_id = ?", (tarea_id, cliente_fiscal_id)).fetchone()[0] + len(adjuntos) > MAX_ADJUNTOS_CLIENTE_POR_TAREA:
                raise ComentarioInvalido("limite_archivos", f"Esta tarea ya tiene muchos archivos tuyos (máximo {MAX_ADJUNTOS_CLIENTE_POR_TAREA}).")
            if conn.execute("SELECT COUNT(*) FROM tarea_comentarios_cliente_adjuntos WHERE cliente_fiscal_id = ? AND creado_en >= ?", (cliente_fiscal_id, hace_un_dia)).fetchone()[0] + len(adjuntos) > MAX_ADJUNTOS_CLIENTE_POR_DIA:
                raise ComentarioInvalido("limite_archivos", "Has subido muchos archivos hoy. Vuelve a intentarlo mañana.")
        cur = conn.execute("INSERT INTO tarea_comentarios_cliente (tenant_id, tarea_id, cliente_fiscal_id, autor, texto, creado_en) VALUES (?, ?, ?, 'cliente', ?, ?)",
                           (tenant_id, tarea_id, cliente_fiscal_id, texto, ahora.isoformat(timespec="seconds")))
        import hashlib
        for nombre, mime, contenido in adjuntos:
            conn.execute("INSERT INTO tarea_comentarios_cliente_adjuntos (tenant_id, comentario_id, tarea_id, cliente_fiscal_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, hash_sha256, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, cur.lastrowid, tarea_id, cliente_fiscal_id, nombre, mime, len(contenido), contenido, hashlib.sha256(contenido).hexdigest(), ahora.isoformat(timespec="seconds")))
        auditoria.registrar(tenant_id, None, "tarea.comentario_cliente", "tarea", tarea_id, {"comentario": cur.lastrowid, "cliente": cliente_fiscal_id, "archivos": len(adjuntos)}, conn=conn)
        conn.commit()
        return {"id": cur.lastrowid, "tarea": {"id": t["id"], "asunto": t["asunto"]}, "destinatarios": sorted({u for u in (t["usuario_id"], t["asignada_a"]) if u}), "adjuntos": len(adjuntos)}
    finally:
        conn.close()


def _adjuntos_por_comentario(conn, comentario_ids: list[int]) -> dict[int, list[dict]]:
    """Metadatos (sin el contenido) de los archivos de esos comentarios. Quien llama ya excluyó los ocultos."""
    res: dict[int, list[dict]] = {}
    for i in range(0, len(comentario_ids), 500):
        lote = comentario_ids[i:i + 500]
        for a in conn.execute(f"SELECT id, comentario_id, nombre_archivo, tipo_mime, tamano_bytes FROM tarea_comentarios_cliente_adjuntos WHERE comentario_id IN ({','.join('?' * len(lote))}) ORDER BY id", lote):
            res.setdefault(a["comentario_id"], []).append({"id": a["id"], "nombre": a["nombre_archivo"], "tipo": a["tipo_mime"], "tamano": a["tamano_bytes"]})
    return res


def leer_adjunto_de_cliente_para_cliente(tenant_id: int, cliente_fiscal_id: int, adjunto_id: int) -> dict | None:
    """Un cliente descarga SOLO sus archivos, de comentarios no ocultos y en tareas que el despacho le sigue enseñando. Cualquier otra cosa es None (404)."""
    conn = db.get_connection()
    try:
        f = conn.execute(
            f"""SELECT a.* FROM tarea_comentarios_cliente_adjuntos a JOIN tarea_comentarios_cliente c ON c.id = a.comentario_id
                WHERE a.id = ? AND a.cliente_fiscal_id = ? AND a.tenant_id = ? AND c.oculto_en IS NULL
                  AND a.tarea_id IN (SELECT t.id FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id WHERE {_VISIBLE_PARA_CLIENTE})""",
            (adjunto_id, cliente_fiscal_id, tenant_id, tenant_id, cliente_fiscal_id, cliente_fiscal_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return None if f is None else {"nombre_archivo": f["nombre_archivo"], "tipo_mime": f["tipo_mime"], "contenido": bytes(f["contenido"]), "imagen": False}


def leer_adjunto_de_cliente_para_equipo(usuario_id: int, adjunto_id: int) -> dict | None:
    """El equipo descarga el archivo de un cliente si ve la tarea y el comentario no está oculto."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT a.* FROM tarea_comentarios_cliente_adjuntos a JOIN tarea_comentarios_cliente c ON c.id = a.comentario_id WHERE a.id = ? AND c.oculto_en IS NULL", (adjunto_id,)).fetchone()
    finally:
        conn.close()
    if f is None or db.obtener_tarea_outlook_visible(usuario_id, f["tarea_id"]) is None:
        return None
    return {"nombre_archivo": f["nombre_archivo"], "tipo_mime": f["tipo_mime"], "contenido": bytes(f["contenido"]), "imagen": False}


def conversaciones_con_clientes(usuario_id: int, tarea_id: int) -> list[dict]:
    """Para el equipo: una conversación por cliente vinculado que haya escrito o a quien se haya contestado, con lo no leído. Lo ocultado se ve marcado. Solo quien ve la tarea."""
    if db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        return []
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            """SELECT c.*, cf.nombre AS cliente FROM tarea_comentarios_cliente c JOIN clientes_fiscales cf ON cf.id = c.cliente_fiscal_id WHERE c.tarea_id = ? ORDER BY c.id""", (tarea_id,))]
    finally:
        conn.close()
    conn = db.get_connection()
    try:
        adj = _adjuntos_por_comentario(conn, [f["id"] for f in filas if f["oculto_en"] is None])
    finally:
        conn.close()
    por_cliente: dict[int, dict] = {}
    for f in filas:
        f["adjuntos"] = adj.get(f["id"], [])
        h = por_cliente.setdefault(f["cliente_fiscal_id"], {"cliente_fiscal_id": f["cliente_fiscal_id"], "cliente": f["cliente"], "mensajes": [], "sin_leer": 0})
        f["usuario"] = db.nombre_mostrado_usuario(f["usuario_id"]) if f["usuario_id"] else None
        h["mensajes"].append(f)
        if f["autor"] == "cliente" and f["leido_en"] is None and f["oculto_en"] is None:
            h["sin_leer"] += 1
    return list(por_cliente.values())


def marcar_conversaciones_leidas(usuario_id: int, tarea_id: int) -> None:
    if db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        return
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tarea_comentarios_cliente SET leido_en = ? WHERE tarea_id = ? AND autor = 'cliente' AND leido_en IS NULL", (db.now_iso(), tarea_id))
        conn.commit()
    finally:
        conn.close()


def sin_leer_de_clientes(tarea_id: int) -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM tarea_comentarios_cliente WHERE tarea_id = ? AND autor = 'cliente' AND leido_en IS NULL AND oculto_en IS NULL", (tarea_id,)).fetchone()[0]
    finally:
        conn.close()


def responder_al_cliente(usuario_id: int, tarea_id: int, cliente_fiscal_id: int, texto: str) -> dict:
    """El equipo contesta a un cliente en la conversación de esa tarea. Quien trabaja la tarea; el cliente tiene que estar vinculado a ella. Devuelve {"id", "cliente_fiscal_id"}."""
    if db.obtener_tarea_outlook_visible(usuario_id, tarea_id) is None:
        raise TransicionInvalida("no_encontrada", "Tarea no encontrada.")
    if not db.puede_trabajar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para contestar al cliente en esta tarea.")
    texto = (texto or "").strip()
    if not texto:
        raise TransicionInvalida("vacio", "Escribe la respuesta.", "texto")
    if len(texto) > MAX_CARACTERES_COMENTARIO:
        raise TransicionInvalida("largo", f"La respuesta admite como máximo {MAX_CARACTERES_COMENTARIO} caracteres.", "texto")
    if int(cliente_fiscal_id or 0) not in {c["id"] for c in clientes_de_tarea(tarea_id)}:
        raise TransicionInvalida("cliente_invalido", "Ese cliente no está vinculado a la tarea.", "cliente_fiscal_id")
    conn = db.get_connection()
    try:
        tenant = _tenant_de_usuario(conn, usuario_id)
        cur = conn.execute("INSERT INTO tarea_comentarios_cliente (tenant_id, tarea_id, cliente_fiscal_id, autor, usuario_id, texto, creado_en, leido_en) VALUES (?, ?, ?, 'despacho', ?, ?, ?, ?)",
                           (tenant, tarea_id, int(cliente_fiscal_id), usuario_id, texto, db.now_iso(), db.now_iso()))
        auditoria.registrar(tenant, usuario_id, "tarea.respuesta_cliente", "tarea", tarea_id, {"comentario": cur.lastrowid, "cliente": int(cliente_fiscal_id)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    db.registrar_actividad_tarea(usuario_id, tarea_id, "respuesta_cliente")
    return {"id": cur.lastrowid, "cliente_fiscal_id": int(cliente_fiscal_id)}


AVISO_CORREO_MINUTOS = 60


def avisar_por_correo_comentario_cliente(destinatario_id: int, tarea_id: int, asunto_tarea: str, cliente_nombre: str, tenant_id: int | None, url: str) -> bool:
    """Correo al equipo cuando un cliente comenta en una tarea. Opt-in de cada persona (`usuario_perfil.avisos_cliente_por_correo`), solo a su propio correo, SIN el texto del cliente (el correo es un canal
    menos protegido que la ficha: dice quién y en qué tarea, y el enlace lleva a leerlo) y como mucho UNO por persona y tarea cada hora, aunque el cliente escriba diez veces. Se anota antes de enviar: nunca
    dos veces. True si salió; un fallo o la falta de correo nunca afecta al comentario."""
    from datetime import datetime, timedelta
    from . import correo_diseno, notificaciones_email
    from .notificaciones_email import _
    if not notificaciones_email.configurado():
        return False
    ahora = datetime.now().replace(microsecond=0)
    conn = db.get_connection()
    try:
        perfil = conn.execute("SELECT avisos_cliente_por_correo FROM usuario_perfil WHERE usuario_id = ?", (destinatario_id,)).fetchone()
        correo = conn.execute("SELECT email FROM usuarios WHERE id = ?", (destinatario_id,)).fetchone()
        if not perfil or not perfil["avisos_cliente_por_correo"] or not correo or not correo["email"]:
            return False
        limite = (ahora - timedelta(minutes=AVISO_CORREO_MINUTOS)).isoformat()
        cur = conn.execute("UPDATE tarea_avisos_correo SET enviado_en = ? WHERE usuario_id = ? AND tarea_id = ? AND enviado_en < ?", (ahora.isoformat(), destinatario_id, tarea_id, limite))
        if cur.rowcount == 0:
            cur = conn.execute("INSERT INTO tarea_avisos_correo (usuario_id, tarea_id, enviado_en) VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (destinatario_id, tarea_id, ahora.isoformat()))
        conn.commit()
        if cur.rowcount == 0:                                  # ya se avisó hace menos de una hora
            return False
        destino = correo["email"]
    finally:
        conn.close()
    try:
        titulo = _("Un cliente ha comentado en una tarea")
        plano, html = correo_diseno.construir(titulo, [_("%(cliente)s ha escrito en la tarea «%(tarea)s». Ábrela para leerlo y contestar.", cliente=cliente_nombre, tarea=asunto_tarea)],
                                              boton=(_("Abrir la tarea"), url), aviso=_("Recibes este aviso porque lo activaste en tu perfil, en Notificaciones. Como mucho te escribimos una vez por hora y tarea."),
                                              preencabezado=cliente_nombre, marca=notificaciones_email._marca(tenant_id))
        notificaciones_email._enviar(destino, notificaciones_email._asunto(titulo, tenant_id), plano, html)
    except Exception:  # noqa: BLE001
        return False
    return True


def avisar_respuesta_al_cliente(tenant_id: int | None, cliente_fiscal_id: int, texto: str, url_entrada: str) -> bool:
    """Correo al cliente avisando de que tiene una respuesta (con el enlace de entrada al portal, como en los mensajes de los vencimientos). True si salió; un fallo o la falta de correo nunca estropea la respuesta, que ya está guardada."""
    from . import notificaciones_email
    cliente = db.obtener_cliente_fiscal(tenant_id, cliente_fiscal_id) if tenant_id else None
    if cliente is None or not cliente["email"]:
        return False
    try:
        notificaciones_email.enviar_respuesta_portal(cliente["email"], (texto or "").strip(), url_entrada, tenant_id=tenant_id)
    except notificaciones_email.ErrorNotificacionesEmail:
        return False
    return True


def ocultar_comentario_de_cliente(usuario_id: int, comentario_id: int) -> int | None:
    """Moderación: oculta un comentario del cliente (no se borra: queda en la base y en la auditoría). Quien trabaja la tarea. Devuelve el id de la tarea, o None si no se pudo."""
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT tarea_id, tenant_id FROM tarea_comentarios_cliente WHERE id = ? AND oculto_en IS NULL", (comentario_id,)).fetchone()
        if c is None or not db.puede_trabajar_tarea(usuario_id, c["tarea_id"]):
            return None
        conn.execute("UPDATE tarea_comentarios_cliente SET oculto_en = ?, oculto_por = ? WHERE id = ?", (db.now_iso(), usuario_id, comentario_id))
        auditoria.registrar(c["tenant_id"], usuario_id, "tarea.comentario_cliente.ocultar", "tarea", c["tarea_id"], {"comentario": comentario_id}, conn=conn)
        conn.commit()
        return c["tarea_id"]
    finally:
        conn.close()
