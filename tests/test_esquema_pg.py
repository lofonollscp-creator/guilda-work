"""Esquema de PostgreSQL (fase 4 de la migración).

* Sin servidor: los ficheros generados de app/bd/esquema_pg/ coinciden con lo que el generador produce HOY desde el esquema de SQLite
  (si añades una tabla o columna a SQLite, ejecuta scripts/migracion/generar_esquema_pg.py y confirma los cambios).
* Con servidor (GUILDA_TEST_PG_URL, base con permiso para crear bases de datos): el esquema se crea de cero, es equivalente al de SQLite
  y los triggers portados se comportan como los de SQLite.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "migracion"))
import comparar_esquemas  # noqa: E402
import generar_esquema_pg  # noqa: E402

from app.bd import esquema  # noqa: E402


def test_los_ficheros_generados_estan_al_dia(_plantilla_bd):
    generados, _ = generar_esquema_pg.generar(_plantilla_bd)
    atrasados = [f for f, texto in generados.items() if (esquema.DIRECTORIO / f).read_text(encoding="utf-8") != texto]
    assert not atrasados, f"{atrasados} no coinciden con el esquema de SQLite: ejecuta scripts/migracion/generar_esquema_pg.py <base.db>"


URL = os.environ.get("GUILDA_TEST_PG_URL", "")
psycopg = pytest.importorskip("psycopg", reason="sin psycopg")
pytest.importorskip("psycopg_pool")
pg_real = pytest.mark.skipif(not URL, reason="sin GUILDA_TEST_PG_URL")


@pytest.fixture(scope="module")
def base_pg(_plantilla_bd, tmp_path_factory):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from app.bd import postgres as pg
    nombre = "t_esq_" + uuid.uuid4().hex[:8]
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nombre}")
    url = make_conninfo(URL, dbname=nombre)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f"ALTER DATABASE {nombre} SET timezone TO 'Europe/Madrid'")
    pg.fijar_url(url)
    conn = pg.conectar()
    creado = esquema.crear_si_falta(conn)
    conn.close()
    yield url, _plantilla_bd, creado
    pg.cerrar_pool()
    pg.fijar_url(None)
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {nombre} WITH (FORCE)")


@pg_real
def test_el_esquema_se_crea_una_sola_vez_y_equivale_al_de_sqlite(base_pg):
    from app.bd import postgres as pg
    url, sqlite_db, creado = base_pg
    assert creado
    conn = pg.conectar()
    assert esquema.crear_si_falta(conn) is False
    conn.close()
    dif = comparar_esquemas.comparar(comparar_esquemas.esquema_sqlite(sqlite_db), comparar_esquemas.esquema_postgres(url))
    assert not dif, "\n".join(dif)


@pg_real
def test_triggers_de_cambios_y_version(base_pg):
    from app.bd import postgres as pg
    conn = pg.conectar()
    try:
        uid = conn.execute("INSERT INTO usuarios (email, contrasena_hash, creado_en) VALUES ('t@t.t', 'x', 'ahora')").lastrowid
        nota = conn.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (?, 'hola', 'ahora')", (uid,)).lastrowid
        conn.execute("UPDATE notas SET papelera_en = 'hoy' WHERE id = ?", (nota,))
        conn.execute("DELETE FROM notas WHERE id = ?", (nota,))
        acciones = [f["accion"] for f in conn.execute("SELECT accion FROM api_cambios WHERE entidad = 'notas' ORDER BY id")]
        assert acciones == ["upsert", "delete", "delete"]
        t = conn.execute("INSERT INTO tareas_outlook (usuario_id, asunto, creada_en) VALUES (?, 'a', 'ahora')", (uid,)).lastrowid
        v0 = conn.execute("SELECT version FROM tareas_outlook WHERE id = ?", (t,)).fetchone()["version"]
        conn.execute("UPDATE tareas_outlook SET asunto = 'b' WHERE id = ?", (t,))
        assert conn.execute("SELECT version FROM tareas_outlook WHERE id = ?", (t,)).fetchone()["version"] == v0 + 1
        conn.commit()
    finally:
        conn.close()


@pg_real
def test_auditoria_solo_de_anexado(base_pg):
    from app import bd
    from app.bd import postgres as pg
    conn = pg.conectar()
    try:
        conn.execute("INSERT INTO auditoria_eventos (accion, entidad, creado_en) VALUES ('x', 'y', 'ahora')")
        conn.commit()
        with pytest.raises(bd.ErrorIntegridad, match="no se puede modificar"):
            conn.execute("UPDATE auditoria_eventos SET accion = 'z'")
        conn.rollback()
        with pytest.raises(bd.ErrorIntegridad, match="no se puede borrar"):
            conn.execute("DELETE FROM auditoria_eventos")
        conn.rollback()
        conn.execute("INSERT INTO auditoria_control (clave, valor) VALUES ('permitir_borrado', '1')")
        assert conn.execute("DELETE FROM auditoria_eventos").rowcount == 1
        conn.rollback()
    finally:
        conn.close()


@pg_real
def test_revision_de_tareas_y_funciones(base_pg):
    from app import bd
    from app.bd import postgres as pg
    conn = pg.conectar()
    try:
        uid = conn.execute("INSERT INTO usuarios (email, contrasena_hash, creado_en) VALUES ('r@t.t', 'x', 'ahora')").lastrowid
        t = conn.execute("INSERT INTO tareas_outlook (usuario_id, asunto, creada_en) VALUES (?, 'a', 'ahora')", (uid,)).lastrowid
        conn.commit()
        with pytest.raises(bd.ErrorIntegridad, match="solo_por_revision"):
            conn.execute("UPDATE tareas_outlook SET estado = 'en_revision' WHERE id = ?", (t,))
        conn.rollback()
        assert conn.execute("SELECT plano('María Ñandú') AS p").fetchone()["p"] == "maria nandu"
    finally:
        conn.close()


@pg_real
def test_todo_el_sql_de_la_aplicacion_es_valido_contra_el_esquema_de_postgres(base_pg):
    """PREPARE de cada sentencia completa: tablas, columnas, funciones, GROUP BY, tipos de operadores... (scripts/migracion/validar_sql_pg.py)."""
    import validar_sql_pg
    url, _, _ = base_pg
    total, fallos = validar_sql_pg.validar(url)
    assert total > 1500
    assert not fallos, f"{len(fallos)} sentencias que PostgreSQL rechaza:\n" + "\n".join(f"  {r}:{l}  {e}\n      {q}" for r, l, e, q in sorted(fallos)[:30])


@pg_real
def test_el_despacho_plataforma_existe_y_los_nuevos_nunca_toman_el_id_0(base_pg):
    from app.bd import postgres as pg
    conn = pg.conectar()
    try:
        assert conn.execute("SELECT nombre FROM tenants WHERE id = 0").fetchone()["nombre"] == "Plataforma"
        nuevo = conn.execute("INSERT INTO tenants (nombre, creado_en) VALUES ('Despacho real', 'ahora')").lastrowid
        assert nuevo >= 1
        from app.bd import esquema
        assert esquema.crear_si_falta(conn) is False                 # la semilla no se duplica ni se repite
        assert conn.execute("SELECT COUNT(*) FROM tenants WHERE id = 0").fetchone()[0] == 1
        conn.commit()
    finally:
        conn.close()
