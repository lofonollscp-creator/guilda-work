"""Acceso a datos de categorías, tareas y eventos, tareas estilo Outlook y todo lo que cuelga de ellas (recurrentes, compartidas, comentarios, plantillas, dependencias, recordatorios, checklist).

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


# --- Categorías --------------------------------------------------------

def crear_categoria(usuario_id: int, nombre: str, color: str | None = None, icono: str | None = None) -> int:
    """Crea un proyecto, o reutiliza uno existente del MISMO usuario con el
    mismo nombre.

    `nombre` tiene una restricción UNIQUE por (usuario_id, nombre) en la
    tabla, y esa restricción no distingue entre proyectos activos y en la
    papelera — así que sin este chequeo, crear un proyecto con el mismo
    nombre que uno propio ya borrado (pero todavía en la papelera)
    reventaría con un IntegrityError. Si el que existe está en la
    papelera, se restaura en vez de fallar.

    El filtro `usuario_id = ?` de aquí abajo es imprescindible: sin él,
    dos usuarios distintos con un proyecto de igual nombre acababan
    compartiendo la misma fila sin saberlo (bug real, corregido en la
    revisión de lógica — ver también _migrar_categorias_unique_por_usuario).
    """
    nombre = nombre.strip()
    conn = _db.get_connection()
    try:
        existente = conn.execute(
            "SELECT id, papelera_en FROM categorias WHERE nombre = ? AND usuario_id = ?", (nombre, usuario_id)
        ).fetchone()
        if existente is not None:
            if existente["papelera_en"] is not None:
                conn.execute(
                    "UPDATE categorias SET papelera_en = NULL WHERE id = ?", (existente["id"],)
                )
                conn.commit()
            return existente["id"]

        siguiente_orden = conn.execute(
            "SELECT COALESCE(MAX(orden), -1) + 1 FROM categorias WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO categorias (usuario_id, nombre, color, icono, creada_en, orden) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, nombre, color, icono, _db.now_iso(), siguiente_orden),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_categorias(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL ORDER BY orden, nombre",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def _categoria_id_propio(conn: sqlite3.Connection, usuario_id: int, categoria_id: int | None) -> int | None:
    """Defensa en profundidad: ningún punto que recibe un categoria_id ya
    numérico (formulario manipulado a mano, o la tool de MCP cuando se le
    pasa el id directamente en vez del nombre) comprobaba que esa
    categoría fuera de verdad del usuario que la usa -- con la UNIQUE
    global de antes eso ya no hacía falta que colisionara por nombre
    para pasar desapercibido (revisión de lógica). Si no es suya, se
    trata como si no se hubiera indicado ninguna (mismo criterio
    permisivo que el resto de validaciones de esta app: se degrada en
    silencio, no revienta la petición entera)."""
    if categoria_id is None:
        return None
    fila = conn.execute(
        "SELECT 1 FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
    ).fetchone()
    if fila is not None:
        return categoria_id
    # También un proyecto compartido del despacho en el que se puede colaborar.
    return categoria_id if _db._rol_en_proyecto(conn, usuario_id, categoria_id) == "colabora" else None


def mover_categoria(usuario_id: int, categoria_id: int, direccion: str) -> None:
    """Reordena un proyecto un puesto arriba o abajo (`direccion`: 'arriba'/'abajo')."""
    conn = _db.get_connection()
    try:
        activas = conn.execute(
            "SELECT id, orden FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL ORDER BY orden, nombre",
            (usuario_id,),
        ).fetchall()
        ids = [f["id"] for f in activas]
        if categoria_id not in ids:
            return
        idx = ids.index(categoria_id)
        vecino_idx = idx - 1 if direccion == "arriba" else idx + 1
        if vecino_idx < 0 or vecino_idx >= len(ids):
            return
        conn.execute(
            "UPDATE categorias SET orden = ? WHERE id = ?", (activas[vecino_idx]["orden"], categoria_id)
        )
        conn.execute(
            "UPDATE categorias SET orden = ? WHERE id = ?", (activas[idx]["orden"], ids[vecino_idx])
        )
        conn.commit()
    finally:
        conn.close()


def reordenar_categorias(usuario_id: int, orden_ids: list[int]) -> None:
    """Reescribe `orden` según la lista completa recibida (0, 1, 2...), para
    el arrastrar-y-soltar de la barra lateral — a diferencia de
    `mover_categoria`, que mueve un solo puesto. Los ids que no existan (o no
    estén activos, o no sean del usuario) se ignoran sin fallar; los proyectos
    activos que falten en la lista conservan su `orden` actual, detrás de
    los que sí se han movido."""
    conn = _db.get_connection()
    try:
        activos = {
            f["id"] for f in conn.execute(
                "SELECT id FROM categorias WHERE usuario_id = ? AND papelera_en IS NULL", (usuario_id,)
            )
        }
        siguiente = 0
        for categoria_id in orden_ids:
            if categoria_id in activos:
                conn.execute("UPDATE categorias SET orden = ? WHERE id = ?", (siguiente, categoria_id))
                siguiente += 1
        conn.commit()
    finally:
        conn.close()


def alternar_favorito_categoria(usuario_id: int, categoria_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE categorias SET favorito = 1 - favorito WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def obtener_categoria(usuario_id: int, categoria_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM categorias WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (categoria_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def renombrar_categoria(usuario_id: int, categoria_id: int, nombre: str, color: str | None = None, icono: str | None = None) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE categorias SET nombre = ?, color = ?, icono = ? WHERE id = ? AND usuario_id = ?",
            (nombre.strip(), color, icono, categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_categoria(usuario_id: int, categoria_id: int) -> None:
    """Manda un proyecto (y todo lo que contiene) a la papelera. No borra nada de
    verdad — se puede restaurar, o purgar definitivamente desde la papelera."""
    conn = _db.get_connection()
    try:
        ahora = _db._marca_papelera()
        conn.execute(
            "UPDATE categorias SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (ahora, categoria_id, usuario_id),
        )
        conn.execute(
            "UPDATE tareas SET papelera_en = ? WHERE categoria_id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (ahora, categoria_id, usuario_id),
        )
        conn.execute(
            "UPDATE notas SET papelera_en = ? WHERE categoria_id = ? AND usuario_id = ? AND papelera_en IS NULL",
            (ahora, categoria_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def restaurar_categoria(usuario_id: int, categoria_id: int) -> None:
    """Saca un proyecto de la papelera, junto con lo que se mandó a la papelera
    a la vez que él (no restaura notas/tareas que ya estaban en la papelera
    por separado antes de borrar el proyecto)."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            "SELECT papelera_en FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id)
        ).fetchone()
        if fila is None or fila["papelera_en"] is None:
            return
        marca = fila["papelera_en"]
        conn.execute("UPDATE categorias SET papelera_en = NULL WHERE id = ?", (categoria_id,))
        conn.execute(
            "UPDATE tareas SET papelera_en = NULL WHERE categoria_id = ? AND papelera_en = ?",
            (categoria_id, marca),
        )
        conn.execute(
            "UPDATE notas SET papelera_en = NULL WHERE categoria_id = ? AND papelera_en = ?",
            (categoria_id, marca),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_categoria_definitivamente(usuario_id: int, categoria_id: int) -> None:
    """Borra un proyecto y todo lo que contiene de verdad (sin pasar por la
    papelera). Lo usa el botón "Eliminar definitivamente" y la purga
    automática de la papelera."""
    conn = _db.get_connection()
    try:
        tarea_ids = [
            row["id"] for row in conn.execute(
                "SELECT id FROM tareas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id)
            ).fetchall()
        ]
        if tarea_ids:
            marcas = ",".join("?" * len(tarea_ids))
            conn.execute(f"DELETE FROM pausas WHERE tarea_id IN ({marcas})", tarea_ids)
            conn.execute(f"DELETE FROM notas WHERE tarea_id IN ({marcas})", tarea_ids)
        conn.execute("DELETE FROM notas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.execute("DELETE FROM tareas WHERE categoria_id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.execute("DELETE FROM plantillas WHERE categoria_id = ?", (categoria_id,))
        conn.execute("DELETE FROM categorias WHERE id = ? AND usuario_id = ?", (categoria_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def contar_entradas_hoy_por_usuario(usuario_id: int) -> dict[int, int]:
    """Cuenta las entradas (notas + tareas) de hoy por proyecto, para todos los
    proyectos del usuario a la vez (2 consultas GROUP BY en vez de una por
    proyecto) -- usado en el dashboard."""
    conn = _db.get_connection()
    try:
        hoy = _db.datetime.now().strftime("%Y-%m-%d")
        manana = _db._fecha_exclusiva(hoy)
        resultado: dict[int, int] = {}
        for fila in conn.execute(
            "SELECT categoria_id, COUNT(*) AS n FROM notas WHERE usuario_id = ? AND papelera_en IS NULL AND creada_en >= ? AND creada_en < ? AND categoria_id IS NOT NULL GROUP BY categoria_id",
            (usuario_id, hoy, manana),
        ):
            resultado[fila["categoria_id"]] = resultado.get(fila["categoria_id"], 0) + fila["n"]
        for fila in conn.execute(
            "SELECT categoria_id, COUNT(*) AS n FROM tareas WHERE usuario_id = ? AND papelera_en IS NULL AND inicio_en >= ? AND inicio_en < ? AND categoria_id IS NOT NULL GROUP BY categoria_id",
            (usuario_id, hoy, manana),
        ):
            resultado[fila["categoria_id"]] = resultado.get(fila["categoria_id"], 0) + fila["n"]
        return resultado
    finally:
        conn.close()


# --- Tareas / eventos ---------------------------------------------------

def crear_tarea(usuario_id: int, nombre: str, categoria_id: int, tipo: str, tarea_outlook_id: int | None = None) -> int:
    conn = _db.get_connection()
    try:
        # categoria_id es NOT NULL en esta tabla (a diferencia de notas/
        # tareas_outlook, aquí el proyecto es obligatorio) -- así que si no es
        # del usuario no se puede degradar a None como en el resto, hay
        # que rechazar la petición entera (defensa en profundidad: en uso
        # normal el <select> del formulario ya solo ofrece proyectos propios).
        if _db._categoria_id_propio(conn, usuario_id, categoria_id) is None:
            raise ValueError(f"La categoría/proyecto {categoria_id} no existe o no es tuya.")
        ahora = _db.now_iso()
        if tipo == "instantanea":
            cur = conn.execute(
                """INSERT INTO tareas
                   (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
                   VALUES (?, ?, ?, 'instantanea', 'finalizada', ?, NULL, NULL)""",
                (usuario_id, nombre.strip(), categoria_id, ahora),
            )
        else:
            cur = conn.execute(
                """INSERT INTO tareas
                   (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos, tarea_outlook_id)
                   VALUES (?, ?, ?, 'duracion', 'en_curso', ?, NULL, NULL, ?)""",
                (usuario_id, nombre.strip(), categoria_id, ahora, tarea_outlook_id),
            )
        conn.commit()
        tarea_id = cur.lastrowid
    finally:
        conn.close()
    _db._reindexar_tarea(usuario_id, tarea_id)
    return tarea_id


def _reindexar_tarea(usuario_id: int, tarea_id: int) -> None:
    """Mismo criterio que _reindexar_nota (ver más arriba) — falla en
    silencio, es una mejora de UX, no debe romper el registro de
    actividad en sí."""
    from . import busqueda
    try:
        tarea = _db.obtener_tarea(usuario_id, tarea_id)
        if tarea is not None:
            busqueda.indexar_tarea(dict(tarea))
    except busqueda.ErrorBusqueda:
        pass


def _quitar_tarea_del_indice(tarea_id: int) -> None:
    from . import busqueda
    try:
        busqueda.eliminar_del_indice("tarea", tarea_id)
    except busqueda.ErrorBusqueda:
        pass


def importar_tarea(
    usuario_id: int,
    nombre: str,
    categoria_id: int,
    tipo: str,
    inicio_en: str,
    fin_en: str | None,
    duracion_segundos: int | None,
) -> int:
    """Inserta una tarea/evento ya finalizado con timestamps explícitos
    (usado por la importación de datos exportados previamente). A
    diferencia de crear_tarea(), no usa la hora actual ni deja la tarea en
    curso — todo lo que se importa entra como histórico ya cerrado."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO tareas
               (usuario_id, nombre, categoria_id, tipo, estado, inicio_en, fin_en, duracion_segundos)
               VALUES (?, ?, ?, ?, 'finalizada', ?, ?, ?)""",
            (usuario_id, nombre.strip(), categoria_id, tipo, inicio_en, fin_en, duracion_segundos),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def hubo_actividad_reciente(usuario_id: int, minutos: int) -> bool:
    """True si se ha creado alguna nota o tarea en los últimos `minutos`."""
    conn = _db.get_connection()
    try:
        limite = (_db.datetime.now() - _db.timedelta(minutes=minutos)).isoformat(timespec="seconds")
        n = conn.execute(
            "SELECT COUNT(*) FROM notas WHERE usuario_id = ? AND creada_en >= ?", (usuario_id, limite)
        ).fetchone()[0]
        t = conn.execute(
            "SELECT COUNT(*) FROM tareas WHERE usuario_id = ? AND inicio_en >= ?", (usuario_id, limite)
        ).fetchone()[0]
        return (n + t) > 0
    finally:
        conn.close()


def _segundos_pausados_cerrados(conn: sqlite3.Connection, tarea_id: int) -> int:
    """Suma la duración de las pausas ya cerradas (reanudadas) de una tarea."""
    total = 0
    for r in conn.execute(
        "SELECT pausada_en, reanudada_en FROM pausas WHERE tarea_id = ? AND reanudada_en IS NOT NULL",
        (tarea_id,),
    ):
        total += int(
            (_db.datetime.fromisoformat(r["reanudada_en"]) - _db.datetime.fromisoformat(r["pausada_en"])).total_seconds()
        )
    return total


def pausar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE tareas SET estado = 'pausada' WHERE id = ? AND usuario_id = ? AND tipo = 'duracion' AND estado = 'en_curso'",
            (tarea_id, usuario_id),
        )
        if cur.rowcount:
            conn.execute(
                "INSERT INTO pausas (tarea_id, pausada_en) VALUES (?, ?)",
                (tarea_id, _db.now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def reanudar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE tareas SET estado = 'en_curso' WHERE id = ? AND usuario_id = ? AND estado = 'pausada'",
            (tarea_id, usuario_id),
        )
        if cur.rowcount:
            conn.execute(
                """UPDATE pausas SET reanudada_en = ?
                   WHERE tarea_id = ? AND reanudada_en IS NULL""",
                (_db.now_iso(), tarea_id),
            )
        conn.commit()
    finally:
        conn.close()


def finalizar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = _db.get_connection()
    try:
        row = conn.execute(
            "SELECT inicio_en, estado, nombre FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        ).fetchone()
        if row is None:
            return
        fin = _db.now_iso()
        if row["estado"] == "pausada":
            conn.execute(
                "UPDATE pausas SET reanudada_en = ? WHERE tarea_id = ? AND reanudada_en IS NULL",
                (fin, tarea_id),
            )
        inicio = _db.datetime.fromisoformat(row["inicio_en"])
        segundos_pausados = _db._segundos_pausados_cerrados(conn, tarea_id)
        duracion = max(int((_db.datetime.fromisoformat(fin) - inicio).total_seconds()) - segundos_pausados, 0)
        conn.execute(
            "UPDATE tareas SET estado = 'finalizada', fin_en = ?, duracion_segundos = ? WHERE id = ?",
            (fin, duracion, tarea_id),
        )
        conn.commit()
    finally:
        conn.close()
    _db._emitir_evento_tarea_finalizada(usuario_id, tarea_id, row["nombre"], duracion)


def _emitir_evento(usuario_id: int, evento: str, payload: dict) -> None:
    """Webhook saliente del tenant del usuario (ver app/eventos.py). Un fallo
    al emitir nunca afecta a la operación ya hecha."""
    from . import eventos
    try:
        tenant = _db.tenant_de_usuario(usuario_id)
        eventos.emitir(evento, tenant["id"] if tenant else None, payload)
    except Exception:
        pass


def _emitir_evento_tarea_finalizada(usuario_id: int, tarea_id: int, nombre: str, duracion_segundos: int) -> None:
    """Segunda excepción documentada (junto a busqueda) a "db.py no
    depende de otros app/*.py": un webhook es, por naturaleza, un
    efecto secundario de la escritura, no una operación de negocio más
    — mismo criterio ya aplicado a la indexación de búsqueda. Import
    perezoso para evitar cualquier ciclo, aunque hoy app/eventos.py
    solo importa db.py, no al revés."""
    from . import eventos
    try:
        tenant = _db.tenant_de_usuario(usuario_id)
        eventos.emitir(
            "tarea.finalizada", tenant["id"] if tenant else None,
            {"tarea_id": tarea_id, "nombre": nombre, "duracion_segundos": duracion_segundos},
        )
    except Exception:
        pass  # un fallo al emitir el evento no debe afectar a la tarea ya finalizada


def tareas_activas(usuario_id: int) -> list[dict]:
    """Tareas con duración en curso o en pausa, con el tiempo ya pausado calculado."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas t JOIN categorias c ON c.id = t.categoria_id
               WHERE t.usuario_id = ? AND t.tipo = 'duracion' AND t.estado IN ('en_curso', 'pausada')
                 AND t.papelera_en IS NULL
               ORDER BY t.inicio_en""",
            (usuario_id,),
        ).fetchall()
        resultado = []
        for f in filas:
            d = dict(f)
            d["segundos_pausados"] = _db._segundos_pausados_cerrados(conn, f["id"])
            if f["estado"] == "pausada":
                pausa_abierta = conn.execute(
                    "SELECT pausada_en FROM pausas WHERE tarea_id = ? AND reanudada_en IS NULL",
                    (f["id"],),
                ).fetchone()
                inicio = _db.datetime.fromisoformat(f["inicio_en"])
                pausada_en = _db.datetime.fromisoformat(pausa_abierta["pausada_en"])
                d["segundos_trabajados_congelado"] = max(
                    int((pausada_en - inicio).total_seconds()) - d["segundos_pausados"], 0
                )
            resultado.append(d)
        return resultado
    finally:
        conn.close()


def obtener_tarea(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre
               FROM tareas t JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND t.usuario_id = ? AND t.papelera_en IS NULL""",
            (tarea_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def editar_tarea(usuario_id: int, tarea_id: int, nombre: str) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET nombre = ? WHERE id = ? AND usuario_id = ?",
            (nombre.strip(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_tarea(usuario_id, tarea_id)


def editar_tiempos_tarea(usuario_id: int, tarea_id: int, inicio_en: str, fin_en: str | None = None) -> str | None:
    """Ajusta manualmente el inicio (y el fin, si la tarea ya está finalizada).

    Devuelve un mensaje de error legible si la entrada no es válida, o None si todo fue bien.
    """
    conn = _db.get_connection()
    try:
        row = conn.execute(
            "SELECT tipo, estado, fin_en FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        ).fetchone()
        if row is None:
            return "La tarea ya no existe."
        try:
            inicio = _db.datetime.fromisoformat(inicio_en)
        except ValueError:
            return "La fecha/hora de inicio no es válida."

        if row["estado"] == "finalizada" and row["tipo"] == "duracion":
            if not fin_en:
                return "Falta la fecha/hora de fin."
            try:
                fin = _db.datetime.fromisoformat(fin_en)
            except ValueError:
                return "La fecha/hora de fin no es válida."
            if fin <= inicio:
                return "El fin debe ser posterior al inicio."
            segundos_pausados = _db._segundos_pausados_cerrados(conn, tarea_id)
            duracion = max(int((fin - inicio).total_seconds()) - segundos_pausados, 0)
            conn.execute(
                "UPDATE tareas SET inicio_en = ?, fin_en = ?, duracion_segundos = ? WHERE id = ?",
                (inicio.isoformat(timespec="seconds"), fin.isoformat(timespec="seconds"), duracion, tarea_id),
            )
        else:
            if inicio > _db.datetime.now():
                return "El inicio no puede ser en el futuro."
            conn.execute(
                "UPDATE tareas SET inicio_en = ? WHERE id = ?",
                (inicio.isoformat(timespec="seconds"), tarea_id),
            )
        conn.commit()
        return None
    finally:
        conn.close()


def eliminar_tarea(usuario_id: int, tarea_id: int) -> None:
    """Manda una tarea/evento a la papelera (no la borra de verdad)."""
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET papelera_en = ? WHERE id = ? AND usuario_id = ?",
            (_db._marca_papelera(), tarea_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    _db._quitar_tarea_del_indice(tarea_id)


def restaurar_tarea(usuario_id: int, tarea_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tareas SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()
    _db._reindexar_tarea(usuario_id, tarea_id)


def eliminar_tarea_definitivamente(usuario_id: int, tarea_id: int) -> None:
    """Borra una tarea/evento y sus pausas y notas asociadas de verdad."""
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM pausas WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM notas WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM tareas WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id))
        conn.commit()
    finally:
        conn.close()
    _db._quitar_tarea_del_indice(tarea_id)


def estimacion_valida(valor) -> int | None:
    """Minutos de estimación (1 a 6000) o None. Lo que no sea un entero razonable se ignora."""
    try:
        minutos = int(valor)
    except (TypeError, ValueError):
        return None
    return minutos if 1 <= minutos <= 6000 else None


def registrar_actividad_tarea(usuario_id: int, tarea_id: int, tipo: str, detalle: str = "") -> None:
    """Anota una línea en el historial de la tarea. Es solo un registro: un fallo
    aquí nunca debe romper la acción que se está registrando."""
    try:
        conn = _db.get_connection()
        try:
            conn.execute(
                "INSERT INTO tarea_actividad (tarea_id, usuario_id, tipo, detalle, creado_en) VALUES (?, ?, ?, ?, ?)",
                (tarea_id, usuario_id, tipo, (detalle or "")[:200], _db.now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def crear_tarea_outlook(
    usuario_id: int,
    asunto: str,
    cuerpo: str | None = None,
    estado: str = "no_iniciada",
    porcentaje_completado: int = 0,
    prioridad: str = "normal",
    fecha_inicio: str | None = None,
    fecha_vencimiento: str | None = None,
    categoria_outlook: str | None = None,
    categoria_id: int | None = None,
    outlook_entry_id: str | None = None,
    tarea_recurrente_id: int | None = None,
    cliente_fiscal_id: int | None = None,
    mensaje_correo_id: int | None = None,
    asignada_a: int | None = None,
    estimacion_min: int | None = None,
    vencimiento_id: int | None = None,
) -> int:
    estimacion_min = _db.estimacion_valida(estimacion_min)
    conn = _db.get_connection()
    try:
        categoria_id = _db._categoria_id_propio(conn, usuario_id, categoria_id)
        cliente_fiscal_id = _db._cliente_fiscal_id_del_tenant(conn, usuario_id, cliente_fiscal_id)
        vencimiento_id = _db._vencimiento_id_del_tenant(conn, usuario_id, vencimiento_id)
        mensaje_correo_id = _db._mensaje_correo_id_propio(conn, usuario_id, mensaje_correo_id)
        asignada_a = _db._companero_del_tenant(conn, usuario_id, asignada_a)
        cur = conn.execute(
            """INSERT INTO tareas_outlook
               (usuario_id, asunto, cuerpo, estado, porcentaje_completado, prioridad,
                fecha_inicio, fecha_vencimiento, categoria_outlook, categoria_id,
                outlook_entry_id, tarea_recurrente_id, cliente_fiscal_id, mensaje_correo_id,
                asignada_a, estimacion_min, vencimiento_id, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                usuario_id, asunto.strip(), (cuerpo or "").strip() or None, estado,
                porcentaje_completado, prioridad, fecha_inicio, fecha_vencimiento,
                (categoria_outlook or "").strip() or None, categoria_id, outlook_entry_id,
                tarea_recurrente_id, cliente_fiscal_id, mensaje_correo_id, asignada_a, estimacion_min, vencimiento_id, _db.now_iso(),
            ),
        )
        conn.commit()
        tarea_id = cur.lastrowid
    finally:
        conn.close()
    _db.registrar_actividad_tarea(usuario_id, tarea_id, "creada")
    _db._emitir_evento(usuario_id, "tarea.creada", {"tarea_id": tarea_id, "asunto": asunto.strip(), "asignada_a": asignada_a})
    return tarea_id


def _cliente_fiscal_id_del_tenant(conn: sqlite3.Connection, usuario_id: int, cliente_fiscal_id: int | None) -> int | None:
    """Solo se enlaza un cliente fiscal del propio despacho (mismo criterio
    permisivo que _categoria_id_propio: si no es válido, se ignora)."""
    if cliente_fiscal_id is None:
        return None
    fila = conn.execute(
        """SELECT c.id FROM clientes_fiscales c JOIN usuarios u ON u.tenant_id = c.tenant_id
           WHERE c.id = ? AND u.id = ? AND c.papelera_en IS NULL""",
        (cliente_fiscal_id, usuario_id),
    ).fetchone()
    return fila["id"] if fila else None


def _vencimiento_id_del_tenant(conn: sqlite3.Connection, usuario_id: int, vencimiento_id: int | None) -> int | None:
    """Solo se enlaza un vencimiento fiscal del propio despacho (mismo criterio permisivo que el cliente fiscal: si no es válido, se ignora)."""
    if vencimiento_id is None:
        return None
    fila = conn.execute(
        """SELECT v.id FROM vencimientos_fiscales v JOIN usuarios u ON u.tenant_id = v.tenant_id
           WHERE v.id = ? AND u.id = ? AND v.papelera_en IS NULL""",
        (vencimiento_id, usuario_id),
    ).fetchone()
    return fila["id"] if fila else None


_TAREA_DE_LA_PERSONA = ("(t.usuario_id = ? OR t.asignada_a = ? OR t.id IN (SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))")


def tareas_de_vencimiento(tenant_id: int, vencimiento_id: int, usuario_id: int) -> list[dict]:
    """Las tareas ligadas a un vencimiento que la persona puede ver (suyas, asignadas a ella o en las que colabora): las generadas por una regla y las creadas desde su ficha.
    Las tareas de otras personas no se listan (ver `resumen_tareas_de_vencimiento` para el recuento de todas)."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            f"""SELECT t.id, t.asunto, t.estado, t.fecha_vencimiento, t.usuario_id, t.asignada_a,
                       EXISTS (SELECT 1 FROM tareas_por_vencimiento_generadas g WHERE g.tarea_id = t.id) AS generada
                FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id
                WHERE t.vencimiento_id = ? AND u.tenant_id = ? AND t.papelera_en IS NULL AND {_TAREA_DE_LA_PERSONA}
                ORDER BY (t.estado = 'completada'), t.fecha_vencimiento, t.id""",
            (vencimiento_id, tenant_id, usuario_id, usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def resumen_tareas_de_vencimiento(tenant_id: int, vencimiento_id: int) -> dict:
    """`{total, abiertas}` de TODAS las tareas ligadas al vencimiento (sin enseñar cuáles), para avisar de que ya están todas hechas."""
    conn = _db.get_connection()
    try:
        f = conn.execute(
            """SELECT COUNT(*) AS total, COALESCE(SUM(t.estado != 'completada'), 0) AS abiertas FROM tareas_outlook t JOIN usuarios u ON u.id = t.usuario_id
               WHERE t.vencimiento_id = ? AND u.tenant_id = ? AND t.papelera_en IS NULL""", (vencimiento_id, tenant_id)).fetchone()
        return {"total": f["total"], "abiertas": f["abiertas"]}
    finally:
        conn.close()


def completar_tareas_de_vencimiento(tenant_id: int, vencimiento_id: int) -> int:
    """Al presentar un vencimiento, completa las tareas que **una regla `tareas_por_vencimiento` generó** para él (las creadas a mano no se tocan). Cada una la completa su dueña,
    con los mismos efectos que completarla a mano (cronómetros, eventos, desbloqueos). Idempotente. Devuelve cuántas quedan completadas."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT t.id, t.usuario_id FROM tareas_por_vencimiento_generadas g JOIN tareas_outlook t ON t.id = g.tarea_id JOIN usuarios u ON u.id = t.usuario_id
               WHERE g.vencimiento_id = ? AND u.tenant_id = ? AND t.estado != 'completada' AND t.papelera_en IS NULL""", (vencimiento_id, tenant_id)).fetchall()
    finally:
        conn.close()
    for f in filas:
        _db.completar_tarea_outlook(f["usuario_id"], f["id"])
    if not filas:
        return 0
    conn = _db.get_connection()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM tareas_outlook WHERE estado = 'completada' AND id IN ({','.join('?' * len(filas))})", [f["id"] for f in filas]).fetchone()[0]
    finally:
        conn.close()


def _mensaje_correo_id_propio(conn: sqlite3.Connection, usuario_id: int, mensaje_id: int | None) -> int | None:
    if mensaje_id is None:
        return None
    fila = conn.execute(
        """SELECT m.id FROM correo_mensajes m JOIN correo_cuentas c ON c.id = m.cuenta_id
           WHERE m.id = ? AND c.usuario_id = ?""",
        (mensaje_id, usuario_id),
    ).fetchone()
    return fila["id"] if fila else None


def _companero_del_tenant(conn: sqlite3.Connection, usuario_id: int, otro_id: int | None) -> int | None:
    """Solo se puede asignar a alguien del MISMO despacho (y no a uno mismo:
    la tarea ya es suya). Si no, se ignora."""
    if otro_id is None or otro_id == usuario_id:
        return None
    fila = conn.execute(
        """SELECT o.id FROM usuarios o JOIN usuarios yo ON yo.tenant_id = o.tenant_id
           WHERE o.id = ? AND yo.id = ? AND yo.tenant_id IS NOT NULL""",
        (otro_id, usuario_id),
    ).fetchone()
    return fila["id"] if fila else None


def listar_companeros_tenant(usuario_id: int) -> list[sqlite3.Row]:
    """Compañeros del mismo despacho (sin el propio usuario), con el nombre
    elegido o, en su defecto, el correo -- para el selector de asignación."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT o.id, COALESCE(NULLIF(p.nombre_mostrado, ''), o.email) AS nombre
               FROM usuarios o JOIN usuarios yo ON yo.tenant_id = o.tenant_id
               LEFT JOIN usuario_perfil p ON p.usuario_id = o.id
               WHERE yo.id = ? AND yo.tenant_id IS NOT NULL AND o.id != ? ORDER BY nombre""",
            (usuario_id, usuario_id),
        ).fetchall()
    finally:
        conn.close()


def crear_tarea_recurrente(
    usuario_id: int, asunto: str, periodicidad: str, dia: int, categoria_id: int | None = None,
    mes: int | None = None,
) -> int:
    """`dia`: 0-6 (lunes-domingo) si es semanal; 1-31 si es mensual, trimestral
    (primer mes de cada trimestre) o anual; sin uso (0) en diaria/laborables.
    `mes` (1-12) solo se usa en anual."""
    if periodicidad not in _db.PERIODICIDADES_RECURRENTES:
        raise ValueError(f"Periodicidad no válida: {periodicidad}")
    conn = _db.get_connection()
    try:
        categoria_id = _db._categoria_id_propio(conn, usuario_id, categoria_id)
        cur = conn.execute(
            "INSERT INTO tareas_recurrentes (usuario_id, categoria_id, asunto, periodicidad, dia, mes, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, categoria_id, asunto.strip(), periodicidad, dia, mes, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def crear_regla_por_vencimiento(
    usuario_id: int, modelo: str, asunto: str, crear_dias_antes: int = 14, vence_dias_antes: int = 2,
    categoria_id: int | None = None, asignar_responsable: bool = True, estimacion_min: int | None = None, prioridad: str = "normal",
) -> int:
    """Lanza ValueError con un mensaje legible si algo no vale. El asunto admite {cliente}, {modelo} y {periodo}."""
    modelo, asunto = (modelo or "").strip()[:20], " ".join((asunto or "").split())[:200]
    if not modelo or not asunto:
        raise ValueError("Indica el modelo (por ejemplo 303) y el asunto de la tarea.")
    if not 0 <= int(crear_dias_antes) <= 120 or not 0 <= int(vence_dias_antes) <= 120:
        raise ValueError("Los días van de 0 a 120.")
    if int(vence_dias_antes) > int(crear_dias_antes):
        raise ValueError("La tarea no puede vencer antes de crearse: «vence» debe ser menos días antes que «crear».")
    conn = _db.get_connection()
    try:
        u = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if u is None or u["tenant_id"] is None:
            raise ValueError("Tu usuario no pertenece a ningún despacho.")
        if conn.execute("SELECT COUNT(*) FROM tareas_por_vencimiento WHERE usuario_id = ?", (usuario_id,)).fetchone()[0] >= _db.MAX_REGLAS_POR_VENCIMIENTO:
            raise ValueError("Has llegado al máximo de reglas.")
        cur = conn.execute(
            """INSERT INTO tareas_por_vencimiento
               (usuario_id, tenant_id, modelo, asunto, crear_dias_antes, vence_dias_antes, categoria_id, asignar_responsable, estimacion_min, prioridad, creada_en)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, u["tenant_id"], modelo, asunto, int(crear_dias_antes), int(vence_dias_antes), _db._categoria_id_propio(conn, usuario_id, categoria_id),
             1 if asignar_responsable else 0, _db.estimacion_valida(estimacion_min), prioridad if prioridad in ("baja", "normal", "alta") else "normal", _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_reglas_por_vencimiento(usuario_id: int) -> list[dict]:
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT r.*, (SELECT COUNT(*) FROM tareas_por_vencimiento_generadas g WHERE g.regla_id = r.id) AS generadas
               FROM tareas_por_vencimiento r WHERE r.usuario_id = ? ORDER BY r.id DESC""",
            (usuario_id,))]
    finally:
        conn.close()


def alternar_regla_por_vencimiento(usuario_id: int, regla_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tareas_por_vencimiento SET activa = 1 - activa WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def eliminar_regla_por_vencimiento(usuario_id: int, regla_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM tareas_por_vencimiento WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def generar_tareas_por_vencimiento(hoy: _db.date | None = None, regla_id: int | None = None) -> int:
    """Crea las tareas que toquen: para cada regla activa (o solo `regla_id`) y cada vencimiento pendiente de su modelo en
    su despacho cuya fecha límite esté a `crear_dias_antes` días o menos (y no haya pasado), una tarea del dueño de la regla
    (asignada al responsable del vencimiento si la regla lo pide y es del despacho) que vence `vence_dias_antes` días antes
    de la fecha límite. Idempotente: un vencimiento no genera dos veces con la misma regla."""
    hoy = hoy or _db.date.today()
    creadas = 0
    conn = _db.get_connection()
    try:
        reglas = conn.execute(
            "SELECT * FROM tareas_por_vencimiento WHERE activa = 1" + (" AND id = ?" if regla_id is not None else ""),
            (regla_id,) if regla_id is not None else (),
        ).fetchall()
        pendientes = []
        for regla in reglas:
            horizonte = (hoy + _db.timedelta(days=regla["crear_dias_antes"])).isoformat()
            filas = conn.execute(
                """SELECT v.id, v.fecha_limite, v.periodo, v.modelo, v.usuario_id AS responsable_id, v.cliente_fiscal_id, c.nombre AS cliente
                   FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id
                   WHERE v.tenant_id = ? AND v.estado = 'pendiente' AND v.papelera_en IS NULL AND c.papelera_en IS NULL
                     AND lower(v.modelo) = lower(?) AND substr(v.fecha_limite, 1, 10) >= ? AND substr(v.fecha_limite, 1, 10) <= ?
                     AND NOT EXISTS (SELECT 1 FROM tareas_por_vencimiento_generadas g WHERE g.regla_id = ? AND g.vencimiento_id = v.id)""",
                (regla["tenant_id"], regla["modelo"], hoy.isoformat(), horizonte, regla["id"]),
            ).fetchall()
            pendientes += [(regla, f) for f in filas]
    finally:
        conn.close()
    for regla, v in pendientes:
        limite = _db.datetime.strptime(v["fecha_limite"][:10], "%Y-%m-%d").date()
        vence = max(limite - _db.timedelta(days=regla["vence_dias_antes"]), hoy)
        asunto = (regla["asunto"].replace("{cliente}", v["cliente"] or "").replace("{modelo}", v["modelo"] or "").replace("{periodo}", v["periodo"] or ""))[:200]
        conn = _db.get_connection()
        try:
            # Se reserva primero: si dos procesos coinciden, solo uno crea la tarea.
            reservado = conn.execute(
                "INSERT OR IGNORE INTO tareas_por_vencimiento_generadas (regla_id, vencimiento_id, creada_en) VALUES (?, ?, ?)",
                (regla["id"], v["id"], _db.now_iso()),
            ).rowcount
            conn.commit()
        finally:
            conn.close()
        if not reservado:
            continue
        destino = v["responsable_id"] if regla["asignar_responsable"] and v["responsable_id"] not in (None, regla["usuario_id"]) else None
        tarea_id = _db.crear_tarea_outlook(
            regla["usuario_id"], asunto, prioridad=regla["prioridad"], fecha_vencimiento=vence.isoformat(), categoria_id=regla["categoria_id"],
            cliente_fiscal_id=v["cliente_fiscal_id"], asignada_a=destino, estimacion_min=regla["estimacion_min"], vencimiento_id=v["id"],
        )
        conn = _db.get_connection()
        try:
            conn.execute("UPDATE tareas_por_vencimiento_generadas SET tarea_id = ? WHERE regla_id = ? AND vencimiento_id = ?", (tarea_id, regla["id"], v["id"]))
            conn.commit()
        finally:
            conn.close()
        creadas += 1
    return creadas


def listar_tareas_recurrentes(usuario_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tareas_recurrentes WHERE usuario_id = ? ORDER BY creado_en DESC", (usuario_id,),
        ).fetchall()
    finally:
        conn.close()


def alternar_activa_tarea_recurrente(usuario_id: int, regla_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute(
            "UPDATE tareas_recurrentes SET activa = 1 - activa WHERE id = ? AND usuario_id = ?",
            (regla_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_recurrente(usuario_id: int, regla_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("DELETE FROM tareas_recurrentes WHERE id = ? AND usuario_id = ?", (regla_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def _existe_tarea_generada_este_periodo(conn: sqlite3.Connection, regla_id: int, desde: str, hasta: str) -> bool:
    fila = conn.execute(
        "SELECT 1 FROM tareas_outlook WHERE tarea_recurrente_id = ? AND creada_en >= ? AND creada_en < ? "
        "AND papelera_en IS NULL LIMIT 1",
        (regla_id, desde, hasta),
    ).fetchone()
    return fila is not None


def generar_tareas_recurrentes() -> int:
    """Recurrencia automática por cron (ver scripts/generar_tareas_recurrentes.py),
    pensado para correr una vez al día -- para cada regla activa, comprueba
    si HOY es el día que le toca (día de la semana si es semanal, día del
    mes si es mensual -- si el mes no tiene ese día, se usa su último día,
    ver `dia_efectivo` abajo) y, si es así y todavía no se ha generado una
    tarea de ESTE periodo (semana o mes en curso, ver
    _existe_tarea_generada_este_periodo), crea una tareas_outlook nueva
    enlazada a la regla vía tarea_recurrente_id. Idempotente -- ejecutarlo
    varias veces el mismo día no duplica nada, mismo criterio que
    generar_vencimientos_automaticos()."""
    hoy = _db.datetime.now()
    hoy_iso = hoy.strftime("%Y-%m-%d")
    manana_iso = (hoy + _db.timedelta(days=1)).strftime("%Y-%m-%d")
    inicio_anio, fin_anio = f"{hoy.year}-01-01", f"{hoy.year + 1}-01-01"
    inicio_semana = (hoy - _db.timedelta(days=hoy.weekday())).strftime("%Y-%m-%d")
    fin_semana = (hoy - _db.timedelta(days=hoy.weekday()) + _db.timedelta(days=7)).strftime("%Y-%m-%d")
    inicio_mes = hoy.replace(day=1).strftime("%Y-%m-%d")
    if hoy.month == 12:
        fin_mes = hoy.replace(year=hoy.year + 1, month=1, day=1).strftime("%Y-%m-%d")
    else:
        fin_mes = hoy.replace(month=hoy.month + 1, day=1).strftime("%Y-%m-%d")
    ultimo_dia_del_mes = (_db.datetime.fromisoformat(fin_mes) - _db.timedelta(days=1)).day

    creadas = 0
    conn = _db.get_connection()
    try:
        reglas = conn.execute("SELECT * FROM tareas_recurrentes WHERE activa = 1").fetchall()
        for regla in reglas:
            periodicidad = regla["periodicidad"]
            if periodicidad == "diaria":
                le_toca_hoy, (desde, hasta) = True, (hoy_iso, manana_iso)
            elif periodicidad == "laborables":
                le_toca_hoy, (desde, hasta) = hoy.weekday() < 5, (hoy_iso, manana_iso)
            elif periodicidad == "semanal":
                le_toca_hoy = hoy.weekday() == regla["dia"]
                desde, hasta = inicio_semana, fin_semana
            elif periodicidad == "trimestral":
                # Primer mes de cada trimestre (enero, abril, julio, octubre).
                le_toca_hoy = hoy.month in (1, 4, 7, 10) and hoy.day == min(regla["dia"], ultimo_dia_del_mes)
                desde, hasta = inicio_mes, fin_mes
            elif periodicidad == "anual":
                le_toca_hoy = hoy.month == (regla["mes"] or 1) and hoy.day == min(regla["dia"], ultimo_dia_del_mes)
                desde, hasta = inicio_anio, fin_anio
            else:  # mensual
                dia_efectivo = min(regla["dia"], ultimo_dia_del_mes)
                le_toca_hoy = hoy.day == dia_efectivo
                desde, hasta = inicio_mes, fin_mes
            if not le_toca_hoy:
                continue
            if _db._existe_tarea_generada_este_periodo(conn, regla["id"], desde, hasta):
                continue
            categoria_id = _db._categoria_id_propio(conn, regla["usuario_id"], regla["categoria_id"])
            conn.execute(
                """INSERT INTO tareas_outlook
                   (usuario_id, asunto, categoria_id, tarea_recurrente_id, creada_en)
                   VALUES (?, ?, ?, ?, ?)""",
                (regla["usuario_id"], regla["asunto"], categoria_id, regla["id"], _db.now_iso()),
            )
            creadas += 1
        conn.commit()
        return creadas
    finally:
        conn.close()


def listar_tareas_outlook(
    usuario_id: int,
    estado: str | None = None,
    prioridad: str | None = None,
    categoria_outlook: str | None = None,
    texto: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    excluir_completadas: bool = False,
    limite: int | None = None,
    offset: int = 0,
    incluir_asignadas: bool = False,
    solo_asignadas: bool = False,
    categoria_id: int | None = None,
    cliente_fiscal_id: int | None = None,
    solo_compartidas: bool = False,
) -> list[sqlite3.Row]:
    """Tareas activas (no en la papelera), filtradas opcionalmente.

    Por defecto solo las del propio usuario (las llamadas existentes -- API,
    MCP, exportaciones -- no cambian). `incluir_asignadas`: añade las que un
    compañero le ha asignado; `solo_asignadas`: solo esas. `categoria_id`
    filtra por proyecto y `cliente_fiscal_id` por cliente.

    `desde`/`hasta` filtran por fecha_vencimiento (YYYY-MM-DD, inclusive) —
    los usa la vista calendario para pedir solo las de un rango de días.
    `excluir_completadas`: atajo para la vista "To-Do" por defecto de
    tareas_lista.html (solo tiene efecto si no se pasa `estado` explícito;
    antes ese filtro se aplicaba en Python DESPUÉS de traer las filas, lo
    que rompía la paginación por SQL de abajo).
    `limite`/`offset`: paginación (mismo estilo que db.listar_mensajes_correo)
    -- `limite=None` (por defecto) devuelve todo, para no romper a las
    llamadas existentes que esperan el conjunto completo (calendario,
    export a .ics/.csv, la API en rutas_api.py).
    """
    conn = _db.get_connection()
    try:
        # t.usuario_id/t.papelera_en llevan el prefijo de tabla porque
        # categorias también tiene esas dos columnas (JOIN ambiguo si no);
        # el resto de condiciones no lo necesitan, son propias de tareas_outlook.
        compartida = "t.id IN (SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?)"
        if solo_compartidas:
            cond, params = [compartida, "t.papelera_en IS NULL"], [usuario_id]
        elif solo_asignadas:
            cond, params = ["t.asignada_a = ?", "t.papelera_en IS NULL"], [usuario_id]
        elif incluir_asignadas:
            cond, params = [f"(t.usuario_id = ? OR t.asignada_a = ? OR {compartida})", "t.papelera_en IS NULL"], [usuario_id, usuario_id, usuario_id]
        else:
            cond, params = ["t.usuario_id = ?", "t.papelera_en IS NULL"], [usuario_id]
        if categoria_id is not None:
            cond.append("t.categoria_id = ?"); params.append(categoria_id)
        if cliente_fiscal_id is not None:
            cond.append("(t.cliente_fiscal_id = ? OR t.id IN (SELECT tarea_id FROM tarea_clientes WHERE cliente_fiscal_id = ?))"); params.extend((cliente_fiscal_id, cliente_fiscal_id))
        if estado:
            cond.append("estado = ?"); params.append(estado)
        elif excluir_completadas:
            cond.append("estado != 'completada'")
        if prioridad:
            cond.append("prioridad = ?"); params.append(prioridad)
        if categoria_outlook:
            cond.append("categoria_outlook = ?"); params.append(categoria_outlook)
        if texto:
            cond.append("(asunto LIKE ? OR cuerpo LIKE ?)")
            params.extend([f"%{texto}%", f"%{texto}%"])
        if desde:
            cond.append("fecha_vencimiento >= ?"); params.append(desde)
        if hasta:
            cond.append("fecha_vencimiento < ?"); params.append(_db._fecha_exclusiva(hasta))
        where = " AND ".join(cond)
        query = f"""SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color,
                       COALESCE(NULLIF(pa.nombre_mostrado, ''), ua.email) AS asignada_nombre,
                       COALESCE(NULLIF(po.nombre_mostrado, ''), uo.email) AS creador_nombre,
                       cf.nombre AS cliente_fiscal_nombre
                FROM tareas_outlook t LEFT JOIN categorias c ON c.id = t.categoria_id
                LEFT JOIN usuarios ua ON ua.id = t.asignada_a LEFT JOIN usuario_perfil pa ON pa.usuario_id = t.asignada_a
                LEFT JOIN usuarios uo ON uo.id = t.usuario_id LEFT JOIN usuario_perfil po ON po.usuario_id = t.usuario_id
                LEFT JOIN clientes_fiscales cf ON cf.id = t.cliente_fiscal_id
                WHERE {where}
                ORDER BY (t.fecha_vencimiento IS NULL), t.fecha_vencimiento, t.prioridad DESC"""
        if limite is not None:
            query += " LIMIT ? OFFSET ?"
            params = params + [limite, offset]
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def obtener_tarea_outlook(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas_outlook t LEFT JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND t.usuario_id = ? AND t.papelera_en IS NULL""",
            (tarea_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def obtener_tarea_outlook_visible(usuario_id: int, tarea_id: int) -> sqlite3.Row | None:
    """Como obtener_tarea_outlook, pero también para quien la tiene ASIGNADA:
    puede verla, completarla, cambiarle el estado, marcar su checklist y
    dedicarle tiempo; y también para sus participantes (ver rol_en_tarea).
    Eliminarla o compartirla sigue siendo solo del dueño."""
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT t.*, c.nombre AS categoria_nombre, c.color AS categoria_color
               FROM tareas_outlook t LEFT JOIN categorias c ON c.id = t.categoria_id
               WHERE t.id = ? AND (t.usuario_id = ? OR t.asignada_a = ? OR t.id IN (
                         SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ?))
                 AND t.papelera_en IS NULL""",
            (tarea_id, usuario_id, usuario_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()


def obtener_tarea_outlook_por_entry_id(usuario_id: int, entry_id: str) -> sqlite3.Row | None:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tareas_outlook WHERE outlook_entry_id = ? AND usuario_id = ?", (entry_id, usuario_id)
        ).fetchone()
    finally:
        conn.close()


def upsert_tarea_outlook_por_entry_id(usuario_id: int, outlook_entry_id: str | None, **campos) -> tuple[int, bool]:
    """Crea la tarea, o actualiza la ya existente con ese `outlook_entry_id`.

    Devuelve (id, creada) — creada=True si no existía y se ha creado nueva.
    Pensado para sincronizar desde una fuente externa (.ics, .csv, o más
    adelante COM) sin duplicar tareas ya importadas en una sincronización anterior.
    """
    existente = _db.obtener_tarea_outlook_por_entry_id(usuario_id, outlook_entry_id) if outlook_entry_id else None
    if existente:
        campos_validos = {c: v for c, v in campos.items() if c in _db.CAMPOS_TAREA_OUTLOOK}
        _db.editar_tarea_outlook(usuario_id, existente["id"], **campos_validos)
        return existente["id"], False

    # crear_tarea_outlook no acepta fecha_completada como argumento de creación
    # (una tarea recién creada no puede nacer ya completada por diseño del
    # formulario normal) — si el origen externo trae una, se aplica aparte.
    fecha_completada = campos.get("fecha_completada")
    campos_creacion = {
        c: v for c, v in campos.items()
        if c in _db.CAMPOS_TAREA_OUTLOOK and c not in ("fecha_completada", "outlook_entry_id")
    }
    tid = _db.crear_tarea_outlook(usuario_id, outlook_entry_id=outlook_entry_id, **campos_creacion)
    if fecha_completada:
        _db.editar_tarea_outlook(usuario_id, tid, fecha_completada=fecha_completada)
    return tid, True


def editar_tarea_outlook(usuario_id: int, tarea_id: int, **campos) -> None:
    """Actualiza los campos indicados (cualquiera de CAMPOS_TAREA_OUTLOOK)."""
    columnas = [c for c in campos if c in _db.CAMPOS_TAREA_OUTLOOK or c in ("cliente_fiscal_id", "mensaje_correo_id")]
    if not columnas:
        return
    conn = _db.get_connection()
    try:
        # Dueño o colaborador. El proyecto y el correo enlazado son del dueño:
        # un colaborador no los cambia (sus propios proyectos no valen aquí).
        es_dueno = conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)).fetchone()
        if not es_dueno:
            if not _db._es_colaborador(conn, usuario_id, tarea_id):
                return
            columnas = [c for c in columnas if c not in ("categoria_id", "mensaje_correo_id")]
            if not columnas:
                return
        if "estimacion_min" in campos:
            campos["estimacion_min"] = _db.estimacion_valida(campos["estimacion_min"])
        if "categoria_id" in campos:
            campos["categoria_id"] = _db._categoria_id_propio(conn, usuario_id, campos["categoria_id"])
        if "cliente_fiscal_id" in campos:
            campos["cliente_fiscal_id"] = _db._cliente_fiscal_id_del_tenant(conn, usuario_id, campos["cliente_fiscal_id"])
        if "mensaje_correo_id" in campos:
            campos["mensaje_correo_id"] = _db._mensaje_correo_id_propio(conn, usuario_id, campos["mensaje_correo_id"])
        asignaciones = ", ".join(f"{c} = ?" for c in columnas)
        valores = [campos[c] for c in columnas]
        antes = conn.execute("SELECT * FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
        conn.execute(
            f"UPDATE tareas_outlook SET {asignaciones}, actualizada_en = ? WHERE id = ?",
            [*valores, _db.now_iso(), tarea_id],
        )
        conn.commit()
        cambiados = [
            _db.ETIQUETAS_CAMPO_TAREA[c] for c in columnas
            if c in _db.ETIQUETAS_CAMPO_TAREA and antes is not None and (antes[c] or None) != (campos[c] or None)
        ]
        if cambiados:
            _db.registrar_actividad_tarea(usuario_id, tarea_id, "editada", ", ".join(cambiados))
    finally:
        conn.close()


def completar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    """Completa la tarea (la puede completar su dueño o quien la tiene
    asignada) y cierra los cronómetros que siguieran en marcha sobre ella.
    No hace nada si aún espera a otras tareas (ver tarea_bloqueada)."""
    if _db.tarea_bloqueada(tarea_id):
        return
    from . import tareas_trabajo
    if tareas_trabajo.impedimento_de_cierre(tarea_id):
        return                                 # política de cierre: sin subtareas abiertas ni revisión pendiente (app/tareas_trabajo.py)
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            """UPDATE tareas_outlook
               SET estado = 'completada', porcentaje_completado = 100,
                   fecha_completada = ?, actualizada_en = ?
               WHERE id = ? AND (usuario_id = ? OR asignada_a = ? OR id IN (
                     SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))""",
            (_db.now_iso(), _db.now_iso(), tarea_id, usuario_id, usuario_id, usuario_id),
        )
        conn.commit()
        abiertos = conn.execute(
            "SELECT id, usuario_id FROM tareas WHERE tarea_outlook_id = ? AND tipo = 'duracion' "
            "AND estado IN ('en_curso', 'pausada') AND papelera_en IS NULL",
            (tarea_id,),
        ).fetchall() if cur.rowcount else []
        completada = cur.rowcount > 0
    finally:
        conn.close()
    for abierto in abiertos:
        _db.finalizar_tarea(abierto["usuario_id"], abierto["id"])
    if completada:
        _db.registrar_actividad_tarea(usuario_id, tarea_id, "completada")
        for libre in _db.tareas_desbloqueadas_por(tarea_id):
            _db.registrar_actividad_tarea(usuario_id, libre["id"], "desbloqueada", _db._asunto_tarea(tarea_id))
            _db._emitir_evento(usuario_id, "tarea.desbloqueada", {"tarea_id": libre["id"], "responsable_id": libre["responsable_id"]})
        _db._emitir_evento(usuario_id, "tarea.completada", {"tarea_id": tarea_id, "completada_por": usuario_id})


def cambiar_estado_tarea_outlook(usuario_id: int, tarea_id: int, estado: str) -> bool:
    """Cambia el estado (tablero). 'completada' pasa por completar_tarea_outlook
    (porcentaje, fecha y cronómetros); al reabrir una completada se limpia su fecha."""
    estados = ("no_iniciada", "en_progreso", "completada", "esperando", "aplazada")
    if estado not in estados or not _db.puede_trabajar_tarea(usuario_id, tarea_id):
        return False
    if estado in ("en_progreso", "completada") and _db.tarea_bloqueada(tarea_id):
        return False
    from . import tareas_trabajo
    if estado == "completada" and tareas_trabajo.impedimento_de_cierre(tarea_id):
        return False
    antes = (_db.obtener_tarea_outlook_visible(usuario_id, tarea_id) or {"estado": None})["estado"]
    if estado == "completada":
        _db.completar_tarea_outlook(usuario_id, tarea_id)
        return True
    conn = _db.get_connection()
    try:
        conn.execute(
            """UPDATE tareas_outlook SET estado = ?, fecha_completada = NULL, actualizada_en = ?,
                   porcentaje_completado = CASE WHEN estado = 'completada' THEN 0 ELSE porcentaje_completado END,
                   motivo_bloqueo = CASE WHEN ? = 'esperando' THEN motivo_bloqueo ELSE NULL END
               WHERE id = ? AND (usuario_id = ? OR asignada_a = ? OR id IN (
                     SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))""",
            (estado, _db.now_iso(), estado, tarea_id, usuario_id, usuario_id, usuario_id),
        )
        conn.commit()
    finally:
        conn.close()
    _db.registrar_actividad_tarea(usuario_id, tarea_id, "estado", estado)
    tareas_trabajo.al_cambiar_estado(usuario_id, tarea_id, antes, estado)
    return True


def _es_colaborador(conn: sqlite3.Connection, usuario_id: int, tarea_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM tareas_participantes_todos WHERE tarea_id = ? AND usuario_id = ? AND rol = 'colabora'",
        (tarea_id, usuario_id),
    ).fetchone() is not None


def rol_en_tarea(usuario_id: int, tarea_id: int) -> str | None:
    """'dueno', 'asignada', 'colabora', 'observa' o None si no la ve."""
    conn = _db.get_connection()
    try:
        t = conn.execute(
            "SELECT usuario_id, asignada_a FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)
        ).fetchone()
        if t is None:
            return None
        if t["usuario_id"] == usuario_id:
            return "dueno"
        p = conn.execute(
            "SELECT rol FROM tareas_participantes_todos WHERE tarea_id = ? AND usuario_id = ? ORDER BY rol = 'colabora' DESC",
            (tarea_id, usuario_id),
        ).fetchone()
        if p is not None:
            return p["rol"]
        return "asignada" if t["asignada_a"] == usuario_id else None
    finally:
        conn.close()


def puede_trabajar_tarea(usuario_id: int, tarea_id: int) -> bool:
    """Completar, cambiar estado, checklist y cronómetro: dueño, asignado y
    colaboradores (los observadores solo ven)."""
    return _db.rol_en_tarea(usuario_id, tarea_id) in ("dueno", "asignada", "colabora")


def puede_editar_tarea(usuario_id: int, tarea_id: int) -> bool:
    """Editar los datos de la tarea: dueño y colaboradores."""
    return _db.rol_en_tarea(usuario_id, tarea_id) in ("dueno", "colabora")


def compartir_tarea_outlook(usuario_id: int, tarea_id: int, otro_id: int, rol: str = "colabora") -> bool:
    """El dueño comparte la tarea con un compañero del mismo tenant (o cambia
    su rol). False si no es suya, el compañero no es del tenant o el rol no vale."""
    if rol not in _db.ROLES_PARTICIPANTE:
        return False
    conn = _db.get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (tarea_id, usuario_id)
        ).fetchone() is None:
            return False
        destino = _db._companero_del_tenant(conn, usuario_id, otro_id)
        if destino is None:
            return False
        conn.execute(
            """INSERT INTO tareas_participantes (tarea_id, usuario_id, rol, compartida_en) VALUES (?, ?, ?, ?)
               ON CONFLICT(tarea_id, usuario_id) DO UPDATE SET rol = excluded.rol""",
            (tarea_id, destino, rol, _db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    _db.registrar_actividad_tarea(
        usuario_id, tarea_id, "compartida", f"{_db.nombre_mostrado_usuario(destino) or destino} ({'colabora' if rol == 'colabora' else 'solo lectura'})"
    )
    _db._emitir_evento(usuario_id, "tarea.compartida", {"tarea_id": tarea_id, "con": destino, "rol": rol})
    return True


def dejar_de_compartir_tarea_outlook(usuario_id: int, tarea_id: int, otro_id: int) -> bool:
    """El dueño quita a un participante; el propio participante puede salirse."""
    conn = _db.get_connection()
    try:
        dueno = conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)).fetchone()
        if not dueno and otro_id != usuario_id:
            return False
        cur = conn.execute("DELETE FROM tareas_participantes WHERE tarea_id = ? AND usuario_id = ?", (tarea_id, otro_id))
        conn.commit()
        quitado = cur.rowcount > 0
    finally:
        conn.close()
    if quitado:
        _db.registrar_actividad_tarea(usuario_id, tarea_id, "dejo_compartir", _db.nombre_mostrado_usuario(otro_id) or str(otro_id))
    return quitado


def participantes_de_tarea(tarea_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            """SELECT p.usuario_id, p.rol, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre
               FROM tareas_participantes p JOIN usuarios u ON u.id = p.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = p.usuario_id
               WHERE p.tarea_id = ? ORDER BY nombre""",
            (tarea_id,),
        ).fetchall()
    finally:
        conn.close()


def participantes_de_tareas(tarea_ids: list[int]) -> dict[int, list[dict]]:
    """Participantes por tarea (para mostrar las insignias en lista/tablero)."""
    if not tarea_ids:
        return {}
    conn = _db.get_connection()
    try:
        marcas = ",".join("?" * len(tarea_ids))
        filas = conn.execute(
            f"""SELECT p.tarea_id, p.usuario_id, p.rol, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre
                FROM tareas_participantes p JOIN usuarios u ON u.id = p.usuario_id
                LEFT JOIN usuario_perfil pf ON pf.usuario_id = p.usuario_id
                WHERE p.tarea_id IN ({marcas}) ORDER BY nombre""",
            tarea_ids,
        ).fetchall()
    finally:
        conn.close()
    resultado: dict[int, list[dict]] = {}
    for f in filas:
        resultado.setdefault(f["tarea_id"], []).append(dict(f))
    return resultado


def personas_de_tarea(usuario_id: int, tarea_id: int) -> list[dict]:
    """Quienes ven la tarea (dueño, asignado y participantes), con su nombre y
    rol: las únicas personas a las que se puede mencionar. [] si el usuario no la ve."""
    if _db.rol_en_tarea(usuario_id, tarea_id) is None:
        return []
    conn = _db.get_connection()
    try:
        t = conn.execute("SELECT usuario_id, asignada_a FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
        ids: dict[int, str] = {t["usuario_id"]: "dueno"}
        if t["asignada_a"]:
            ids.setdefault(t["asignada_a"], "asignada")
        for p in conn.execute("SELECT usuario_id, rol FROM tareas_participantes WHERE tarea_id = ?", (tarea_id,)):
            ids.setdefault(p["usuario_id"], p["rol"])
        resultado = []
        for uid, rol in ids.items():
            f = conn.execute(
                """SELECT COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre FROM usuarios u
                   LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id WHERE u.id = ?""",
                (uid,),
            ).fetchone()
            if f:
                resultado.append({"id": uid, "nombre": f["nombre"], "rol": rol})
        return sorted(resultado, key=lambda x: x["nombre"].lower())
    finally:
        conn.close()


def detectar_menciones(texto: str, personas: list[dict], excluir_id: int | None = None) -> list[int]:
    """Ids de las personas citadas como @Nombre en el texto (el nombre completo,
    sin distinguir mayúsculas; el más largo primero para que '@Ana Ruiz' no se
    confunda con '@Ana')."""
    bajo = (texto or "").lower()
    encontradas: list[int] = []
    consumido = bajo
    for p in sorted(personas, key=lambda x: len(x["nombre"]), reverse=True):
        marca = "@" + p["nombre"].lower()
        if marca in consumido and p["id"] != excluir_id and p["id"] not in encontradas:
            encontradas.append(p["id"])
            consumido = consumido.replace(marca, " " * len(marca))
    return encontradas


def comentar_tarea_outlook(usuario_id: int, tarea_id: int, texto: str) -> dict | None:
    """Añade un comentario (lo puede hacer cualquiera que vea la tarea, también
    un observador). Devuelve {id, menciones, destinatarios} o None si no procede."""
    texto = (texto or "").strip()[:_db.COMENTARIO_MAX_CARACTERES]
    if not texto:
        return None
    personas = _db.personas_de_tarea(usuario_id, tarea_id)
    if not personas:
        return None
    menciones = _db.detectar_menciones(texto, personas, excluir_id=usuario_id)
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tarea_comentarios (tarea_id, usuario_id, texto, menciones, creado_en) VALUES (?, ?, ?, ?, ?)",
            (tarea_id, usuario_id, texto, ",".join(str(i) for i in menciones), _db.now_iso()),
        )
        conn.commit()
        nuevo = cur.lastrowid
    finally:
        conn.close()
    _db.registrar_actividad_tarea(usuario_id, tarea_id, "comentario")
    _db._emitir_evento(usuario_id, "tarea.comentada", {"tarea_id": tarea_id, "comentario_id": nuevo, "menciones": menciones})
    otros = [p["id"] for p in personas if p["id"] != usuario_id and p["id"] not in menciones]
    return {"id": nuevo, "menciones": menciones, "otros": otros}


def listar_comentarios_tarea(usuario_id: int, tarea_id: int) -> list[dict]:
    """Comentarios de la tarea (viejos primero), solo si el usuario la ve. Cada uno
    lleva `autor`, `mios` y los nombres de lo mencionado en `mencionados`."""
    personas = _db.personas_de_tarea(usuario_id, tarea_id)
    if not personas:
        return []
    nombres = {p["id"]: p["nombre"] for p in personas}
    dueno = next((p["id"] for p in personas if p["rol"] == "dueno"), None)
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT c.*, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM tarea_comentarios c JOIN usuarios u ON u.id = c.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = c.usuario_id
               WHERE c.tarea_id = ? ORDER BY c.id""",
            (tarea_id,),
        ).fetchall()
    finally:
        conn.close()
    resultado = []
    for f in filas:
        d = dict(f)
        ids = [int(i) for i in d["menciones"].split(",") if i]
        d["mencionados"] = [nombres[i] for i in ids if i in nombres]
        d["mio"] = d["usuario_id"] == usuario_id
        d["puede_borrar"] = d["mio"] or usuario_id == dueno
        resultado.append(d)
    return resultado


def eliminar_comentario_tarea(usuario_id: int, tarea_id: int, comentario_id: int) -> bool:
    """Lo borra su autor o el dueño de la tarea."""
    es_dueno = _db.rol_en_tarea(usuario_id, tarea_id) == "dueno"
    conn = _db.get_connection()
    try:
        c = conn.execute(
            "SELECT usuario_id FROM tarea_comentarios WHERE id = ? AND tarea_id = ?", (comentario_id, tarea_id)
        ).fetchone()
        if c is None or not (es_dueno or c["usuario_id"] == usuario_id) or _db.rol_en_tarea(usuario_id, tarea_id) is None:
            return False
        conn.execute("DELETE FROM tarea_comentarios WHERE id = ?", (comentario_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def contar_comentarios_tareas(tarea_ids: list[int]) -> dict[int, int]:
    if not tarea_ids:
        return {}
    conn = _db.get_connection()
    try:
        marcas = ",".join("?" * len(tarea_ids))
        return {
            f["tarea_id"]: f["n"]
            for f in conn.execute(
                f"SELECT tarea_id, COUNT(*) AS n FROM tarea_comentarios WHERE tarea_id IN ({marcas}) GROUP BY tarea_id",
                tarea_ids,
            )
        }
    finally:
        conn.close()


def parsear_items_plantilla(texto: str) -> list[dict]:
    """Una tarea por línea con el formato `asunto | días | prioridad` (días y
    prioridad son opcionales: días desde la fecha de inicio, prioridad baja/
    normal/alta). Las líneas que empiezan por `- ` son subtareas de la tarea
    anterior. Ignora líneas vacías y los valores que no se entienden."""
    items: list[dict] = []
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        if linea.startswith("- "):
            if items and linea[2:].strip():
                items[-1]["checklist"].append(" ".join(linea[2:].split())[:_db.CHECKLIST_MAX_CARACTERES])
            continue
        partes = [p.strip() for p in linea.split("|")]
        asunto = " ".join(partes[0].split())[:200]
        if not asunto:
            continue
        dias = 0
        if len(partes) > 1 and partes[1].lstrip("+-").isdigit():
            dias = max(-3650, min(3650, int(partes[1])))
        prioridad = partes[2].lower() if len(partes) > 2 and partes[2].lower() in ("baja", "normal", "alta") else "normal"
        items.append({"asunto": asunto, "dias": dias, "prioridad": prioridad, "checklist": []})
        if len(items) >= _db.PLANTILLA_MAX_ITEMS:
            break
    return items


def items_a_texto(items) -> str:
    """Inversa de parsear_items_plantilla (para volver a mostrar la plantilla al editarla)."""
    lineas = []
    for i in items:
        lineas.append(f"{i['asunto']} | {i['dias']} | {i['prioridad']}")
        lineas += [f"- {c}" for c in (i["checklist"].split("\n") if isinstance(i["checklist"], str) else i["checklist"]) if c]
    return "\n".join(lineas)


def crear_plantilla_tareas(usuario_id: int, nombre: str, descripcion: str | None, texto_items: str, compartida: bool = False) -> int | None:
    """None si no tiene nombre o no hay ninguna tarea válida."""
    nombre = " ".join((nombre or "").split())[:120]
    items = _db.parsear_items_plantilla(texto_items)
    if not nombre or not items:
        return None
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO plantillas_tareas (usuario_id, nombre, descripcion, compartida, creada_en) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, nombre, (descripcion or "").strip()[:500] or None, 1 if compartida else 0, _db.now_iso()),
        )
        plantilla_id = cur.lastrowid
        _db._guardar_items_plantilla(conn, plantilla_id, items)
        conn.commit()
        return plantilla_id
    finally:
        conn.close()


def _guardar_items_plantilla(conn: sqlite3.Connection, plantilla_id: int, items: list[dict]) -> None:
    conn.execute("DELETE FROM plantilla_tareas_items WHERE plantilla_id = ?", (plantilla_id,))
    for orden, i in enumerate(items, 1):
        conn.execute(
            "INSERT INTO plantilla_tareas_items (plantilla_id, orden, asunto, prioridad, dias, checklist) VALUES (?, ?, ?, ?, ?, ?)",
            (plantilla_id, orden, i["asunto"], i["prioridad"], i["dias"], "\n".join(i["checklist"])),
        )


def editar_plantilla_tareas(usuario_id: int, plantilla_id: int, nombre: str, descripcion: str | None, texto_items: str, compartida: bool) -> bool:
    nombre = " ".join((nombre or "").split())[:120]
    items = _db.parsear_items_plantilla(texto_items)
    if not nombre or not items:
        return False
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE plantillas_tareas SET nombre = ?, descripcion = ?, compartida = ? WHERE id = ? AND usuario_id = ?",
            (nombre, (descripcion or "").strip()[:500] or None, 1 if compartida else 0, plantilla_id, usuario_id),
        )
        if cur.rowcount == 0:
            return False
        _db._guardar_items_plantilla(conn, plantilla_id, items)
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_plantilla_tareas(usuario_id: int, plantilla_id: int) -> bool:
    conn = _db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM plantillas_tareas WHERE id = ? AND usuario_id = ?", (plantilla_id, usuario_id)).fetchone() is None:
            return False
        conn.execute("DELETE FROM plantilla_tareas_items WHERE plantilla_id = ?", (plantilla_id,))
        conn.execute("DELETE FROM plantillas_tareas WHERE id = ?", (plantilla_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def listar_plantillas_tareas(usuario_id: int) -> list[dict]:
    """Las propias y las compartidas por compañeros del mismo despacho."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT p.*, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor,
                      (SELECT COUNT(*) FROM plantilla_tareas_items i WHERE i.plantilla_id = p.id) AS n_tareas
               FROM plantillas_tareas p JOIN usuarios u ON u.id = p.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = p.usuario_id
               WHERE p.usuario_id = ? OR (p.compartida = 1 AND u.tenant_id IS NOT NULL
                     AND u.tenant_id = (SELECT tenant_id FROM usuarios WHERE id = ?))
               ORDER BY p.nombre""",
            (usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def obtener_plantilla_tareas(usuario_id: int, plantilla_id: int) -> dict | None:
    """Con sus tareas (`items`), si es del usuario o está compartida en su despacho."""
    visibles = {p["id"]: p for p in _db.listar_plantillas_tareas(usuario_id)}
    p = visibles.get(plantilla_id)
    if p is None:
        return None
    conn = _db.get_connection()
    try:
        p["items"] = [
            dict(i) for i in conn.execute(
                "SELECT asunto, prioridad, dias, checklist FROM plantilla_tareas_items WHERE plantilla_id = ? ORDER BY orden",
                (plantilla_id,),
            )
        ]
    finally:
        conn.close()
    return p


def aplicar_plantilla_tareas(
    usuario_id: int, plantilla_id: int, fecha_inicio: str, *, categoria_id: int | None = None,
    nuevo_proyecto: str | None = None, cliente_fiscal_id: int | None = None, asignada_a: int | None = None,
    encadenar: bool = False,
) -> list[int]:
    """Crea las tareas de la plantilla con vencimiento = fecha de inicio + sus días
    (YYYY-MM-DD). `nuevo_proyecto` crea (o reutiliza) un proyecto con ese nombre.
    `encadenar`: cada tarea espera a que se complete la anterior.
    Devuelve los ids de las tareas creadas ([] si la plantilla no es visible)."""
    plantilla = _db.obtener_plantilla_tareas(usuario_id, plantilla_id)
    if plantilla is None:
        return []
    try:
        base = _db.datetime.strptime(fecha_inicio[:10], "%Y-%m-%d").date()
    except ValueError:
        base = _db.datetime.now().date()
    if nuevo_proyecto and nuevo_proyecto.strip():
        categoria_id = _db.crear_categoria(usuario_id, nuevo_proyecto.strip()[:80])
    ids = []
    for item in plantilla["items"]:
        vence = (base + _db.timedelta(days=item["dias"])).strftime("%Y-%m-%dT09:00")
        tarea_id = _db.crear_tarea_outlook(
            usuario_id, item["asunto"], prioridad=item["prioridad"], fecha_inicio=base.strftime("%Y-%m-%dT09:00"),
            fecha_vencimiento=vence, categoria_id=categoria_id, cliente_fiscal_id=cliente_fiscal_id, asignada_a=asignada_a,
        )
        for texto in (item["checklist"] or "").split("\n"):
            if texto:
                _db.agregar_item_checklist(usuario_id, tarea_id, texto)
        if encadenar and ids:
            _db.anadir_dependencia_tarea(usuario_id, tarea_id, ids[-1])  # cada tarea espera a la anterior
        ids.append(tarea_id)
    return ids


# ---- Dependencias entre tareas -----------------------------------------------

def _depende_transitivamente(conn: sqlite3.Connection, tarea_id: int, objetivo_id: int) -> bool:
    """¿`tarea_id` depende (directa o indirectamente) de `objetivo_id`?"""
    visto: set[int] = set()
    pendientes = [tarea_id]
    while pendientes:
        actual = pendientes.pop()
        if actual == objetivo_id:
            return True
        if actual in visto:
            continue
        visto.add(actual)
        pendientes += [f["depende_de_id"] for f in conn.execute(
            "SELECT depende_de_id FROM tareas_dependencias WHERE tarea_id = ?", (actual,))]
    return False


def anadir_dependencia_tarea(usuario_id: int, tarea_id: int, depende_de_id: int) -> bool:
    """`tarea_id` pasa a esperar a `depende_de_id`. Hace falta poder editar la
    primera y ver la segunda; no se permiten ciclos ni auto-dependencias."""
    if tarea_id == depende_de_id or not _db.puede_editar_tarea(usuario_id, tarea_id):
        return False
    if _db.rol_en_tarea(usuario_id, depende_de_id) is None:
        return False
    conn = _db.get_connection()
    try:
        if _db._depende_transitivamente(conn, depende_de_id, tarea_id):
            return False  # crearía un ciclo
        conn.execute(
            "INSERT OR IGNORE INTO tareas_dependencias (tarea_id, depende_de_id) VALUES (?, ?)", (tarea_id, depende_de_id)
        )
        conn.commit()
    finally:
        conn.close()
    _db.registrar_actividad_tarea(usuario_id, tarea_id, "dependencia", _db._asunto_tarea(depende_de_id))
    return True


def quitar_dependencia_tarea(usuario_id: int, tarea_id: int, depende_de_id: int) -> bool:
    if not _db.puede_editar_tarea(usuario_id, tarea_id):
        return False
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM tareas_dependencias WHERE tarea_id = ? AND depende_de_id = ?", (tarea_id, depende_de_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _asunto_tarea(tarea_id: int) -> str:
    conn = _db.get_connection()
    try:
        f = conn.execute("SELECT asunto FROM tareas_outlook WHERE id = ?", (tarea_id,)).fetchone()
        return f["asunto"][:80] if f else ""
    finally:
        conn.close()


def dependencias_de_tarea(tarea_id: int) -> list[dict]:
    """De qué tareas depende (con su estado); las eliminadas no cuentan."""
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT t.id, t.asunto, t.estado FROM tareas_dependencias d JOIN tareas_outlook t ON t.id = d.depende_de_id
               WHERE d.tarea_id = ? AND t.papelera_en IS NULL ORDER BY t.id""",
            (tarea_id,),
        )]
    finally:
        conn.close()


def bloqueos_de_tareas(tarea_ids: list[int]) -> dict[int, int]:
    """{tarea_id: nº de tareas previas sin completar}, solo para las bloqueadas.

    Dos consultas simples en vez de un JOIN: el planificador de SQLite arrancaba el
    JOIN recorriendo TODAS las tareas (60-135 ms con 3.000 y la tabla vacía); así
    se parte de las dependencias, que casi siempre son pocas o ninguna."""
    if not tarea_ids:
        return {}
    conn = _db.get_connection()
    try:
        previas: dict[int, list[int]] = {}
        for inicio in range(0, len(tarea_ids), 500):
            lote = tarea_ids[inicio:inicio + 500]
            for f in conn.execute(
                f"SELECT tarea_id, depende_de_id FROM tareas_dependencias WHERE tarea_id IN ({','.join('?' * len(lote))})", lote
            ):
                previas.setdefault(f["tarea_id"], []).append(f["depende_de_id"])
        if not previas:
            return {}
        todas = sorted({d for lista in previas.values() for d in lista})
        abiertas: set[int] = set()
        for inicio in range(0, len(todas), 500):
            lote = todas[inicio:inicio + 500]
            abiertas.update(
                f["id"] for f in conn.execute(
                    f"SELECT id FROM tareas_outlook WHERE id IN ({','.join('?' * len(lote))}) AND papelera_en IS NULL AND estado != 'completada'",
                    lote,
                )
            )
        cuentas = {tid: sum(1 for d in lista if d in abiertas) for tid, lista in previas.items()}
        return {tid: n for tid, n in cuentas.items() if n}
    finally:
        conn.close()


def tarea_bloqueada(tarea_id: int) -> bool:
    return bool(_db.bloqueos_de_tareas([tarea_id]).get(tarea_id))


def tareas_desbloqueadas_por(tarea_id: int) -> list[dict]:
    """Tareas abiertas que esperaban a `tarea_id` y que ya no esperan a nadie
    (con su responsable: el asignado o, si no, el dueño)."""
    conn = _db.get_connection()
    try:
        candidatas = conn.execute(
            """SELECT t.id, t.asunto, COALESCE(t.asignada_a, t.usuario_id) AS responsable_id
               FROM tareas_dependencias d JOIN tareas_outlook t ON t.id = d.tarea_id
               WHERE d.depende_de_id = ? AND t.papelera_en IS NULL AND t.estado != 'completada'""",
            (tarea_id,),
        ).fetchall()
    finally:
        conn.close()
    pendientes = _db.bloqueos_de_tareas([c["id"] for c in candidatas])
    return [dict(c) for c in candidatas if not pendientes.get(c["id"])]


def _canales_validos(canales) -> str:
    elegidos = [c for c in _db.CANALES_RECORDATORIO if c in (canales or [])]
    return ",".join(elegidos or ["app"])


def anadir_recordatorio_tarea(usuario_id: int, tarea_id: int, avisar_en: str, canales=None) -> int | None:
    """Pone un recordatorio propio en una tarea que el usuario ve. `avisar_en`
    es una fecha y hora ISO (YYYY-MM-DDTHH:MM). None si no procede."""
    if _db.rol_en_tarea(usuario_id, tarea_id) is None:
        return None
    try:
        momento = _db.datetime.fromisoformat(avisar_en.strip().replace(" ", "T")[:19])
    except (ValueError, AttributeError):
        return None
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tarea_recordatorios (tarea_id, usuario_id, avisar_en, canales, creado_en) VALUES (?, ?, ?, ?, ?)",
            (tarea_id, usuario_id, momento.isoformat(timespec="seconds"), _db._canales_validos(canales), _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def recordatorio_relativo(usuario_id: int, tarea_id: int, clave: str, canales=None) -> int | None:
    """Atajos respecto al vencimiento: 'al_vencer', '1h_antes', '1d_antes'. None si la
    tarea no tiene vencimiento."""
    tarea = _db.obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if tarea is None or not tarea["fecha_vencimiento"]:
        return None
    try:
        vence = _db.datetime.fromisoformat(tarea["fecha_vencimiento"].replace(" ", "T")[:19])
    except ValueError:
        return None
    restas = {"al_vencer": _db.timedelta(0), "1h_antes": _db.timedelta(hours=1), "1d_antes": _db.timedelta(days=1)}
    if clave not in restas:
        return None
    return _db.anadir_recordatorio_tarea(usuario_id, tarea_id, (vence - restas[clave]).isoformat(timespec="seconds"), canales)


def listar_recordatorios_tarea(usuario_id: int, tarea_id: int) -> list[dict]:
    """Los recordatorios del propio usuario en esa tarea (si la ve)."""
    if _db.rol_en_tarea(usuario_id, tarea_id) is None:
        return []
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            "SELECT * FROM tarea_recordatorios WHERE tarea_id = ? AND usuario_id = ? ORDER BY avisar_en",
            (tarea_id, usuario_id),
        )]
    finally:
        conn.close()


def eliminar_recordatorio_tarea(usuario_id: int, recordatorio_id: int) -> bool:
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM tarea_recordatorios WHERE id = ? AND usuario_id = ?", (recordatorio_id, usuario_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def posponer_recordatorio_tarea(usuario_id: int, recordatorio_id: int, opcion: str, ahora: _db.datetime | None = None) -> bool:
    """Reprograma un recordatorio propio (vuelve a estar pendiente): '1h' (dentro de
    una hora), 'manana' (mañana a las 9:00) o '1s' (dentro de una semana, 9:00)."""
    ahora = ahora or _db.datetime.now()
    if opcion == "1h":
        nuevo = ahora + _db.timedelta(hours=1)
    elif opcion == "manana":
        nuevo = (ahora + _db.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif opcion == "1s":
        nuevo = (ahora + _db.timedelta(days=7)).replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        return False
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE tarea_recordatorios SET avisar_en = ?, enviado_en = NULL WHERE id = ? AND usuario_id = ?",
            (nuevo.isoformat(timespec="seconds"), recordatorio_id, usuario_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def recordatorios_de_tarea_pendientes_de_aviso(ahora: _db.datetime | None = None) -> list[dict]:
    """Recordatorios cuyo momento ya ha llegado y no se han enviado, de tareas que
    siguen abiertas, con los datos para avisar."""
    ahora = ahora or _db.datetime.now()
    conn = _db.get_connection()
    try:
        return [dict(f) for f in conn.execute(
            """SELECT r.id, r.tarea_id, r.usuario_id, r.avisar_en, r.canales, t.asunto, t.fecha_vencimiento,
                      u.email, tn.ntfy_topic, tn.ntfy_token
               FROM tarea_recordatorios r JOIN tareas_outlook t ON t.id = r.tarea_id
               JOIN usuarios u ON u.id = r.usuario_id LEFT JOIN tenants tn ON tn.id = u.tenant_id
               WHERE r.enviado_en IS NULL AND r.avisar_en <= ? AND t.papelera_en IS NULL AND t.estado != 'completada'
               ORDER BY r.avisar_en""",
            (ahora.isoformat(timespec="seconds"),),
        )]
    finally:
        conn.close()


def reservar_recordatorio_tarea(recordatorio_id: int) -> bool:
    """Se queda con el recordatorio de forma atómica: devuelve True solo a UNA
    de las llamadas (hilo o proceso) que lo intenten a la vez; el resto ve False
    y no lo envía, así no hay avisos duplicados aunque haya varios workers."""
    conn = _db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE tarea_recordatorios SET enviado_en = ? WHERE id = ? AND enviado_en IS NULL", (_db.now_iso(), recordatorio_id)
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def marcar_recordatorio_tarea_enviado(recordatorio_id: int) -> None:
    conn = _db.get_connection()
    try:
        conn.execute("UPDATE tarea_recordatorios SET enviado_en = ? WHERE id = ?", (_db.now_iso(), recordatorio_id))
        conn.commit()
    finally:
        conn.close()


def carga_equipo(usuario_id: int) -> list[dict]:
    """Carga de trabajo por persona sobre las tareas abiertas que el usuario ve
    (propias, asignadas a él o compartidas con él). Cada tarea cuenta para su
    responsable: el asignado o, si no hay, el dueño. Así nunca se revela nada de
    tareas privadas de otros. Ordenado por más atrasadas y más abiertas."""
    hoy = _db.datetime.now().strftime("%Y-%m-%d")
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT COALESCE(t.asignada_a, t.usuario_id) AS responsable_id,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre,
                      COUNT(*) AS abiertas,
                      SUM(CASE WHEN t.fecha_vencimiento IS NOT NULL AND substr(t.fecha_vencimiento, 1, 10) < ? THEN 1 ELSE 0 END) AS atrasadas,
                      SUM(CASE WHEN substr(t.fecha_vencimiento, 1, 10) = ? THEN 1 ELSE 0 END) AS hoy,
                      SUM(CASE WHEN t.estado = 'en_progreso' THEN 1 ELSE 0 END) AS en_progreso
               FROM tareas_outlook t
               JOIN usuarios u ON u.id = COALESCE(t.asignada_a, t.usuario_id)
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id
               WHERE t.papelera_en IS NULL AND t.estado != 'completada'
                 AND (t.usuario_id = ? OR t.asignada_a = ?
                      OR t.id IN (SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?))
               GROUP BY responsable_id ORDER BY atrasadas DESC, abiertas DESC, nombre""",
            (hoy, hoy, usuario_id, usuario_id, usuario_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def _celda_vacia() -> dict:
    return {"min": 0, "n": 0, "sin_estimar": 0, "tareas": [], "mas": 0}


def _sumar_a_celda(celda: dict, t: dict) -> None:
    celda["n"] += 1
    if t["estimacion_min"]:
        celda["min"] += t["estimacion_min"]
    else:
        celda["sin_estimar"] += 1
    if len(celda["tareas"]) < _db.TAREAS_POR_CELDA:
        celda["tareas"].append(t)
    else:
        celda["mas"] += 1


def carga_semanal(usuario_id: int, lunes: _db.date) -> dict:
    """Plan de la semana (lunes a domingo) por persona: minutos estimados de las tareas abiertas que vencen
    cada día, frente a la capacidad diaria (jornada semanal / 5 del fichaje si está, o 8 h). Aparte, las
    atrasadas y las que no tienen fecha. Cada tarea cuenta para su responsable (el asignado o, si no, el
    dueño). Solo entra lo que el usuario puede ver (suyas, asignadas, compartidas o de proyectos
    compartidos con él): nunca se revela una tarea privada de otra persona."""
    dias = [lunes + _db.timedelta(days=i) for i in range(7)]
    desde, hasta = dias[0].isoformat(), dias[-1].isoformat()
    conn = _db.get_connection()
    try:
        yo = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if yo is None:
            return {"personas": [], "dias": dias}
        personas_filas = conn.execute(
            """SELECT u.id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre, fd.jornada_semanal_horas AS jornada
               FROM usuarios u LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id LEFT JOIN fichaje_datos fd ON fd.usuario_id = u.id
               WHERE u.id = ? OR (? IS NOT NULL AND u.tenant_id = ?) ORDER BY (u.id = ?) DESC, nombre""",
            (usuario_id, yo["tenant_id"], yo["tenant_id"], usuario_id),
        ).fetchall()
        filas = conn.execute(
            """SELECT t.id, t.asunto, t.estimacion_min, t.prioridad, t.estado, substr(t.fecha_vencimiento, 1, 10) AS fecha,
                      COALESCE(t.asignada_a, t.usuario_id) AS responsable_id, t.categoria_id
               FROM tareas_outlook t
               WHERE t.papelera_en IS NULL AND t.estado != 'completada'
                 AND (t.fecha_vencimiento IS NULL OR substr(t.fecha_vencimiento, 1, 10) <= ?)
                 AND (t.usuario_id = ? OR t.asignada_a = ?
                      OR t.id IN (SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ?))
               ORDER BY t.fecha_vencimiento, CASE t.prioridad WHEN 'alta' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, t.id""",
            (hasta, usuario_id, usuario_id, usuario_id),
        ).fetchall()
    finally:
        conn.close()
    personas = {}
    for f in personas_filas:
        capacidad = round(f["jornada"] * 60 / 5) if f["jornada"] and f["jornada"] > 0 else round(_db.HORAS_DIA_DEFECTO * 60)
        personas[f["id"]] = {
            "id": f["id"], "nombre": f["nombre"], "capacidad_dia_min": capacidad, "yo": f["id"] == usuario_id,
            "dias": {d.isoformat(): _db._celda_vacia() for d in dias}, "atrasadas": _db._celda_vacia(), "sin_fecha": _db._celda_vacia(),
        }
    for f in filas:
        persona = personas.get(f["responsable_id"])
        if persona is None:
            continue
        t = dict(f)
        if not f["fecha"]:
            _db._sumar_a_celda(persona["sin_fecha"], t)
        elif f["fecha"] < desde:
            _db._sumar_a_celda(persona["atrasadas"], t)
        else:
            _db._sumar_a_celda(persona["dias"][f["fecha"]], t)
    for p in personas.values():
        p["semana_min"] = sum(c["min"] for c in p["dias"].values())
        p["capacidad_semana_min"] = p["capacidad_dia_min"] * 5
    return {"personas": list(personas.values()), "dias": dias}


def reasignar_tarea_outlook(usuario_id: int, tarea_id: int, asignada_a: int | None) -> bool:
    """Cambia quién hace la tarea: su dueño (a cualquier compañero del despacho) o, en un proyecto, quien lo
    organiza (a su dueño o a un colaborador). None la devuelve a su dueño."""
    conn = _db.get_connection()
    try:
        t = conn.execute("SELECT usuario_id, categoria_id FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        if t is None:
            return False
        if t["usuario_id"] == usuario_id:
            pass
        elif t["categoria_id"] is not None and _db._puede_organizar_proyecto(conn, usuario_id, t["categoria_id"]):
            if asignada_a is not None and asignada_a != t["usuario_id"] and _db._rol_en_proyecto(conn, asignada_a, t["categoria_id"]) != "colabora":
                return False
            conn.execute("UPDATE tareas_outlook SET asignada_a = ?, actualizada_en = ? WHERE id = ?",
                         (None if asignada_a in (None, t["usuario_id"]) else asignada_a, _db.now_iso(), tarea_id))
            conn.commit()
            destino = asignada_a if asignada_a not in (None, t["usuario_id"]) else None
            _db.registrar_actividad_tarea(usuario_id, tarea_id, "asignada", (_db.nombre_mostrado_usuario(destino) or "") if destino else "")
            if destino is not None:
                _db._emitir_evento(usuario_id, "tarea.asignada", {"tarea_id": tarea_id, "asignada_a": destino})
            return True
        else:
            return False
    finally:
        conn.close()
    return _db.asignar_tarea_outlook(usuario_id, tarea_id, asignada_a)


def filtros_vista_validos(filtros: dict) -> dict:
    """Se queda solo con los filtros conocidos y con valores razonables (lo que llega de un formulario no se guarda tal cual)."""
    estados = {"no_iniciada", "en_progreso", "completada", "esperando", "aplazada"}
    limpios = {}
    for clave in _db.FILTROS_VISTA_TAREAS:
        valor = str(filtros.get(clave) or "").strip()[:100]
        if not valor:
            continue
        if clave == "vista" and valor not in ("mias", "asignadas", "compartidas"):
            continue
        if clave == "estado" and valor not in estados:
            continue
        if clave == "prioridad" and valor not in ("baja", "normal", "alta"):
            continue
        if clave == "completadas" and valor != "1":
            continue
        limpios[clave] = valor
    return limpios


def crear_vista_tareas(usuario_id: int, nombre: str, filtros: dict, compartida: bool = False) -> int | None:
    """None si no hay nombre, no hay ningún filtro que guardar o se ha llegado al máximo. Mismo nombre = actualiza."""
    nombre = " ".join((nombre or "").split())[:60]
    limpios = _db.filtros_vista_validos(filtros)
    if not nombre or not limpios:
        return None
    conn = _db.get_connection()
    try:
        u = conn.execute("SELECT tenant_id FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if u is None:
            return None
        existente = conn.execute("SELECT id FROM tareas_vistas WHERE usuario_id = ? AND nombre = ?", (usuario_id, nombre)).fetchone()
        valores = (json.dumps(limpios, ensure_ascii=False), 1 if (compartida and u["tenant_id"] is not None) else 0)
        if existente:
            conn.execute("UPDATE tareas_vistas SET filtros = ?, compartida = ?, tenant_id = ? WHERE id = ?", (*valores, u["tenant_id"], existente["id"]))
            conn.commit()
            return existente["id"]
        if conn.execute("SELECT COUNT(*) FROM tareas_vistas WHERE usuario_id = ?", (usuario_id,)).fetchone()[0] >= _db.MAX_VISTAS_TAREAS:
            return None
        cur = conn.execute(
            "INSERT INTO tareas_vistas (usuario_id, tenant_id, nombre, filtros, compartida, creada_en) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, u["tenant_id"], nombre, *valores, _db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def listar_vistas_tareas(usuario_id: int) -> list[dict]:
    """Las del usuario y las compartidas por su despacho (con `mia` y el nombre de quien las creó)."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT v.*, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM tareas_vistas v JOIN usuarios u ON u.id = v.usuario_id LEFT JOIN usuario_perfil pf ON pf.usuario_id = v.usuario_id
               JOIN usuarios yo ON yo.id = ?
               WHERE v.usuario_id = yo.id OR (v.compartida = 1 AND v.tenant_id IS NOT NULL AND v.tenant_id = yo.tenant_id AND u.tenant_id = yo.tenant_id)
               ORDER BY (v.usuario_id = yo.id) DESC, v.nombre""",
            (usuario_id,),
        ).fetchall()
    finally:
        conn.close()
    resultado = []
    for f in filas:
        try:
            filtros = _db.filtros_vista_validos(json.loads(f["filtros"]))
        except (ValueError, TypeError):
            continue
        resultado.append({"id": f["id"], "nombre": f["nombre"], "filtros": filtros, "compartida": bool(f["compartida"]), "mia": f["usuario_id"] == usuario_id, "autor": f["autor"]})
    return resultado


def eliminar_vista_tareas(usuario_id: int, vista_id: int) -> bool:
    conn = _db.get_connection()
    try:
        cur = conn.execute("DELETE FROM tareas_vistas WHERE id = ? AND usuario_id = ?", (vista_id, usuario_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def accion_en_lote(usuario_id: int, ids: list, accion: str, valor: str | None = None) -> dict:
    """Aplica una acción a varias tareas, cada una con los permisos de siempre (dueño, colaborador, organizador del
    proyecto). Nada se da por hecho: se vuelve a leer la tarea y solo cuenta como hecha la que ha cambiado de verdad.
    Devuelve {'ok': n, 'fallos': m}."""
    if accion not in _db.ACCIONES_LOTE:
        raise ValueError("Acción en lote desconocida.")
    limpios = []
    for i in ids or []:
        try:
            n = int(i)
        except (TypeError, ValueError):
            continue
        if n not in limpios:
            limpios.append(n)
    limpios = limpios[:_db.MAX_TAREAS_LOTE]
    valor = (valor or "").strip()
    resultado = {"ok": 0, "fallos": 0}
    for tarea_id in limpios:
        antes = _db.obtener_tarea_outlook_visible(usuario_id, tarea_id)
        if antes is None:
            resultado["fallos"] += 1
            continue
        hecho = False
        try:
            if accion == "completar":
                _db.completar_tarea_outlook(usuario_id, tarea_id)
                hecho = _db.obtener_tarea_outlook_visible(usuario_id, tarea_id)["estado"] == "completada"
            elif accion == "estado":
                hecho = _db.cambiar_estado_tarea_outlook(usuario_id, tarea_id, valor)
            elif accion == "prioridad":
                if valor in ("baja", "normal", "alta") and _db.puede_editar_tarea(usuario_id, tarea_id):
                    _db.editar_tarea_outlook(usuario_id, tarea_id, prioridad=valor)
                    hecho = True
            elif accion == "fecha":
                hecho = _db.cambiar_fecha_tarea_proyecto(usuario_id, tarea_id, valor or None)
            elif accion == "asignar":
                hecho = _db.reasignar_tarea_outlook(usuario_id, tarea_id, int(valor) if valor.isdigit() else None)
            elif accion == "proyecto":
                destino = int(valor) if valor.isdigit() else None
                if antes["usuario_id"] == usuario_id:
                    _db.editar_tarea_outlook(usuario_id, tarea_id, categoria_id=destino)
                    hecho = _db.obtener_tarea_outlook_visible(usuario_id, tarea_id)["categoria_id"] == destino
            elif accion == "seccion":
                if antes["categoria_id"] is not None:
                    hecho = _db.mover_tarea_en_proyecto(usuario_id, tarea_id, int(valor) if valor.isdigit() else None, None)
        except ValueError:
            hecho = False
        resultado["ok" if hecho else "fallos"] += 1
    return resultado


def actividad_de_tarea(usuario_id: int, tarea_id: int, limite: int = 40) -> list[dict]:
    """Historial de la tarea (lo más reciente primero), solo para quien la ve."""
    if _db.rol_en_tarea(usuario_id, tarea_id) is None:
        return []
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT a.tipo, a.detalle, a.creado_en, a.usuario_id,
                      COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS autor
               FROM tarea_actividad a JOIN usuarios u ON u.id = a.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = a.usuario_id
               WHERE a.tarea_id = ? ORDER BY a.id DESC LIMIT ?""",
            (tarea_id, limite),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def tiempo_equipo_tarea(usuario_id: int, tarea_id: int) -> dict:
    """Tiempo registrado en la tarea por cada persona (cronómetros finalizados) y
    el total del equipo. Solo si el usuario la ve; {'total': 0, 'personas': []} si no."""
    vacio = {"total": 0, "personas": []}
    if _db.rol_en_tarea(usuario_id, tarea_id) is None:
        return vacio
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT t.usuario_id, COALESCE(NULLIF(pf.nombre_mostrado, ''), u.email) AS nombre,
                      COALESCE(SUM(t.duracion_segundos), 0) AS segundos
               FROM tareas t JOIN usuarios u ON u.id = t.usuario_id
               LEFT JOIN usuario_perfil pf ON pf.usuario_id = t.usuario_id
               WHERE t.tarea_outlook_id = ? AND t.estado = 'finalizada' AND t.papelera_en IS NULL
               GROUP BY t.usuario_id ORDER BY segundos DESC""",
            (tarea_id,),
        ).fetchall()
    finally:
        conn.close()
    personas = [dict(f) for f in filas if f["segundos"]]
    return {"total": sum(p["segundos"] for p in personas), "personas": personas}


def asignar_tarea_outlook(usuario_id: int, tarea_id: int, asignada_a: int | None) -> bool:
    """Asigna la tarea a un compañero del mismo despacho (o la desasigna con
    None). Solo su dueño. Devuelve False si no es suya o el compañero no es
    válido."""
    conn = _db.get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (tarea_id, usuario_id)
        ).fetchone() is None:
            return False
        destino = _db._companero_del_tenant(conn, usuario_id, asignada_a)
        if asignada_a is not None and destino is None:
            return False
        conn.execute(
            "UPDATE tareas_outlook SET asignada_a = ?, actualizada_en = ? WHERE id = ?", (destino, _db.now_iso(), tarea_id)
        )
        conn.commit()
    finally:
        conn.close()
    _db.registrar_actividad_tarea(usuario_id, tarea_id, "asignada", (_db.nombre_mostrado_usuario(destino) or "") if destino else "")
    if destino is not None:
        _db._emitir_evento(usuario_id, "tarea.asignada", {"tarea_id": tarea_id, "asignada_a": destino})
    return True


# ---- Cronómetro enlazado a una tarea de la lista ---------------------------

def iniciar_cronometro_tarea_outlook(usuario_id: int, tarea_id: int, categoria_id: int | None = None) -> int:
    """Pone en marcha un registro de tiempo (tareas) enlazado a esta tarea de
    la lista. Quien lo inicia es quien registra el tiempo. Necesita un
    proyecto: el de la tarea o el indicado."""
    tarea = _db.obtener_tarea_outlook_visible(usuario_id, tarea_id)
    if tarea is None or not _db.puede_trabajar_tarea(usuario_id, tarea_id):
        raise ValueError("La tarea no existe.")
    if _db.tarea_bloqueada(tarea_id):
        raise ValueError("Esta tarea espera a otras que todavía no están completadas.")
    conn = _db.get_connection()
    try:
        en_marcha = conn.execute(
            "SELECT 1 FROM tareas WHERE tarea_outlook_id = ? AND usuario_id = ? AND estado IN ('en_curso', 'pausada') "
            "AND papelera_en IS NULL",
            (tarea_id, usuario_id),
        ).fetchone()
    finally:
        conn.close()
    if en_marcha:
        raise ValueError("Esta tarea ya tiene el cronómetro en marcha.")
    proyecto = categoria_id or tarea["categoria_id"]
    if proyecto is None:
        raise ValueError("Elige un proyecto para registrar el tiempo de esta tarea.")
    nuevo = _db.crear_tarea(usuario_id, tarea["asunto"], proyecto, "duracion", tarea_outlook_id=tarea_id)
    _db.registrar_actividad_tarea(usuario_id, tarea_id, "cronometro")
    if tarea["estado"] == "no_iniciada":
        _db.cambiar_estado_tarea_outlook(usuario_id, tarea_id, "en_progreso")
    return nuevo


def cronometros_de_tareas_outlook(usuario_id: int, tarea_ids: list[int]) -> dict[int, dict]:
    """Por tarea de la lista: el tiempo ya registrado por este usuario
    (`total_segundos`, cronómetros finalizados) y su cronómetro en marcha o
    en pausa, si lo hay (`activo`, con el formato de tareas_activas)."""
    if not tarea_ids:
        return {}
    resultado = {i: {"total_segundos": 0, "equipo_segundos": 0, "activo": None} for i in tarea_ids}
    conn = _db.get_connection()
    try:
        marcas = ",".join("?" * len(tarea_ids))
        # Tiempo de todas las personas que han trabajado en la tarea (para compararlo con la estimación).
        for f in conn.execute(
            f"""SELECT tarea_outlook_id, COALESCE(SUM(duracion_segundos), 0) AS total FROM tareas
                WHERE estado = 'finalizada' AND papelera_en IS NULL AND tarea_outlook_id IN ({marcas})
                GROUP BY tarea_outlook_id""",
            tarea_ids,
        ):
            resultado[f["tarea_outlook_id"]]["equipo_segundos"] = f["total"]
        for f in conn.execute(
            f"""SELECT tarea_outlook_id, COALESCE(SUM(duracion_segundos), 0) AS total FROM tareas
                WHERE usuario_id = ? AND estado = 'finalizada' AND papelera_en IS NULL
                  AND tarea_outlook_id IN ({marcas}) GROUP BY tarea_outlook_id""",
            [usuario_id, *tarea_ids],
        ):
            resultado[f["tarea_outlook_id"]]["total_segundos"] = f["total"]
    finally:
        conn.close()
    for activa in _db.tareas_activas(usuario_id):
        enlace = activa.get("tarea_outlook_id")
        if enlace in resultado:
            resultado[enlace]["activo"] = activa
    return resultado


def listar_checklist(tarea_id: int) -> list[sqlite3.Row]:
    conn = _db.get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tarea_checklist WHERE tarea_outlook_id = ? ORDER BY orden, id", (tarea_id,)
        ).fetchall()
    finally:
        conn.close()


def resumen_checklist(tarea_ids: list[int]) -> dict[int, tuple[int, int]]:
    """{tarea_id: (hechas, total)} solo para las tareas que tienen items."""
    if not tarea_ids:
        return {}
    conn = _db.get_connection()
    try:
        marcas = ",".join("?" * len(tarea_ids))
        return {
            f["tarea_outlook_id"]: (f["hechas"], f["total"])
            for f in conn.execute(
                f"""SELECT tarea_outlook_id, SUM(hecha) AS hechas, COUNT(*) AS total FROM tarea_checklist
                    WHERE tarea_outlook_id IN ({marcas}) GROUP BY tarea_outlook_id""",
                tarea_ids,
            )
        }
    finally:
        conn.close()


def _recalcular_porcentaje_checklist(conn: sqlite3.Connection, tarea_id: int) -> None:
    fila = conn.execute(
        "SELECT SUM(hecha) AS hechas, COUNT(*) AS total FROM tarea_checklist WHERE tarea_outlook_id = ?", (tarea_id,)
    ).fetchone()
    if fila["total"]:
        conn.execute(
            "UPDATE tareas_outlook SET porcentaje_completado = ? WHERE id = ? AND estado != 'completada'",
            (round(100 * (fila["hechas"] or 0) / fila["total"]), tarea_id),
        )


def agregar_item_checklist(usuario_id: int, tarea_id: int, texto: str) -> int | None:
    """El dueño o un colaborador. Devuelve el id, o None si no procede."""
    texto = " ".join((texto or "").split())[:_db.CHECKLIST_MAX_CARACTERES]
    if not texto:
        return None
    conn = _db.get_connection()
    try:
        if conn.execute(
            "SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ? AND papelera_en IS NULL", (tarea_id, usuario_id)
        ).fetchone() is None and not (
            _db._es_colaborador(conn, usuario_id, tarea_id)
            and conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND papelera_en IS NULL", (tarea_id,)).fetchone()
        ):
            return None
        actuales = conn.execute("SELECT COUNT(*) AS n, COALESCE(MAX(orden), 0) AS m FROM tarea_checklist WHERE tarea_outlook_id = ?", (tarea_id,)).fetchone()
        if actuales["n"] >= _db.CHECKLIST_MAX_ITEMS:
            return None
        cur = conn.execute(
            "INSERT INTO tarea_checklist (tarea_outlook_id, texto, orden) VALUES (?, ?, ?)", (tarea_id, texto, actuales["m"] + 1)
        )
        _db._recalcular_porcentaje_checklist(conn, tarea_id)
        conn.commit()
        nuevo_item = cur.lastrowid
    finally:
        conn.close()
    _db.registrar_actividad_tarea(usuario_id, tarea_id, "subtarea_nueva", texto)
    return nuevo_item


def alternar_item_checklist(usuario_id: int, item_id: int) -> bool:
    """Marca o desmarca un item: lo puede hacer el dueño o quien tiene la tarea asignada."""
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            """SELECT i.tarea_outlook_id FROM tarea_checklist i JOIN tareas_outlook t ON t.id = i.tarea_outlook_id
               WHERE i.id = ? AND (t.usuario_id = ? OR t.asignada_a = ? OR t.id IN (
                     SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))
                 AND t.papelera_en IS NULL""",
            (item_id, usuario_id, usuario_id, usuario_id),
        ).fetchone()
        if fila is None:
            return False
        conn.execute("UPDATE tarea_checklist SET hecha = 1 - hecha WHERE id = ?", (item_id,))
        _db._recalcular_porcentaje_checklist(conn, fila["tarea_outlook_id"])
        conn.commit()
        item = conn.execute("SELECT texto, hecha FROM tarea_checklist WHERE id = ?", (item_id,)).fetchone()
        tarea_del_item = fila["tarea_outlook_id"]
    finally:
        conn.close()
    _db.registrar_actividad_tarea(usuario_id, tarea_del_item, "subtarea_hecha" if item["hecha"] else "subtarea_reabierta", item["texto"])
    return True


def eliminar_item_checklist(usuario_id: int, item_id: int) -> bool:
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            """SELECT i.tarea_outlook_id FROM tarea_checklist i JOIN tareas_outlook t ON t.id = i.tarea_outlook_id
               WHERE i.id = ? AND (t.usuario_id = ? OR t.id IN (
                     SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ? AND rol = 'colabora'))""",
            (item_id, usuario_id, usuario_id),
        ).fetchone()
        if fila is None:
            return False
        conn.execute("DELETE FROM tarea_checklist WHERE id = ?", (item_id,))
        _db._recalcular_porcentaje_checklist(conn, fila["tarea_outlook_id"])
        conn.commit()
        return True
    finally:
        conn.close()


def tareas_para_hoy(usuario_id: int) -> dict[str, list]:
    """"Mi día": lo pendiente (propio o asignado) que hay que mirar hoy.
    `vencidas` (vencimiento anterior a hoy), `hoy` (vence hoy), `en_progreso`
    (en progreso sin vencimiento hoy/anterior) y `asignadas` (asignadas a mí,
    pendientes, que no estén ya en otra sección)."""
    hoy = _db.datetime.now().strftime("%Y-%m-%d")
    vistas: set[int] = set()
    secciones: dict[str, list] = {"vencidas": [], "hoy": [], "en_progreso": [], "asignadas": [], "compartidas": []}
    conn = _db.get_connection()
    try:
        compartidas_conmigo = {f["tarea_id"] for f in conn.execute(
            "SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?", (usuario_id,))}
    finally:
        conn.close()
    for t in _db.listar_tareas_outlook(usuario_id, excluir_completadas=True, incluir_asignadas=True):
        fecha = (t["fecha_vencimiento"] or "")[:10]
        if fecha and fecha < hoy:
            secciones["vencidas"].append(t)
        elif fecha == hoy:
            secciones["hoy"].append(t)
        elif t["estado"] == "en_progreso":
            secciones["en_progreso"].append(t)
        elif t["asignada_a"] == usuario_id:
            secciones["asignadas"].append(t)
        elif t["id"] in compartidas_conmigo and t["usuario_id"] != usuario_id:
            secciones["compartidas"].append(t)  # compartidas conmigo, sin fecha ni en curso
        else:
            continue
        vistas.add(t["id"])
    return secciones


def contar_mi_dia(usuario_id: int) -> tuple[int, int]:
    """(vencidas, de hoy) de "Mi día" SIN cargar las tareas: lo pide la barra
    superior en cada página y antes traía todas las tareas abiertas (con sus
    JOINs) solo para contarlas. Mismo criterio que tareas_para_hoy."""
    hoy = _db.datetime.now().strftime("%Y-%m-%d")
    conn = _db.get_connection()
    try:
        fila = conn.execute(
            """SELECT COALESCE(SUM(substr(t.fecha_vencimiento, 1, 10) < ?), 0) AS vencidas,
                      COALESCE(SUM(substr(t.fecha_vencimiento, 1, 10) = ?), 0) AS hoy
               FROM tareas_outlook t
               WHERE t.papelera_en IS NULL AND t.estado != 'completada'
                 AND t.fecha_vencimiento IS NOT NULL AND substr(t.fecha_vencimiento, 1, 10) <= ?
                 AND (t.usuario_id = ? OR t.asignada_a = ?
                      OR t.id IN (SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?))""",
            (hoy, hoy, hoy, usuario_id, usuario_id, usuario_id),
        ).fetchone()
        return int(fila["vencidas"]), int(fila["hoy"])
    finally:
        conn.close()


def eliminar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    conn = _db.get_connection()
    try:
        marca = _db._marca_papelera()
        conn.execute("UPDATE tareas_outlook SET papelera_en = ? WHERE id = ? AND usuario_id = ?", (marca, tarea_id, usuario_id))
        conn.execute("UPDATE tareas_outlook SET papelera_en = ? WHERE tarea_padre_id = ? AND papelera_en IS NULL "
                     "AND ? IN (SELECT id FROM tareas_outlook WHERE id = ? AND usuario_id = ?)", (marca, tarea_id, tarea_id, tarea_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def restaurar_tarea_outlook(usuario_id: int, tarea_id: int) -> None:
    conn = _db.get_connection()
    try:
        marca = conn.execute("SELECT papelera_en FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)).fetchone()
        if marca and marca["papelera_en"]:       # solo las subtareas que se fueron con el padre (misma marca), no las borradas aparte
            conn.execute("UPDATE tareas_outlook SET papelera_en = NULL WHERE tarea_padre_id = ? AND papelera_en = ?", (tarea_id, marca["papelera_en"]))
        conn.execute(
            "UPDATE tareas_outlook SET papelera_en = NULL WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_tarea_outlook_definitivamente(usuario_id: int, tarea_id: int) -> None:
    conn = _db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id)).fetchone():
            for hija in conn.execute("SELECT id FROM tareas_outlook WHERE tarea_padre_id = ?", (tarea_id,)).fetchall():
                for tabla, col in (("tareas_participantes", "tarea_id"), ("tarea_comentarios", "tarea_id"), ("tarea_actividad", "tarea_id"), ("tarea_recordatorios", "tarea_id"),
                                   ("tarea_adjuntos", "tarea_id"), ("tarea_clientes", "tarea_id"), ("tarea_checklist", "tarea_outlook_id")):
                    conn.execute(f"DELETE FROM {tabla} WHERE {col} = ?", (hija["id"],))
                conn.execute("DELETE FROM tareas_dependencias WHERE tarea_id = ? OR depende_de_id = ?", (hija["id"], hija["id"]))
                conn.execute("DELETE FROM tareas_outlook WHERE id = ?", (hija["id"],))
            conn.execute("DELETE FROM tarea_adjuntos WHERE tarea_id = ?", (tarea_id,))
            conn.execute("DELETE FROM tareas_participantes WHERE tarea_id = ?", (tarea_id,))
            conn.execute("DELETE FROM tarea_comentarios WHERE tarea_id = ?", (tarea_id,))
            conn.execute("DELETE FROM tarea_actividad WHERE tarea_id = ?", (tarea_id,))
            conn.execute("DELETE FROM tareas_dependencias WHERE tarea_id = ? OR depende_de_id = ?", (tarea_id, tarea_id))
            conn.execute("DELETE FROM tarea_recordatorios WHERE tarea_id = ?", (tarea_id,))
        conn.execute("DELETE FROM tareas_outlook WHERE id = ? AND usuario_id = ?", (tarea_id, usuario_id))
        conn.commit()
    finally:
        conn.close()


def listar_categorias_outlook(usuario_id: int) -> list[str]:
    """Nombres de categoría (estilo "Categories" de Outlook) usados hasta ahora."""
    conn = _db.get_connection()
    try:
        filas = conn.execute(
            """SELECT DISTINCT categoria_outlook FROM tareas_outlook
               WHERE usuario_id = ? AND categoria_outlook IS NOT NULL AND papelera_en IS NULL
               ORDER BY categoria_outlook""",
            (usuario_id,),
        ).fetchall()
        return [f["categoria_outlook"] for f in filas]
    finally:
        conn.close()
