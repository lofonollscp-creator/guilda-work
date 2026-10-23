"""Ayudas para las pruebas contra un PostgreSQL de verdad (GUILDA_TEST_PG_URL): base de datos nueva con el esquema, y vuelta a dejarlo todo como estaba."""
import os
import uuid

URL = os.environ.get("GUILDA_TEST_PG_URL", "")


def crear_base_con_esquema() -> tuple[str, callable]:
    """Crea una base de datos con el esquema de PostgreSQL y apunta el pool de la aplicación a ella. Devuelve (url, limpiar)."""
    import psycopg
    from psycopg.conninfo import make_conninfo
    from app.bd import esquema
    from app.bd import postgres as pg
    nombre = "t_" + uuid.uuid4().hex[:10]
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nombre}")
    url = make_conninfo(URL, dbname=nombre)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f"ALTER DATABASE {nombre} SET timezone TO 'Europe/Madrid'")
    pg.fijar_url(url)
    conn = pg.conectar()
    esquema.crear_si_falta(conn)
    conn.close()

    def limpiar():
        pg.cerrar_pool()
        pg.fijar_url(None)
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {nombre} WITH (FORCE)")

    return url, limpiar
