"""Acceso a datos del histórico combinado, las estadísticas y las frases favoritas.

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


# --- Histórico combinado ---------------------------------------------------

def historial(
    usuario_id: int,
    desde: str | None = None,
    hasta: str | None = None,
    categoria_id: int | None = None,
    texto: str | None = None,
    limite: int | None = None,
    offset: int = 0,
):
    """Devuelve notas y tareas combinadas, ordenadas cronológicamente descendente.

    desde/hasta: fechas 'YYYY-MM-DD' (inclusive).
    texto: si se indica, filtra por coincidencia parcial (insensible a mayúsculas).
    limite/offset: paginación (mismo estilo que db.listar_mensajes_correo) --
    si `limite` es None (por defecto) devuelve todo, sin paginar, para no
    romper a quien ya llama a esta función esperando el conjunto completo
    (export.py, el widget "hoy" del dashboard, etc.).
    """
    conn = _db.get_connection()
    try:
        # El filtro de fecha se aplica DENTRO de cada rama (sobre la columna
        # de timestamp real, notas.creada_en / tareas.inicio_en) en vez de
        # sobre un alias calculado en la consulta exterior — así SQLite
        # puede usar los índices idx_notas_categoria_creada /
        # idx_tareas_categoria_inicio en vez de escanear ambas tablas
        # enteras antes de filtrar.
        hasta_excl = _db._fecha_exclusiva(hasta) if hasta else None

        cond_n = ["n.usuario_id = ?", "n.papelera_en IS NULL"]
        cond_t = ["t.usuario_id = ?", "t.papelera_en IS NULL"]
        params_n: list = [usuario_id]
        params_t: list = [usuario_id]
        if desde:
            cond_n.append("n.creada_en >= ?"); params_n.append(desde)
            cond_t.append("t.inicio_en >= ?"); params_t.append(desde)
        if hasta_excl:
            cond_n.append("n.creada_en < ?"); params_n.append(hasta_excl)
            cond_t.append("t.inicio_en < ?"); params_t.append(hasta_excl)
        if categoria_id:
            cond_n.append("n.categoria_id = ?"); params_n.append(categoria_id)
            cond_t.append("t.categoria_id = ?"); params_t.append(categoria_id)
        if texto:
            cond_n.append("(n.texto LIKE ? OR n.titulo LIKE ?)"); params_n.extend([f"%{texto}%", f"%{texto}%"])
            cond_t.append("t.nombre LIKE ?"); params_t.append(f"%{texto}%")

        query = f"""
            SELECT * FROM (
                SELECT
                    'nota' AS origen,
                    n.id AS id,
                    n.texto AS texto,
                    NULL AS tipo,
                    NULL AS estado,
                    n.creada_en AS timestamp,
                    NULL AS fin_en,
                    NULL AS duracion_segundos,
                    n.categoria_id AS categoria_id,
                    c.nombre AS categoria_nombre,
                    c.color AS categoria_color,
                    n.titulo AS titulo,
                    n.fijada AS fijada
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE {' AND '.join(cond_n)}

                UNION ALL

                SELECT
                    'tarea' AS origen,
                    t.id AS id,
                    t.nombre AS texto,
                    t.tipo AS tipo,
                    t.estado AS estado,
                    t.inicio_en AS timestamp,
                    t.fin_en AS fin_en,
                    t.duracion_segundos AS duracion_segundos,
                    t.categoria_id AS categoria_id,
                    c.nombre AS categoria_nombre,
                    c.color AS categoria_color,
                    NULL AS titulo,
                    0 AS fijada
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE {' AND '.join(cond_t)}
            )
            ORDER BY timestamp DESC
        """
        params = [*params_n, *params_t]
        if limite is not None:
            query += " LIMIT ? OFFSET ?"
            params += [limite, offset]
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def resumen_historial(usuario_id: int, desde=None, hasta=None, categoria_id=None, texto=None) -> dict:
    """Agregado del histórico para el filtro dado (panel "Resumen del
    periodo" de /historial): total de entradas, tiempo total registrado y
    reparto por proyecto. Reutiliza historial() sin paginar -- mismo criterio
    que export.py (construir_export), que ya trae el conjunto completo del
    filtro para generar el export; aquí solo se agrega en Python en vez de
    escribirse como columnas, porque el dataset por usuario es pequeño
    (nunca miles de filas) y así se evita duplicar la query UNION ALL de
    arriba con un segundo camino de SQL a mantener en paralelo.
    """
    filas = _db.historial(usuario_id, desde=desde, hasta=hasta, categoria_id=categoria_id, texto=texto)
    total_segundos = sum(f["duracion_segundos"] or 0 for f in filas)
    por_menu: dict[str, dict] = {}
    for f in filas:
        nombre = f["categoria_nombre"] or "Sin proyecto"
        entrada = por_menu.setdefault(nombre, {"nombre": nombre, "color": f["categoria_color"] or "#7c8ba1", "entradas": 0})
        entrada["entradas"] += 1
    total_entradas = len(filas)
    for entrada in por_menu.values():
        entrada["porcentaje"] = round(entrada["entradas"] / total_entradas * 100) if total_entradas else 0
    return {
        "total_entradas": total_entradas,
        "total_segundos": total_segundos,
        "por_menu": sorted(por_menu.values(), key=lambda e: e["entradas"], reverse=True),
    }


# --- Estadísticas ----------------------------------------------------------

def estadisticas_por_categoria(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo total (tareas finalizadas) y nº de entradas por categoría."""
    conn = _db.get_connection()
    try:
        cond_t = ["t.usuario_id = ?", "t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        cond_ev = ["tt.usuario_id = ?", "tt.tipo = 'instantanea'", "tt.papelera_en IS NULL"]
        cond_n = ["n.usuario_id = ?", "n.papelera_en IS NULL"]
        params_t: list = [usuario_id]
        params_ev: list = [usuario_id]
        params_n: list = [usuario_id]
        hasta_excl = _db._fecha_exclusiva(hasta) if hasta else None
        if desde:
            cond_t.append("t.inicio_en >= ?"); params_t.append(desde)
            cond_ev.append("tt.inicio_en >= ?"); params_ev.append(desde)
            cond_n.append("n.creada_en >= ?"); params_n.append(desde)
        if hasta_excl:
            cond_t.append("t.inicio_en < ?"); params_t.append(hasta_excl)
            cond_ev.append("tt.inicio_en < ?"); params_ev.append(hasta_excl)
            cond_n.append("n.creada_en < ?"); params_n.append(hasta_excl)

        filas = conn.execute(
            f"""SELECT c.id, c.nombre, c.color,
                   COALESCE((SELECT SUM(t.duracion_segundos) FROM tareas t
                             WHERE t.categoria_id = c.id AND {' AND '.join(cond_t)}), 0) AS segundos_totales,
                   COALESCE((SELECT COUNT(*) FROM tareas t
                             WHERE t.categoria_id = c.id AND {' AND '.join(cond_t)}), 0) AS num_tareas,
                   COALESCE((SELECT COUNT(*) FROM tareas tt
                             WHERE tt.categoria_id = c.id AND {' AND '.join(cond_ev)}), 0) AS num_eventos,
                   COALESCE((SELECT COUNT(*) FROM notas n
                             WHERE n.categoria_id = c.id AND {' AND '.join(cond_n)}), 0) AS num_notas
               FROM categorias c
               WHERE c.usuario_id = ?
               ORDER BY segundos_totales DESC, c.nombre""",
            [*params_t, *params_t, *params_ev, *params_n, usuario_id],
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def estadisticas_por_dia(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo total en tareas con duración finalizadas, agrupado por día y categoría."""
    conn = _db.get_connection()
    try:
        cond = ["t.usuario_id = ?", "t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        params: list = [usuario_id]
        if desde:
            cond.append("t.inicio_en >= ?"); params.append(desde)
        if hasta:
            cond.append("t.inicio_en < ?"); params.append(_db._fecha_exclusiva(hasta))
        where = " AND ".join(cond)
        filas = conn.execute(
            f"""SELECT substr(t.inicio_en,1,10) AS fecha, c.nombre AS categoria, c.color AS categoria_color,
                       SUM(t.duracion_segundos) AS segundos
                FROM tareas t JOIN categorias c ON c.id = t.categoria_id
                WHERE {where}
                GROUP BY fecha, c.id
                ORDER BY fecha DESC, segundos DESC""",
            params,
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def estadisticas_equipo_por_usuario(
    tenant_id: int, desde: str | None = None, hasta: str | None = None,
) -> list[dict]:
    """Carga de trabajo por usuario de un tenant -- a diferencia de
    estadisticas_por_categoria(), no se puede reutilizar esa misma
    consulta ampliándola con un IN de usuarios: las categorías
    (`categorias.usuario_id`) son propias de cada persona, no
    compartidas por tenant, así que agregar "por categoría" mezclaría
    categorías de nombre distinto entre sí sin ningún criterio común.
    Aquí se agrega directamente por usuario (email), que sí es una
    dimensión compartida con sentido a nivel de equipo."""
    conn = _db.get_connection()
    try:
        ids = _db.usuarios_de_tenant(tenant_id)
        if not ids:
            return []
        marcadores = ",".join("?" * len(ids))
        cond_t = [f"t.usuario_id IN ({marcadores})", "t.tipo = 'duracion'", "t.estado = 'finalizada'", "t.papelera_en IS NULL"]
        cond_n = [f"n.usuario_id IN ({marcadores})", "n.papelera_en IS NULL"]
        params_t: list = list(ids)
        params_n: list = list(ids)
        hasta_excl = _db._fecha_exclusiva(hasta) if hasta else None
        if desde:
            cond_t.append("t.inicio_en >= ?"); params_t.append(desde)
            cond_n.append("n.creada_en >= ?"); params_n.append(desde)
        if hasta_excl:
            cond_t.append("t.inicio_en < ?"); params_t.append(hasta_excl)
            cond_n.append("n.creada_en < ?"); params_n.append(hasta_excl)

        filas = conn.execute(
            f"""SELECT u.id, u.email,
                   COALESCE((SELECT SUM(t.duracion_segundos) FROM tareas t
                             WHERE t.usuario_id = u.id AND {' AND '.join(cond_t)}), 0) AS segundos_totales,
                   COALESCE((SELECT COUNT(*) FROM tareas t
                             WHERE t.usuario_id = u.id AND {' AND '.join(cond_t)}), 0) AS num_tareas,
                   COALESCE((SELECT COUNT(*) FROM notas n
                             WHERE n.usuario_id = u.id AND {' AND '.join(cond_n)}), 0) AS num_notas
               FROM usuarios u
               WHERE u.id IN ({marcadores})
               ORDER BY segundos_totales DESC, u.email""",
            [*params_t, *params_t, *params_n, *ids],
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def tiempo_medio_resolucion_vencimientos(tenant_id: int) -> float | None:
    """Media de días entre crear un vencimiento fiscal y marcarlo como
    presentado -- KPI de equipo, no personal. None si no hay ningún
    vencimiento presentado todavía (evita mostrar un falso "0 días").
    No existe un equivalente para tiquets: son un tablero interno
    COMPARTIDO por toda la plataforma (sin tenant_id, ver
    app/rutas_tiquets.py), no datos de un tenant/cliente concreto --
    calcular un tiempo de resolución "por tenant" no tendría sentido
    ahí."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            """SELECT AVG(julianday(actualizado_en) - julianday(creado_en)) AS media_dias
               FROM vencimientos_fiscales
               WHERE tenant_id = ? AND estado = 'presentado' AND actualizado_en IS NOT NULL""",
            (tenant_id,),
        ).fetchone()
        return fila["media_dias"]
    finally:
        conn.close()


def crear_plantilla(categoria_id: int, texto: str) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO plantillas (categoria_id, texto, creada_en) VALUES (?, ?, ?)",
            (categoria_id, texto.strip(), _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_plantillas(categoria_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM plantillas WHERE categoria_id = ? ORDER BY id", (categoria_id,)
        ).fetchall()
    finally:
        conn.close()


def eliminar_plantilla(plantilla_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM plantillas WHERE id = ?", (plantilla_id,))
        conn.commit()
    finally:
        conn.close()
