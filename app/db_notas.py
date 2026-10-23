"""Acceso a datos de las notas y sus adjuntos.

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


# --- Notas ---------------------------------------------------------------

def crear_nota(
    usuario_id: int, texto: str, categoria_id: int | None = None, tarea_id: int | None = None,
    creada_en: str | None = None, cliente_uuid: str | None = None,
    titulo: str | None = None, fijada: bool = False, cliente_fiscal_id: int | None = None,
    tarea_outlook_id: int | None = None, mensaje_correo_id: int | None = None,
) -> int:
    """`creada_en`/`cliente_uuid`: igual que en `fichar()`, para la cola
    offline de la app móvil -- conservan la hora real de creación y evitan
    duplicar la nota si se reintenta la sincronización."""
    conn = _db.get_connection()
    try:
        if cliente_uuid is not None:
            existente = conn.execute("SELECT id FROM notas WHERE cliente_uuid = ?", (cliente_uuid,)).fetchone()
            if existente is not None:
                return existente["id"]
        # Aquí categoria_id sí es opcional -- si no es del usuario, se
        # degrada a "sin proyecto" en vez de rechazar la nota entera (ver
        # _categoria_id_propio).
        categoria_id = _db._categoria_id_propio(conn, usuario_id, categoria_id)
        ahora = _db.now_iso()
        if creada_en is not None and creada_en > ahora:
            raise ValueError("La fecha de creación de la nota no puede ser futura.")
        cur = conn.execute(
            """INSERT INTO notas (usuario_id, texto, categoria_id, tarea_id, creada_en, cliente_uuid,
                                  titulo, fijada, cliente_fiscal_id, tarea_outlook_id, mensaje_correo_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, texto.strip(), categoria_id, tarea_id, creada_en or ahora, cliente_uuid,
                _db._titulo_nota(titulo), 1 if fijada else 0,
                _db._cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id),
                _db._tarea_outlook_id_propia(conn, usuario_id, tarea_outlook_id),
                _db._mensaje_correo_id_propio(conn, usuario_id, mensaje_correo_id),
            ),
        )
        conn.commit()
        nota_id = cur.lastrowid
    finally:
        conn.close()
    _db._reindexar_nota(usuario_id, nota_id)
    _db._emitir_evento_nota_creada(usuario_id, nota_id, texto.strip())
    return nota_id


def _emitir_evento_nota_creada(usuario_id: int, nota_id: int, texto: str) -> None:
    """Solo al CREAR — editar una nota no vuelve a emitir el evento
    (ver _reindexar_nota, compartido entre crear/editar, que sí se
    ejecuta en ambos casos). Mismo criterio de import perezoso que
    _emitir_evento_tarea_finalizada."""
    from . import eventos
    try:
        tenant = _db.tenant_de_usuario(usuario_id)
        eventos.emitir("nota.creada", tenant["id"] if tenant else None, {"nota_id": nota_id, "texto": texto})
    except Exception:
        pass


def _reindexar_nota(usuario_id: int, nota_id: int) -> None:
    """Reindexa una nota en el buscador unificado (ver app/busqueda.py)
    tras crearla/editarla — falla en silencio si el buscador no está
    configurado/caído, es una mejora de UX, no debe romper el registro
    de actividad en sí. Import perezoso a propósito: db.py no depende
    de ningún otro módulo de app/ como regla general, esta es la única
    excepción (indexar es, por naturaleza, un efecto secundario de cada
    escritura, no una operación de negocio más)."""
    from . import busqueda
    try:
        nota = _db.obtener_nota(usuario_id, nota_id)
        if nota is not None:
            busqueda.indexar_nota(dict(nota))
    except busqueda.ErrorBusqueda:
        pass


def importar_nota(usuario_id: int, texto: str, categoria_id: int | None, creada_en: str, titulo: str | None = None) -> int:
    """Inserta una nota con un timestamp explícito (importación de datos exportados)."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO notas (usuario_id, texto, categoria_id, tarea_id, creada_en, titulo) VALUES (?, ?, ?, NULL, ?, ?)",
            (usuario_id, texto.strip(), categoria_id, creada_en, _db._titulo_nota(titulo)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_nota(usuario_id: int, nota_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT n.*, c.nombre AS categoria_nombre, cf.nombre AS cliente_fiscal_nombre
               FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
               LEFT JOIN clientes_fiscales cf ON cf.id = n.cliente_fiscal_id
               WHERE n.id = ? AND n.usuario_id = ? AND n.papelera_en IS NULL""",
            (nota_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def rol_en_nota(usuario_id: int, nota_id: int) -> str | None:
    """'dueno', 'colabora', 'observa' o None si no la ve."""
    conn = _db.get_connection()
    try:
        n = conn.execute("SELECT usuario_id FROM notas WHERE id = ? AND papelera_en IS NULL", (nota_id,)).fetchone()
        if n is None:
            return None
        if n["usuario_id"] == usuario_id:
            return "dueno"
        p = conn.execute(
            "SELECT rol FROM notas_participantes WHERE nota_id = ? AND usuario_id = ?", (nota_id, usuario_id)
        ).fetchone()
        return p["rol"] if p else None
    finally:
        conn.close()


def obtener_nota_visible(usuario_id: int, nota_id: int) -> sqlite3.Row | None:
    """Como obtener_nota, pero también para quien la tiene compartida."""
    if _db.rol_en_nota(usuario_id, nota_id) is None:
        return None
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT n.*, c.nombre AS categoria_nombre, cf.nombre AS cliente_fiscal_nombre,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS dueno_nombre
               FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
               LEFT JOIN clientes_fiscales cf ON cf.id = n.cliente_fiscal_id
               JOIN usuarios u ON u.id = n.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = n.usuario_id
               WHERE n.id = ? AND n.papelera_en IS NULL""",
            (nota_id,),
        ).fetchone()
    finally:
        conn.close()


def compartir_nota(usuario_id: int, nota_id: int, otro_id: int, rol: str = "colabora") -> bool:
    """El dueño comparte la nota con un compañero del mismo despacho (o cambia su rol)."""
    if rol not in _db.ROLES_PARTICIPANTE:
        return False
    conn = _db.get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM notas WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (nota_id, usuario_id)
        ).fetchone() is None:
            return False
        destino = _db._companero_del_tenant(conn, usuario_id, otro_id)
        if destino is None:
            return False
        conn.execute(
            """INSERT INTO notas_participantes (nota_id, usuario_id, rol, compartida_en) VALUES (?, ?, ?, ?)
               ON CONFLICT(nota_id, usuario_id) DO UPDATE SET rol = excluded.rol""",
            (nota_id, destino, rol, _db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    _db._emitir_evento(usuario_id, "nota.compartida", {"nota_id": nota_id, "con": destino, "rol": rol})
    return True


def dejar_de_compartir_nota(usuario_id: int, nota_id: int, otro_id: int) -> bool:
    """El dueño quita a un participante; el propio participante puede salirse."""
    conn = _db.get_connection()
    try:
        dueno = conn.execute("SELECT 1 FROM notas WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id)).fetchone()
        if not dueno and otro_id != usuario_id:
            return False
        cur = conn.execute("DELETE FROM notas_participantes WHERE nota_id = ? AND usuario_id = ?", (nota_id, otro_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def participantes_de_nota(nota_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT p.usuario_id, p.rol, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre
               FROM notas_participantes p JOIN usuarios u ON u.id = p.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = p.usuario_id
               WHERE p.nota_id = ? ORDER BY nombre""",
            (nota_id,),
        ).fetchall()
    finally:
        conn.close()


def contar_participantes_notas(nota_ids: list[int]) -> dict[int, int]:
    if not nota_ids:
        return {}
    conn = _db.get_connection()
    try:
        marcas = ",".join("?" * len(nota_ids))
        return {
            f["nota_id"]: f["n"]
            for f in conn.execute(
                f"SELECT nota_id, COUNT(*) AS n FROM notas_participantes WHERE nota_id IN ({marcas}) GROUP BY nota_id", nota_ids
            )
        }
    finally:
        conn.close()


def _titulo_nota(titulo: str | None) -> str | None:
    titulo = " ".join((titulo or "").split())[:_db.NOTA_TITULO_MAX_CARACTERES]
    return titulo or None


def _tarea_outlook_id_propia(conn: sqlite3.Connection, usuario_id: int, tarea_id: int | None) -> int | None:
    if tarea_id is None:
        return None
    fila = conn.execute(
        "SELECT id FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (tarea_id, usuario_id)
    ).fetchone()
    return fila["id"] if fila else None


def editar_nota(
    usuario_id: int, nota_id: int, texto: str, *, titulo=_db._SIN_CAMBIO, fijada=_db._SIN_CAMBIO,
    cliente_fiscal_id=_db._SIN_CAMBIO, tarea_outlook_id=_db._SIN_CAMBIO, mensaje_correo_id=_db._SIN_CAMBIO,
) -> None:
    """Actualiza el texto y, si se indican, el título, si está fijada y sus
    vínculos (cliente fiscal, tarea de la lista, correo). Lo no indicado no se toca.
    La edita su dueño o un colaborador; el colaborador solo cambia texto y título
    (fijar y los vínculos son del dueño)."""
    rol = _db.rol_en_nota(usuario_id, nota_id)
    if rol not in ("dueno", "colabora"):
        return
    if rol == "colabora":
        fijada = cliente_fiscal_id = tarea_outlook_id = mensaje_correo_id = _db._SIN_CAMBIO
    conn = _db.get_connection()
    try:
        dueno_id = conn.execute("SELECT usuario_id FROM notas WHERE id = ?", (nota_id,)).fetchone()["usuario_id"]
        cambios = {"texto": texto.strip()}
        if titulo is not _db._SIN_CAMBIO:
            cambios["titulo"] = _db._titulo_nota(titulo)
        if fijada is not _db._SIN_CAMBIO:
            cambios["fijada"] = 1 if fijada else 0
        if cliente_fiscal_id is not _db._SIN_CAMBIO:
            cambios["cliente_fiscal_id"] = _db._cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id)
        if tarea_outlook_id is not _db._SIN_CAMBIO:
            cambios["tarea_outlook_id"] = _db._tarea_outlook_id_propia(conn, usuario_id, tarea_outlook_id)
        if mensaje_correo_id is not _db._SIN_CAMBIO:
            cambios["mensaje_correo_id"] = _db._mensaje_correo_id_propio(conn, usuario_id, mensaje_correo_id)
        asignaciones = ", ".join(f"{c} = ?" for c in cambios)
        conn.execute(
            f"UPDATE notas SET {asignaciones} WHERE id = ?",
            [*cambios.values(), nota_id],
        )
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_nota(dueno_id, nota_id)
    _db._emitir_evento(usuario_id, "nota.editada", {"nota_id": nota_id})


def alternar_fijada_nota(usuario_id: int, nota_id: int) -> bool:
    """Fija o desfija la nota. Devuelve False si no es del usuario."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE notas SET fijada = 1 - fijada WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (nota_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def listar_notas_fijadas(usuario_id: int, categoria_id: int | None = None) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        cond, params = ["n.usuario_id = ?", "n.fijada = 1", "n.papelera_en IS NULL"], [usuario_id]
        if categoria_id is not None:
            cond.append("n.categoria_id = ?"); params.append(categoria_id)
        return conn.execute(
            f"""SELECT n.*, c.nombre AS categoria_nombre, c.color AS categoria_color
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                WHERE {' AND '.join(cond)} ORDER BY n.creada_en DESC""",
            params,
        ).fetchall()
    finally:
        conn.close()


def listar_notas(
    usuario_id: int, categoria_id: int | None = None, texto: str | None = None, limite: int = 300,
    incluir_compartidas: bool = False, solo_compartidas: bool = False, offset: int = 0,
) -> list[sqlite3.Row]:
    """Notas del usuario para la pantalla Notas: las fijadas primero y luego
    las más recientes; filtro opcional por proyecto y por texto/título."""
    conn = _db.get_connection()
    try:
        compartida = "n.id IN (SELECT nota_id FROM notas_participantes WHERE usuario_id = ?)"
        if solo_compartidas:
            cond, params = [compartida, "n.papelera_en IS NULL"], [usuario_id]
        elif incluir_compartidas:
            cond, params = [f"(n.usuario_id = ? OR {compartida})", "n.papelera_en IS NULL"], [usuario_id, usuario_id]
        else:
            cond, params = ["n.usuario_id = ?", "n.papelera_en IS NULL"], [usuario_id]
        if categoria_id is not None:
            cond.append("n.categoria_id = ?"); params.append(categoria_id)
        if texto:
            patron = "%" + texto.replace("%", r"\%").replace("_", r"\_") + "%"
            cond.append("(LOWER(n.texto) LIKE LOWER(?) ESCAPE '\\' OR LOWER(n.titulo) LIKE LOWER(?) ESCAPE '\\')"); params += [patron, patron]
        return conn.execute(
            f"""SELECT n.*, c.nombre AS categoria_nombre, c.color AS categoria_color,
                       COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS dueno_nombre
                FROM notas n LEFT JOIN categorias c ON c.id = n.categoria_id
                JOIN usuarios u ON u.id = n.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = n.usuario_id
                WHERE {' AND '.join(cond)}
                ORDER BY n.fijada DESC, n.creada_en DESC LIMIT ? OFFSET ?""",
            params + [limite, offset],
        ).fetchall()
    finally:
        conn.close()


def contar_notas(usuario_id: int, categoria_id: int | None = None, texto: str | None = None) -> int:
    """Total de notas propias con esos filtros (para paginar en SQL sin traerlas todas)."""
    cond, params = ["usuario_id = ?", "papelera_en IS NULL"], [usuario_id]
    if categoria_id is not None:
        cond.append("categoria_id = ?"); params.append(categoria_id)
    if texto:
        patron = "%" + texto.replace("%", r"\%").replace("_", r"\_") + "%"
        cond.append("(LOWER(texto) LIKE LOWER(?) ESCAPE '\\' OR LOWER(titulo) LIKE LOWER(?) ESCAPE '\\')"); params += [patron, patron]
    conn = _db.get_connection()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM notas WHERE {' AND '.join(cond)}", params).fetchone()[0]
    finally:
        conn.close()


def agregar_adjunto_nota(usuario_id: int, nota_id: int, nombre: str, tipo_mime: str, contenido: bytes) -> int:
    """Adjunta un fichero a una nota propia. Lanza ValueError con un mensaje
    para la persona usuaria si no procede (tipo, tamaño, límite, nota ajena)."""
    nombre = (nombre or "").replace("\\", "/").split("/")[-1].strip()[:200] or "adjunto"
    if tipo_mime not in _db.NOTAS_ADJUNTOS_MIME:
        raise ValueError("Tipo de archivo no permitido: solo imágenes, PDF o texto.")
    if len(contenido) > _db.NOTAS_ADJUNTOS_TAMANO_MAXIMO:
        raise ValueError("El archivo pesa demasiado (máximo 5 MB).")
    if not contenido:
        raise ValueError("El archivo está vacío.")
    conn = _db.get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM notas WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (nota_id, usuario_id)
        ).fetchone() is None:
            raise ValueError("La nota no existe.")
        if conn.execute("SELECT COUNT(*) FROM notas_adjuntos WHERE nota_id = ?", (nota_id,)).fetchone()[0] >= _db.NOTAS_ADJUNTOS_MAXIMO_POR_NOTA:
            raise ValueError(f"Una nota admite como máximo {_db.NOTAS_ADJUNTOS_MAXIMO_POR_NOTA} adjuntos.")
        cur = conn.execute(
            "INSERT INTO notas_adjuntos (nota_id, nombre, tipo_mime, tamano, contenido, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
            (nota_id, nombre, tipo_mime, len(contenido), contenido, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_adjuntos_nota(nota_id: int) -> list[sqlite3.Row]:
    """Sin el contenido (BLOB): solo lo necesario para listarlos."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT id, nota_id, nombre, tipo_mime, tamano, creado_en FROM notas_adjuntos WHERE nota_id = ? ORDER BY id",
            (nota_id,),
        ).fetchall()
    finally:
        conn.close()


def contar_adjuntos_notas(nota_ids: list[int]) -> dict[int, int]:
    if not nota_ids:
        return {}
    conn = _db.get_connection()
    try:
        marcas = ",".join("?" * len(nota_ids))
        return {
            f["nota_id"]: f["n"]
            for f in conn.execute(f"SELECT nota_id, COUNT(*) AS n FROM notas_adjuntos WHERE nota_id IN ({marcas}) GROUP BY nota_id", nota_ids)
        }
    finally:
        conn.close()


def obtener_adjunto_nota(usuario_id: int, adjunto_id: int) -> sqlite3.Row | None:
    """Con contenido; si la nota es del usuario o está compartida con él."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT a.* FROM notas_adjuntos a JOIN notas n ON n.id = a.nota_id
               WHERE a.id = ? AND n.papelera_en IS NULL AND (n.usuario_id = ? OR n.id IN (
                     SELECT nota_id FROM notas_participantes WHERE usuario_id = ?))""",
            (adjunto_id, usuario_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def eliminar_adjunto_nota(usuario_id: int, adjunto_id: int) -> bool:
    conn = _db.get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM notas_adjuntos a JOIN notas n ON n.id = a.nota_id WHERE a.id = ? AND n.usuario_id = ?",
            (adjunto_id, usuario_id),
        ).fetchone() is None:
            return False
        conn.execute("DELETE FROM notas_adjuntos WHERE id = ?", (adjunto_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_nota(usuario_id: int, nota_id: int) -> None:
    """Manda una nota a la papelera (no la borra de verdad)."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE notas SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (_db._marca_papelera(), nota_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    _db._quitar_nota_del_indice(nota_id)


def _quitar_nota_del_indice(nota_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("nota", nota_id)
    except busqueda.ErrorBusqueda:
        pass


def restaurar_nota(usuario_id: int, nota_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE notas SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_nota(usuario_id, nota_id)


def eliminar_nota_definitivamente(usuario_id: int, nota_id: int) -> None:
    conn_p = _db.get_connection()
    try:
        if conn_p.execute("SELECT 1 FROM notas WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id)).fetchone():
            conn_p.execute("DELETE FROM notas_participantes WHERE nota_id = ?", (nota_id,))
            conn_p.commit()
    finally:
        conn_p.close()
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM notas WHERE id = ? AND usuario_id = ?", (nota_id, usuario_id))
        conn.commit()
    finally:
        conn.close()
    _db._quitar_nota_del_indice(nota_id)
