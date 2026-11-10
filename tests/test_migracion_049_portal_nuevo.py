"""Migración 049 (interruptor del portal con la navegación nueva) sobre una base que YA está en versión 48: añade las columnas y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
COLUMNAS = (("portal_recordatorios_config", "portal_nuevo"),)


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for tabla, columna in COLUMNAS:
        conn.execute(f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS {columna}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 48")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay(conn, tabla, columna) -> bool:
    return conn.execute(f"SELECT 1 FROM information_schema.columns WHERE table_name = '{tabla}' AND column_name = '{columna}' AND table_schema = current_schema()").fetchone() is not None


def test_la_migracion_anade_las_columnas_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 49 in migraciones.pendientes(conn) and not any(_hay(conn, t, c) for t, c in COLUMNAS)
    migraciones.aplicar(conn)
    assert all(_hay(conn, t, c) for t, c in COLUMNAS)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 49")
    conn.commit()
    migraciones.aplicar(conn)
    assert all(_hay(conn, t, c) for t, c in COLUMNAS)
