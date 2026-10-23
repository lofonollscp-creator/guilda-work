"""Capa de acceso a datos de dos motores (fase 2 de la migración a PostgreSQL).

Sin PostgreSQL ni psycopg: el traductor de SQL, `Fila` frente a `sqlite3.Row` y la lógica de
`ConexionPG` (transacción implícita, SAVEPOINT, lastrowid, BEGIN IMMEDIATE, despacho de RLS)
contra una conexión falsa que registra lo que se le envía. La prueba contra un PostgreSQL de
verdad está en test_bd_postgres_real.py (se salta si no hay servidor).
"""
import sqlite3

import pytest

from app import bd
from app.bd import postgres as pg
from app.bd.fila import fabrica_filas
from app.bd.traduccion import NoPortable, preparar


# --- traductor ---------------------------------------------------------------------------------------------------------------------------------

def test_marcadores_y_porcentajes():
    p = preparar("SELECT * FROM t WHERE a = ? AND b LIKE '%x?%' -- ¿?\n AND c = ?")
    assert p.sql_con_parametros == "SELECT * FROM t WHERE a = %s AND b LIKE '%%x?%%' -- ¿?\n AND c = %s"
    assert "%%" not in p.sql_sin_parametros and "'%x?%'" in p.sql_sin_parametros


def test_modulo_y_casts_no_se_confunden_con_marcadores():
    p = preparar("SELECT 50 % 3, a::int FROM t WHERE x = :x")
    assert p.nombrados and "%(x)s" in p.sql_con_parametros and "::int" in p.sql_con_parametros and "50 %% 3" in p.sql_con_parametros


def test_insert_or_ignore_se_traduce():
    p = preparar("INSERT OR IGNORE INTO t (a) VALUES (?)")
    assert p.sql_con_parametros == "INSERT INTO t (a) VALUES (%s) ON CONFLICT DO NOTHING"
    assert p.tabla_insert == "t" and p.es_escritura
    q = preparar("INSERT OR IGNORE INTO t (a) VALUES (?) RETURNING id")
    assert q.sql_con_parametros.endswith("ON CONFLICT DO NOTHING RETURNING id")
    assert "ON CONFLICT (a) DO UPDATE" in preparar("INSERT INTO t (a) VALUES (?) ON CONFLICT (a) DO UPDATE SET a = 1").sql_con_parametros


@pytest.mark.parametrize("sql", ["REPLACE INTO t VALUES (1)", "INSERT OR REPLACE INTO t VALUES (1)", "INSERT OR ABORT INTO t VALUES (1)", "PRAGMA integrity_check"])
def test_lo_no_portable_falla_con_claridad(sql):
    with pytest.raises(NoPortable):
        p = preparar(sql)
        # PRAGMAs reconocidos como sintaxis pero sin equivalente fallan al ejecutarse, no al preparar
        ConexionPG_falsa().execute(sql) if p.pragma else None


def test_begin_variantes():
    assert preparar("BEGIN IMMEDIATE").begin_inmediato and preparar("BEGIN IMMEDIATE").sql_con_parametros == "BEGIN"
    assert not preparar("BEGIN").begin_inmediato


# --- Fila frente a sqlite3.Row ---------------------------------------------------------------------------------------------------------------

def test_fila_se_comporta_como_sqlite3_row():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("create table t (id integer, Nombre text)")
    con.execute("insert into t values (1, 'a')")
    real = con.execute("select id, Nombre from t").fetchone()
    mia = fabrica_filas(["id", "Nombre"])((1, "a"))
    assert (mia["id"], mia["nombre"], mia["NOMBRE"], mia[0], mia[-1]) == (real["id"], real["nombre"], real["NOMBRE"], real[0], real[-1])
    assert mia.keys() == real.keys() and len(mia) == len(real)
    assert dict(mia) == dict(real) and list(mia) == list(real) and tuple(mia[0:2]) == tuple(real[0:2])
    a, b = mia
    assert (a, b) == (1, "a")
    with pytest.raises(IndexError):
        mia["no_existe"]


# --- ConexionPG con una conexión falsa -------------------------------------------------------------------------------------------------------

class _ErrorFalso(Exception):
    pass


class _Col:
    def __init__(self, name):
        self.name = name


class _Info:
    def __init__(self):
        self.transaction_status = 0
        self.dbname = "falsa"


class _CursorFalso:
    def __init__(self, raw, row_factory=None):
        self.raw, self.row_factory, self.rowcount, self.description, self._filas = raw, row_factory, 0, None, []

    def execute(self, sql, params=None):
        self.raw._ejecutar(sql, params)
        self.description, self._filas = self.raw._respuesta(sql)
        f = self.row_factory(self) if (self.row_factory and self.description) else None
        if f:
            self._filas = [f(v) for v in self._filas]
        return self

    def executemany(self, sql, lote):
        self.raw._ejecutar(sql, list(lote))
        self.rowcount = len(lote)

    def fetchone(self):
        return self._filas.pop(0) if self._filas else None

    def fetchall(self):
        filas, self._filas = self._filas, []
        return filas

    def __iter__(self):
        return iter(self.fetchall())


class _RawFalso:
    def __init__(self):
        self.info = _Info()
        self.registro = []
        self.respuestas = {}          # subcadena -> (columnas, filas)
        self.fallar_si = None
        self.devuelta = 0

    def _ejecutar(self, sql, params):
        self.registro.append(sql if params is None else (sql, params))
        s = sql.strip().upper()
        if self.fallar_si and self.fallar_si(sql):
            raise _ErrorFalso("falla")
        if s == "BEGIN":
            self.info.transaction_status = 2
        elif s in ("COMMIT", "ROLLBACK"):
            self.info.transaction_status = 0

    def _respuesta(self, sql):
        for clave, (cols, filas) in self.respuestas.items():
            if clave in sql:
                return [_Col(c) for c in cols], [tuple(f) for f in filas]
        return None, []

    def execute(self, sql, params=None):
        c = _CursorFalso(self)
        return c.execute(sql, params)

    def cursor(self, row_factory=None):
        return _CursorFalso(self, row_factory)


def ConexionPG_falsa(**kw):
    raw = _RawFalso()
    conn = pg.ConexionPG(raw, lambda r: setattr(r, "devuelta", r.devuelta + 1), **kw)
    return conn


def _sentencias(conn):
    return [x if isinstance(x, str) else x[0] for x in conn._raw.registro]


def test_lectura_fuera_de_transaccion_no_abre_transaccion():
    conn = ConexionPG_falsa()
    conn._raw.respuestas["FROM t"] = (["id", "nombre"], [(1, "a")])
    fila = conn.execute("SELECT id, nombre FROM t WHERE x = ?", (7,)).fetchone()
    assert fila["nombre"] == "a" and fila[0] == 1
    assert _sentencias(conn) == ["SELECT id, nombre FROM t WHERE x = %s"]
    assert not conn.in_transaction


def test_escritura_abre_transaccion_con_savepoint_y_devuelve_lastrowid():
    conn = ConexionPG_falsa()
    conn._raw.respuestas["pg_attribute"] = (["attname"], [("id",)])
    conn._raw.respuestas["RETURNING"] = (["id"], [(41,), (42,)])
    cur = conn.execute("INSERT INTO t (a) VALUES (?)", ("x",))
    assert cur.lastrowid == 42
    s = _sentencias(conn)
    assert s[0] == "BEGIN" and any("pg_attribute" in x for x in s)
    assert s[-3] == "SAVEPOINT guilda_sp" and s[-2].endswith('RETURNING "id"') and s[-1] == "RELEASE SAVEPOINT guilda_sp"
    assert conn.in_transaction
    conn.commit()
    assert _sentencias(conn)[-1] == "COMMIT" and not conn.in_transaction


def test_sentencia_fallida_no_invalida_la_transaccion():
    conn = ConexionPG_falsa()
    conn.execute("UPDATE t SET a = 1")
    conn._raw.fallar_si = lambda sql: sql.startswith("INSERT")
    with pytest.raises(_ErrorFalso):
        conn.execute("INSERT INTO t (a) VALUES (?)", (1,))
    s = _sentencias(conn)
    assert "ROLLBACK TO SAVEPOINT guilda_sp" in s and s[-1] == "RELEASE SAVEPOINT guilda_sp"
    assert conn.in_transaction                                  # la transacción sigue viva, como en SQLite
    conn._raw.fallar_si = None
    conn.execute("UPDATE t SET a = 2")


def test_returning_propio_no_se_duplica_y_tabla_sin_identidad_no_tiene_lastrowid():
    conn = ConexionPG_falsa()
    conn._raw.respuestas["RETURNING id"] = (["id"], [(5,)])
    cur = conn.execute("INSERT INTO t (a) VALUES (?) RETURNING id", (1,))
    assert cur.lastrowid is None and cur.fetchone()["id"] == 5
    assert sum(1 for x in _sentencias(conn) if "RETURNING" in x) == 1
    sin = ConexionPG_falsa()
    cur2 = sin.execute("INSERT INTO sin_identidad (a) VALUES (?)", (1,))    # el catálogo no devuelve columna
    assert cur2.lastrowid is None and not any(x.endswith('RETURNING "id"') for x in _sentencias(sin))


def test_begin_immediate_serializa_con_bloqueo_asesor():
    conn = ConexionPG_falsa()
    conn.execute("BEGIN IMMEDIATE")
    s = _sentencias(conn)
    assert s[0] == "BEGIN" and "pg_advisory_xact_lock" in s[1] and conn.in_transaction
    conn.execute("BEGIN IMMEDIATE")                             # dentro de una transacción no hace nada
    assert len(conn._raw.registro) == 2


def test_despacho_se_fija_con_set_local_en_cada_transaccion():
    conn = ConexionPG_falsa(despacho=7)
    conn.execute("UPDATE t SET a = 1")
    assert any("set_config('app.tenant_id', %s, true)" in x for x in _sentencias(conn))
    assert ("select set_config('app.tenant_id', %s, true)", ("7",)) in conn._raw.registro
    conn.commit()
    conn._raw.registro.clear()
    conn.execute("SELECT 1")                                    # lectura con despacho fuera de transacción: transacción corta
    assert _sentencias(conn)[0] == "BEGIN" and _sentencias(conn)[-1] == "COMMIT"


def test_close_hace_rollback_y_devuelve_al_pool_una_sola_vez():
    conn = ConexionPG_falsa()
    raw = conn._raw
    conn.execute("UPDATE t SET a = 1")
    conn.close()
    conn.close()
    assert _sentencias(conn)[-1] == "ROLLBACK" and raw.devuelta == 1 and not conn.in_transaction


def test_pragmas_inofensivos_son_noop_y_los_demas_fallan_claro():
    conn = ConexionPG_falsa()
    assert conn.execute("PRAGMA foreign_keys = ON").fetchall() == []
    assert conn._raw.registro == []
    with pytest.raises(NoPortable):
        conn.execute("PRAGMA integrity_check")
    conn._raw.respuestas["information_schema"] = (["cid", "name", "type", "notnull", "dflt_value", "pk"], [(0, "id", "BIGINT", 1, None, 1)])
    assert [f["name"] for f in conn.execute("PRAGMA table_info(tareas)")] == ["id"]
    assert conn._raw.registro[-1][1] == ("tareas", "tareas")


def test_executescript_confirma_antes_y_executemany_va_en_una_transaccion():
    conn = ConexionPG_falsa()
    conn.execute("UPDATE t SET a = 1")
    conn.executescript("CREATE TABLE x (a int); CREATE TABLE y (a int);")
    s = _sentencias(conn)
    assert "COMMIT" in s and s[-1].startswith("CREATE TABLE x")
    cur = conn.executemany("INSERT INTO t (a) VALUES (?)", [(1,), (2,), (3,)])
    assert cur.rowcount == 3 and conn.in_transaction


def test_parametros_nombrados_y_porcentajes_sin_parametros():
    conn = ConexionPG_falsa()
    conn.execute("UPDATE t SET a = :a WHERE id = :id", {"a": 1, "id": 2})
    assert conn._raw.registro[-2][1] == {"a": 1, "id": 2}
    conn.rollback()
    conn.execute("SELECT * FROM t WHERE n LIKE '%a%'")
    assert conn._raw.registro[-1] == "SELECT * FROM t WHERE n LIKE '%a%'"      # sin parámetros el % no se duplica


def test_errores_comunes_incluyen_sqlite3():
    assert sqlite3.IntegrityError in bd.ErrorIntegridad and sqlite3.OperationalError in bd.ErrorOperacional and sqlite3.Error in bd.ErrorBD


def test_motor_por_defecto_es_sqlite_y_get_connection_no_cambia():
    from app import db
    assert bd.MOTOR == "sqlite"
    conn = db.get_connection()
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


def test_executescript_ignora_solo_el_ddl_idempotente_de_sqlite():
    ddl = """
    CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT, a TEXT);
    CREATE UNIQUE INDEX IF NOT EXISTS i ON t(a);
    CREATE TRIGGER IF NOT EXISTS tr AFTER INSERT ON t BEGIN INSERT INTO x VALUES (NEW.id); END;
    DROP TRIGGER IF EXISTS viejo;
    """
    conn = ConexionPG_falsa()
    conn.executescript(ddl)
    assert conn._raw.registro == []                              # no llega nada al servidor
    conn.executescript("INSERT INTO t (a) VALUES ('semilla');")   # un script con datos SÍ se ejecuta
    conn.executescript("CREATE TABLE IF NOT EXISTS u (a int); INSERT INTO u VALUES (1);")
    conn.executescript("ALTER TABLE t ADD COLUMN b TEXT;")
    assert len(conn._raw.registro) == 3
    conn.ejecutar_script("CREATE TABLE IF NOT EXISTS t (a int);")  # sin filtrar
    assert len(conn._raw.registro) == 4
