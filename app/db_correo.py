"""Acceso a datos del correo: cuentas, caché de mensajes, adjuntos, reglas, borradores, seguimiento, cola de operaciones y correo de equipo.

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


# ---- Correo de equipo (mensajes asignados / compartidos / notas internas) ------

def _dueno_del_mensaje(conn: sqlite3.Connection, mensaje_id: int) -> int | None:
    f = conn.execute(
        "SELECT c.usuario_id FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id WHERE m.id = ?", (mensaje_id,)
    ).fetchone()
    return f["usuario_id"] if f else None


def rol_en_correo(usuario_id: int, mensaje_id: int) -> str | None:
    """'dueno', 'asignado', 'compartido' o None si no lo ve."""
    conn = _db.get_connection()
    try:
        dueno = _db._dueno_del_mensaje(conn, mensaje_id)
        if dueno is None:
            return None
        if dueno == usuario_id:
            return "dueno"
        # Quien ya no está en el despacho del dueño pierde el acceso aunque
        # siga figurando como asignado o compartido.
        mismo_despacho = conn.execute(
            "SELECT 1 FROM usuarios a JOIN usuarios b ON b.tenant_id = a.tenant_id "
            "WHERE a.id = ? AND b.id = ? AND a.tenant_id IS NOT NULL", (usuario_id, dueno),
        ).fetchone()
        if mismo_despacho is None:
            return None
        eq = conn.execute("SELECT asignado_a FROM correo_equipo WHERE mensaje_id = ?", (mensaje_id,)).fetchone()
        if eq and eq["asignado_a"] == usuario_id:
            return "asignado"
        if conn.execute(
            "SELECT 1 FROM correo_compartidos WHERE mensaje_id = ? AND usuario_id = ?", (mensaje_id, usuario_id)
        ).fetchone():
            return "compartido"
        return None
    finally:
        conn.close()


def _auditar_correo_equipo(conn: sqlite3.Connection, mensaje_id: int, usuario_id: int, accion: str, detalle: str | None = None) -> None:
    conn.execute(
        "INSERT INTO correo_equipo_auditoria (mensaje_id, usuario_id, accion, detalle, creado_en) VALUES (?, ?, ?, ?, ?)",
        (mensaje_id, usuario_id, accion, detalle, _db.now_iso()),
    )


def registrar_lectura_correo_equipo(usuario_id: int, mensaje_id: int) -> None:
    """Anota que un compañero (no el dueño) ha abierto el mensaje: una vez por
    persona y día, para saber quién lo ha visto sin llenar el historial."""
    hoy = _db.now_iso()[:10]
    conn = _db.get_connection()
    try:
        if _db._dueno_del_mensaje(conn, mensaje_id) in (None, usuario_id):
            return
        ya = conn.execute(
            "SELECT 1 FROM correo_equipo_auditoria WHERE mensaje_id = ? AND usuario_id = ? AND accion = 'leer' AND creado_en >= ?",
            (mensaje_id, usuario_id, hoy),
        ).fetchone()
        if ya is None:
            _db._auditar_correo_equipo(conn, mensaje_id, usuario_id, "leer")
            conn.commit()
    finally:
        conn.close()


def historial_correo_equipo(usuario_id: int, mensaje_id: int) -> list[dict]:
    """Solo el dueño del mensaje ve quién ha hecho qué con él."""
    conn = _db.get_connection()
    try:
        if _db._dueno_del_mensaje(conn, mensaje_id) != usuario_id:
            return []
        return [dict(f) for f in conn.execute(
            """SELECT a.accion, a.detalle, a.creado_en, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM correo_equipo_auditoria a JOIN usuarios u ON u.id = a.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = a.usuario_id
               WHERE a.mensaje_id = ? ORDER BY a.id DESC LIMIT 100""",
            (mensaje_id,),
        )]
    finally:
        conn.close()


def asignar_correo(usuario_id: int, mensaje_id: int, destino_id: int | None) -> bool:
    """El dueño asigna el mensaje a un compañero del despacho (que además pasa a
    verlo) o quita la asignación con None. Cada asignación nueva reabre el estado."""
    conn = _db.get_connection()
    try:
        if _db._dueno_del_mensaje(conn, mensaje_id) != usuario_id:
            return False
        destino = None
        if destino_id is not None:
            destino = _db._companero_del_tenant(conn, usuario_id, destino_id)
            if destino is None:
                return False
        conn.execute(
            """INSERT INTO correo_equipo (mensaje_id, asignado_a, asignado_por, estado, actualizado_en)
               VALUES (?, ?, ?, 'abierto', ?)
               ON CONFLICT(mensaje_id) DO UPDATE SET asignado_a = excluded.asignado_a,
                   asignado_por = excluded.asignado_por, estado = 'abierto', actualizado_en = excluded.actualizado_en""",
            (mensaje_id, destino, usuario_id, _db.now_iso()),
        )
        _db._auditar_correo_equipo(conn, mensaje_id, usuario_id, "asignar" if destino else "desasignar", str(destino) if destino else None)
        conn.commit()
    finally:
        conn.close()
    _db._emitir_evento(usuario_id, "correo.asignado", {"mensaje_id": mensaje_id, "asignado_a": destino})
    return True


def compartir_correo(usuario_id: int, mensaje_id: int, otro_id: int) -> bool:
    """El dueño comparte el mensaje (solo lectura) con un compañero del despacho."""
    conn = _db.get_connection()
    try:
        if _db._dueno_del_mensaje(conn, mensaje_id) != usuario_id:
            return False
        destino = _db._companero_del_tenant(conn, usuario_id, otro_id)
        if destino is None:
            return False
        ya = conn.execute("SELECT 1 FROM correo_compartidos WHERE mensaje_id = ? AND usuario_id = ?", (mensaje_id, destino)).fetchone()
        if ya is None:
            if conn.execute("SELECT COUNT(*) FROM correo_compartidos WHERE mensaje_id = ?", (mensaje_id,)).fetchone()[0] >= _db.MAX_COMPARTIDOS_POR_MENSAJE:
                return False
            conn.execute(
                "INSERT INTO correo_compartidos (mensaje_id, usuario_id, compartido_en) VALUES (?, ?, ?)",
                (mensaje_id, destino, _db.now_iso()),
            )
            _db._auditar_correo_equipo(conn, mensaje_id, usuario_id, "compartir", str(destino))
            conn.commit()
        return True
    finally:
        conn.close()


def dejar_de_compartir_correo(usuario_id: int, mensaje_id: int, otro_id: int) -> bool:
    """El dueño quita a alguien; cada persona puede salirse. No toca la asignación."""
    conn = _db.get_connection()
    try:
        if _db._dueno_del_mensaje(conn, mensaje_id) != usuario_id and otro_id != usuario_id:
            return False
        cur = conn.execute("DELETE FROM correo_compartidos WHERE mensaje_id = ? AND usuario_id = ?", (mensaje_id, otro_id))
        if cur.rowcount > 0:
            _db._auditar_correo_equipo(conn, mensaje_id, usuario_id, "quitar", str(otro_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def cambiar_estado_correo_equipo(usuario_id: int, mensaje_id: int, estado: str) -> bool:
    """'abierto' o 'resuelto': lo cambia el dueño o quien lo tiene asignado."""
    if estado not in ("abierto", "resuelto") or _db.rol_en_correo(usuario_id, mensaje_id) not in ("dueno", "asignado"):
        return False
    conn = _db.get_connection()
    try:
        conn.execute(
            """INSERT INTO correo_equipo (mensaje_id, asignado_a, asignado_por, estado, actualizado_en)
               VALUES (?, NULL, ?, ?, ?)
               ON CONFLICT(mensaje_id) DO UPDATE SET estado = excluded.estado, actualizado_en = excluded.actualizado_en""",
            (mensaje_id, usuario_id, estado, _db.now_iso()),
        )
        _db._auditar_correo_equipo(conn, mensaje_id, usuario_id, "estado", estado)
        conn.commit()
        return True
    finally:
        conn.close()


def estado_correo_equipo(mensaje_id: int) -> dict:
    """Asignación, estado y personas con acceso de un mensaje (sin comprobar permisos:
    el llamante ya ha comprobado que el usuario lo ve)."""
    conn = _db.get_connection()
    try:
        eq = conn.execute(
            """SELECT e.asignado_a, e.estado, e.actualizado_en,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS asignado_nombre
               FROM correo_equipo e LEFT JOIN usuarios u ON u.id = e.asignado_a
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = e.asignado_a WHERE e.mensaje_id = ?""",
            (mensaje_id,),
        ).fetchone()
        compartidos = [dict(f) for f in conn.execute(
            """SELECT c.usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre
               FROM correo_compartidos c JOIN usuarios u ON u.id = c.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = c.usuario_id
               WHERE c.mensaje_id = ? ORDER BY nombre""",
            (mensaje_id,),
        )]
    finally:
        conn.close()
    base = dict(eq) if eq else {"asignado_a": None, "estado": "abierto", "actualizado_en": None, "asignado_nombre": None}
    base["compartidos"] = compartidos
    return base


def obtener_correo_equipo(usuario_id: int, mensaje_id: int) -> dict | None:
    """El mensaje (sin HTML ni adjuntos: solo texto) para quien lo ve por estar
    asignado o compartido, con su rol y el nombre del dueño."""
    rol = _db.rol_en_correo(usuario_id, mensaje_id)
    if rol is None:
        return None
    conn = _db.get_connection()
    try:
        f = conn.execute(
            """SELECT m.id, m.asunto, m.remitente, m.destinatarios, m.fecha, m.cuerpo_texto,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS dueno_nombre, c.usuario_id AS dueno_id
               FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               JOIN usuarios u ON u.id = c.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = c.usuario_id
               WHERE m.id = ?""",
            (mensaje_id,),
        ).fetchone()
    finally:
        conn.close()
    if f is None:
        return None
    from . import correo_cifrado
    d = dict(correo_cifrado.completar_uno(f))
    d["rol"] = rol
    d.update({k: v for k, v in _db.estado_correo_equipo(mensaje_id).items()})
    return d


def listar_correo_equipo(usuario_id: int, vista: str = "asignados") -> list[dict]:
    """'asignados' (a mí), 'compartidos' (conmigo) o 'enviados' (los míos que he
    asignado o compartido). Lo resuelto va al final."""
    conn = _db.get_connection()
    try:
        base = """SELECT m.id, m.asunto, m.remitente, m.fecha, COALESCE(e.estado, 'abierto') AS estado, e.asignado_a,
                         COALESCE(NULLIF(pfd.nombre_mostrado, ''), ud.email) AS dueno_nombre,
                         COALESCE(NULLIF(pfa.nombre_mostrado, ''), ua.email) AS asignado_nombre,
                         (SELECT COUNT(*) FROM correo_notas_internas n WHERE n.mensaje_id = m.id) AS n_notas
                  FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
                  JOIN usuarios ud ON ud.id = c.usuario_id LEFT JOIN usuario_perfil pfd ON pfd.usuario_id = c.usuario_id
                  LEFT JOIN correo_equipo e ON e.mensaje_id = m.id
                  LEFT JOIN usuarios ua ON ua.id = e.asignado_a LEFT JOIN usuario_perfil pfa ON pfa.usuario_id = e.asignado_a"""
        if vista == "compartidos":
            donde, params = "WHERE m.id IN (SELECT mensaje_id FROM correo_compartidos WHERE usuario_id = ?)", [usuario_id]
        elif vista == "enviados":
            donde, params = (
                "WHERE c.usuario_id = ? AND (e.asignado_a IS NOT NULL OR m.id IN (SELECT mensaje_id FROM correo_compartidos))",
                [usuario_id],
            )
        else:
            donde, params = "WHERE e.asignado_a = ?", [usuario_id]
        filas = conn.execute(
            f"{base} {donde} ORDER BY (COALESCE(e.estado, 'abierto') = 'resuelto'), m.fecha DESC LIMIT 200", params
        ).fetchall()
        from . import correo_cifrado
        return [dict(f) for f in correo_cifrado.completar(filas)]
    finally:
        conn.close()


def contar_correo_asignado_abierto(usuario_id: int) -> int:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM correo_equipo WHERE asignado_a = ? AND estado = 'abierto'", (usuario_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


def anadir_nota_interna_correo(usuario_id: int, mensaje_id: int, texto: str) -> int | None:
    """Nota interna del equipo sobre un mensaje: la puede escribir cualquiera que lo vea."""
    texto = (texto or "").strip()[:_db.NOTA_INTERNA_MAX_CARACTERES]
    if not texto or _db.rol_en_correo(usuario_id, mensaje_id) is None:
        return None
    conn = _db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM correo_notas_internas WHERE mensaje_id = ?", (mensaje_id,)).fetchone()[0] >= _db.MAX_NOTAS_INTERNAS_POR_MENSAJE:
            return None
        cur = conn.execute(
            "INSERT INTO correo_notas_internas (mensaje_id, usuario_id, texto, creado_en) VALUES (?, ?, ?, ?)",
            (mensaje_id, usuario_id, texto, _db.now_iso()),
        )
        _db._auditar_correo_equipo(conn, mensaje_id, usuario_id, "nota")
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_notas_internas_correo(usuario_id: int, mensaje_id: int) -> list[dict]:
    rol = _db.rol_en_correo(usuario_id, mensaje_id)
    if rol is None:
        return []
    conn = _db.get_connection()
    try:
        return [
            {**dict(f), "mia": f["usuario_id"] == usuario_id, "puede_borrar": f["usuario_id"] == usuario_id or rol == "dueno"}
            for f in conn.execute(
                """SELECT n.id, n.usuario_id, n.texto, n.creado_en, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
                   FROM correo_notas_internas n JOIN usuarios u ON u.id = n.usuario_id
                   LEFT JOIN usuario_perfil pf ON pf.usuario_id = n.usuario_id
                   WHERE n.mensaje_id = ? ORDER BY n.id""",
                (mensaje_id,),
            )
        ]
    finally:
        conn.close()


def eliminar_nota_interna_correo(usuario_id: int, mensaje_id: int, nota_id: int) -> bool:
    rol = _db.rol_en_correo(usuario_id, mensaje_id)
    if rol is None:
        return False
    conn = _db.get_connection()
    try:
        n = conn.execute("SELECT usuario_id FROM correo_notas_internas WHERE id = ? AND mensaje_id = ?", (nota_id, mensaje_id)).fetchone()
        if n is None or not (n["usuario_id"] == usuario_id or rol == "dueno"):
            return False
        conn.execute("DELETE FROM correo_notas_internas WHERE id = ?", (nota_id,))
        _db._auditar_correo_equipo(conn, mensaje_id, usuario_id, "nota_borrada")
        conn.commit()
        return True
    finally:
        conn.close()


def crear_cuenta_correo(
    usuario_id: int,
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True, auth_tipo: str = "password",
) -> int:
    """`auth_tipo`: 'password' (contraseña en el almacén de credenciales), 'google' o 'microsoft' (OAuth2)."""
    if auth_tipo not in ("password", "google", "microsoft"):
        raise ValueError("auth_tipo no válido")
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_cuentas
               (usuario_id, nombre, protocolo, host, puerto, usa_tls, usuario,
                smtp_host, smtp_puerto, smtp_tls, auth_tipo, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, nombre.strip(), protocolo, host.strip(), puerto, int(usa_tls),
             usuario.strip(), (smtp_host or "").strip() or None, smtp_puerto,
             int(smtp_tls), auth_tipo, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_cuentas_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_cuentas WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def obtener_cuenta_correo(usuario_id: int, cuenta_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_cuentas WHERE id = ? AND usuario_id = ?", (cuenta_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def editar_cuenta_correo(
    usuario_id: int, cuenta_id: int,
    nombre: str, protocolo: str, host: str, puerto: int, usuario: str,
    usa_tls: bool = True, smtp_host: str | None = None,
    smtp_puerto: int | None = None, smtp_tls: bool = True,
) -> None:
    """Mismos campos que crear_cuenta_correo, pero UPDATE -- la
    contraseña NO se toca aquí (vive en keyring, ver
    app/correo.py:editar_cuenta), así que un error tipográfico de
    host/puerto ya no obliga a borrar y recrear la cuenta entera
    (que borraba también los mensajes en caché)."""
    conn = _db.get_connection()
    try:
        conn.execute(
            """UPDATE correo_cuentas
               SET nombre = ?, protocolo = ?, host = ?, puerto = ?, usa_tls = ?, usuario = ?,
                   smtp_host = ?, smtp_puerto = ?, smtp_tls = ?
               WHERE id = ? AND usuario_id = ?""",
            (nombre.strip(), protocolo, host.strip(), puerto, int(usa_tls), usuario.strip(),
             (smtp_host or "").strip() or None, smtp_puerto, int(smtp_tls), cuenta_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_cuenta_correo(usuario_id: int, cuenta_id: int) -> None:
    """Borra la cuenta y sus mensajes/carpetas cacheados. Sin papelera: la
    credencial en keyring se borra aparte, desde app/correo.py, antes de
    llamar aquí."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_mensajes WHERE cuenta_id IN (SELECT id FROM correo_cuentas WHERE id = ? AND usuario_id = ?)",
            (cuenta_id, usuario_id),
        )
        conn.execute(
            "DELETE FROM correo_carpetas WHERE cuenta_id IN (SELECT id FROM correo_cuentas WHERE id = ? AND usuario_id = ?)",
            (cuenta_id, usuario_id),
        )
        conn.execute("DELETE FROM correo_cuentas WHERE id = ? AND usuario_id = ?", (cuenta_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def guardar_firma_correo(usuario_id: int, cuenta_id: int, firma_html: str | None, firma_en_nuevos: bool, firma_en_respuestas: bool) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            """UPDATE correo_cuentas SET firma_html = ?, firma_en_nuevos = ?, firma_en_respuestas = ?
               WHERE id = ? AND usuario_id = ?""",
            (firma_html, int(firma_en_nuevos), int(firma_en_respuestas), cuenta_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Carpetas IMAP (POP3 no tiene fila aquí, ver comentario del esquema) ------

def guardar_carpetas_correo(cuenta_id: int, carpetas: list[tuple[str, str]]) -> None:
    """`carpetas`: lista de (nombre, nombre_visible). Upsert — no borra
    carpetas que ya no aparezcan en el servidor, para no perder sus mensajes
    cacheados si es un fallo puntual de listado."""
    conn = _db.get_connection()
    try:
        for nombre, nombre_visible in carpetas:
            conn.execute(
                """INSERT INTO correo_carpetas (cuenta_id, nombre, nombre_visible) VALUES (?, ?, ?)
                   ON CONFLICT (cuenta_id, nombre) DO UPDATE SET nombre_visible = excluded.nombre_visible""",
                (cuenta_id, nombre, nombre_visible),
            )
        conn.commit()
    finally:
        conn.close()


def listar_carpetas_correo(cuenta_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_carpetas WHERE cuenta_id = ? ORDER BY nombre_visible", (cuenta_id,)
        ).fetchall()
    finally:
        conn.close()


# --- Categorías de correo (propias de Guilda Work, no se sincronizan) --------

def crear_categoria_correo(usuario_id: int, nombre: str, color: str) -> int:
    """Lanza ValueError (mensaje legible, lo traduce app/correo.py a
    ErrorCorreo) si ya tienes una categoría de correo con ese nombre --
    antes era un IntegrityError sin capturar, 500 en crudo (revisión de
    lógica; la UNIQUE ahora es por (usuario_id, nombre), así que esto ya
    NUNCA salta por culpa de OTRO usuario, solo por repetir un nombre
    propio)."""
    conn = _db.get_connection()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO correo_categorias (usuario_id, nombre, color, creada_en) VALUES (?, ?, ?, ?)",
                (usuario_id, nombre.strip(), color, _db.now_iso()),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"Ya tienes una categoría de correo llamada '{nombre.strip()}'.") from None
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_categorias_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_categorias WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def eliminar_categoria_correo(usuario_id: int, categoria_id: int) -> None:
    """Los mensajes que la tuvieran asignada se quedan sin categoría
    (ON DELETE SET NULL en el esquema)."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


# --- Plantillas de respuesta guardadas (app/rutas_correo.py) ---------------

def crear_plantilla_correo(usuario_id: int, nombre: str, asunto: str | None, cuerpo: str, modelo: str | None = None) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO correo_plantillas (usuario_id, nombre, asunto, cuerpo, modelo, creada_en) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, nombre.strip(), (asunto or "").strip() or None, cuerpo, (modelo or "").strip()[:20] or None, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def editar_plantilla_correo(usuario_id: int, plantilla_id: int, nombre: str, asunto: str | None, cuerpo: str, modelo: str | None = None) -> bool:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE correo_plantillas SET nombre = ?, asunto = ?, cuerpo = ?, modelo = ? WHERE id = ? AND usuario_id = ?",
            (nombre.strip(), (asunto or "").strip() or None, cuerpo, (modelo or "").strip()[:20] or None, plantilla_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def listar_plantillas_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_plantillas WHERE usuario_id = ? ORDER BY nombre", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def obtener_plantilla_correo(usuario_id: int, plantilla_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_plantillas WHERE id = ? AND usuario_id = ?", (plantilla_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def eliminar_plantilla_correo(usuario_id: int, plantilla_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_plantillas WHERE id = ? AND usuario_id = ?", (plantilla_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


# --- Borradores al redactar (app/rutas_correo.py) --------------------------

def guardar_borrador_correo(
    usuario_id: int, borrador_id: int | None, *, cuenta_id: int | None, destinatarios: str,
    cc: str, bcc: str, asunto: str, cuerpo_html: str, en_respuesta_a: str | None,
) -> int:
    """Crea el borrador si `borrador_id` es None, si no lo actualiza --
    mismo id se reutiliza en guardados sucesivos del mismo compositor."""
    conn = _db.get_connection()
    try:
        if borrador_id is not None:
            cur = conn.execute(
                """UPDATE correo_borradores SET cuenta_id = ?, destinatarios = ?, cc = ?, bcc = ?,
                   asunto = ?, cuerpo_html = ?, en_respuesta_a = ?, actualizado_en = ?
                   WHERE id = ? AND usuario_id = ?""",
                (cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a,
                 _db.now_iso(), borrador_id, usuario_id),
            )
            conn.commit()
            if cur.rowcount:
                return borrador_id
        cur = conn.execute(
            """INSERT INTO correo_borradores
               (usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a, actualizado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_borradores_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_borradores WHERE usuario_id = ? ORDER BY actualizado_en DESC", (usuario_id,)
        ).fetchall()
    finally:
        conn.close()


def contar_borradores_correo(usuario_id: int) -> int:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM correo_borradores WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


def obtener_borrador_correo(usuario_id: int, borrador_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_borradores WHERE id = ? AND usuario_id = ?", (borrador_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def listar_adjuntos_borrador(usuario_id: int, borrador_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT a.id, a.nombre, a.tipo, length(a.contenido) AS tamano
               FROM correo_borradores_adjuntos a JOIN correo_borradores b ON b.id = a.borrador_id
               WHERE a.borrador_id = ? AND b.usuario_id = ? ORDER BY a.id""",
            (borrador_id, usuario_id),
        ).fetchall()
    finally:
        conn.close()


def adjuntos_borrador_para_enviar(usuario_id: int, borrador_id: int, ids: list[int]) -> list[dict]:
    """Contenido de los adjuntos guardados del borrador cuyos ids se indican."""
    if not ids:
        return []
    conn = _db.get_connection()
    try:
        marcadores = ",".join("?" * len(ids))
        filas = conn.execute(
            f"""SELECT a.id, a.nombre, a.tipo, a.contenido FROM correo_borradores_adjuntos a
                JOIN correo_borradores b ON b.id = a.borrador_id
                WHERE a.borrador_id = ? AND b.usuario_id = ? AND a.id IN ({marcadores}) ORDER BY a.id""",
            [borrador_id, usuario_id, *ids],
        ).fetchall()
        return [{"nombre": f["nombre"], "tipo": f["tipo"], "bytes": bytes(f["contenido"])} for f in filas]
    finally:
        conn.close()


def copiar_adjuntos_envio_a_borrador(envio_id: int, borrador_id: int) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_borradores_adjuntos (borrador_id, nombre, tipo, contenido)
               SELECT ?, nombre, tipo, contenido FROM correo_envios_adjuntos WHERE envio_id = ? ORDER BY id""",
            (borrador_id, envio_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def eliminar_borrador_correo(usuario_id: int, borrador_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_borradores_adjuntos WHERE borrador_id IN "
            "(SELECT id FROM correo_borradores WHERE id = ? AND usuario_id = ?)", (borrador_id, usuario_id)
        )
        conn.execute(
            "DELETE FROM correo_borradores WHERE id = ? AND usuario_id = ?", (borrador_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def asignar_categoria_correo(usuario_id: int, mensaje_id: int, categoria_id: int | None) -> None:
    """`usuario_id` solo para comprobar que `categoria_id` es suya --
    quien llama ya tiene que haber comprobado por su cuenta que
    `mensaje_id` es del usuario (ver _mensaje_de_usuario_o_404 en
    rutas_correo.py), esta función no repite esa parte."""
    conn = _db.get_connection()
    try:
        if categoria_id is not None:
            fila = conn.execute(
                "SELECT 1 FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
            ).fetchone()
            if fila is None:
                categoria_id = None
        from . import correo_cifrado
        if not correo_cifrado.reescribir_asociacion(mensaje_id, categoria_id=categoria_id):      # en Estricto vive dentro del bloque cifrado
            conn.execute("UPDATE correo_mensajes SET categoria_id = ? WHERE id = ?", (categoria_id, mensaje_id))
            conn.commit()
    finally:
        conn.close()


def cliente_fiscal_id_por_email(tenant_id: int, email: str | None) -> int | None:
    """El cliente fiscal cuyo email coincide con `email` (sin distinguir
    mayúsculas), solo si es único en el despacho: con dos clientes con el mismo
    correo no se adivina y no se vincula ninguno."""
    email = (email or "").strip().lower()
    if not email:
        return None
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT id FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL AND LOWER(TRIM(email)) = ? LIMIT 2",
            (tenant_id, email),
        ).fetchall()
        return filas[0]["id"] if len(filas) == 1 else None
    finally:
        conn.close()


def mensajes_correo_sin_cliente(usuario_id: int, limite: int = 5000) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT m.id, m.remitente, m.cifrado FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE c.usuario_id = ? AND m.cliente_fiscal_id IS NULL AND (m.remitente IS NOT NULL OR m.cifrado = 1)
               ORDER BY m.id DESC LIMIT ?""",
            (usuario_id, limite),
        ).fetchall()
    finally:
        conn.close()
    from . import correo_cifrado
    if not correo_cifrado.hay_alguno():
        return filas
    # Sellados: el remitente (y el cliente, en Estricto) solo están disponibles con clave; sin ella no se puede vincular y se omiten.
    return [f for f in correo_cifrado.completar(filas) if not f.get("protegido") and f.get("cliente_fiscal_id") is None and f.get("remitente")]


def asignar_cliente_fiscal_correo(tenant_id: int, mensaje_id: int, cliente_fiscal_id: int | None) -> None:
    """`tenant_id` solo para comprobar que `cliente_fiscal_id` es suyo --
    mismo criterio que asignar_categoria_correo, quien llama ya tiene
    que haber comprobado que `mensaje_id` es del usuario actual."""
    conn = _db.get_connection()
    try:
        if cliente_fiscal_id is not None:
            fila = conn.execute(
                "SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL",
                (cliente_fiscal_id, tenant_id),
            ).fetchone()
            if fila is None:
                cliente_fiscal_id = None
        from . import correo_cifrado
        if not correo_cifrado.reescribir_asociacion(mensaje_id, cliente_fiscal_id=cliente_fiscal_id):
            conn.execute(
                "UPDATE correo_mensajes SET cliente_fiscal_id = ? WHERE id = ?", (cliente_fiscal_id, mensaje_id)
            )
            conn.commit()
    finally:
        conn.close()


def listar_correos_de_cliente_fiscal(cliente_fiscal_id: int) -> list[sqlite3.Row]:
    """Correos vinculados manualmente a un cliente fiscal (ver
    asignar_cliente_fiscal_correo), para la sección "Correos
    relacionados" de su ficha (app/rutas_fiscal.py:ficha_cliente) --
    mismo criterio de agregación que listar_documentos_vencimiento."""
    from . import correo_cifrado
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT * FROM correo_mensajes WHERE cliente_fiscal_id = ? ORDER BY fecha DESC",
            (cliente_fiscal_id,),
        ).fetchall()
        tenant = conn.execute("SELECT tenant_id FROM clientes_fiscales WHERE id = ?", (cliente_fiscal_id,)).fetchone() if correo_cifrado.hay_alguno() else None
    finally:
        conn.close()
    filas = correo_cifrado.completar(filas)
    if tenant is not None:     # en Estricto el cliente vive dentro del bloque cifrado: se busca entre los descifrados
        filas = filas + [m for m in correo_cifrado.candidatos_estricto(tenant_id=tenant["tenant_id"]) if m.get("cliente_fiscal_id") == cliente_fiscal_id]
        filas.sort(key=lambda m: (m.get("fecha") or ""), reverse=True)
    return filas


# --- Remitentes de confianza (imágenes/adjuntos no se bloquean) --------------

def confiar_en_remitente(usuario_id: int, direccion: str) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_remitentes_confiables (usuario_id, direccion, creada_en)
               VALUES (?, ?, ?)
               ON CONFLICT (usuario_id, direccion) DO NOTHING""",
            (usuario_id, direccion.strip().lower(), _db.now_iso()),
        )
        conn.commit()
        fila = conn.execute(
            "SELECT id FROM correo_remitentes_confiables WHERE usuario_id = ? AND direccion = ?",
            (usuario_id, direccion.strip().lower()),
        ).fetchone()
        return fila["id"] if fila else cur.lastrowid
    finally:
        conn.close()


def listar_remitentes_confiables(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_remitentes_confiables WHERE usuario_id = ? ORDER BY direccion",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def eliminar_remitente_confiable(usuario_id: int, remitente_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_remitentes_confiables WHERE id = ? AND usuario_id = ?",
            (remitente_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def es_remitente_confiable(usuario_id: int, direccion: str | None) -> bool:
    if not direccion:
        return False
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM correo_remitentes_confiables WHERE usuario_id = ? AND direccion = ?",
            (usuario_id, direccion.strip().lower()),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


# --- Reglas de categorización automática por remitente -----------------------

def crear_regla_categoria_correo(usuario_id: int, remitente_patron: str, categoria_id: int) -> int:
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT 1 FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        ).fetchone()
        if fila is None:
            raise ValueError(f"La categoría de correo {categoria_id} no existe o no es tuya.")
        cur = conn.execute(
            """INSERT INTO correo_reglas_categoria (usuario_id, remitente_patron, categoria_id, creada_en)
               VALUES (?, ?, ?, ?)""",
            (usuario_id, remitente_patron.strip().lower(), categoria_id, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_reglas_categoria_correo(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT r.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM correo_reglas_categoria r
               JOIN correo_categorias c ON c.id = r.categoria_id AND c.usuario_id = r.usuario_id
               WHERE r.usuario_id = ? ORDER BY r.remitente_patron""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def eliminar_regla_categoria_correo(usuario_id: int, regla_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_reglas_categoria WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def crear_regla_correo(
    usuario_id: int, remitente_patron: str | None = None, asunto_patron: str | None = None,
    categoria_id: int | None = None, marcar_leido: bool = False, destacar: bool = False,
    cliente_fiscal_id: int | None = None, archivar_adjuntos: bool = False,
) -> int:
    """Regla avanzada. Necesita al menos una condición (remitente o asunto) y
    al menos una acción; categoría y cliente se validan contra el usuario."""
    remitente_patron = (remitente_patron or "").strip().lower() or None
    asunto_patron = (asunto_patron or "").strip().lower() or None
    if not remitente_patron and not asunto_patron:
        raise ValueError("Indica al menos una condición: remitente o asunto.")
    conn = _db.get_connection()
    try:
        if categoria_id is not None and conn.execute(
            "SELECT 1 FROM correo_categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        ).fetchone() is None:
            raise ValueError("La categoría elegida no existe.")
        cliente_fiscal_id = _db._cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id)
        if archivar_adjuntos and cliente_fiscal_id is None:
            raise ValueError("Para archivar los adjuntos en el expediente, elige el cliente.")
        if categoria_id is None and not marcar_leido and not destacar and cliente_fiscal_id is None:
            raise ValueError("Elige al menos una acción para la regla.")
        cur = conn.execute(
            """INSERT INTO correo_reglas
               (usuario_id, remitente_patron, asunto_patron, categoria_id, marcar_leido, destacar, cliente_fiscal_id,
                archivar_adjuntos, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, remitente_patron, asunto_patron, categoria_id, 1 if marcar_leido else 0,
             1 if destacar else 0, cliente_fiscal_id, 1 if archivar_adjuntos else 0, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --- Destinatarios recientes (para autocompletar al redactar) ----------------

def registrar_destinatario_reciente(usuario_id: int, direccion: str, nombre_mostrado: str | None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            """INSERT INTO correo_destinatarios_recientes
               (usuario_id, direccion, nombre_mostrado, ultima_vez_en, veces_usado)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT (usuario_id, direccion) DO UPDATE SET
                   nombre_mostrado = excluded.nombre_mostrado,
                   ultima_vez_en = excluded.ultima_vez_en,
                   veces_usado = veces_usado + 1""",
            (usuario_id, direccion.strip().lower(), nombre_mostrado, _db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def buscar_destinatarios_recientes(usuario_id: int, q: str | None = None, limite: int = 8) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        if q:
            patron = f"%{q.strip().lower()}%"
            return conn.execute(
                """SELECT * FROM correo_destinatarios_recientes
                   WHERE usuario_id = ? AND (direccion LIKE ? OR LOWER(nombre_mostrado) LIKE ?)
                   ORDER BY veces_usado DESC, ultima_vez_en DESC LIMIT ?""",
                (usuario_id, patron, patron, limite),
            ).fetchall()
        return conn.execute(
            """SELECT * FROM correo_destinatarios_recientes WHERE usuario_id = ?
               ORDER BY veces_usado DESC, ultima_vez_en DESC LIMIT ?""",
            (usuario_id, limite),
        ).fetchall()
    finally:
        conn.close()


def encolar_envio_correo(
    usuario_id: int, cuenta_id: int, destinatarios: str, cc: str, bcc: str, asunto: str,
    cuerpo_html: str, en_respuesta_a: str | None, adjuntos: list[dict], enviar_en: str,
    programado: bool = False, seguimiento_dias: int | None = None,
) -> int:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO correo_envios
               (usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a,
                enviar_en, programado, seguimiento_dias, creado_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, cuenta_id, destinatarios, cc, bcc, asunto, cuerpo_html, en_respuesta_a,
             enviar_en, int(programado), _db.seguimiento_dias_valido(seguimiento_dias), _db.now_iso()),
        )
        envio_id = cur.lastrowid
        for a in adjuntos:
            conn.execute(
                "INSERT INTO correo_envios_adjuntos (envio_id, nombre, tipo, contenido) VALUES (?, ?, ?, ?)",
                (envio_id, a["nombre"], a["tipo"], a["bytes"]),
            )
        conn.commit()
        return envio_id
    finally:
        conn.close()


def seguimiento_dias_valido(valor) -> int | None:
    try:
        dias = int(valor)
    except (TypeError, ValueError):
        return None
    return dias if 1 <= dias <= _db.DIAS_SEGUIMIENTO_MAX else None


def crear_seguimiento_correo(
    usuario_id: int, cuenta_id: int, message_id: str, asunto: str, destinatarios: str, dias, ahora: _db.datetime | None = None,
) -> int | None:
    """Empieza a esperar respuesta a un correo enviado (por su Message-ID). Uno por mensaje: repetirlo no duplica."""
    dias = _db.seguimiento_dias_valido(dias)
    message_id = (message_id or "").strip()
    if dias is None or not message_id:
        return None
    ahora = ahora or _db.datetime.now()
    conn = _db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM correo_cuentas WHERE id = ? AND usuario_id = ?", (cuenta_id, usuario_id)).fetchone() is None:
            return None
        previo = conn.execute(
            "SELECT id FROM correo_seguimientos WHERE usuario_id = ? AND message_id = ? AND estado = 'esperando'", (usuario_id, message_id)
        ).fetchone()
        if previo:
            return previo["id"]
        cur = conn.execute(
            """INSERT INTO correo_seguimientos (usuario_id, cuenta_id, message_id, asunto, destinatarios, creado_en, avisar_en)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, cuenta_id, message_id, (asunto or "")[:300], (destinatarios or "")[:500], ahora.isoformat(timespec="seconds"),
             (ahora + _db.timedelta(days=dias)).isoformat(timespec="seconds")),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_seguimientos_correo(usuario_id: int, solo_esperando: bool = True) -> list[dict]:
    conn = _db.get_connection()
    try:
        filtro = "AND estado = 'esperando'" if solo_esperando else ""
        return [dict(f) for f in conn.execute(
            f"SELECT * FROM correo_seguimientos WHERE usuario_id = ? {filtro} ORDER BY avisar_en LIMIT 100", (usuario_id,))]
    finally:
        conn.close()


def seguimiento_de_mensaje(usuario_id: int, message_id: str | None) -> dict | None:
    """El seguimiento más reciente de ese Message-ID (el que se ve en la lectura del correo)."""
    if not message_id:
        return None
    conn = _db.get_connection()
    try:
        f = conn.execute(
            "SELECT * FROM correo_seguimientos WHERE usuario_id = ? AND message_id = ? ORDER BY id DESC LIMIT 1", (usuario_id, message_id)
        ).fetchone()
        return dict(f) if f else None
    finally:
        conn.close()


def cancelar_seguimiento_correo(usuario_id: int, seguimiento_id: int) -> bool:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE correo_seguimientos SET estado = 'cancelado', cerrado_en = ? WHERE id = ? AND usuario_id = ? AND estado = 'esperando'",
            (_db.now_iso(), seguimiento_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def seguimientos_en_espera() -> list[dict]:
    """Todos los que siguen esperando, de todos los usuarios: solo para el hilo periódico."""
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM correo_seguimientos WHERE estado = 'esperando' ORDER BY id")]
    finally:
        conn.close()


def cerrar_seguimiento_correo(seguimiento_id: int, estado: str) -> bool:
    """True si lo ha cerrado ahora (con un UPDATE condicional: dos procesos no avisan dos veces)."""
    if estado not in ("respondido", "sin_respuesta"):
        raise ValueError("estado no válido")
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE correo_seguimientos SET estado = ?, cerrado_en = ? WHERE id = ? AND estado = 'esperando'", (estado, _db.now_iso(), seguimiento_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def respuesta_a_mensaje(cuenta_id: int, message_id: str, desde: str, direcciones_propias: set[str]) -> dict | None:
    """Un mensaje recibido después de `desde` que responde a `message_id` (In-Reply-To/References), que no sea de
    las direcciones propias. Devuelve su id y asunto, o None."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT id, remitente, asunto FROM correo_mensajes
               WHERE cuenta_id = ? AND descargado_en >= ? AND (in_reply_to LIKE ? ESCAPE '\\' OR referencias LIKE ? ESCAPE '\\')
               ORDER BY id LIMIT 50""",
            (cuenta_id, desde, _db._like_literal(message_id), _db._like_literal(message_id)),
        ).fetchall()
    finally:
        conn.close()
    from . import correo_cifrado
    filas = correo_cifrado.completar(filas)
    import email.utils as _eu
    for f in filas:
        if ("protegido" in f.keys() and f["protegido"]) and not f["remitente"]:
            continue        # sellado y sin clave: no se puede saber quién lo envía
        if _eu.parseaddr(f["remitente"] or "")[1].strip().lower() not in direcciones_propias:
            return {"id": f["id"], "asunto": f["asunto"]}
    return None


def mensaje_local_por_message_id(usuario_id: int, message_id: str) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            """SELECT m.* FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE c.usuario_id = ? AND m.message_id = ? ORDER BY m.id DESC LIMIT 1""",
            (usuario_id, message_id),
        ).fetchone()
    finally:
        conn.close()
    from . import correo_cifrado
    return correo_cifrado.completar_uno(fila)


def obtener_envio_correo(usuario_id: int, envio_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_envios WHERE id = ? AND usuario_id = ?", (envio_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def listar_envios_programados(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT * FROM correo_envios WHERE usuario_id = ? AND estado = 'pendiente' AND programado = 1
               ORDER BY enviar_en""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def contar_envios_programados(usuario_id: int) -> int:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM correo_envios WHERE usuario_id = ? AND estado = 'pendiente' AND programado = 1",
            (usuario_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def cancelar_envio_correo(usuario_id: int, envio_id: int) -> bool:
    """True si seguía pendiente y queda cancelado; False si ya se ha
    enviado (o se está enviando) o no es del usuario."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE correo_envios SET estado = 'cancelado', procesado_en = ? "
            "WHERE id = ? AND usuario_id = ? AND estado = 'pendiente'",
            (_db.now_iso(), envio_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def envios_correo_vencidos(ahora: str) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_envios WHERE estado = 'pendiente' AND enviar_en <= ? ORDER BY enviar_en, id LIMIT 50",
            (ahora,),
        ).fetchall()
    finally:
        conn.close()


def reclamar_envio_correo(envio_id: int) -> bool:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE correo_envios SET estado = 'enviando', procesado_en = ? WHERE id = ? AND estado = 'pendiente'",
            (_db.now_iso(), envio_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def adjuntos_envio_correo(envio_id: int) -> list[dict]:
    conn = _db.get_connection()
    try:
        return [
            {"nombre": f["nombre"], "tipo": f["tipo"], "bytes": bytes(f["contenido"])}
            for f in conn.execute(
                "SELECT nombre, tipo, contenido FROM correo_envios_adjuntos WHERE envio_id = ? ORDER BY id", (envio_id,)
            ).fetchall()
        ]
    finally:
        conn.close()


def cerrar_envio_correo(envio_id: int, estado: str, error: str | None = None, borrar_adjuntos: bool = True) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE correo_envios SET estado = ?, error = ?, procesado_en = ? WHERE id = ?",
            (estado, error, _db.now_iso(), envio_id),
        )
        if borrar_adjuntos:
            conn.execute("DELETE FROM correo_envios_adjuntos WHERE envio_id = ?", (envio_id,))
        conn.commit()
    finally:
        conn.close()


def rescatar_envios_atascados(antes_de: str) -> list[sqlite3.Row]:
    """Envíos que se quedaron en 'enviando' (el proceso murió a medias):
    se marcan como error para que el usuario no pierda el correo."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT * FROM correo_envios WHERE estado = 'enviando' AND procesado_en < ?", (antes_de,)
        ).fetchall()
        for f in filas:
            conn.execute(
                "UPDATE correo_envios SET estado = 'error', error = ? WHERE id = ?",
                ("El envío se interrumpió; no se sabe si llegó a salir.", f["id"]),
            )
        conn.commit()
        return filas
    finally:
        conn.close()


def purgar_envios_correo_antiguos(antes_de: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "DELETE FROM correo_envios WHERE estado IN ('enviado', 'cancelado', 'error') AND procesado_en < ?",
            (antes_de,),
        )
        conn.commit()
    finally:
        conn.close()


def _obtener_o_crear(conn: sqlite3.Connection, tabla: str, usuario_id: int) -> sqlite3.Row:
    """Fila de `tabla` (clave usuario_id), creándola con sus valores por defecto solo si no
    existe: leerla en cada petición no debe abrir una transacción de escritura."""
    fila = conn.execute(f"SELECT * FROM {tabla} WHERE usuario_id = ?", (usuario_id,)).fetchone()
    if fila is None:
        conn.execute(f"INSERT OR IGNORE INTO {tabla} (usuario_id) VALUES (?)", (usuario_id,))
        conn.commit()
        fila = conn.execute(f"SELECT * FROM {tabla} WHERE usuario_id = ?", (usuario_id,)).fetchone()
    return fila


def obtener_preferencias_correo(usuario_id: int) -> sqlite3.Row:
    conn = _db.get_connection()
    try:
        return _db._obtener_o_crear(conn, "correo_preferencias", usuario_id)
    finally:
        conn.close()


def guardar_preferencias_correo(
    usuario_id: int, densidad: str, marcar_leido_automatico: bool, limite_mensajes: int,
    deshacer_segundos: int | None = None,
) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO correo_preferencias (usuario_id) VALUES (?)", (usuario_id,))
        if deshacer_segundos in _db.DESHACER_ENVIO_OPCIONES:
            conn.execute(
                "UPDATE correo_preferencias SET deshacer_segundos = ? WHERE usuario_id = ?",
                (deshacer_segundos, usuario_id),
            )
        conn.execute(
            """UPDATE correo_preferencias
               SET densidad = ?, marcar_leido_automatico = ?, limite_mensajes = ? WHERE usuario_id = ?""",
            (densidad, int(marcar_leido_automatico), limite_mensajes, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def marcar_sincronizada_cuenta_correo(cuenta_id: int) -> None:
    """Anota la sincronización correcta y limpia el último error."""
    conn = _db.get_connection()
    try:
        conn.execute(
            """UPDATE correo_cuentas
               SET ultima_sincronizacion = ?, ultimo_error_sincronizacion = NULL,
                   ultimo_error_sincronizacion_en = NULL
               WHERE id = ?""",
            (_db.now_iso(), cuenta_id),
        )
        conn.commit()
    finally:
        conn.close()


def marcar_error_sincronizacion_cuenta_correo(cuenta_id: int, error: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE correo_cuentas SET ultimo_error_sincronizacion = ?, ultimo_error_sincronizacion_en = ? WHERE id = ?",
            (error[:300], _db.now_iso(), cuenta_id),
        )
        conn.commit()
    finally:
        conn.close()


def registrar_latido(nombre: str, ok: bool, intervalo_segundos: int, detalle: str | None = None) -> None:
    """Anota que una tarea periódica ha terminado una pasada (bien o con error)."""
    conn = _db.get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO latidos (nombre, intervalo_segundos) VALUES (?, ?)", (nombre, intervalo_segundos))
        if ok:
            conn.execute(
                "UPDATE latidos SET ultimo_ok = ?, detalle = ?, intervalo_segundos = ? WHERE nombre = ?",
                (_db.now_iso(), (detalle or None) and detalle[:300], intervalo_segundos, nombre),
            )
        else:
            conn.execute(
                "UPDATE latidos SET ultimo_error = ?, detalle = ?, intervalo_segundos = ? WHERE nombre = ?",
                (_db.now_iso(), (detalle or None) and detalle[:300], intervalo_segundos, nombre),
            )
        conn.commit()
    finally:
        conn.close()


def registrar_error_servidor(metodo: str, ruta: str, estado: int, request_id: str | None = None) -> None:
    """Anota una respuesta 5xx. `ruta` debe ser la plantilla (`/api/v1/tareas/<int:id>`), no la URL real."""
    ahora = _db.datetime.now()
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO errores_servidor (creado_en, metodo, ruta, estado, request_id) VALUES (?, ?, ?, ?, ?)",
            (ahora.isoformat(timespec="seconds"), metodo[:10], ruta[:160], int(estado), (request_id or "")[:64] or None),
        )
        conn.execute("DELETE FROM errores_servidor WHERE creado_en < ?", ((ahora - _db.timedelta(days=_db.ERRORES_SERVIDOR_RETENCION_DIAS)).isoformat(timespec="seconds"),))
        conn.commit()
    finally:
        conn.close()


def resumen_errores_servidor(desde: str) -> dict:
    """Errores 5xx desde una fecha ISO: total y la ruta que más se repite."""
    conn = _db.get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM errores_servidor WHERE creado_en >= ?", (desde,)).fetchone()[0]
        top = conn.execute(
            "SELECT metodo, ruta, COUNT(*) AS n FROM errores_servidor WHERE creado_en >= ? GROUP BY metodo, ruta ORDER BY n DESC LIMIT 1", (desde,)
        ).fetchone()
        return {"total": total, "ruta": f"{top['metodo']} {top['ruta']}" if top else None, "repeticiones": top["n"] if top else 0}
    finally:
        conn.close()


def listar_latidos() -> dict[str, sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return {f["nombre"]: f for f in conn.execute("SELECT * FROM latidos").fetchall()}
    finally:
        conn.close()


def alerta_salud_enviada(motivo: str, dia: str) -> bool:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM salud_alertas WHERE motivo = ? AND dia = ?", (motivo, dia)).fetchone() is not None
    finally:
        conn.close()


def marcar_alerta_salud(motivo: str, dia: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO salud_alertas (motivo, dia, enviada_en) VALUES (?, ?, ?)", (motivo, dia, _db.now_iso())
        )
        limite = (_db.datetime.strptime(dia, "%Y-%m-%d") - _db.timedelta(days=30)).strftime("%Y-%m-%d")
        conn.execute("DELETE FROM salud_alertas WHERE dia < ?", (limite,))
        conn.commit()
    finally:
        conn.close()


def estado_cuentas_correo_global() -> list[sqlite3.Row]:
    """Todas las cuentas de correo con su última sincronización y error (panel de salud)."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT c.id, c.nombre, u.email AS usuario_email, c.ultima_sincronizacion,
                      c.ultimo_error_sincronizacion, c.ultimo_error_sincronizacion_en
               FROM correo_cuentas c JOIN usuarios u ON u.id = c.usuario_id ORDER BY c.id"""
        ).fetchall()
    finally:
        conn.close()


def contar_entregas_webhook_fallidas(desde: str) -> int:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT COUNT(*) FROM webhooks_entregas
               WHERE entregado_en >= ? AND NOT (estado_http IS NOT NULL AND estado_http BETWEEN 200 AND 299)""",
            (desde,),
        ).fetchone()[0]
    finally:
        conn.close()


def contar_envios_correo_fallidos(desde: str) -> int:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM correo_envios WHERE estado = 'error' AND procesado_en >= ?", (desde,)
        ).fetchone()[0]
    finally:
        conn.close()


def contar_envios_correo_atascados(vencidos_antes_de: str) -> int:
    """Envíos pendientes cuya hora pasó hace rato: el hilo de envíos no está trabajando."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM correo_envios WHERE estado = 'pendiente' AND enviar_en < ?", (vencidos_antes_de,)
        ).fetchone()[0]
    finally:
        conn.close()


def listar_todas_las_cuentas_correo() -> list[sqlite3.Row]:
    """Cuentas de correo de TODOS los usuarios (id y usuario_id): las usa
    la sincronización automática del servidor, que no tiene un usuario
    concreto detrás."""
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT id, usuario_id, protocolo FROM correo_cuentas ORDER BY id").fetchall()
    finally:
        conn.close()


def uids_existentes_correo(cuenta_id: int, carpeta: str = "INBOX") -> set[str]:
    """UIDs ya descargados para esa cuenta/carpeta — usado por la
    sincronización para pedir al servidor solo los mensajes que faltan."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT uid FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ?",
            (cuenta_id, carpeta),
        ).fetchall()
        return {f["uid"] for f in filas}
    finally:
        conn.close()


def obtener_ultimo_uid_sincronizado(cuenta_id: int, carpeta: str) -> str | None:
    """UID más alto ya sincronizado de esa carpeta -- permite pedirle al
    servidor solo "UID <n>:*" en vez de un SEARCH ALL completo. `None`
    significa que esta carpeta nunca se ha sincronizado todavía (primera
    sincronización, sigue haciendo falta un barrido completo)."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT ultimo_uid_sincronizado FROM correo_carpetas WHERE cuenta_id = ? AND nombre = ?",
            (cuenta_id, carpeta),
        ).fetchone()
        return fila["ultimo_uid_sincronizado"] if fila else None
    finally:
        conn.close()


def actualizar_ultimo_uid_sincronizado(cuenta_id: int, carpeta: str, uid: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE correo_carpetas SET ultimo_uid_sincronizado = ? WHERE cuenta_id = ? AND nombre = ?",
            (uid, cuenta_id, carpeta),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_cuenta_correo_por_id(cuenta_id: int) -> sqlite3.Row | None:
    """Sin comprobar el usuario: solo para tareas internas (segundo plano) que ya parten de un mensaje del usuario."""
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT * FROM correo_cuentas WHERE id = ?", (cuenta_id,)).fetchone()
    finally:
        conn.close()


def _asegurar_fts_correo(conn: sqlite3.Connection) -> bool:
    """Índice de texto completo (FTS5) del correo: asunto, remitente, destinatarios y cuerpo,
    sin distinguir mayúsculas ni acentos y con búsqueda por prefijo. Es un índice «externo»:
    no duplica el texto, solo guarda el índice, y unos disparadores lo mantienen al día. Se
    crea y se rellena una sola vez; devuelve False si este SQLite no tiene FTS5 (entonces la
    búsqueda sigue usando LIKE)."""
    try:
        existia = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'correo_fts'").fetchone() is not None
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS correo_fts USING fts5({_db._FTS_CORREO_COLUMNAS}, "
            "content='correo_mensajes', content_rowid='id', tokenize='unicode61 remove_diacritics 2', prefix='2 3')"
        )
    except sqlite3.OperationalError:
        return False
    if not existia:
        # Primero el texto de los solo-HTML y la reconstrucción, SIN disparadores: un 'delete' de
        # una fila que el índice aún no contiene lo corrompería.
        for t in ("correo_fts_ai", "correo_fts_ad", "correo_fts_au"):
            conn.execute(f"DROP TRIGGER IF EXISTS {t}")
        _db._rellenar_texto_de_correos_html(conn)
        conn.execute("INSERT INTO correo_fts(correo_fts) VALUES ('rebuild')")
    nuevas = ", ".join(f"new.{c.strip()}" for c in _db._FTS_CORREO_COLUMNAS.split(","))
    viejas = ", ".join(f"old.{c.strip()}" for c in _db._FTS_CORREO_COLUMNAS.split(","))
    # `cifrado = 2` es «entrando, por sellar» (app/correo_cifrado.py): el mensaje aún está en claro y NO debe llegar al índice, que guardaría su contenido (en minúsculas)
    # para siempre. Se indexa al sellarse, cuando ya solo lleva en claro lo que el nivel permite. Los disparadores se recrean siempre: es barato y deja el esquema al día.
    for t in ("correo_fts_ai", "correo_fts_ad", "correo_fts_au", "correo_fts_sellado"):
        conn.execute(f"DROP TRIGGER IF EXISTS {t}")
    conn.execute(f"CREATE TRIGGER correo_fts_ai AFTER INSERT ON correo_mensajes WHEN new.cifrado != 2 BEGIN "
                 f"INSERT INTO correo_fts(rowid, {_db._FTS_CORREO_COLUMNAS}) VALUES (new.id, {nuevas}); END")
    conn.execute(f"CREATE TRIGGER correo_fts_ad AFTER DELETE ON correo_mensajes WHEN old.cifrado != 2 BEGIN "
                 f"INSERT INTO correo_fts(correo_fts, rowid, {_db._FTS_CORREO_COLUMNAS}) VALUES ('delete', old.id, {viejas}); END")
    conn.execute(f"CREATE TRIGGER correo_fts_au AFTER UPDATE OF {_db._FTS_CORREO_COLUMNAS} ON correo_mensajes WHEN old.cifrado != 2 BEGIN "
                 f"INSERT INTO correo_fts(correo_fts, rowid, {_db._FTS_CORREO_COLUMNAS}) VALUES ('delete', old.id, {viejas}); "
                 f"INSERT INTO correo_fts(rowid, {_db._FTS_CORREO_COLUMNAS}) VALUES (new.id, {nuevas}); END")
    conn.execute(f"CREATE TRIGGER correo_fts_sellado AFTER UPDATE OF cifrado ON correo_mensajes WHEN old.cifrado = 2 AND new.cifrado != 2 BEGIN "
                 f"INSERT INTO correo_fts(rowid, {_db._FTS_CORREO_COLUMNAS}) VALUES (new.id, {nuevas}); END")
    return True


def _rellenar_texto_de_correos_html(conn: sqlite3.Connection) -> None:
    """Los correos solo-HTML no tenían texto plano y por eso no se encontraban por su cuerpo: se
    les saca el texto del HTML (una sola vez, al crear el índice)."""
    from .texto_html import html_a_texto_indexable
    filas = conn.execute("SELECT id, cuerpo_html FROM correo_mensajes WHERE (cuerpo_texto IS NULL OR cuerpo_texto = '') AND cuerpo_html IS NOT NULL").fetchall()
    for f in filas:
        texto = html_a_texto_indexable(f["cuerpo_html"])
        if texto:
            conn.execute("UPDATE correo_mensajes SET cuerpo_texto = ? WHERE id = ?", (texto, f["id"]))


def reconstruir_indice_correo() -> int:
    """Vuelve a construir el índice de búsqueda del correo desde cero (por si se desincroniza)."""
    conn = _db.get_connection()
    try:
        if not _db._asegurar_fts_correo(conn):
            return 0
        conn.execute("INSERT INTO correo_fts(correo_fts) VALUES ('rebuild')")
        conn.commit()
        return conn.execute("SELECT COUNT(*) FROM correo_mensajes").fetchone()[0]
    finally:
        conn.close()


def fts_correo_disponible() -> bool:
    conn = _db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'correo_fts'").fetchone() is not None
    finally:
        conn.close()


def consulta_fts(texto: str) -> str | None:
    """Texto escrito por el usuario -> expresión FTS5 segura. Cada palabra busca por prefijo
    («fact» encuentra «factura»), lo que va entre comillas busca la frase exacta, y se exigen
    todas. Todo va entre comillas para que ningún carácter se interprete como operador."""
    # Con símbolos que el índice descarta (% _ $ € # & /) o sin ninguna letra/dígito, el usuario
    # busca el texto literal: ahí se usa LIKE, que sí lo respeta («50%» no es «500»).
    if not re.search(r"[^\W_]", texto or "") or re.search(r"[%_$€#&/\\]", texto or ""):
        return None
    partes = []
    for m in _db._TROZO_BUSQUEDA.finditer(texto or ""):
        frase, palabra = m.group(1), m.group(2)
        if frase:
            partes.append('"' + frase.replace('"', '""') + '"')
        elif palabra:
            partes.append('"' + palabra.replace('"', '""') + '"*')
    return " ".join(partes) or None


def _crear_vista_participantes_todos(conn: sqlite3.Connection) -> None:
    """`tareas_participantes_todos`: quién puede ver/trabajar cada tarea, sumando a los
    participantes explícitos (tareas_participantes) los del PROYECTO compartido en que está la
    tarea: los miembros con su rol, el dueño del proyecto como colaborador y los supervisores del
    despacho como observadores. Solo para comprobar PERMISOS: las listas generales («Mis tareas»,
    «Mi día») siguen usando solo la tabla explícita, o se llenarían con todo lo del equipo.
    Siempre exige el mismo despacho que el dueño del proyecto (quien sale del despacho lo pierde)."""
    conn.execute("DROP VIEW IF EXISTS tareas_participantes_todos")
    conn.execute(
        """CREATE VIEW tareas_participantes_todos AS
           SELECT tarea_id, usuario_id, rol FROM tareas_participantes
           UNION
           SELECT t.id, m.usuario_id, m.rol
             FROM tareas_outlook t
             JOIN categorias c ON c.id = t.categoria_id AND c.proy_compartido = 1 AND c.papelera_en IS NULL
             JOIN proyecto_miembros m ON m.categoria_id = c.id
             JOIN usuarios um ON um.id = m.usuario_id
             JOIN usuarios uo ON uo.id = c.usuario_id
            WHERE um.tenant_id IS NOT NULL AND um.tenant_id = uo.tenant_id
           UNION
           SELECT t.id, c.usuario_id, 'colabora'
             FROM tareas_outlook t
             JOIN categorias c ON c.id = t.categoria_id AND c.proy_compartido = 1 AND c.papelera_en IS NULL
            WHERE t.usuario_id != c.usuario_id
           UNION
           SELECT t.id, us.id, 'observa'
             FROM tareas_outlook t
             JOIN categorias c ON c.id = t.categoria_id AND c.proy_compartido = 1 AND c.papelera_en IS NULL
             JOIN usuarios uo ON uo.id = c.usuario_id
             JOIN usuarios us ON us.tenant_id = uo.tenant_id AND us.supervisor_tenant = 1
            WHERE uo.tenant_id IS NOT NULL AND us.id != t.usuario_id AND us.id != c.usuario_id"""
    )


def estado_carpeta_correo(cuenta_id: int, carpeta: str) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_carpetas WHERE cuenta_id = ? AND nombre = ?", (cuenta_id, carpeta)
        ).fetchone()
    finally:
        conn.close()


def guardar_estado_carpeta_correo(cuenta_id: int, carpeta: str, **campos) -> None:
    """Actualiza uidvalidity, ultimo_uid_sincronizado, ultima_pasada_completa y descarga_pendiente."""
    permitidos = ("uidvalidity", "ultimo_uid_sincronizado", "ultima_pasada_completa", "descarga_pendiente", "modseq")
    columnas = [c for c in campos if c in permitidos]
    if not columnas:
        return
    conn = _db.get_connection()
    try:
        conn.execute(
            f"UPDATE correo_carpetas SET {', '.join(c + ' = ?' for c in columnas)} WHERE cuenta_id = ? AND nombre = ?",
            [campos[c] for c in columnas] + [cuenta_id, carpeta],
        )
        conn.commit()
    finally:
        conn.close()


def vaciar_carpeta_correo(cuenta_id: int, carpeta: str) -> None:
    """El servidor ha cambiado el UIDVALIDITY de la carpeta: los UID guardados ya no
    valen. Se borra lo cacheado de esa carpeta (se volverá a descargar) y las operaciones
    pendientes sobre ella."""
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ?", (cuenta_id, carpeta))
        conn.execute("DELETE FROM correo_operaciones WHERE cuenta_id = ? AND carpeta = ?", (cuenta_id, carpeta))
        conn.execute(
            "UPDATE correo_carpetas SET ultimo_uid_sincronizado = NULL, ultima_pasada_completa = NULL, descarga_pendiente = 0, modseq = NULL "
            "WHERE cuenta_id = ? AND nombre = ?", (cuenta_id, carpeta),
        )
        conn.commit()
    finally:
        conn.close()


def encolar_operacion_correo(cuenta_id: int, carpeta: str, uid: str, operacion: str, uidvalidity: str | None = None) -> int:
    conn = _db.get_connection()
    try:
        if uidvalidity is None:
            fila = conn.execute("SELECT uidvalidity FROM correo_carpetas WHERE cuenta_id = ? AND nombre = ?", (cuenta_id, carpeta)).fetchone()
            uidvalidity = fila["uidvalidity"] if fila else None
        cur = conn.execute(
            "INSERT INTO correo_operaciones (cuenta_id, carpeta, uid, uidvalidity, operacion, creada_en) VALUES (?, ?, ?, ?, ?, ?)",
            (cuenta_id, carpeta, uid, uidvalidity, operacion, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def operaciones_pendientes_correo(cuenta_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_operaciones WHERE cuenta_id = ? AND estado = 'pendiente' ORDER BY id", (cuenta_id,)
        ).fetchall()
    finally:
        conn.close()


def operaciones_por_mensaje_correo(cuenta_id: int, carpeta: str) -> dict[str, set[str]]:
    """{uid: {operaciones pendientes}} de una carpeta: la sincronización de entrada no
    pisa el estado de esos mensajes ni vuelve a descargar los que se están borrando."""
    conn = _db.get_connection()
    try:
        resultado: dict[str, set[str]] = {}
        for f in conn.execute(
            "SELECT uid, operacion FROM correo_operaciones WHERE cuenta_id = ? AND carpeta = ? AND estado = 'pendiente'", (cuenta_id, carpeta)
        ):
            resultado.setdefault(f["uid"], set()).add(f["operacion"])
        return resultado
    finally:
        conn.close()


def cerrar_operacion_correo(operacion_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM correo_operaciones WHERE id = ?", (operacion_id,))
        conn.commit()
    finally:
        conn.close()


def fallar_operacion_correo(operacion_id: int, error: str) -> None:
    """Un intento fallido: se reintentará; tras MAX_INTENTOS_OPERACION_CORREO pasa a 'error'."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE correo_operaciones SET intentos = intentos + 1, ultimo_error = ?, "
            "estado = CASE WHEN intentos + 1 >= ? THEN 'error' ELSE estado END WHERE id = ?",
            (error[:300], _db.MAX_INTENTOS_OPERACION_CORREO, operacion_id),
        )
        conn.commit()
    finally:
        conn.close()


def contar_operaciones_correo_con_error(usuario_id: int) -> int:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM correo_operaciones o JOIN correo_cuentas c ON c.id = o.cuenta_id "
            "WHERE c.usuario_id = ? AND o.estado = 'error'", (usuario_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def operaciones_correo_con_error(usuario_id: int) -> list[dict]:
    """Cambios hechos aquí (leído, destacado, borrado) que no se han podido aplicar en el servidor tras
    varios intentos, con la cuenta y el asunto del mensaje si todavía está en la base."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT o.id, o.cuenta_id, o.carpeta, o.operacion, o.intentos, o.ultimo_error, o.creada_en,
                      c.nombre AS cuenta_nombre, m.asunto AS asunto
               FROM correo_operaciones o JOIN correo_cuentas c ON c.id = o.cuenta_id
               LEFT JOIN correo_mensajes m ON m.cuenta_id = o.cuenta_id AND m.carpeta = o.carpeta AND m.uid = o.uid
               WHERE c.usuario_id = ? AND o.estado = 'error' ORDER BY o.id LIMIT 200""",
            (usuario_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def reintentar_operaciones_correo(usuario_id: int, ids: list[int] | None = None) -> list[int]:
    """Devuelve a la cola (intentos a cero) las operaciones con error del usuario (todas o las de `ids`).
    Devuelve los ids de las cuentas afectadas."""
    conn = _db.get_connection()
    try:
        filtro, params = "", [usuario_id]
        if ids is not None:
            if not ids:
                return []
            filtro = f" AND o.id IN ({','.join('?' * len(ids))})"
            params += ids
        cuentas = [f[0] for f in conn.execute(
            f"SELECT DISTINCT o.cuenta_id FROM correo_operaciones o JOIN correo_cuentas c ON c.id = o.cuenta_id "
            f"WHERE c.usuario_id = ? AND o.estado = 'error'{filtro}", params)]
        conn.execute(
            f"UPDATE correo_operaciones SET estado = 'pendiente', intentos = 0, ultimo_error = NULL WHERE estado = 'error' AND id IN "
            f"(SELECT o.id FROM correo_operaciones o JOIN correo_cuentas c ON c.id = o.cuenta_id WHERE c.usuario_id = ?{filtro})", params)
        conn.commit()
        return cuentas
    finally:
        conn.close()


def descartar_operaciones_correo(usuario_id: int, ids: list[int] | None = None) -> int:
    """Olvida las operaciones con error (el mensaje se queda como esté aquí; el servidor no se toca)."""
    conn = _db.get_connection()
    try:
        filtro, params = "", [usuario_id]
        if ids is not None:
            if not ids:
                return 0
            filtro = f" AND o.id IN ({','.join('?' * len(ids))})"
            params += ids
        cur = conn.execute(
            f"DELETE FROM correo_operaciones WHERE estado = 'error' AND id IN "
            f"(SELECT o.id FROM correo_operaciones o JOIN correo_cuentas c ON c.id = o.cuenta_id WHERE c.usuario_id = ?{filtro})", params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def mensaje_correo_por_uid(cuenta_id: int, carpeta: str, uid: str) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND uid = ?", (cuenta_id, carpeta, uid)
        ).fetchone()
    finally:
        conn.close()


def estados_mensajes_correo(cuenta_id: int, carpeta: str, uid_minimo: int | None = None) -> dict[str, tuple[int, int]]:
    """{uid: (leido, destacado)} de los mensajes cacheados, opcionalmente solo desde un UID."""
    conn = _db.get_connection()
    try:
        sql = "SELECT uid, leido, destacado FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ?"
        params: list = [cuenta_id, carpeta]
        if uid_minimo is not None:
            sql += " AND CAST(uid AS INTEGER) >= ?"
            params.append(uid_minimo)
        return {f["uid"]: (f["leido"], f["destacado"]) for f in conn.execute(sql, params)}
    finally:
        conn.close()


def aplicar_estados_servidor_correo(cuenta_id: int, carpeta: str, cambios: list[tuple[str, int, int]]) -> None:
    """`cambios`: (uid, leido, destacado) que el servidor tiene distinto de lo cacheado."""
    if not cambios:
        return
    conn = _db.get_connection()
    try:
        conn.executemany(
            "UPDATE correo_mensajes SET leido = ?, destacado = ? WHERE cuenta_id = ? AND carpeta = ? AND uid = ?",
            [(leido, destacado, cuenta_id, carpeta, uid) for uid, leido, destacado in cambios],
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_mensajes_correo_por_uid(cuenta_id: int, carpeta: str, uids: list[str]) -> int:
    """Quita de la caché los mensajes que ya no existen en el servidor."""
    if not uids:
        return 0
    conn = _db.get_connection()
    try:
        total = 0
        for inicio in range(0, len(uids), 500):
            lote = uids[inicio:inicio + 500]
            cur = conn.execute(
                f"DELETE FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND uid IN ({','.join('?' * len(lote))})",
                [cuenta_id, carpeta, *lote],
            )
            total += cur.rowcount
        conn.commit()
        return total
    finally:
        conn.close()


def normalizar_asunto(asunto: str | None) -> str:
    """Asunto sin prefijos de respuesta/reenvío (Re:, RE:, Rv:, Fwd:...),
    en minúsculas y con espacios colapsados: lo que comparten los mensajes
    de una misma conversación."""
    return " ".join(_db._PREFIJOS_ASUNTO.sub("", asunto or "").lower().split())


def _direccion_simple(texto: str | None) -> str:
    from email.utils import parseaddr
    return parseaddr(texto or "")[1].strip().lower()


def _clave_hilo_por_asunto(asunto, remitente, destinatarios, direccion_propia: str) -> str | None:
    """Sin cabeceras utilizables: asunto normalizado + contraparte (el
    remitente si no soy yo; si no, el primer destinatario). Así dos
    «Factura» de proveedores distintos no se mezclan. Asunto vacío = sin hilo."""
    norm = _db.normalizar_asunto(asunto)
    if not norm:
        return None
    remitente_dir = _db._direccion_simple(remitente)
    if remitente_dir and remitente_dir != direccion_propia:
        contraparte = remitente_dir
    else:
        primero = (destinatarios or "").split(",")[0]
        contraparte = _db._direccion_simple(primero) or remitente_dir
    return f"{norm}|{contraparte}"[:300]


def calcular_hilo_clave(
    conn: sqlite3.Connection, cuenta_id: int, asunto, remitente, destinatarios,
    in_reply_to: str | None, referencias: str | None, direccion_propia: str,
) -> str | None:
    """Si el mensaje responde (In-Reply-To/References) a uno ya guardado de
    la misma cuenta, hereda su hilo; si no, se deduce del asunto y la contraparte."""
    ids = _db._PATRON_ID_MENSAJE.findall(in_reply_to or "") + _db._PATRON_ID_MENSAJE.findall(referencias or "")[::-1]
    for candidato in ids[:20]:
        fila = conn.execute(
            "SELECT hilo_clave FROM correo_mensajes WHERE cuenta_id = ? AND message_id = ? AND hilo_clave IS NOT NULL LIMIT 1",
            (cuenta_id, candidato),
        ).fetchone()
        if fila:
            return fila["hilo_clave"]
    from . import correo_cifrado
    return correo_cifrado.hilo_para_cuenta(cuenta_id, _db._clave_hilo_por_asunto(asunto, remitente, destinatarios, direccion_propia))


def _rellenar_hilos_correo(conn: sqlite3.Connection) -> None:
    """Migración idempotente: da clave de hilo a los mensajes que no la
    tienen (los guardados antes de existir las conversaciones)."""
    pendientes = conn.execute(
        """SELECT m.id, m.cuenta_id, m.asunto, m.remitente, m.destinatarios, lower(c.usuario) AS propia
           FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
           WHERE m.hilo_clave IS NULL AND m.asunto IS NOT NULL AND trim(m.asunto) <> ''"""
    ).fetchall()
    for f in pendientes:
        clave = _db._clave_hilo_por_asunto(f["asunto"], f["remitente"], f["destinatarios"], _db._direccion_simple(f["propia"]))
        if clave:
            conn.execute("UPDATE correo_mensajes SET hilo_clave = ? WHERE id = ?", (clave, f["id"]))
    conn.commit()


def contar_hilos_correo(cuenta_id: int, claves: list[str]) -> dict[str, int]:
    """Nº de mensajes de la cuenta (todas las carpetas) por clave de hilo."""
    claves = [c for c in dict.fromkeys(claves) if c]
    if not claves:
        return {}
    conn = _db.get_connection()
    try:
        marcadores = ",".join("?" * len(claves))
        filas = conn.execute(
            f"""SELECT hilo_clave, COUNT(*) AS n FROM correo_mensajes
                WHERE cuenta_id = ? AND hilo_clave IN ({marcadores}) GROUP BY hilo_clave""",
            [cuenta_id, *claves],
        ).fetchall()
        return {f["hilo_clave"]: f["n"] for f in filas}
    finally:
        conn.close()


def mensajes_del_hilo_correo(cuenta_id: int, hilo_clave: str | None) -> list[sqlite3.Row]:
    if not hilo_clave:
        return []
    from . import correo_cifrado
    conn = _db.get_connection()
    try:
        return correo_cifrado.completar(conn.execute(
            """SELECT id, carpeta, asunto, remitente, fecha, leido FROM correo_mensajes
               WHERE cuenta_id = ? AND hilo_clave = ? ORDER BY fecha ASC, id ASC LIMIT 100""",
            (cuenta_id, hilo_clave),
        ).fetchall())
    finally:
        conn.close()


def guardar_mensaje_correo(
    cuenta_id: int, uid: str, asunto: str | None, remitente: str | None,
    destinatarios: str | None, fecha: str | None, cuerpo_texto: str | None,
    cuerpo_html: str | None, carpeta: str = "INBOX", message_id: str | None = None,
    cc: str | None = None, in_reply_to: str | None = None, referencias: str | None = None,
    leido: bool = False, destacado: bool = False,
) -> int | None:
    """`leido`/`destacado`: el estado que ya tiene el mensaje en el servidor.
    Devuelve el id del mensaje (recién insertado, o el ya existente si
    `(cuenta_id, carpeta, uid)` ya estaba en caché) — para poder colgarle
    adjuntos justo después."""
    conn = _db.get_connection()
    try:
        cuenta = conn.execute("SELECT usuario FROM correo_cuentas WHERE id = ?", (cuenta_id,)).fetchone()
        hilo = _db.calcular_hilo_clave(
            conn, cuenta_id, asunto, remitente, destinatarios, in_reply_to, referencias,
            _db._direccion_simple(cuenta["usuario"]) if cuenta else "",
        )
        from . import correo_cifrado
        conn.execute(
            """INSERT OR IGNORE INTO correo_mensajes
               (cuenta_id, carpeta, uid, asunto, remitente, destinatarios,
                cc, fecha, cuerpo_texto, cuerpo_html, message_id, in_reply_to, referencias,
                hilo_clave, descargado_en, leido, destacado, cifrado)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cuenta_id, carpeta, uid, asunto, remitente, destinatarios,
             cc, fecha, cuerpo_texto, cuerpo_html, message_id,
             (in_reply_to or None) and in_reply_to[:1000], (referencias or None) and referencias[:4000],
             hilo, _db.now_iso(), int(leido), int(destacado), 2 if correo_cifrado.config_de_cuenta(cuenta_id) else 0),
        )
        conn.commit()
        fila = conn.execute(
            "SELECT id FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND uid = ?",
            (cuenta_id, carpeta, uid),
        ).fetchone()
        return fila["id"] if fila else None
    finally:
        conn.close()


def _like_literal(texto: str) -> str:
    """Patrón LIKE que busca `texto` tal cual (sin que % y _ hagan de comodín)."""
    return "%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def listar_mensajes_correo(
    cuenta_id: int, carpeta: str = "INBOX", solo_no_leidos: bool = False,
    texto: str | None = None, limite: int = 50, incluir_pospuestos: bool = False,
    con_adjuntos: bool = False, categoria_id: int | None = None, desde: str | None = None,
    hasta: str | None = None, solo_destacados: bool = False, cliente_fiscal_id: int | None = None,
    remitente: str | None = None, destinatarios: str | None = None, asunto: str | None = None,
) -> list[sqlite3.Row]:
    """`remitente`, `destinatarios` y `asunto` filtran por esa columna (contiene, sin distinguir mayúsculas).
    `texto` busca en asunto, remitente, destinatarios y CUERPO del mensaje.
    Filtros: con adjuntos, categoría, rango de fechas (YYYY-MM-DD, `hasta`
    inclusive), destacados y cliente fiscal vinculado."""
    from . import correo_cifrado
    en_memoria = correo_cifrado.usa_memoria(cuenta_id, texto, remitente, destinatarios, asunto, categoria_id, cliente_fiscal_id)
    if en_memoria:
        # Con correo cifrado el texto y las cabeceras no se pueden consultar en SQL (el índice de texto completo guardaría el contenido en claro): se descifran los
        # candidatos (con los demás filtros) y se filtra aquí. Sin clave solo se encuentra lo que el nivel deja en claro.
        filtro_mem = (texto, remitente, destinatarios, asunto)
        asociaciones_mem = None
        if correo_cifrado.config_de_cuenta(cuenta_id)["nivel"] == "estricto":      # en Estricto categoría y cliente viven dentro del bloque cifrado
            asociaciones_mem, categoria_id, cliente_fiscal_id = (categoria_id, cliente_fiscal_id), None, None
        texto = remitente = destinatarios = asunto = None
        limite_final, limite = limite, correo_cifrado.LIMITE_MEMORIA
    conn = _db.get_connection()
    try:
        cond = ["cuenta_id = ?", "carpeta = ?"]
        params: list = [cuenta_id, carpeta]
        if solo_no_leidos:
            cond.append("leido = 0")
        if texto:
            expresion = _db.consulta_fts(texto) if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'correo_fts'").fetchone() else None
            if expresion:
                # Índice de texto completo: instantáneo aunque haya decenas de miles de correos
                # (LIKE '%x%' recorría todos los cuerpos). Sin acentos ni mayúsculas, por prefijo.
                cond.append("id IN (SELECT rowid FROM correo_fts WHERE correo_fts MATCH ?)")
                params.append(expresion)
            else:
                cond.append(
                    "(asunto LIKE ? ESCAPE '\\' OR remitente LIKE ? ESCAPE '\\' OR destinatarios LIKE ? ESCAPE '\\' "
                    "OR cuerpo_texto LIKE ? ESCAPE '\\')"
                )
                params.extend([_db._like_literal(texto)] * 4)
        for columna, valor in (("remitente", remitente), ("destinatarios", destinatarios), ("asunto", asunto)):
            if valor:
                cond.append(f"{columna} LIKE ? ESCAPE '\\'"); params.append(_db._like_literal(valor))
        if con_adjuntos:
            cond.append("EXISTS (SELECT 1 FROM correo_adjuntos a WHERE a.mensaje_id = correo_mensajes.id)")
        if categoria_id is not None:
            cond.append("categoria_id = ?"); params.append(categoria_id)
        if cliente_fiscal_id is not None:
            cond.append("cliente_fiscal_id = ?"); params.append(cliente_fiscal_id)
        if solo_destacados:
            cond.append("destacado = 1")
        if desde:
            cond.append("fecha >= ?"); params.append(desde)
        if hasta:
            cond.append("fecha < ?"); params.append(_db._fecha_exclusiva(hasta))
        if not incluir_pospuestos:
            cond.append("(pospuesto_hasta IS NULL OR pospuesto_hasta <= ?)")
            params.append(_db.now_iso())
        where = " AND ".join(cond)
        params.append(limite)
        filas = conn.execute(
            # "ORDER BY fecha DESC" basta: SQLite ya trata NULL como el valor
            # más pequeño, así que en DESC los mensajes sin fecha quedan al
            # final solos — no hace falta "(fecha IS NULL), fecha DESC" (esa
            # expresión extra impedía usar idx_correo_mensajes_cuenta_carpeta_fecha
            # para el propio ORDER BY, forzando un TEMP B-TREE en cada carga
            # de la bandeja).
            f"""SELECT {correo_cifrado.columnas_sin_bloque() if en_memoria else '*'} FROM correo_mensajes WHERE {where}
                ORDER BY fecha DESC LIMIT ?""",
            params,
        ).fetchall()
        if en_memoria:
            ligeras = correo_cifrado.completar(filas, con_pajar=True)
            cat, cli = asociaciones_mem or (None, None)
            elegidas = [m["id"] for m in ligeras if correo_cifrado.coincide(m, *filtro_mem) and (cat is None or m.get("categoria_id") == cat) and (cli is None or m.get("cliente_fiscal_id") == cli)][:limite_final]
            por_id = {f["id"]: f for f in filas}
            return correo_cifrado.completar([por_id[i] for i in elegidas])       # solo las que se devuelven se descifran por completo (cuerpo y HTML)
        return correo_cifrado.completar(filas)
    finally:
        conn.close()


def obtener_mensaje_correo(mensaje_id: int) -> sqlite3.Row | None:
    """El mensaje con su contenido real. Si está sellado y hay clave se descifra (queda anotado en el registro de accesos); si no, sale con `protegido = True`."""
    from . import correo_cifrado
    conn = _db.get_connection()
    try:
        fila = conn.execute("SELECT * FROM correo_mensajes WHERE id = ?", (mensaje_id,)).fetchone()
    finally:
        conn.close()
    if fila is None:
        return None
    d = correo_cifrado.completar_uno(fila)
    if fila["cifrado"] == 1 and not d["protegido"]:
        from . import cifrado_despacho
        cifrado_despacho.registrar_acceso(correo_cifrado.tenant_de_cuenta(fila["cuenta_id"]), None, mensaje_id, cifrado_despacho.canal_actual() or "persona", "correo")
    return d


def mensaje_correo_pertenece_a_usuario(usuario_id: int, mensaje_id: int) -> bool:
    """Comprueba que un mensaje cuelga de una cuenta del usuario, antes de
    dejarle leer/modificar un `mensaje_id` que le podrían pasar por URL."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            """SELECT 1 FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE m.id = ? AND c.usuario_id = ?""",
            (mensaje_id, usuario_id),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def guardar_adjuntos_correo(mensaje_id: int, adjuntos: list[dict]) -> None:
    """`adjuntos` es una lista de {"nombre", "tipo", "bytes"}, tal como los
    devuelve app.correo._cuerpos()."""
    conn = _db.get_connection()
    try:
        for a in adjuntos:
            conn.execute(
                """INSERT INTO correo_adjuntos
                   (mensaje_id, nombre_archivo, tipo_mime, tamano_bytes, contenido, creado_en)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (mensaje_id, a["nombre"], a["tipo"], len(a["bytes"]), a["bytes"], _db.now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def listar_adjuntos_correo(mensaje_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT id, mensaje_id, nombre_archivo, tipo_mime, tamano_bytes, creado_en, cifrado, nombre_cifrado "
            "FROM correo_adjuntos WHERE mensaje_id = ? ORDER BY id",
            (mensaje_id,),
        ).fetchall()
    finally:
        conn.close()
    from . import correo_cifrado
    return [correo_cifrado.abrir_adjunto(f, con_contenido=False) for f in filas] if correo_cifrado.hay_alguno() else filas


def obtener_adjunto_correo(adjunto_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        fila = conn.execute("SELECT * FROM correo_adjuntos WHERE id = ?", (adjunto_id,)).fetchone()
    finally:
        conn.close()
    from . import correo_cifrado
    return correo_cifrado.abrir_adjunto(fila) if fila is not None else None      # sellado y sin clave: lanza DespachoBloqueado


def adjunto_correo_pertenece_a_usuario(usuario_id: int, adjunto_id: int) -> bool:
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            """SELECT 1 FROM correo_adjuntos a
               JOIN correo_mensajes m ON m.id = a.mensaje_id
               JOIN correo_cuentas c ON c.id = m.cuenta_id
               WHERE a.id = ? AND c.usuario_id = ?""",
            (adjunto_id, usuario_id),
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def marcar_leido_mensaje_correo(mensaje_id: int, leido: bool = True) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE correo_mensajes SET leido = ? WHERE id = ?", (int(leido), mensaje_id))
        conn.commit()
    finally:
        conn.close()


def destacar_mensaje_correo(mensaje_id: int, destacado: bool, fecha_aviso: str | None = None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE correo_mensajes SET destacado = ?, fecha_aviso = ? WHERE id = ?",
            (int(destacado), fecha_aviso if destacado else None, mensaje_id),
        )
        conn.commit()
    finally:
        conn.close()


def posponer_mensaje_correo(mensaje_id: int, hasta: str | None) -> None:
    """`hasta=None` quita el pospuesto (el mensaje vuelve a verse ya)."""
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE correo_mensajes SET pospuesto_hasta = ? WHERE id = ?", (hasta, mensaje_id))
        conn.commit()
    finally:
        conn.close()


def eliminar_mensaje_correo(mensaje_id: int) -> None:
    """Borra el mensaje de la caché local (no del servidor de correo). Si
    sigue en el buzón real, una futura sincronización volverá a descargarlo
    (su UID ya no está en la caché local) — borrarlo también en el servidor
    queda fuera de alcance de esta fase."""
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM correo_mensajes WHERE id = ?", (mensaje_id,))
        conn.commit()
    finally:
        conn.close()


def contar_no_leidos_correo(cuenta_id: int, carpeta: str = "INBOX") -> int:
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT COUNT(*) AS n FROM correo_mensajes WHERE cuenta_id = ? AND carpeta = ? AND leido = 0",
            (cuenta_id, carpeta),
        ).fetchone()
        return fila["n"]
    finally:
        conn.close()


def contar_no_leidos_por_cuenta_y_carpeta(usuario_id: int) -> dict[int, dict[str, int]]:
    """Una sola consulta agregada para el rail de Correo (cuenta_id ->
    {carpeta: no_leidos}) -- antes _contexto_bandeja hacía una llamada a
    contar_no_leidos_correo() POR CADA cuenta (N+1), y esa función solo
    cuenta una carpeta a la vez (por defecto INBOX), así que el badge de
    cada cuenta reflejaba solo lo no leído en INBOX, nunca el total real
    de la cuenta ni el desglose por carpeta."""
    conn = _db.get_connection()
    try:
        # Parte de las cuentas del usuario y cuenta sobre el índice parcial
        # idx_correo_no_leidos (solo no leídos, cubriente): O(no leídos) sin tocar las filas.
        filas = conn.execute(
            """SELECT cuenta_id, carpeta, COUNT(*) AS n FROM correo_mensajes
               WHERE leido = 0 AND cuenta_id IN (SELECT id FROM correo_cuentas WHERE usuario_id = ?)
               GROUP BY cuenta_id, carpeta""",
            (usuario_id,),
        ).fetchall()
        resultado: dict[int, dict[str, int]] = {}
        for fila in filas:
            resultado.setdefault(fila["cuenta_id"], {})[fila["carpeta"]] = fila["n"]
        return resultado
    finally:
        conn.close()


def contar_no_leidos_total_correo(usuario_id: int) -> int:
    """Total de mensajes no leídos en TODAS las cuentas y carpetas de un
    usuario (para el badge de "correo nuevo" del rail de iconos)."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT COUNT(*) AS n FROM correo_mensajes
               WHERE leido = 0 AND cuenta_id IN (SELECT id FROM correo_cuentas WHERE usuario_id = ?)""",
            (usuario_id,),
        ).fetchone()["n"]
    finally:
        conn.close()
