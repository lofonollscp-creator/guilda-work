"""Acceso a datos de los tiquets de soporte interno.

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


# ---- Tiquets (soporte interno: errores/sugerencias, tablero compartido) ----

def crear_tiquet(usuario_id: int, tipo: str, titulo: str, descripcion: str | None = None) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tiquets (usuario_id, tipo, titulo, descripcion, creado_en)
               VALUES (?, ?, ?, ?, ?)""",
            (usuario_id, tipo, titulo.strip(), (descripcion or "").strip() or None, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_tiquets(
    estado: str | None = None, tipo: str | None = None,
    prioridad: str | None = None, usuario_asignado_id: int | None = None,
) -> list[sqlite3.Row]:
    """Todos los tiquets, de cualquier usuario -- tablero compartido, a
    diferencia de notas/tareas/correo que siempre filtran por
    usuario_id. Ordenados por prioridad (alta primero) y luego por id
    (orden de inclusión dentro de la misma prioridad)."""
    conn = _db.get_connection()
    try:
        cond = []
        params: list = []
        if estado:
            cond.append("t.estado = ?"); params.append(estado)
        if tipo:
            cond.append("t.tipo = ?"); params.append(tipo)
        if prioridad:
            cond.append("t.prioridad = ?"); params.append(prioridad)
        if usuario_asignado_id:
            cond.append("t.usuario_asignado_id = ?"); params.append(usuario_asignado_id)
        where = f"WHERE {' AND '.join(cond)}" if cond else ""
        return conn.execute(
            f"""SELECT t.*, u.email AS autor_email, a.email AS asignado_email
                FROM tiquets t
                LEFT JOIN usuarios u ON u.id = t.usuario_id
                LEFT JOIN usuarios a ON a.id = t.usuario_asignado_id
                {where}
                ORDER BY CASE t.prioridad WHEN 'alta' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, t.id""",
            params,
        ).fetchall()
    finally:
        conn.close()


def obtener_tiquet(tiquet_id: int) -> sqlite3.Row | None:
    """Sin filtrar por usuario_id -- hay dos roles con distinto alcance
    (dueño / admin) y quien llama (rutas_tiquets.py, mcp_tools.py) es
    quien decide si el usuario actual puede verlo/tocarlo."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT t.*, u.email AS autor_email, a.email AS asignado_email
               FROM tiquets t
               LEFT JOIN usuarios u ON u.id = t.usuario_id
               LEFT JOIN usuarios a ON a.id = t.usuario_asignado_id
               WHERE t.id = ?""",
            (tiquet_id,),
        ).fetchone()
    finally:
        conn.close()


def editar_tiquet(usuario_id: int, tiquet_id: int, titulo: str, descripcion: str | None, tipo: str) -> bool:
    """Solo actualiza si `usuario_id` es el dueño Y el tiquet sigue en
    'sin_revisar' -- devuelve False sin tocar nada si no se cumple
    alguna de las dos condiciones (quien llama decide qué error mostrar)."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """UPDATE tiquets SET titulo = ?, descripcion = ?, tipo = ?, actualizado_en = ?
               WHERE id = ? AND usuario_id = ? AND estado = 'sin_revisar'""",
            (titulo.strip(), (descripcion or "").strip() or None, tipo, _db.now_iso(), tiquet_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def cambiar_estado_tiquet(tiquet_id: int, estado: str) -> None:
    """Sin chequeo de permisos aquí -- quien llama (ruta con
    @admin_required, o la tool de MCP tras comprobar db.es_admin) ya
    decidió que puede hacerlo."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tiquets SET estado = ?, actualizado_en = ? WHERE id = ?", (estado, _db.now_iso(), tiquet_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tiquet(tiquet_id: int) -> None:
    """Sin chequeo de permisos aquí tampoco -- ver cambiar_estado_tiquet."""
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM tiquets WHERE id = ?", (tiquet_id,))
        conn.commit()
    finally:
        conn.close()


def asignar_tiquet(tiquet_id: int, prioridad: str, usuario_asignado_id: int | None) -> None:
    """Sin chequeo de permisos aquí -- ver cambiar_estado_tiquet, mismo
    criterio (solo admin puede llamar, comprobado en la ruta)."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tiquets SET prioridad = ?, usuario_asignado_id = ?, actualizado_en = ? WHERE id = ?",
            (prioridad, usuario_asignado_id, _db.now_iso(), tiquet_id),
        )
        conn.commit()
    finally:
        conn.close()


def guardar_adjunto_tiquet(tiquet_id: int, nombre_archivo: str, tipo_mime: str, contenido: bytes) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tiquets_adjuntos (tiquet_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tiquet_id, nombre_archivo, tipo_mime, len(contenido), contenido, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_adjuntos_tiquet(tiquet_id: int) -> list[sqlite3.Row]:
    """Sin el BLOB `contenido` -- para listar en tarjetas/edición no hace
    falta traer los bytes enteros de cada adjunto, solo al descargar uno
    en concreto (ver obtener_adjunto_tiquet)."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT id, tiquet_id, nombre_archivo, tipo_mime, tamano_bytes, creado_en
               FROM tiquets_adjuntos WHERE tiquet_id = ? ORDER BY id""",
            (tiquet_id,),
        ).fetchall()
    finally:
        conn.close()


def obtener_adjunto_tiquet(adjunto_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM tiquets_adjuntos WHERE id = ?", (adjunto_id,)).fetchone()
    finally:
        conn.close()


def eliminar_adjunto_tiquet(adjunto_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM tiquets_adjuntos WHERE id = ?", (adjunto_id,))
        conn.commit()
    finally:
        conn.close()
