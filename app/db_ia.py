"""Acceso a datos del asistente de IA: preferencias y conversaciones.

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


# --- Asistente IA (OpenRouter): preferencias y conversación -------------------

def obtener_preferencias_ia(usuario_id: int) -> sqlite3.Row:
    conn = _db.get_connection()
    try:
        return _db._obtener_o_crear(conn, "ia_preferencias", usuario_id)
    finally:
        conn.close()


def guardar_preferencias_ia(usuario_id: int, modelo: str, modo_autonomo: bool, solo_lectura: bool | None = None) -> None:
    """`solo_lectura` None = no tocar (los clientes antiguos no lo envían)."""
    conn = _db.get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            "UPDATE ia_preferencias SET modelo = ?, modo_autonomo = ? WHERE usuario_id = ?",
            (modelo, int(modo_autonomo), usuario_id),
        )
        if solo_lectura is not None:
            conn.execute(
                "UPDATE ia_preferencias SET solo_lectura = ? WHERE usuario_id = ?", (int(solo_lectura), usuario_id)
            )
        conn.commit()
    finally:
        conn.close()


# --- IA local (Ollama/LM Studio): recordar el último proveedor/modelo usado --

def obtener_preferencias_ia_local(usuario_id: int) -> sqlite3.Row:
    conn = _db.get_connection()
    try:
        return _db._obtener_o_crear(conn, "ia_preferencias", usuario_id)
    finally:
        conn.close()


def guardar_preferencias_ia_local(usuario_id: int, proveedor: str, modelo: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO ia_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            "UPDATE ia_preferencias SET proveedor_local = ?, modelo_local = ? WHERE usuario_id = ?",
            (proveedor, modelo, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def _titulo_desde_texto(texto: str | None) -> str | None:
    """Título automático: primera línea del primer mensaje, recortada."""
    if not texto:
        return None
    linea = " ".join(texto.strip().splitlines()[0].split()) if texto.strip() else ""
    if not linea:
        return None
    return linea if len(linea) <= _db.IA_TITULO_MAX_CARACTERES else linea[: _db.IA_TITULO_MAX_CARACTERES - 1].rstrip() + "…"


def _migrar_conversaciones_ia(conn: sqlite3.Connection) -> None:
    """Idempotente: los mensajes anteriores a las conversaciones (conversacion_id
    NULL) pasan a UNA conversación por usuario, que queda activa."""
    for fila in conn.execute(
        "SELECT usuario_id, MIN(creado_en) AS desde, MAX(creado_en) AS hasta FROM ia_mensajes "
        "WHERE conversacion_id IS NULL AND usuario_id IS NOT NULL GROUP BY usuario_id"
    ).fetchall():
        uid = fila["usuario_id"]
        primero = conn.execute(
            "SELECT contenido FROM ia_mensajes WHERE usuario_id = ? AND conversacion_id IS NULL AND rol = 'user' ORDER BY id LIMIT 1",
            (uid,),
        ).fetchone()
        activa = conn.execute(
            "SELECT 1 FROM ia_conversaciones WHERE usuario_id = ? AND activa = 1", (uid,)
        ).fetchone()
        cur = conn.execute(
            "INSERT INTO ia_conversaciones (usuario_id, titulo, creada_en, actualizada_en, activa) VALUES (?, ?, ?, ?, ?)",
            (uid, _db._titulo_desde_texto(primero["contenido"] if primero else None), fila["desde"], fila["hasta"], 0 if activa else 1),
        )
        conn.execute(
            "UPDATE ia_mensajes SET conversacion_id = ? WHERE usuario_id = ? AND conversacion_id IS NULL",
            (cur.lastrowid, uid),
        )


def _crear_conversacion_ia(conn: sqlite3.Connection, usuario_id: int) -> int:
    ahora = _db.now_iso()
    conn.execute("UPDATE ia_conversaciones SET activa = 0 WHERE usuario_id = ?", (usuario_id,))
    cur = conn.execute(
        "INSERT INTO ia_conversaciones (usuario_id, titulo, creada_en, actualizada_en, activa) VALUES (?, NULL, ?, ?, 1)",
        (usuario_id, ahora, ahora),
    )
    # Tope: se descartan las más antiguas (nunca la activa).
    sobran = conn.execute(
        "SELECT COUNT(*) AS n FROM ia_conversaciones WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()["n"] - _db.IA_MAX_CONVERSACIONES_POR_USUARIO
    if sobran > 0:
        for antigua in conn.execute(
            "SELECT id FROM ia_conversaciones WHERE usuario_id = ? AND activa = 0 ORDER BY actualizada_en, id LIMIT ?",
            (usuario_id, sobran),
        ).fetchall():
            conn.execute("DELETE FROM ia_mensajes WHERE conversacion_id = ?", (antigua["id"],))
            conn.execute("DELETE FROM ia_conversaciones WHERE id = ?", (antigua["id"],))
    return cur.lastrowid


def conversacion_ia_activa_id(usuario_id: int, crear: bool = True) -> int | None:
    """La conversación activa del usuario; si no tiene ninguna y `crear`, abre una."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT id FROM ia_conversaciones WHERE usuario_id = ? AND activa = 1", (usuario_id,)
        ).fetchone()
        if fila:
            return fila["id"]
        if not crear:
            return None
        nueva = _db._crear_conversacion_ia(conn, usuario_id)
        conn.commit()
        return nueva
    finally:
        conn.close()


def listar_conversaciones_ia(usuario_id: int) -> list[sqlite3.Row]:
    """Las conversaciones del usuario, la más reciente primero, con cuántos
    mensajes suyos tiene cada una (`mensajes`)."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM ia_mensajes m WHERE m.conversacion_id = c.id AND m.rol = 'user') AS mensajes
               FROM ia_conversaciones c WHERE c.usuario_id = ? ORDER BY c.actualizada_en DESC, c.id DESC""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def crear_conversacion_ia(usuario_id: int) -> int:
    """Abre una conversación nueva y la deja activa. Si la activa todavía no
    tiene ningún mensaje se reutiliza (no se acumulan conversaciones vacías)."""
    conn = _db.get_connection()
    try:
        activa = conn.execute(
            """SELECT c.id FROM ia_conversaciones c WHERE c.usuario_id = ? AND c.activa = 1
               AND NOT EXISTS (SELECT 1 FROM ia_mensajes m WHERE m.conversacion_id = c.id)""",
            (usuario_id,),
        ).fetchone()
        if activa:
            return activa["id"]
        nueva = _db._crear_conversacion_ia(conn, usuario_id)
        conn.commit()
        return nueva
    finally:
        conn.close()


def activar_conversacion_ia(usuario_id: int, conversacion_id: int) -> bool:
    conn = _db.get_connection()
    try:
        if not conn.execute(
            "SELECT 1 FROM ia_conversaciones WHERE id = ? AND usuario_id = ?", (conversacion_id, usuario_id)
        ).fetchone():
            return False
        conn.execute("UPDATE ia_conversaciones SET activa = (id = ?) WHERE usuario_id = ?", (conversacion_id, usuario_id))
        conn.commit()
        return True
    finally:
        conn.close()


def renombrar_conversacion_ia(usuario_id: int, conversacion_id: int, titulo: str) -> bool:
    titulo = " ".join((titulo or "").split())
    if not titulo:
        raise ValueError("El título no puede estar vacío.")
    titulo = titulo[:_db.IA_TITULO_MAX_CARACTERES]
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE ia_conversaciones SET titulo = ? WHERE id = ? AND usuario_id = ?", (titulo, conversacion_id, usuario_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def eliminar_conversacion_ia(usuario_id: int, conversacion_id: int) -> bool:
    """Borra la conversación y sus mensajes. Si era la activa, pasa a serlo la
    más reciente que quede (o ninguna: se abrirá una al escribir)."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT activa FROM ia_conversaciones WHERE id = ? AND usuario_id = ?", (conversacion_id, usuario_id)
        ).fetchone()
        if fila is None:
            return False
        conn.execute("DELETE FROM ia_mensajes WHERE conversacion_id = ?", (conversacion_id,))
        conn.execute("DELETE FROM ia_conversaciones WHERE id = ?", (conversacion_id,))
        if fila["activa"]:
            reciente = conn.execute(
                "SELECT id FROM ia_conversaciones WHERE usuario_id = ? ORDER BY actualizada_en DESC, id DESC LIMIT 1",
                (usuario_id,),
            ).fetchone()
            if reciente:
                conn.execute("UPDATE ia_conversaciones SET activa = 1 WHERE id = ?", (reciente["id"],))
        conn.commit()
        return True
    finally:
        conn.close()


def listar_mensajes_ia(usuario_id: int, conversacion_id: int | None = None) -> list[sqlite3.Row]:
    """Mensajes de la conversación indicada o, por defecto, de la activa
    (lista vacía si el usuario no tiene ninguna todavía)."""
    if conversacion_id is None:
        conversacion_id = _db.conversacion_ia_activa_id(usuario_id, crear=False)
        if conversacion_id is None:
            return []
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT * FROM ia_mensajes WHERE usuario_id = ? AND conversacion_id = ? ORDER BY id",
            (usuario_id, conversacion_id),
        ).fetchall()
    finally:
        conn.close()
    if not any((f["contenido"] or "").startswith("enc1:") for f in filas):
        return filas
    from . import cifrado_despacho
    return [{**dict(f), "contenido": cifrado_despacho.abrir_resultado_ia(usuario_id, f["contenido"])} for f in filas]


def agregar_mensaje_ia(
    usuario_id: int,
    rol: str,
    contenido: str | None = None,
    tool_calls_json: str | None = None,
    tool_call_id: str | None = None,
    nombre_herramienta: str | None = None,
    fuentes_json: str | None = None,
) -> int:
    """Añade el mensaje a la conversación activa (abriéndola si no hay). El
    primer mensaje de la persona usuaria da título a la conversación. El resultado de una herramienta que devuelve correo o documentos cifrados se guarda sellado."""
    from . import cifrado_despacho
    if rol == "tool":
        contenido = cifrado_despacho.sellar_resultado_ia(usuario_id, nombre_herramienta, contenido)
    conn = _db.get_connection()
    try:
        activa = conn.execute(
            "SELECT id, titulo FROM ia_conversaciones WHERE usuario_id = ? AND activa = 1", (usuario_id,)
        ).fetchone()
        if activa is None:
            conversacion_id, titulo_actual = _db._crear_conversacion_ia(conn, usuario_id), None
        else:
            conversacion_id, titulo_actual = activa["id"], activa["titulo"]
        ahora = _db.now_iso()
        cursor = conn.execute(
            """INSERT INTO ia_mensajes
               (usuario_id, conversacion_id, rol, contenido, tool_calls_json, tool_call_id, nombre_herramienta,
                fuentes_json, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, conversacion_id, rol, contenido, tool_calls_json, tool_call_id, nombre_herramienta,
             fuentes_json, ahora),
        )
        titulo = titulo_actual
        if not titulo and rol == "user":
            titulo = _db._titulo_desde_texto(contenido)
        conn.execute(
            "UPDATE ia_conversaciones SET actualizada_en = ?, titulo = ? WHERE id = ?", (ahora, titulo, conversacion_id)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def listar_atajos_ia(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM ia_atajos WHERE usuario_id = ? ORDER BY id", (usuario_id,)).fetchall()
    finally:
        conn.close()


def crear_atajo_ia(usuario_id: int, titulo: str, prompt: str) -> int:
    titulo, prompt = (titulo or "").strip()[:40], (prompt or "").strip()[:1000]
    if not titulo or not prompt:
        raise ValueError("El atajo necesita un título y un texto.")
    conn = _db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM ia_atajos WHERE usuario_id = ?", (usuario_id,)).fetchone()[0] >= _db.IA_MAX_ATAJOS:
            raise ValueError(f"Máximo {_db.IA_MAX_ATAJOS} atajos propios.")
        cur = conn.execute(
            "INSERT INTO ia_atajos (usuario_id, titulo, prompt, creado_en) VALUES (?, ?, ?, ?)",
            (usuario_id, titulo, prompt, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def eliminar_atajo_ia(usuario_id: int, atajo_id: int) -> bool:
    conn = _db.get_connection()
    try:
        cur = conn.execute("DELETE FROM ia_atajos WHERE id = ? AND usuario_id = ?", (atajo_id, usuario_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def vaciar_mensajes_ia(usuario_id: int) -> None:
    """"Nueva conversación": abre una conversación en blanco. La anterior NO se
    borra, queda en la lista de conversaciones del usuario."""
    _db.crear_conversacion_ia(usuario_id)
