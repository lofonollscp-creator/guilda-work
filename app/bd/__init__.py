"""Acceso a datos con dos motores (SQLite hoy, PostgreSQL + Citus mañana).

Plan: docs/plan-migracion-postgresql-citus.md (fase 2). El resto de la aplicación
sigue llamando a `db.get_connection()` y escribiendo SQL con `?`; esta capa decide
qué motor hay detrás y hace que el de PostgreSQL se comporte como el de SQLite en
lo que la aplicación da por supuesto (filas indexables por nombre, `lastrowid`,
transacción implícita antes de escribir, sentencia fallida que no invalida la
transacción).

    GUILDA_DB_ENGINE=sqlite|postgres        (por defecto sqlite)
    GUILDA_DATABASE_URL=postgresql://...    (solo con postgres)
"""
import os

MOTOR = os.environ.get("GUILDA_DB_ENGINE", "sqlite").strip().lower() or "sqlite"
if MOTOR not in ("sqlite", "postgres"):
    raise RuntimeError(f"GUILDA_DB_ENGINE no válido: {MOTOR!r} (sqlite o postgres)")

from . import contexto, tenant  # noqa: E402,F401
from .errores import ErrorBD, ErrorIntegridad, ErrorOperacional  # noqa: E402,F401
from .fila import Fila  # noqa: E402,F401


def es_postgres() -> bool:
    return MOTOR == "postgres"


def es_postgres(conn) -> bool:
    """¿Esta conexión es de PostgreSQL? (se decide por la conexión, no por el motor global: los tests mezclan los dos)."""
    return hasattr(conn, "fijar_despacho")


def existe_tabla(conn, nombre: str) -> bool:
    """¿Existe la tabla (o la tabla virtual) en la base de datos de esta conexión? Sustituye a consultar `sqlite_master`."""
    if es_postgres(conn):
        return bool(conn.execute("SELECT to_regclass(?) IS NOT NULL AS existe", (nombre,)).fetchone()[0])
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (nombre,)).fetchone() is not None


_TIPO_SQLITE_DE_PG = {"bigint": "INTEGER", "integer": "INTEGER", "smallint": "INTEGER", "double precision": "REAL", "real": "REAL", "numeric": "REAL", "bytea": "BLOB"}


def columnas_de_tabla(conn, tabla: str) -> list[dict]:
    """Las columnas de la tabla como las da `PRAGMA table_info` de SQLite: `[{name, type, notnull, pk}]`, con el tipo en el vocabulario de SQLite (INTEGER, REAL, TEXT, BLOB)."""
    if not es_postgres(conn):
        return [dict(f) for f in conn.execute(f"PRAGMA table_info({tabla})").fetchall()]
    claves = {f[0] for f in conn.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = to_regclass(?) AND i.indisprimary AND a.attname <> 'tenant_id'", (tabla,)).fetchall()}
    filas = conn.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ? "
                         "AND column_name <> 'tenant_id' ORDER BY ordinal_position", (tabla,)).fetchall()
    return [{"name": f[0], "type": _TIPO_SQLITE_DE_PG.get(f[1], "TEXT"), "notnull": 1 if f[2] == "NO" else 0, "pk": 1 if f[0] in claves else 0} for f in filas]
