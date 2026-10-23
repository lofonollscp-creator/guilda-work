"""Conexión a PostgreSQL con el comportamiento de `sqlite3` que la aplicación da por supuesto.

Lo que se reproduce (todo observable en el código actual):
  * Parámetros `?` y `:nombre`, y filas indexables por nombre y por posición (`Fila`).
  * Transacción implícita ANTES de escribir (INSERT/UPDATE/DELETE) y no antes de leer; las
    lecturas fuera de transacción van en autocommit. `commit()`/`rollback()`/`close()` igual que en SQLite.
  * Una sentencia que falla NO invalida la transacción (en PostgreSQL sí): cada escritura va
    dentro de un SAVEPOINT. `except ErrorIntegridad: pass` y seguir sigue funcionando.
  * `cursor.lastrowid` tras un INSERT (columna de identidad/serie de la tabla, con RETURNING).
  * `BEGIN IMMEDIATE` serializa a los escritores: aquí con un bloqueo asesor de transacción.
  * `close()` devuelve la conexión al pool.
  * Contexto de despacho para RLS (`fijar_despacho`): `set_config('app.tenant_id', X, true)` al
    empezar CADA transacción (SET LOCAL; decisión D8 del ADR), nunca por sesión.

`psycopg` se importa solo al abrir la primera conexión: con GUILDA_DB_ENGINE=sqlite no hace falta.
"""
import os
import threading
import weakref
from typing import Optional

from .fila import fabrica_filas
from .traduccion import NoPortable, PRAGMAS_SIN_EFECTO, preparar

_IDLE = 0                                   # psycopg.pq.TransactionStatus.IDLE
_CLAVE_BEGIN_IMMEDIATE = "guilda.begin_immediate"
_SAVEPOINT = "guilda_sp"

_SQL_AUTOGENERADA = (
    "select a.attname from pg_attribute a join pg_class c on c.oid = a.attrelid "
    "left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum "
    "where c.oid = to_regclass(%s) and a.attnum > 0 and not a.attisdropped "
    "and (a.attidentity <> '' or pg_get_expr(d.adbin, d.adrelid) like 'nextval(%%') "
    "order by a.attnum limit 1"
)
_SQL_TABLE_INFO = (
    "select (c.ordinal_position - 1) as cid, c.column_name as name, upper(c.data_type) as type, "
    "case when c.is_nullable = 'NO' then 1 else 0 end as notnull, c.column_default as dflt_value, "
    "coalesce(k.pos, 0) as pk from information_schema.columns c left join ("
    "select kcu.column_name, kcu.ordinal_position as pos from information_schema.table_constraints tc "
    "join information_schema.key_column_usage kcu on kcu.constraint_name = tc.constraint_name "
    "and kcu.table_schema = tc.table_schema and kcu.table_name = tc.table_name "
    "where tc.constraint_type = 'PRIMARY KEY' and tc.table_name = %s and tc.table_schema = current_schema()"
    ") k on k.column_name = c.column_name where c.table_name = %s and c.table_schema = current_schema() "
    "order by c.ordinal_position"
)

_autogeneradas: dict = {}                   # (base de datos, tabla) -> columna o None
_candado = threading.Lock()


def _fabrica_filas(cursor):
    descripcion = cursor.description
    if descripcion is None:
        return lambda valores: valores
    return fabrica_filas([c.name for c in descripcion])


class CursorPG:
    """Envuelve un cursor de psycopg con la interfaz de `sqlite3.Cursor` que usa la aplicación."""

    def __init__(self, cursor, lastrowid=None):
        self._c = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def fetchmany(self, n=None):
        return self._c.fetchmany(n) if n else self._c.fetchmany()

    def __iter__(self):
        return iter(self._c)

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def description(self):
        return self._c.description

    def close(self):
        self._c.close()


class _CursorVacio:
    lastrowid = None
    rowcount = 0
    description = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def fetchmany(self, n=None):
        return []

    def __iter__(self):
        return iter(())

    def close(self):
        pass


def _devolver_seguro(raw, devolver):
    try:
        if raw.info.transaction_status != _IDLE:
            raw.execute("ROLLBACK")
    except Exception:
        pass
    try:
        devolver(raw)
    except Exception:
        pass


class ConexionPG:
    def __init__(self, raw, devolver, despacho=None, savepoints=True):
        self._raw = raw
        self._savepoints = savepoints
        self._despacho = despacho
        self._cerrada = False
        self.row_factory = None                             # se acepta y se ignora: las filas ya son `Fila`
        self._final = weakref.finalize(self, _devolver_seguro, raw, devolver)

    # --- estado ------------------------------------------------------------
    @property
    def in_transaction(self) -> bool:
        return self._raw.info.transaction_status != _IDLE

    def fijar_despacho(self, tenant_id: Optional[int]) -> None:
        """Despacho activo para RLS. Se aplica con SET LOCAL al abrir cada transacción (y ya, si hay una abierta)."""
        self._despacho = None if tenant_id is None else int(tenant_id)
        if self._despacho is not None and self.in_transaction:
            self._aplicar_despacho()

    def _aplicar_despacho(self):
        if self._despacho is not None:
            self._raw.execute("select set_config('app.tenant_id', %s, true)", (str(self._despacho),))

    # --- transacciones -----------------------------------------------------
    def _abrir_transaccion(self, inmediata=False):
        if self.in_transaction:
            return
        self._raw.execute("BEGIN")
        self._aplicar_despacho()
        if inmediata:
            self._raw.execute("select pg_advisory_xact_lock(hashtext(%s))", (_CLAVE_BEGIN_IMMEDIATE,))

    def commit(self):
        if self.in_transaction:
            self._raw.execute("COMMIT")

    def rollback(self):
        if self.in_transaction:
            self._raw.execute("ROLLBACK")

    def close(self):
        if self._cerrada:
            return
        self._cerrada = True
        self._final()                                       # rollback si quedaba algo sin confirmar y vuelta al pool

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, traza):
        if tipo is None:
            self.commit()
        else:
            self.rollback()
        return False

    # --- ejecución ---------------------------------------------------------
    def execute(self, sql, params=()):
        p = preparar(sql)
        if p.pragma:
            return self._pragma(*p.pragma)
        if p.verbo == "BEGIN":
            self._abrir_transaccion(p.begin_inmediato)
            return _CursorVacio()
        if p.verbo in ("COMMIT", "END"):
            self.commit()
            return _CursorVacio()
        if p.verbo == "ROLLBACK" and " TO " not in sql.upper():
            self.rollback()
            return _CursorVacio()
        texto, args = self._argumentos(p, params)
        cur = self._raw.cursor(row_factory=_fabrica_filas)
        envoltorio = CursorPG(cur)
        if p.es_escritura:
            self._abrir_transaccion()
            columna = None if p.tiene_returning or not p.tabla_insert else self._columna_autogenerada(p.tabla_insert)
            if columna:
                texto = texto.rstrip().rstrip(";") + f'\nRETURNING "{columna}"'
            self._con_savepoint(lambda: cur.execute(texto, args))
            if columna:
                filas = cur.fetchall()
                envoltorio.lastrowid = filas[-1][0] if filas else None
        elif self._despacho is not None and not self.in_transaction:
            self._leer_con_despacho(cur, texto, args)
        else:
            cur.execute(texto, args)
        return envoltorio

    def executemany(self, sql, secuencia):
        p = preparar(sql)
        texto, _ = self._argumentos(p, ())
        lote = [tuple(x) if not isinstance(x, dict) else x for x in secuencia]
        cur = self._raw.cursor(row_factory=_fabrica_filas)
        if p.es_escritura:
            self._abrir_transaccion()
            self._con_savepoint(lambda: cur.executemany(texto, lote))
        else:
            cur.executemany(texto, lote)
        return CursorPG(cur)

    def executescript(self, script):
        self.commit()                                       # como sqlite3: confirma lo pendiente antes
        self._raw.execute(script)                           # sin parámetros psycopg admite varias sentencias
        return _CursorVacio()

    def create_function(self, *a, **k):
        raise NoPortable("create_function es de SQLite: la función debe existir como función SQL en PostgreSQL")

    # --- internos ----------------------------------------------------------
    @staticmethod
    def _argumentos(p, params):
        if p.nombrados:
            return p.sql_con_parametros, dict(params or {})
        if params is None or len(params) == 0:
            return p.sql_sin_parametros, None
        return p.sql_con_parametros, tuple(params)

    def _con_savepoint(self, accion):
        if not (self._savepoints and self.in_transaction):
            return accion()
        self._raw.execute(f"SAVEPOINT {_SAVEPOINT}")
        try:
            accion()
        except BaseException:
            try:
                self._raw.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
                self._raw.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            except Exception:
                pass
            raise
        self._raw.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")

    def _leer_con_despacho(self, cur, texto, args):
        """Lectura con despacho activo fuera de transacción: una transacción corta para poder fijar el contexto con SET LOCAL."""
        self._abrir_transaccion()
        try:
            cur.execute(texto, args)                        # el resultado ya está completo en el cliente al volver
        except BaseException:
            self.rollback()
            raise
        self._raw.execute("COMMIT")

    def _columna_autogenerada(self, tabla):
        clave = (self._raw.info.dbname, tabla)
        with _candado:
            if clave in _autogeneradas:
                return _autogeneradas[clave]
        fila = self._raw.execute(_SQL_AUTOGENERADA, (tabla,)).fetchone()
        columna = fila[0] if fila else None
        with _candado:
            _autogeneradas[clave] = columna
        return columna

    def _pragma(self, nombre, argumento):
        if nombre in PRAGMAS_SIN_EFECTO:
            return _CursorVacio()
        if nombre == "table_info":
            cur = self._raw.cursor(row_factory=_fabrica_filas)
            tabla = (argumento or "").strip().strip("\"'`")
            cur.execute(_SQL_TABLE_INFO, (tabla, tabla))
            return CursorPG(cur)
        raise NoPortable(f"PRAGMA {nombre}: sin equivalente automático en PostgreSQL (se resuelve en las fases 3 y 10)")


# --- pool -------------------------------------------------------------------
_pool = None
_url_forzada: Optional[str] = None
_candado_pool = threading.Lock()


def fijar_url(url: Optional[str]) -> None:
    """Para tests y herramientas: usa esta URL en lugar de GUILDA_DATABASE_URL (y descarta el pool actual)."""
    global _url_forzada
    _url_forzada = url
    cerrar_pool()


def _url() -> str:
    url = _url_forzada or os.environ.get("GUILDA_DATABASE_URL", "")
    if not url:
        raise RuntimeError("GUILDA_DB_ENGINE=postgres requiere GUILDA_DATABASE_URL")
    return url


def _obtener_pool():
    global _pool
    with _candado_pool:
        if _pool is None:
            from psycopg_pool import ConnectionPool
            maximo = int(os.environ.get("GUILDA_PG_POOL_MAX", "20"))
            _pool = ConnectionPool(
                _url(), min_size=1, max_size=maximo, open=True, timeout=float(os.environ.get("GUILDA_PG_POOL_ESPERA", "10")),
                kwargs={"autocommit": True, "prepare_threshold": None},    # sin sentencias preparadas: compatible con PgBouncer
                max_lifetime=1800,
            )
        return _pool


def cerrar_pool() -> None:
    global _pool
    with _candado_pool:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close()


def conectar(despacho: Optional[int] = None) -> ConexionPG:
    pool = _obtener_pool()
    raw = pool.getconn()
    return ConexionPG(raw, pool.putconn, despacho=despacho, savepoints=os.environ.get("GUILDA_PG_SAVEPOINTS", "1") != "0")
