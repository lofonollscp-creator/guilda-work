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


def fijar_clientes(usuario_id: int, tarea_id: int, cliente_ids: list[int], principal_id: int | None = None, version: int | None = None) -> list[dict]:
    """Sustituye los clientes de la tarea. Reglas: quien edita la tarea; todos los clientes del mismo despacho que la persona (los demás se rechazan, no se ignoran);
    sin repetidos; un solo principal (el indicado o, si no, el primero); `tareas_outlook.cliente_fiscal_id` queda igual al principal. Lista vacía = tarea sin cliente."""
    if not db.puede_editar_tarea(usuario_id, tarea_id):
        raise TransicionInvalida("sin_permiso", "No tienes permiso para cambiar los clientes de esta tarea.")
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
