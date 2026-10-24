"""Comprobaciones de salud de la base de datos PostgreSQL + Citus para el panel Salud del backoffice (fase 10). Se añaden a `app/salud.py:panel()` solo cuando el motor es PostgreSQL, y los
rojos llegan por correo con el mismo vigilante (`salud.vigilar`), una vez al día por motivo.

  Conexiones · Archivo de WAL (la recuperación a un instante depende de él) · Copia base (la deja scripts/backup_postgres.sh) · Esperas de bloqueo ·
  Transacciones abiertas sin actividad · Nodos de Citus · Ranuras de replicación detenidas (retienen WAL y llenan el disco)

Hace falta un rol con `pg_monitor` (el de la plataforma lo tiene, ver app/bd/esquema_pg/mt/10_roles.sql). Los textos van en español, sin gettext: es un panel de operación.
Los umbrales son constantes para poder cambiarlos y para que los tests los acorten."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

VERDE, AMBAR, ROJO, GRIS = "verde", "ambar", "rojo", "gris"          # los mismos valores que app/salud.py
GRUPO = "Base de datos"

CONEXIONES_AMBAR_PCT = 70
CONEXIONES_ROJO_PCT = 90
WAL_PENDIENTE_AMBAR = 3                   # segmentos de WAL esperando a ser archivados
WAL_PENDIENTE_ROJO = 10
BASE_VERDE_HORAS = 36
BASE_AMBAR_DIAS = 3
BLOQUEO_AMBAR_SEG = 30
BLOQUEO_ROJO_SEG = 120
INACTIVA_AMBAR_MIN = 10
INACTIVA_ROJO_MIN = 60
RANURA_AMBAR_BYTES = 1 << 30              # WAL retenido por una ranura sin lector
RANURA_ROJO_BYTES = 5 << 30


def _item(clave: str, titulo: str, estado: str, detalle: str) -> dict:
    return {"grupo": GRUPO, "clave": clave, "titulo": titulo, "estado": estado, "detalle": detalle}


def _legible(segundos: float) -> str:
    segundos = max(0, int(segundos))
    if segundos < 120:
        return f"{segundos} s"
    if segundos < 7200:
        return f"{segundos // 60} min"
    if segundos < 172800:
        return f"{segundos // 3600} h"
    return f"{segundos // 86400} d"


def _escala(valor: float, ambar: float, rojo: float) -> str:
    return ROJO if valor >= rojo else (AMBAR if valor >= ambar else VERDE)


def _conexiones(conn) -> dict:
    usadas, maximo = conn.execute("SELECT count(*), current_setting('max_connections')::int FROM pg_stat_activity WHERE backend_type = 'client backend'").fetchone()
    pct = 100 * usadas / maximo
    return _item("pg_conexiones", "Conexiones a la base de datos", _escala(pct, CONEXIONES_AMBAR_PCT, CONEXIONES_ROJO_PCT), f"{usadas} de {maximo} ({pct:.0f} %).")


def _archivo_wal(conn) -> dict:
    titulo = "Archivo de WAL (recuperación a un instante)"
    if conn.execute("SELECT current_setting('archive_mode')").fetchone()[0] == "off":
        return _item("pg_archivo_wal", titulo, ROJO, "El archivo de WAL está desactivado: solo se podría recuperar la última copia base, no un instante concreto.")
    ultimo, ultimo_t, fallo, fallo_t, pendientes = conn.execute(
        "SELECT last_archived_wal, last_archived_time, last_failed_wal, last_failed_time, (SELECT count(*) FROM pg_ls_archive_statusdir() WHERE right(name, 6) = '.ready') FROM pg_stat_archiver").fetchone()
    if fallo_t is not None and (ultimo_t is None or fallo_t > ultimo_t):
        return _item("pg_archivo_wal", titulo, ROJO, f"El último intento de archivar {fallo} falló (hace {_legible((datetime.now(fallo_t.tzinfo) - fallo_t).total_seconds())}); {pendientes} segmento(s) esperando.")
    estado = _escala(pendientes, WAL_PENDIENTE_AMBAR, WAL_PENDIENTE_ROJO)
    if ultimo_t is None:
        return _item("pg_archivo_wal", titulo, AMBAR if estado == VERDE else estado, "Todavía no se ha archivado ningún segmento desde el último arranque.")
    return _item("pg_archivo_wal", titulo, estado, f"Último segmento archivado hace {_legible((datetime.now(ultimo_t.tzinfo) - ultimo_t).total_seconds())}; {pendientes} esperando.")


def _copia_base(ahora: datetime, ruta_estado: Path) -> dict:
    titulo = "Copia base de la base de datos"
    if not ruta_estado.exists():
        return _item("pg_copia_base", titulo, GRIS, "Todavía no se ha ejecutado scripts/backup_postgres.sh.")
    e = json.loads(ruta_estado.read_text(encoding="utf-8"))
    if not e.get("ultimo_ok"):
        return _item("pg_copia_base", titulo, ROJO, f"Ninguna copia base completada: {e.get('error') or 'sin detalle'}.")
    edad = (ahora - datetime.fromisoformat(e["ultimo_ok"])).total_seconds()
    if e.get("error") and (e.get("ultimo_error") or "") > e["ultimo_ok"]:
        return _item("pg_copia_base", titulo, ROJO, f"La última pasada falló: {e['error']} (la última buena es de hace {_legible(edad)}).")
    estado = VERDE if edad <= BASE_VERDE_HORAS * 3600 else (AMBAR if edad <= BASE_AMBAR_DIAS * 86400 else ROJO)
    return _item("pg_copia_base", titulo, estado, f"Última copia base hace {_legible(edad)} ({e.get('bases', '?')} conservadas, {e.get('tamano_bases', 0) / 1e9:.1f} GB; WAL archivado {e.get('tamano_wal', 0) / 1e9:.1f} GB).")


def _bloqueos(conn) -> list[dict]:
    espera = conn.execute("SELECT coalesce(max(extract(epoch FROM now() - state_change)), 0), count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND backend_type = 'client backend'").fetchone()
    inactiva = conn.execute("SELECT coalesce(max(extract(epoch FROM now() - state_change)), 0), count(*) FROM pg_stat_activity WHERE state IN ('idle in transaction', 'idle in transaction (aborted)') AND backend_type = 'client backend'").fetchone()
    return [
        _item("pg_bloqueos", "Esperas de bloqueo", _escala(float(espera[0]), BLOQUEO_AMBAR_SEG, BLOQUEO_ROJO_SEG),
              f"{espera[1]} sesión(es) esperando un bloqueo" + (f" (la más antigua, {_legible(float(espera[0]))})." if espera[1] else ".")),
        _item("pg_transacciones_abiertas", "Transacciones abiertas sin actividad", _escala(float(inactiva[0]) / 60, INACTIVA_AMBAR_MIN, INACTIVA_ROJO_MIN),
              f"{inactiva[1]} sesión(es)" + (f" (la más antigua, {_legible(float(inactiva[0]))})." if inactiva[1] else ".")),
    ]


def _citus(conn) -> list[dict]:
    if conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'citus'").fetchone() is None:
        return []
    total, caidos = conn.execute("SELECT count(*), count(*) FILTER (WHERE NOT isactive) FROM pg_dist_node").fetchone()
    mal = []
    try:
        mal = [f"{r[0]}→{r[2]}" for r in conn.execute("SELECT from_nodename, from_nodeport, to_nodename FROM citus_check_cluster_node_health() WHERE NOT result").fetchall()]
    except Exception:                                                                                # noqa: BLE001  (con un solo nodo la función no devuelve nada útil)
        pass
    estado = ROJO if caidos or mal else VERDE
    return [_item("pg_citus", "Nodos de Citus", estado, f"{total} nodo(s)" + (f", {caidos} inactivo(s)" if caidos else "") + (f"; sin conexión entre: {', '.join(mal[:3])}" if mal else "") + ".")]


def _ranuras(conn) -> dict:
    filas = conn.execute("SELECT slot_name, active, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) FROM pg_replication_slots WHERE restart_lsn IS NOT NULL").fetchall()
    detenidas = [(f[0], float(f[2] or 0)) for f in filas if not f[1]]
    retenido = max((r for _n, r in detenidas), default=0.0)
    estado = _escala(retenido, RANURA_AMBAR_BYTES, RANURA_ROJO_BYTES) if detenidas else VERDE
    return _item("pg_ranuras", "Ranuras de replicación", estado,
                 f"{len(filas)} ranura(s)" + (f"; sin lector: {', '.join(n for n, _r in detenidas[:3])} (retienen {retenido / 1e6:.0f} MB de WAL)" if detenidas else "") + ".")


def comprobaciones(conn, ahora: datetime | None = None, ruta_estado: Path | None = None) -> list[dict]:
    """Todos los elementos para el panel. `conn` es cualquier conexión con `.execute(sql).fetchone()/fetchall()` y rol con `pg_monitor`. Cada comprobación va aislada: si una falla, sale en gris."""
    ahora = ahora or datetime.now()
    if ruta_estado is None:
        from . import db
        ruta_estado = db.BACKUPS_DIR / "pg_estado.json"
    items: list[dict] = []
    for clave, titulo, f in (("pg_conexiones", "Conexiones a la base de datos", lambda: _conexiones(conn)), ("pg_archivo_wal", "Archivo de WAL", lambda: _archivo_wal(conn)),
                             ("pg_copia_base", "Copia base de la base de datos", lambda: _copia_base(ahora, ruta_estado)), ("pg_bloqueos", "Bloqueos", lambda: _bloqueos(conn)),
                             ("pg_citus", "Nodos de Citus", lambda: _citus(conn)), ("pg_ranuras", "Ranuras de replicación", lambda: _ranuras(conn))):
        try:
            r = f()
            items.extend(r if isinstance(r, list) else [r])
        except Exception as e:                                                                       # noqa: BLE001
            items.append(_item(clave, titulo, GRIS, f"No se pudo comprobar: {type(e).__name__}."))
    return items


def panel_items() -> list[dict]:
    """Para `salud.panel()`: abre su propia conexión de la plataforma (con pg_monitor)."""
    from . import db
    conn = db.get_connection(plataforma=True)
    try:
        return comprobaciones(conn)
    finally:
        conn.close()
