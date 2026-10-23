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

from .errores import ErrorBD, ErrorIntegridad, ErrorOperacional  # noqa: E402,F401
from .fila import Fila  # noqa: E402,F401


def es_postgres() -> bool:
    return MOTOR == "postgres"


def existe_tabla(conn, nombre: str) -> bool:
    """¿Existe la tabla (o la tabla virtual) en la base de datos de esta conexión? Sustituye a consultar `sqlite_master`."""
    if hasattr(conn, "fijar_despacho"):                    # ConexionPG: se decide por la conexión, no por el motor global (los tests mezclan los dos)
        return bool(conn.execute("SELECT to_regclass(?) IS NOT NULL AS existe", (nombre,)).fetchone()[0])
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (nombre,)).fetchone() is not None
