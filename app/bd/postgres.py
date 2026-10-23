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
import re
import threading
import weakref
from typing import Optional

from .fila import fabrica_filas
from .traduccion import NoPortable, PRAGMAS_SIN_EFECTO, dividir_sentencias, preparar

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


_DDL_IDEMPOTENTE = re.compile(
    r"^\s*(CREATE\s+(UNIQUE\s+)?(TABLE|INDEX|VIRTUAL\s+TABLE|TRIGGER|VIEW)\s+IF\s+NOT\s+EXISTS|DROP\s+(TRIGGER|VIEW|INDEX)\s+IF\s+EXISTS)", re.I)


def _es_ddl_idempotente(script: str) -> bool:
    """¿Todas las sentencias del script son CREATE ... IF NOT EXISTS / DROP ... IF EXISTS? Un script con cualquier otra sentencia (INSERT, UPDATE, ALTER...) NO lo es y se ejecuta."""
    sin = re.sub(r"--[^\n]*", "", script)
    sin = re.sub(r"CREATE\s+TRIGGER\s+IF\s+NOT\s+EXISTS\s+\w+.*?\bEND\b\s*;", "CREATE TRIGGER IF NOT EXISTS t;", sin, flags=re.I | re.S)    # cuerpo del trigger fuera
    trozos = [t for t in sin.split(";") if t.strip()]
    return bool(trozos) and all(_DDL_IDEMPOTENTE.match(t) for t in trozos)


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
    def __init__(self, raw, devolver, despacho=None, savepoints=True, usuario=None):
        self._raw = raw
        self._usuario = usuario
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
            self._raw.execute("select set_config('app.tenant_id', %s, true), set_config('app.usuario_id', %s, true)", (str(self._despacho), "" if self._usuario is None else str(self._usuario)))

    # --- transacciones -----------------------------------------------------
    def _abrir_transaccion(self, inmediata=False):
        if self.in_transaction:
            return
        self._raw.execute("BEGIN")
        self._aplicar_despacho()
        if inmediata:
            self._raw.execute("select pg_advisory_xact_lock(hashtext(%s))", (_CLAVE_BEGIN_IMMEDIATE,))

    def modo_secuencial(self):
        """Citus: dentro de esta transacción los borrados/actualizaciones sobre varios shards van uno tras otro. Hace falta en operaciones largas que mezclan tablas distribuidas y de referencia
        (p. ej. borrar un despacho entero); sin él Citus las rechaza («parallel DML access…»). No hace nada si no hay Citus."""
        self._abrir_transaccion()
        if self._raw.execute("SELECT current_setting('citus.multi_shard_modify_mode', true)").fetchone()[0] is not None:
            self._raw.execute("SET LOCAL citus.multi_shard_modify_mode TO 'sequential'")

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
        """Como sqlite3. Los scripts que son solo DDL idempotente de SQLite (los `crear_esquema` de cada módulo) se ignoran: en PostgreSQL el
        esquema lo crea app/bd/esquema.py. Si falta algo, tests/test_esquema_pg.py y el generador lo delatan."""
        if _es_ddl_idempotente(script):
            return _CursorVacio()
        return self.ejecutar_script(script)

    def ejecutar_script(self, script, por_sentencias: bool = False):
        """Ejecuta el script tal cual, sin filtrar. Por defecto de una vez (una sola transacción implícita); con `por_sentencias`, una a una (Citus no admite varias
        sentencias de definición en un mismo mensaje, y la distribución de tablas no es transaccional de todos modos)."""
        self.commit()                                       # como sqlite3: confirma lo pendiente antes
        if por_sentencias:
            for sentencia in dividir_sentencias(script):
                self._raw.execute(sentencia)
        else:
            self._raw.execute(script)                       # sin parámetros psycopg admite varias sentencias
        return _CursorVacio()

    def create_function(self, *a, **k):
        raise NoPortable("create_function es de SQLite: la función debe existir como función SQL en PostgreSQL")

    # --- internos ----------------------------------------------------------
    def _argumentos(self, p, params):
        con, sin = (p.sql_con_parametros, p.sql_sin_parametros)
        if p.con_despacho is not None:                                              # Citus: la consulta lleva `tenant_id = <despacho>` y se resuelve en un solo shard
            from .citus import SENTINELA
            despacho = self._despacho if self._despacho is not None else self._despacho_de_la_fila(p, params)
            if despacho is not None:
                con, sin = (x.replace(SENTINELA, str(int(despacho))) for x in p.con_despacho)
            elif p.insert_vias is not None:
                raise RuntimeError("INSERT en una tabla de despacho sin despacho: abre la conexión con db.get_connection(despacho) o dentro de `with bd.contexto.en_despacho(...)`.")
            else:
                con, sin = p.sql_con_parametros, p.sql_sin_parametros
        if p.nombrados:
            return con, dict(params or {})
        if params is None or len(params) == 0:
            return sin, None
        return con, tuple(params)

    def _despacho_de_la_fila(self, p, params):
        """Conexión de la plataforma (trabajos en segundo plano, sin despacho): el de la persona o del padre de la fila que se inserta, según el modelo (app/bd/tenant_modelo.json)."""
        for _columna, padre, clave, numero in (p.insert_vias or ()):
            try:
                valor = params[numero - 1]
            except (TypeError, IndexError, KeyError):
                continue
            fila = self._raw.execute(f'SELECT tenant_id FROM "{padre}" WHERE "{clave}" = %s', (valor,)).fetchone()
            if fila is not None:
                return fila[0] if fila[0] is not None else 0                          # la persona sin despacho trabaja en «Plataforma»
        return None

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
# Dos pools: el de la aplicación (rol sujeto a RLS) y el de la plataforma (se salta la RLS). Si no se configura una URL propia para la plataforma, ambos usan GUILDA_DATABASE_URL
# (desarrollo y pruebas con un solo rol).
_pools: dict = {}
_url_forzada: Optional[str] = None
_url_plataforma_forzada: Optional[str] = None
_candado_pool = threading.Lock()


def activar_citus(activo: bool = True) -> None:
    """Reescribe las consultas para que Citus las reparta (app/bd/citus.py). También con GUILDA_PG_CITUS=1 al arrancar."""
    from . import citus, traduccion
    traduccion.configurar_reescritor(citus.reescribir_sqlite if activo else None, citus.reescribir_sqlite_con_despacho if activo else None,
                                     citus.reescribir_insert if activo else None)


if os.environ.get("GUILDA_PG_CITUS", "0") == "1":
    activar_citus(True)


def fijar_url(url: Optional[str], url_plataforma: Optional[str] = None) -> None:
    """Para tests y herramientas: usa estas URL en lugar de las variables de entorno (y descarta los pools actuales)."""
    global _url_forzada, _url_plataforma_forzada
    _url_forzada, _url_plataforma_forzada = url, url_plataforma
    cerrar_pool()


def _url(rol: str = "app") -> str:
    if rol == "plataforma":
        url = _url_plataforma_forzada or os.environ.get("GUILDA_DATABASE_URL_PLATAFORMA", "") or _url_forzada or os.environ.get("GUILDA_DATABASE_URL", "")
    else:
        url = _url_forzada or os.environ.get("GUILDA_DATABASE_URL", "")
    if not url:
        raise RuntimeError("GUILDA_DB_ENGINE=postgres requiere GUILDA_DATABASE_URL")
    return url


def _obtener_pool(rol: str = "app"):
    with _candado_pool:
        if rol not in _pools:
            from psycopg_pool import ConnectionPool
            maximo = int(os.environ.get("GUILDA_PG_POOL_MAX", "20"))
            _pools[rol] = ConnectionPool(
                _url(rol), min_size=1, max_size=maximo, open=True, timeout=float(os.environ.get("GUILDA_PG_POOL_ESPERA", "10")),
                kwargs={"autocommit": True, "prepare_threshold": None},    # sin sentencias preparadas: compatible con PgBouncer
                max_lifetime=1800,
            )
        return _pools[rol]


def cerrar_pool() -> None:
    with _candado_pool:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close()


def conectar(despacho: Optional[int] = None, plataforma: bool = False) -> ConexionPG:
    """Conexión como la aplicación (con `despacho`, sujeta a RLS) o como la plataforma. Sin argumentos, lo que diga el contexto (app/bd/contexto.py)."""
    from . import contexto
    if despacho is None and not plataforma:
        despacho = contexto.despacho_actual()
        plataforma = contexto.es_plataforma() or despacho is None
    elif despacho is not None:
        plataforma = False
    rol = "plataforma" if plataforma else "app"
    pool = _obtener_pool(rol)
    raw = pool.getconn()
    return ConexionPG(raw, pool.putconn, despacho=despacho, savepoints=os.environ.get("GUILDA_PG_SAVEPOINTS", "1") != "0", usuario=None if plataforma else contexto.usuario_actual())
