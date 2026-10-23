"""Acceso a datos de los proyectos compartidos.

Parte de la antigua `db.py`, dividida por dominios sin cambiar su comportamiento: todo lo que no está aquí (la conexión, las constantes y las funciones de otros
dominios) se usa a través de `_db`, que sigue siendo el único espacio de nombres (`_db.nombre` funciona igual que antes y se puede parchear en los tests)."""
import hashlib
import json
import time
import os
import re
import random
import secrets
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

from . import db as _db


def _rol_en_proyecto(conn: sqlite3.Connection, usuario_id: int, categoria_id: int | None) -> str | None:
    """'dueno', 'colabora', 'observa' o None. Un supervisor del despacho ve (solo lectura) todo proyecto compartido."""
    if categoria_id is None:
        return None
    c = conn.execute("SELECT usuario_id, proy_compartido FROM categorias WHERE id = ? AND papelera_en IS NULL", (categoria_id,)).fetchone()
    if c is None:
        return None
    if c["usuario_id"] == usuario_id:
        return "dueno"
    if not c["proy_compartido"]:
        return None
    m = conn.execute(
        """SELECT m.rol FROM proyecto_miembros m
           JOIN usuarios um ON um.id = m.usuario_id JOIN usuarios uo ON uo.id = ?
           WHERE m.categoria_id = ? AND m.usuario_id = ? AND um.tenant_id IS NOT NULL AND um.tenant_id = uo.tenant_id""",
        (c["usuario_id"], categoria_id, usuario_id),
    ).fetchone()
    if m is not None:
        return m["rol"]
    sup = conn.execute(
        """SELECT 1 FROM usuarios us JOIN usuarios uo ON uo.id = ?
           WHERE us.id = ? AND us.supervisor_tenant = 1 AND uo.tenant_id IS NOT NULL AND us.tenant_id = uo.tenant_id""",
        (c["usuario_id"], usuario_id),
    ).fetchone()
    return "observa" if sup else None


def rol_en_proyecto(usuario_id: int, categoria_id: int) -> str | None:
    conn = _db.get_connection()
    try:
        return _db._rol_en_proyecto(conn, usuario_id, categoria_id)
    finally:
        conn.close()


def obtener_proyecto(usuario_id: int, categoria_id: int) -> dict | None:
    """El proyecto (con `rol` y el nombre de su dueño y de su responsable) si el usuario puede verlo."""
    conn = _db.get_connection()
    try:
        rol = _db._rol_en_proyecto(conn, usuario_id, categoria_id)
        if rol is None:
            return None
        f = conn.execute(
            """SELECT c.*, COALESCE(NULLIF(pd.nombre_mostrado, ''), ud.email) AS dueno_nombre,
                      COALESCE(NULLIF(pr.nombre_mostrado, ''), ur.email) AS responsable_nombre, cf.nombre AS cliente_nombre,
                      c.proy_estado AS estado, c.proy_descripcion AS descripcion, c.proy_fecha_objetivo AS fecha_objetivo,
                      c.proy_responsable_id AS responsable_id, c.proy_cliente_id AS cliente_fiscal_id, c.proy_compartido AS compartido
               FROM categorias c JOIN usuarios ud ON ud.id = c.usuario_id LEFT JOIN usuario_perfil pd ON pd.usuario_id = c.usuario_id
               LEFT JOIN usuarios ur ON ur.id = c.proy_responsable_id LEFT JOIN usuario_perfil pr ON pr.usuario_id = c.proy_responsable_id
               LEFT JOIN clientes_fiscales cf ON cf.id = c.proy_cliente_id
               WHERE c.id = ?""",
            (categoria_id,),
        ).fetchone()
        proyecto = dict(f)
        proyecto["rol"] = rol
        return proyecto
    finally:
        conn.close()


def listar_proyectos_compartidos_conmigo(usuario_id: int) -> list[dict]:
    """Proyectos de otros que el usuario puede ver: como miembro o, si es supervisor, todos los compartidos
    del despacho (solo lectura). Una sola consulta (se pide en el inicio); mismas reglas que _rol_en_proyecto."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT c.*, COALESCE(NULLIF(pd.nombre_mostrado, ''), ud.email) AS dueno_nombre, COALESCE(m.rol, 'observa') AS rol
               FROM categorias c
               JOIN usuarios ud ON ud.id = c.usuario_id LEFT JOIN usuario_perfil pd ON pd.usuario_id = c.usuario_id
               JOIN usuarios yo ON yo.id = ?
               LEFT JOIN proyecto_miembros m ON m.categoria_id = c.id AND m.usuario_id = yo.id
               WHERE c.proy_compartido = 1 AND c.papelera_en IS NULL AND c.usuario_id != yo.id AND c.proy_estado != 'archivado'
                 AND yo.tenant_id IS NOT NULL AND yo.tenant_id = ud.tenant_id
                 AND (m.usuario_id IS NOT NULL OR yo.supervisor_tenant = 1)
               ORDER BY c.nombre""",
            (usuario_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def listar_proyectos_usables(usuario_id: int) -> list[dict]:
    """Proyectos en los que se pueden poner tareas: los propios y los compartidos donde se colabora."""
    propios = [dict(c, propio=True, rol="dueno") for c in _db.listar_categorias(usuario_id)]
    ajenos = [dict(c, propio=False) for c in _db.listar_proyectos_compartidos_conmigo(usuario_id) if c["rol"] == "colabora"]
    return propios + ajenos


def miembros_de_proyecto(categoria_id: int) -> list[dict]:
    conn = _db.get_connection()
    try:
        c = conn.execute("SELECT usuario_id FROM categorias WHERE id = ?", (categoria_id,)).fetchone()
        if c is None:
            return []
        filas = conn.execute(
            """SELECT m.usuario_id, m.rol, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre, u.email
               FROM proyecto_miembros m JOIN usuarios u ON u.id = m.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = m.usuario_id
               JOIN usuarios uo ON uo.id = ? WHERE m.categoria_id = ? AND u.tenant_id IS NOT NULL AND u.tenant_id = uo.tenant_id
               ORDER BY nombre""",
            (c["usuario_id"], categoria_id),
        ).fetchall()
        return [dict(f, es_dueno=False) for f in filas]
    finally:
        conn.close()


def compartir_proyecto(usuario_id: int, categoria_id: int, otro_id: int, rol: str = "colabora") -> bool:
    """El dueño añade (o cambia el rol de) un compañero de su despacho. False si no procede."""
    if rol not in _db.ROLES_PROYECTO:
        return False
    conn = _db.get_connection()
    try:
        if _db._rol_en_proyecto(conn, usuario_id, categoria_id) != "dueno":
            return False
        destino = _db._companero_del_tenant(conn, usuario_id, otro_id)
        if destino is None:
            return False
        ya = conn.execute("SELECT 1 FROM proyecto_miembros WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, destino)).fetchone()
        if ya is None and conn.execute("SELECT COUNT(*) FROM proyecto_miembros WHERE categoria_id = ?", (categoria_id,)).fetchone()[0] >= _db.MAX_MIEMBROS_PROYECTO:
            return False
        conn.execute(
            """INSERT INTO proyecto_miembros (categoria_id, usuario_id, rol, anadido_en) VALUES (?, ?, ?, ?)
               ON CONFLICT (categoria_id, usuario_id) DO UPDATE SET rol = excluded.rol""",
            (categoria_id, destino, rol, _db.now_iso()),
        )
        conn.execute("UPDATE categorias SET proy_compartido = 1 WHERE id = ?", (categoria_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def quitar_miembro_proyecto(usuario_id: int, categoria_id: int, otro_id: int) -> bool:
    """El dueño quita a quien quiera; cada miembro puede salirse. Sin miembros, el proyecto vuelve a ser personal."""
    conn = _db.get_connection()
    try:
        rol = _db._rol_en_proyecto(conn, usuario_id, categoria_id)
        if rol is None or (rol != "dueno" and otro_id != usuario_id):
            return False
        cur = conn.execute("DELETE FROM proyecto_miembros WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, otro_id))
        if conn.execute("SELECT COUNT(*) FROM proyecto_miembros WHERE categoria_id = ?", (categoria_id,)).fetchone()[0] == 0:
            conn.execute("UPDATE categorias SET proy_compartido = 0 WHERE id = ?", (categoria_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def actualizar_proyecto(
    usuario_id: int, categoria_id: int, estado: str | None = None, descripcion: str | None = None,
    fecha_objetivo: str | None = None, responsable_id: int | None = None, cliente_fiscal_id: int | None = None,
    cambiar_responsable: bool = False, cambiar_cliente: bool = False,
) -> bool:
    """Datos del proyecto (solo el dueño). `responsable_id` ha de ser el propio dueño o un miembro; el cliente, del despacho."""
    conn = _db.get_connection()
    try:
        if _db._rol_en_proyecto(conn, usuario_id, categoria_id) != "dueno":
            return False
        campos: dict = {}
        if estado is not None:
            if estado not in _db.ESTADOS_PROYECTO:
                return False
            campos["proy_estado"] = estado
        if descripcion is not None:
            campos["proy_descripcion"] = descripcion.strip()[:2000] or None
        if fecha_objetivo is not None:
            try:
                campos["proy_fecha_objetivo"] = _db.datetime.strptime(fecha_objetivo.strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d") if fecha_objetivo.strip() else None
            except ValueError:
                return False
        if cambiar_responsable:
            if responsable_id is not None and responsable_id != usuario_id and conn.execute(
                "SELECT 1 FROM proyecto_miembros WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, responsable_id)
            ).fetchone() is None:
                return False
            campos["proy_responsable_id"] = responsable_id
        if cambiar_cliente:
            campos["proy_cliente_id"] = _db._cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id) if cliente_fiscal_id else None
        if not campos:
            return True
        conn.execute(f"UPDATE categorias SET {', '.join(c + ' = ?' for c in campos)} WHERE id = ?", [*campos.values(), categoria_id])
        conn.commit()
        return True
    finally:
        conn.close()


# --- secciones y tareas del proyecto ---

def listar_secciones(categoria_id: int) -> list[dict]:
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM proyecto_secciones WHERE categoria_id = ? ORDER BY orden, id", (categoria_id,))]
    finally:
        conn.close()


def _puede_organizar_proyecto(conn: sqlite3.Connection, usuario_id: int, categoria_id: int) -> bool:
    return _db._rol_en_proyecto(conn, usuario_id, categoria_id) in ("dueno", "colabora")


def crear_seccion(usuario_id: int, categoria_id: int, nombre: str) -> int | None:
    nombre = (nombre or "").strip()[:80]
    conn = _db.get_connection()
    try:
        if not nombre or not _db._puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return None
        siguiente = conn.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM proyecto_secciones WHERE categoria_id = ?", (categoria_id,)).fetchone()[0]
        cur = conn.execute("INSERT INTO proyecto_secciones (categoria_id, nombre, orden) VALUES (?, ?, ?)", (categoria_id, nombre, siguiente))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _categoria_de_seccion(conn: sqlite3.Connection, seccion_id: int) -> int | None:
    f = conn.execute("SELECT categoria_id FROM proyecto_secciones WHERE id = ?", (seccion_id,)).fetchone()
    return f["categoria_id"] if f else None


def renombrar_seccion(usuario_id: int, seccion_id: int, nombre: str) -> bool:
    nombre = (nombre or "").strip()[:80]
    conn = _db.get_connection()
    try:
        categoria = _db._categoria_de_seccion(conn, seccion_id)
        if not nombre or categoria is None or not _db._puede_organizar_proyecto(conn, usuario_id, categoria):
            return False
        conn.execute("UPDATE proyecto_secciones SET nombre = ? WHERE id = ?", (nombre, seccion_id))
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_seccion(usuario_id: int, seccion_id: int) -> bool:
    """Borra la sección; sus tareas no se tocan (quedan «sin sección»)."""
    conn = _db.get_connection()
    try:
        categoria = _db._categoria_de_seccion(conn, seccion_id)
        if categoria is None or not _db._puede_organizar_proyecto(conn, usuario_id, categoria):
            return False
        conn.execute("UPDATE tareas_outlook SET seccion_id = NULL WHERE seccion_id = ?", (seccion_id,))
        conn.execute("DELETE FROM proyecto_secciones WHERE id = ?", (seccion_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def mover_seccion(usuario_id: int, seccion_id: int, direccion: str) -> bool:
    conn = _db.get_connection()
    try:
        categoria = _db._categoria_de_seccion(conn, seccion_id)
        if categoria is None or direccion not in ("arriba", "abajo") or not _db._puede_organizar_proyecto(conn, usuario_id, categoria):
            return False
        ids = [f["id"] for f in conn.execute("SELECT id FROM proyecto_secciones WHERE categoria_id = ? ORDER BY orden, id", (categoria,))]
        i = ids.index(seccion_id)
        j = i - 1 if direccion == "arriba" else i + 1
        if not 0 <= j < len(ids):
            return False
        ids[i], ids[j] = ids[j], ids[i]
        conn.executemany("UPDATE proyecto_secciones SET orden = ? WHERE id = ?", [(n, sid) for n, sid in enumerate(ids)])
        conn.commit()
        return True
    finally:
        conn.close()


def asignar_seccion_tarea(usuario_id: int, tarea_id: int, seccion_id: int | None) -> bool:
    """Mueve una tarea a una sección de SU proyecto (o la deja sin sección). Quien puede editar la tarea."""
    if not _db.puede_editar_tarea(usuario_id, tarea_id):
        return False
    conn = _db.get_connection()
    try:
        t = conn.execute("SELECT categoria_id FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        if t is None or t["categoria_id"] is None:
            return False
        if seccion_id is not None and _db._categoria_de_seccion(conn, seccion_id) != t["categoria_id"]:
            return False
        conn.execute("UPDATE tareas_outlook SET seccion_id = ? WHERE id = ?", (seccion_id, tarea_id))
        conn.commit()
        return True
    finally:
        conn.close()


def mover_tarea_en_proyecto(usuario_id: int, tarea_id: int, seccion_id: int | None, antes_de_id: int | None = None) -> bool:
    """Coloca una tarea en una sección (o sin sección) justo ANTES de otra tarea de esa sección, o al final si
    `antes_de_id` es None. Es lo que hace arrastrar y soltar en la lista del proyecto."""
    if not _db.puede_editar_tarea(usuario_id, tarea_id):
        return False
    conn = _db.get_connection()
    try:
        t = conn.execute("SELECT categoria_id FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        if t is None or t["categoria_id"] is None:
            return False
        categoria = t["categoria_id"]
        if seccion_id is not None and _db._categoria_de_seccion(conn, seccion_id) != categoria:
            return False
        ids = [f["id"] for f in conn.execute(
            """SELECT id FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL AND id != ?
               AND COALESCE(seccion_id, 0) = COALESCE(?, 0) ORDER BY orden_proyecto, id""",
            (categoria, tarea_id, seccion_id),
        )]
        if antes_de_id is not None and antes_de_id not in ids:
            return False
        posicion = ids.index(antes_de_id) if antes_de_id is not None else len(ids)
        ids.insert(posicion, tarea_id)
        conn.execute("UPDATE tareas_outlook SET seccion_id = ? WHERE id = ?", (seccion_id, tarea_id))
        conn.executemany("UPDATE tareas_outlook SET orden_proyecto = ? WHERE id = ?", [(n + 1, i) for n, i in enumerate(ids)])
        conn.commit()
        return True
    finally:
        conn.close()


def cambiar_fecha_tarea_proyecto(usuario_id: int, tarea_id: int, fecha: str | None) -> bool:
    """Cambia el DÍA de vencimiento conservando la hora si la tenía (arrastrar en el calendario). `fecha`: YYYY-MM-DD o None."""
    if not _db.puede_editar_tarea(usuario_id, tarea_id):
        return False
    if fecha:
        try:
            fecha = _db.datetime.strptime(fecha[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return False
    conn = _db.get_connection()
    try:
        t = conn.execute("SELECT fecha_vencimiento FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        if t is None:
            return False
        antigua = t["fecha_vencimiento"] or ""
        nueva = (fecha + antigua[10:]) if fecha and len(antigua) > 10 else (fecha or None)
        conn.execute("UPDATE tareas_outlook SET fecha_vencimiento = ?, actualizada_en = ? WHERE id = ?", (nueva, _db.now_iso(), tarea_id))
        conn.commit()
    finally:
        conn.close()
    _db.registrar_actividad_tarea(usuario_id, tarea_id, "editada", f"vencimiento {fecha or '—'}")
    return True


def crear_tarea_en_proyecto(
    usuario_id: int, categoria_id: int, asunto: str, seccion_id: int | None = None, prioridad: str = "normal",
    fecha_vencimiento: str | None = None, asignada_a: int | None = None, estimacion_min: int | None = None,
) -> int | None:
    """Alta de una tarea dentro de un proyecto: la puede crear el dueño o un colaborador. Hereda el cliente del proyecto."""
    conn = _db.get_connection()
    try:
        if not _db._puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return None
        if seccion_id is not None and _db._categoria_de_seccion(conn, seccion_id) != categoria_id:
            seccion_id = None
        cliente = conn.execute("SELECT proy_cliente_id FROM categorias WHERE id = ?", (categoria_id,)).fetchone()["proy_cliente_id"]
        orden = conn.execute("SELECT COALESCE(MAX(orden_proyecto), 0) + 1 FROM tareas_outlook WHERE categoria_id = ?", (categoria_id,)).fetchone()[0]
    finally:
        conn.close()
    tarea_id = _db.crear_tarea_outlook(
        usuario_id, asunto, prioridad=prioridad, fecha_vencimiento=fecha_vencimiento, categoria_id=categoria_id,
        cliente_fiscal_id=cliente, asignada_a=asignada_a, estimacion_min=estimacion_min,
    )
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tareas_outlook SET seccion_id = ?, orden_proyecto = ? WHERE id = ?", (seccion_id, orden, tarea_id))
        conn.commit()
    finally:
        conn.close()
    return tarea_id


def tareas_de_proyecto(usuario_id: int, categoria_id: int, incluir_completadas: bool = True) -> list[dict]:
    """Todas las tareas del proyecto, sea quien sea su creador (si el usuario puede ver el proyecto)."""
    conn = _db.get_connection()
    try:
        if _db._rol_en_proyecto(conn, usuario_id, categoria_id) is None:
            return []
        filas = conn.execute(
            f"""SELECT t.*, COALESCE(NULLIF(pc.nombre_mostrado, ''), uc.email) AS creador_nombre,
                       COALESCE(NULLIF(pa.nombre_mostrado, ''), ua.email) AS asignada_nombre,
                       (SELECT COUNT(*) FROM tarea_checklist i WHERE i.tarea_outlook_id = t.id) AS items_total,
                       (SELECT COALESCE(SUM(i.hecha), 0) FROM tarea_checklist i WHERE i.tarea_outlook_id = t.id) AS items_hechos
                FROM tareas_outlook t
                JOIN usuarios uc ON uc.id = t.usuario_id LEFT JOIN usuario_perfil pc ON pc.usuario_id = t.usuario_id
                LEFT JOIN usuarios ua ON ua.id = t.asignada_a LEFT JOIN usuario_perfil pa ON pa.usuario_id = t.asignada_a
                WHERE t.categoria_id = ? AND t.papelera_en IS NULL {'' if incluir_completadas else "AND t.estado != 'completada'"}
                ORDER BY (t.estado = 'completada'), t.orden_proyecto, (t.fecha_vencimiento IS NULL), t.fecha_vencimiento, t.id""",
            (categoria_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def resumen_proyecto(usuario_id: int, categoria_id: int) -> dict | None:
    """Cifras de la cabecera y del Resumen: progreso, vencidas, horas, próximo hito, carga por persona."""
    conn = _db.get_connection()
    try:
        rol = _db._rol_en_proyecto(conn, usuario_id, categoria_id)
        if rol is None:
            return None
        hoy = _db.datetime.now().strftime("%Y-%m-%d")
        lunes = (_db.datetime.now() - _db.timedelta(days=_db.datetime.now().weekday())).strftime("%Y-%m-%d")
        t = conn.execute(
            """SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN estado = 'completada' THEN 1 ELSE 0 END), 0) AS hechas,
                      COALESCE(SUM(CASE WHEN estado != 'completada' AND fecha_vencimiento IS NOT NULL AND substr(fecha_vencimiento, 1, 10) < ? THEN 1 ELSE 0 END), 0) AS vencidas
               FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL""",
            (hoy, categoria_id),
        ).fetchone()
        total, hechas = t["total"], int(t["hechas"])
        horas = conn.execute(
            """SELECT COALESCE(SUM(duracion_segundos), 0) AS total,
                      COALESCE(SUM(CASE WHEN substr(inicio_en, 1, 10) >= ? THEN duracion_segundos ELSE 0 END), 0) AS semana
               FROM tareas WHERE categoria_id = ? AND estado = 'finalizada' AND papelera_en IS NULL""",
            (lunes, categoria_id),
        ).fetchone()
        hito = conn.execute(
            """SELECT asunto, fecha_vencimiento FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL AND estado != 'completada'
               AND fecha_vencimiento IS NOT NULL AND substr(fecha_vencimiento, 1, 10) >= ? ORDER BY fecha_vencimiento LIMIT 1""",
            (categoria_id, hoy),
        ).fetchone()
        proyecto = conn.execute("SELECT proy_cliente_id AS cliente_fiscal_id FROM categorias WHERE id = ?", (categoria_id,)).fetchone()
        vencimiento_cliente = None
        if proyecto["cliente_fiscal_id"]:
            vencimiento_cliente = conn.execute(
                """SELECT modelo, periodo, fecha_limite FROM vencimientos_fiscales WHERE cliente_fiscal_id = ? AND estado = 'pendiente'
                   AND papelera_en IS NULL ORDER BY fecha_limite LIMIT 1""",
                (proyecto["cliente_fiscal_id"],),
            ).fetchone()
        estimado = conn.execute(
            """SELECT COALESCE(SUM(CASE WHEN estado != 'completada' THEN estimacion_min END), 0) AS pendiente,
                      COALESCE(SUM(CASE WHEN estado != 'completada' AND estimacion_min IS NULL THEN 1 END), 0) AS sin_estimar
               FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL""",
            (categoria_id,),
        ).fetchone()
        carga = [dict(f) for f in conn.execute(
            """SELECT COALESCE(t.asignada_a, t.usuario_id) AS usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre, COUNT(*) AS abiertas
               FROM tareas_outlook t JOIN usuarios u ON u.id = COALESCE(t.asignada_a, t.usuario_id) LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id
               WHERE t.categoria_id = ? AND t.papelera_en IS NULL AND t.estado != 'completada' GROUP BY 1, pf.nombre_mostrado, u.email ORDER BY abiertas DESC, nombre""",
            (categoria_id,),
        )]
        por_persona = []
        if rol in ("dueno", "observa"):
            # El desglose de horas por persona solo lo ven el dueño y los supervisores; el resto, los totales.
            por_persona = [dict(f) for f in conn.execute(
                """SELECT t.usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre, COALESCE(SUM(t.duracion_segundos), 0) AS segundos
                   FROM tareas t JOIN usuarios u ON u.id = t.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = t.usuario_id
                   WHERE t.categoria_id = ? AND t.estado = 'finalizada' AND t.papelera_en IS NULL GROUP BY t.usuario_id, pf.nombre_mostrado, u.email ORDER BY segundos DESC""",
                (categoria_id,),
            )] if (rol == "dueno" or conn.execute("SELECT supervisor_tenant FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()[0]) else []
        return {
            "total": total, "hechas": hechas, "abiertas": total - hechas, "vencidas": int(t["vencidas"]),
            "porcentaje": round(hechas * 100 / total) if total else 0,
            "segundos_total": horas["total"], "segundos_semana": horas["semana"],
            "proximo_hito": dict(hito) if hito else None, "vencimiento_cliente": dict(vencimiento_cliente) if vencimiento_cliente else None,
            "carga": carga, "horas_por_persona": por_persona,
            "estimado_pendiente_min": estimado["pendiente"], "sin_estimar": estimado["sin_estimar"],
        }
    finally:
        conn.close()


def crear_nota_proyecto(usuario_id: int, categoria_id: int, texto: str) -> int | None:
    texto = (texto or "").strip()[:4000]
    conn = _db.get_connection()
    try:
        if not texto or not _db._puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return None
        if conn.execute("SELECT COUNT(*) FROM proyecto_notas WHERE categoria_id = ?", (categoria_id,)).fetchone()[0] >= _db.MAX_NOTAS_PROYECTO:
            return None
        cur = conn.execute(
            "INSERT INTO proyecto_notas (categoria_id, usuario_id, texto, creada_en) VALUES (?, ?, ?, ?)",
            (categoria_id, usuario_id, texto, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_notas_proyecto(usuario_id: int, categoria_id: int) -> list[dict]:
    """Notas del proyecto, fijadas primero y luego las más recientes. `puede_borrar`: su autor o el dueño."""
    conn = _db.get_connection()
    try:
        rol = _db._rol_en_proyecto(conn, usuario_id, categoria_id)
        if rol is None:
            return []
        filas = conn.execute(
            """SELECT n.*, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM proyecto_notas n JOIN usuarios u ON u.id = n.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = n.usuario_id
               WHERE n.categoria_id = ? ORDER BY n.fijada DESC, n.id DESC""",
            (categoria_id,),
        ).fetchall()
        return [dict(f, puede_borrar=rol == "dueno" or f["usuario_id"] == usuario_id, puede_fijar=rol in ("dueno", "colabora")) for f in filas]
    finally:
        conn.close()


def fijar_nota_proyecto(usuario_id: int, categoria_id: int, nota_id: int, fijada: bool) -> bool:
    conn = _db.get_connection()
    try:
        if not _db._puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return False
        cur = conn.execute("UPDATE proyecto_notas SET fijada = ? WHERE id = ? AND categoria_id = ?", (1 if fijada else 0, nota_id, categoria_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def eliminar_nota_proyecto(usuario_id: int, categoria_id: int, nota_id: int) -> bool:
    """La borra su autor o el dueño del proyecto (y solo mientras siga pudiendo organizar)."""
    conn = _db.get_connection()
    try:
        rol = _db._rol_en_proyecto(conn, usuario_id, categoria_id)
        n = conn.execute("SELECT usuario_id FROM proyecto_notas WHERE id = ? AND categoria_id = ?", (nota_id, categoria_id)).fetchone()
        if n is None or not (rol == "dueno" or (rol == "colabora" and n["usuario_id"] == usuario_id)):
            return False
        conn.execute("DELETE FROM proyecto_notas WHERE id = ?", (nota_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def actividad_proyecto(usuario_id: int, categoria_id: int, limite: int = 80) -> list[dict]:
    """Línea de tiempo del proyecto: lo que se hace en sus tareas (historial y comentarios) y sus notas.
    Cada entrada: `cuando`, `quien`, `tipo` ('actividad' | 'comentario' | 'nota'), `detalle`, `tarea_id`, `tarea`."""
    conn = _db.get_connection()
    try:
        if _db._rol_en_proyecto(conn, usuario_id, categoria_id) is None:
            return []
        filas = conn.execute(
            """SELECT * FROM (
                 SELECT a.creado_en AS cuando, a.usuario_id AS uid, a.tipo AS subtipo, 'actividad' AS tipo, a.detalle AS detalle,
                        t.id AS tarea_id, t.asunto AS tarea
                 FROM tarea_actividad a JOIN tareas_outlook t ON t.id = a.tarea_id
                 WHERE t.categoria_id = ? AND t.papelera_en IS NULL AND a.tipo != 'comentario'
                 UNION ALL
                 SELECT c.creado_en, c.usuario_id, 'comentario', 'comentario', c.texto, t.id, t.asunto
                 FROM tarea_comentarios c JOIN tareas_outlook t ON t.id = c.tarea_id
                 WHERE t.categoria_id = ? AND t.papelera_en IS NULL
                 UNION ALL
                 SELECT n.creada_en, n.usuario_id, 'nota', 'nota', n.texto, NULL, NULL
                 FROM proyecto_notas n WHERE n.categoria_id = ?
               ) ORDER BY cuando DESC LIMIT ?""",
            (categoria_id, categoria_id, categoria_id, max(1, min(limite, 300))),
        ).fetchall()
        nombres = {
            f["id"]: f["nombre"] for f in conn.execute(
                "SELECT u.id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre FROM usuarios u LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id"
                " WHERE u.id IN (%s)" % ",".join("?" * len({f["uid"] for f in filas})),
                list({f["uid"] for f in filas}),
            )
        } if filas else {}
        return [dict(f, quien=nombres.get(f["uid"], "")) for f in filas]
    finally:
        conn.close()


def _estructura_valida(estructura) -> list[dict]:
    """Normaliza {secciones: [{nombre, tareas: [{asunto, dias}]}]} y descarta lo que no cuadre (máx. 20 secciones, 40 tareas cada una)."""
    resultado = []
    if not isinstance(estructura, list):
        return resultado
    for s in estructura[:20]:
        if not isinstance(s, dict):
            continue
        nombre = str(s.get("nombre") or "").strip()[:80]
        if not nombre:
            continue
        tareas = []
        for t in (s.get("tareas") if isinstance(s.get("tareas"), list) else [])[:40]:
            if not isinstance(t, dict):
                continue
            asunto = str(t.get("asunto") or "").strip()[:200]
            dias = t.get("dias")
            if asunto:
                tareas.append({"asunto": asunto, "dias": dias if isinstance(dias, int) and 0 <= dias <= 730 else None})
        resultado.append({"nombre": nombre, "tareas": tareas})
    return resultado


def aplicar_plantilla_proyecto(usuario_id: int, categoria_id: int, estructura, hoy: _db.date | None = None) -> dict | None:
    """Añade al proyecto las secciones y tareas de una plantilla (nunca borra nada). Las fechas son «días desde hoy».
    Devuelve {'secciones': n, 'tareas': n} o None si no se puede organizar el proyecto."""
    hoy = hoy or _db.date.today()
    estructura = _db._estructura_valida(estructura)
    conn = _db.get_connection()
    try:
        if not _db._puede_organizar_proyecto(conn, usuario_id, categoria_id):
            return None
    finally:
        conn.close()
    n_secciones = n_tareas = 0
    for s in estructura:
        seccion_id = _db.crear_seccion(usuario_id, categoria_id, s["nombre"])
        if seccion_id is None:
            continue
        n_secciones += 1
        for t in s["tareas"]:
            fecha = (hoy + _db.timedelta(days=t["dias"])).isoformat() if t["dias"] is not None else None
            if _db.crear_tarea_en_proyecto(usuario_id, categoria_id, t["asunto"], seccion_id=seccion_id, fecha_vencimiento=fecha):
                n_tareas += 1
    return {"secciones": n_secciones, "tareas": n_tareas}


def guardar_plantilla_desde_proyecto(usuario_id: int, categoria_id: int, nombre: str) -> int | None:
    """Guarda las secciones y los asuntos de las tareas abiertas del proyecto como plantilla del despacho
    (sin fechas, personas ni comentarios). Solo el dueño."""
    nombre = (nombre or "").strip()[:80]
    conn = _db.get_connection()
    try:
        u = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if not nombre or u is None or u["tenant_id"] is None or _db._rol_en_proyecto(conn, usuario_id, categoria_id) != "dueno":
            return None
        if conn.execute("SELECT COUNT(*) FROM proyecto_plantillas WHERE tenant_id = ?", (u["tenant_id"],)).fetchone()[0] >= _db.MAX_PLANTILLAS_TENANT:
            return None
        secciones = conn.execute("SELECT id, nombre FROM proyecto_secciones WHERE categoria_id = ? ORDER BY orden, id", (categoria_id,)).fetchall()
        tareas = conn.execute(
            """SELECT asunto, seccion_id FROM tareas_outlook WHERE categoria_id = ? AND papelera_en IS NULL AND estado != 'completada'
               ORDER BY orden_proyecto, id""",
            (categoria_id,),
        ).fetchall()
        estructura = [{"nombre": s["nombre"], "tareas": [{"asunto": t["asunto"]} for t in tareas if t["seccion_id"] == s["id"]]} for s in secciones]
        sueltas = [{"asunto": t["asunto"]} for t in tareas if t["seccion_id"] is None]
        if sueltas:
            estructura.insert(0, {"nombre": nombre, "tareas": sueltas})
        estructura = _db._estructura_valida(estructura)
        if not estructura:
            return None
        cur = conn.execute(
            "INSERT INTO proyecto_plantillas (tenant_id, usuario_id, nombre, estructura, creada_en) VALUES (?, ?, ?, ?, ?)",
            (u["tenant_id"], usuario_id, nombre, json.dumps(estructura, ensure_ascii=False), _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_plantillas_proyecto(usuario_id: int) -> list[dict]:
    """Plantillas guardadas por el despacho del usuario (`estructura` ya como lista)."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT p.* FROM proyecto_plantillas p JOIN usuarios u ON u.tenant_id = p.tenant_id WHERE u.id = ? ORDER BY p.nombre""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()
    resultado = []
    for f in filas:
        try:
            resultado.append(dict(f, estructura=_db._estructura_valida(json.loads(f["estructura"]))))
        except (ValueError, TypeError):
            continue
    return resultado


def eliminar_plantilla_proyecto(usuario_id: int, plantilla_id: int) -> bool:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM proyecto_plantillas WHERE id = ? AND tenant_id = (SELECT tenant_id FROM usuarios WHERE id = ?)",
            (plantilla_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def correos_de_cliente_para(usuario_id: int, cliente_fiscal_id: int, limite: int = 5) -> list[dict]:
    """Los últimos correos de SUS cuentas vinculados al cliente (el correo es privado: cada quien ve solo los suyos)."""
    from . import correo_cifrado
    limite = max(1, min(limite, 20))
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT m.id, m.asunto, m.remitente, m.fecha, m.leido FROM correo_mensajes m
               JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE c.usuario_id = ? AND m.cliente_fiscal_id = ? ORDER BY m.fecha DESC, m.id DESC LIMIT ?""",
            (usuario_id, cliente_fiscal_id, limite),
        ).fetchall()
    finally:
        conn.close()
    res = [dict(f) for f in correo_cifrado.completar(filas)]
    if correo_cifrado.hay_alguno():
        res += [{k: m.get(k) for k in ("id", "asunto", "remitente", "fecha", "leido", "protegido")} for m in correo_cifrado.candidatos_estricto(usuario_id=usuario_id) if m.get("cliente_fiscal_id") == cliente_fiscal_id]
        res.sort(key=lambda m: ((m.get("fecha") or ""), m["id"]), reverse=True)
    return res[:limite]
