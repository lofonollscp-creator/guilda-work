"""Migración 052 (voz del despacho en la configuración de IA) sobre una base que YA está en versión 51: añade voz vacía a las existentes y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    conn.execute("ALTER TABLE ia_config_despacho DROP COLUMN IF EXISTS voz")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 51")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _columna(conn):
    return conn.execute("SELECT column_default FROM information_schema.columns WHERE table_name = 'ia_config_despacho' AND column_name = 'voz' AND table_schema = current_schema()").fetchone()


def test_la_migracion_anade_voz_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert _columna(conn) is None
    assert 52 in migraciones.pendientes(conn)
    migraciones.aplicar(conn)
    assert "''" in str(_columna(conn)[0])
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 52")
    conn.commit()
    migraciones.aplicar(conn)
    assert _columna(conn) is not None
