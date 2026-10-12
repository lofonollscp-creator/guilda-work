"""Acceso a datos del fichaje de trabajadores (registro horario).

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


# --- Fichaje de trabajadores (registro horario, art. 34.9 ET) -------------

def obtener_fichaje_datos(usuario_id: int) -> sqlite3.Row:
    conn = _db.get_connection()
    try:
        fila = conn.execute("SELECT * FROM fichaje_datos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        if fila is None:  # solo la primera vez (ver obtener_perfil_usuario)
            conn.execute("INSERT OR IGNORE INTO fichaje_datos (usuario_id) VALUES (?)", (usuario_id,))
            conn.commit()
            fila = conn.execute("SELECT * FROM fichaje_datos WHERE usuario_id = ?", (usuario_id,)).fetchone()
        return fila
    finally:
        conn.close()


def guardar_fichaje_datos(
    usuario_id: int, nombre_completo: str, dni_nie: str, numero_afiliacion_ss: str | None = None,
    categoria_profesional: str | None = None, tipo_contrato: str | None = None,
    fecha_alta: str | None = None, jornada_semanal_horas: float | None = None,
    convenio_colectivo: str | None = None,
) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO fichaje_datos (usuario_id) VALUES (?)", (usuario_id,))
        conn.execute(
            """UPDATE fichaje_datos SET nombre_completo = ?, dni_nie = ?, numero_afiliacion_ss = ?,
               categoria_profesional = ?, tipo_contrato = ?, fecha_alta = ?, jornada_semanal_horas = ?,
               convenio_colectivo = ?, actualizado_en = ? WHERE usuario_id = ?""",
            (
                nombre_completo.strip() or None, dni_nie.strip().upper() or None, numero_afiliacion_ss or None,
                categoria_profesional or None, tipo_contrato or None, fecha_alta or None,
                jornada_semanal_horas, convenio_colectivo or None, _db.now_iso(), usuario_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fichaje_datos_completos(usuario_id: int) -> bool:
    """True si el trabajador ya rellenó lo mínimo exigible (nombre + DNI/
    NIE) para identificarse ante una inspección -- se exige antes de dejar
    fichar por primera vez (ver app/rutas_fichaje.py)."""
    datos = _db.obtener_fichaje_datos(usuario_id)
    return bool(datos["nombre_completo"]) and bool(datos["dni_nie"])


def fichar(
    usuario_id: int, tenant_id: int | None, tipo: str, origen: str = "web", creado_por: int | None = None,
    corrige_a: int | None = None, nota: str | None = None,
    marca_tiempo: str | None = None, cliente_uuid: str | None = None,
    latitud: float | None = None, longitud: float | None = None,
) -> int:
    """Inserta un evento de fichaje, validando que la secuencia sea
    coherente (no se puede fichar salida sin una entrada abierta, ni una
    segunda entrada sin haber salido antes) -- lanza ValueError si no
    cuadra, mismo estilo que ErrorCorreo/ErrorBusqueda. `corrige_a` es
    para que un admin corrija un olvido sin tocar la fila original (ver
    comentario de la tabla `fichajes`).

    `marca_tiempo`/`cliente_uuid` son para la cola offline de la app móvil:
    si el evento se pulsó sin cobertura y se sincroniza más tarde,
    `marca_tiempo` conserva la hora real de la pulsación (si no se manda, se
    usa la hora del servidor como siempre) y `cliente_uuid` evita duplicar
    la fila si la sincronización se reintenta. Nota: la validación de
    secuencia sigue mirando el último evento por orden de inserción, no por
    `marca_tiempo` -- un evento offline que llega después de que ya se haya
    fichado algo más reciente puede quedar fuera de secuencia y rechazarse,
    algo inherente a fichar con retraso, no un bug de esta función."""
    if tipo not in ("entrada", "pausa_inicio", "pausa_fin", "salida"):
        raise ValueError(f"Tipo de fichaje no válido: {tipo!r}.")
    conn = _db.get_connection()
    try:
        if cliente_uuid is not None:
            existente = conn.execute("SELECT id FROM fichajes WHERE cliente_uuid = ?", (cliente_uuid,)).fetchone()
            if existente is not None:
                return existente["id"]
        ahora = _db.now_iso()
        if marca_tiempo is not None:
            limite_pasado = (_db.datetime.now() - _db.timedelta(days=7)).isoformat(timespec="seconds")
            if marca_tiempo > ahora or marca_tiempo < limite_pasado:
                raise ValueError("La hora del fichaje enviado no es válida (demasiado futura o de hace más de 7 días).")
        # A partir de aquí, todo el bloque (validación de secuencia +
        # lectura del último hash + INSERT) tiene que ser una sola sección
        # crítica: dos fichajes casi simultáneos (de cualquier usuario,
        # la cadena de hash es global -- ver verificar_integridad_fichajes)
        # podrían leer el mismo "último tipo"/"último hash" antes de que
        # ninguno haya insertado, y dejar la secuencia o la cadena rotas.
        # BEGIN IMMEDIATE adquiere el lock de escritura YA, en vez de
        # esperar a la primera escritura (comportamiento por defecto de
        # sqlite3): un segundo fichar() concurrente se queda esperando aquí
        # (hasta busy_timeout, ya en 5000ms en get_connection()) en vez de
        # leer datos que están a punto de quedar obsoletos.
        conn.execute("BEGIN IMMEDIATE")
        if corrige_a is not None:
            original = conn.execute("SELECT id FROM fichajes WHERE id = ? AND usuario_id = ?", (corrige_a, usuario_id)).fetchone()
            if original is None:
                raise ValueError(f"El fichaje {corrige_a} a corregir no existe o no es de este trabajador.")
        else:
            ultimo = conn.execute(
                "SELECT tipo FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
            ).fetchone()
            ultimo_tipo = ultimo["tipo"] if ultimo else "salida"  # sin fichajes previos = como si estuviera fuera
            if tipo not in _db._FICHAJE_TRANSICIONES_VALIDAS.get(ultimo_tipo, set()):
                raise ValueError(f"No se puede fichar '{tipo}' viniendo de '{ultimo_tipo}' — revisa tu último fichaje.")
        marca_tiempo_final = marca_tiempo or ahora
        creado_por_final = creado_por or usuario_id
        ultimo_hash = conn.execute("SELECT hash FROM fichajes ORDER BY id DESC LIMIT 1").fetchone()
        hash_anterior = ultimo_hash["hash"] if ultimo_hash and ultimo_hash["hash"] else _db._HASH_FICHAJE_GENESIS
        hash_fila = _db._hash_fichaje(hash_anterior, usuario_id, tipo, marca_tiempo_final, creado_por_final)
        cur = conn.execute(
            """INSERT INTO fichajes
               (usuario_id, tenant_id, tipo, marca_tiempo, origen, nota, corrige_a, creado_por, creado_en,
                cliente_uuid, hash, latitud, longitud)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, tenant_id, tipo, marca_tiempo_final, origen, nota, corrige_a, creado_por_final, ahora,
                cliente_uuid, hash_fila, latitud, longitud,
            ),
        )
        conn.commit()
        return cur.lastrowid
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def verificar_integridad_fichajes() -> dict:
    """Recorre TODA la cadena de hashes de `fichajes` (ver _hash_fichaje)
    y confirma que cada fila coincide con el hash recalculado a partir de
    la anterior -- expuesta en /fichaje/admin/verificar-integridad. Es una
    comprobación global (no por tenant): la cadena entrelaza filas de
    todos los tenants, así que verificarla entera es lo único que tiene
    sentido matemáticamente; cualquier admin/gestor puede pedirla, no
    revela contenido de otros tenants, solo si la cadena es íntegra o en
    qué fila se rompió."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            "SELECT id, usuario_id, tipo, marca_tiempo, creado_por, hash FROM fichajes ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    hash_anterior = _db._HASH_FICHAJE_GENESIS
    for fila in filas:
        esperado = _db._hash_fichaje(hash_anterior, fila["usuario_id"], fila["tipo"], fila["marca_tiempo"], fila["creado_por"])
        if fila["hash"] != esperado:
            return {"integra": False, "total_fichajes": len(filas), "primera_fila_rota": fila["id"]}
        hash_anterior = fila["hash"]
    return {"integra": True, "total_fichajes": len(filas), "primera_fila_rota": None}


def estado_actual_fichaje(usuario_id: int) -> str:
    """'fuera' | 'dentro' | 'en_pausa', según el último evento real (no
    cuenta si esa fila es en sí una corrección de otra anterior — el
    último evento cronológico manda igual)."""
    conn = _db.get_connection()
    try:
        ultimo = conn.execute(
            "SELECT tipo FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
        ).fetchone()
        if ultimo is None or ultimo["tipo"] == "salida":
            return "fuera"
        if ultimo["tipo"] == "pausa_inicio":
            return "en_pausa"
        return "dentro"
    finally:
        conn.close()


def jornadas_abiertas_sin_aviso(entrada_antes_de: str) -> list[sqlite3.Row]:
    """Jornadas abiertas (el último evento del trabajador no es una salida)
    cuya última entrada es anterior a `entrada_antes_de` (ISO) y de las que
    todavía no se ha avisado."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT e.id AS entrada_id, e.usuario_id, e.marca_tiempo
               FROM fichajes e
               WHERE e.tipo = 'entrada'
                 AND e.id = (SELECT MAX(id) FROM fichajes WHERE usuario_id = e.usuario_id AND tipo = 'entrada')
                 AND (SELECT tipo FROM fichajes WHERE usuario_id = e.usuario_id ORDER BY id DESC LIMIT 1) != 'salida'
                 AND e.marca_tiempo <= ?
                 AND NOT EXISTS (SELECT 1 FROM fichaje_avisos a WHERE a.usuario_id = e.usuario_id AND a.entrada_id = e.id)""",
            (entrada_antes_de,),
        ).fetchall()
    finally:
        conn.close()


def registrar_aviso_fichaje(usuario_id: int, entrada_id: int) -> bool:
    """True si es la primera vez que se avisa de esta jornada."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO fichaje_avisos (usuario_id, entrada_id, avisado_en) VALUES (?, ?, ?)",
            (usuario_id, entrada_id, _db.now_iso()),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def entrada_abierta_fichaje(usuario_id: int) -> str | None:
    """Marca de tiempo de la entrada de la jornada abierta, o None si está fuera."""
    conn = _db.get_connection()
    try:
        ultimo = conn.execute(
            "SELECT tipo FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
        ).fetchone()
        if ultimo is None or ultimo["tipo"] == "salida":
            return None
        entrada = conn.execute(
            "SELECT marca_tiempo FROM fichajes WHERE usuario_id = ? AND tipo = 'entrada' ORDER BY id DESC LIMIT 1",
            (usuario_id,),
        ).fetchone()
        return entrada["marca_tiempo"] if entrada else None
    finally:
        conn.close()


def ultimo_fichaje(usuario_id: int) -> sqlite3.Row | None:
    """La fila completa del último evento de fichaje -- a diferencia de
    estado_actual_fichaje() (que calcula el ESTADO a partir del mismo
    último evento pero descarta su marca_tiempo), esta sí expone la
    marca_tiempo, para poder mostrar "llevas X tiempo dentro/en pausa"
    en el panel del trabajador."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM fichajes WHERE usuario_id = ? ORDER BY id DESC LIMIT 1", (usuario_id,)
        ).fetchone()
    finally:
        conn.close()


def listar_fichajes(usuario_id: int, desde: str | None = None, hasta: str | None = None) -> list[sqlite3.Row]:
    """Historial de un trabajador -- se usa tanto para su propio
    historial como para el detalle que ve un admin de un trabajador
    concreto (mismos datos, distinto quién pregunta; el control de acceso
    vive en la ruta, no aquí)."""
    conn = _db.get_connection()
    try:
        sql = "SELECT * FROM fichajes WHERE usuario_id = ?"
        params: list = [usuario_id]
        if desde:
            sql += " AND marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND marca_tiempo < ?"
            params.append(_db._fecha_exclusiva(hasta))
        sql += " ORDER BY marca_tiempo DESC"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def fichajes_tenant_crudos(
    tenant_id: int | None, desde: str | None = None, hasta: str | None = None, usuario_id: int | None = None,
) -> list[sqlite3.Row]:
    """Eventos de fichaje en bruto de un tenant (con email/nombre/DNI del
    trabajador ya unidos), para que app/fichaje_export.py construya el
    CSV/PDF -- misma idea que db.historial() alimentando a export.py, la
    tabla en sí no sabe nada de formatos de salida."""
    conn = _db.get_connection()
    try:
        sql = (
            "SELECT f.*, u.email, fd.nombre_completo, fd.dni_nie "
            "FROM fichajes f "
            "JOIN usuarios u ON u.id = f.usuario_id "
            "LEFT JOIN fichaje_datos fd ON fd.usuario_id = f.usuario_id "
            "WHERE (f.tenant_id = ? OR (? IS NULL AND f.tenant_id IS NULL))"
        )
        params: list = [tenant_id, tenant_id]
        if usuario_id:
            sql += " AND f.usuario_id = ?"
            params.append(usuario_id)
        if desde:
            sql += " AND f.marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND f.marca_tiempo < ?"
            params.append(_db._fecha_exclusiva(hasta))
        sql += " ORDER BY f.usuario_id, f.marca_tiempo"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def resumen_fichajes_tenant(tenant_id: int | None, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Horas trabajadas por cada trabajador del tenant en el periodo, para
    el panel de admin. Empareja entrada/salida y resta las pausas
    recorriendo el log en Python (no es un problema que encaje bien en
    SQL puro: es "diferencia entre eventos consecutivos de una serie")."""
    conn = _db.get_connection()
    try:
        sql = (
            "SELECT f.*, u.email, fd.nombre_completo, fd.jornada_semanal_horas "
            "FROM fichajes f "
            "JOIN usuarios u ON u.id = f.usuario_id "
            "LEFT JOIN fichaje_datos fd ON fd.usuario_id = f.usuario_id "
            "WHERE (f.tenant_id = ? OR (? IS NULL AND f.tenant_id IS NULL))"
        )
        params: list = [tenant_id, tenant_id]
        if desde:
            sql += " AND f.marca_tiempo >= ?"
            params.append(desde)
        if hasta:
            sql += " AND f.marca_tiempo < ?"
            params.append(_db._fecha_exclusiva(hasta))
        sql += " ORDER BY f.usuario_id, f.marca_tiempo"
        filas = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    por_usuario: dict[int, dict] = {}
    for f in filas:
        uid = f["usuario_id"]
        info = por_usuario.setdefault(uid, {
            "usuario_id": uid, "email": f["email"], "nombre_completo": f["nombre_completo"],
            "jornada_semanal_horas": f["jornada_semanal_horas"],
            "segundos_trabajados": 0, "segundos_pausa": 0, "num_fichajes": 0,
            "entrada_abierta": None, "pausa_abierta": None,
        })
        info["num_fichajes"] += 1
        marca = _db.datetime.fromisoformat(f["marca_tiempo"])
        if f["tipo"] == "entrada":
            info["entrada_abierta"] = marca
        elif f["tipo"] == "pausa_inicio":
            info["pausa_abierta"] = marca
        elif f["tipo"] == "pausa_fin" and info["pausa_abierta"]:
            info["segundos_pausa"] += (marca - info["pausa_abierta"]).total_seconds()
            info["pausa_abierta"] = None
        elif f["tipo"] == "salida" and info["entrada_abierta"]:
            info["segundos_trabajados"] += (marca - info["entrada_abierta"]).total_seconds()
            info["entrada_abierta"] = None

    resultado = [
        {
            "usuario_id": info["usuario_id"],
            "email": info["email"],
            "nombre_completo": info["nombre_completo"],
            "horas_trabajadas": round(info["segundos_trabajados"] / 3600, 2),
            "horas_pausa": round(info["segundos_pausa"] / 3600, 2),
            "jornada_semanal_horas": info["jornada_semanal_horas"],
            "num_fichajes": info["num_fichajes"],
            "jornada_abierta": info["entrada_abierta"] is not None,
        }
        for info in por_usuario.values()
    ]
    return sorted(resultado, key=lambda r: r["nombre_completo"] or r["email"])
