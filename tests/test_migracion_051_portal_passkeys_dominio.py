"""Migración 051 (dominio de cada passkey del portal) sobre una base que YA está en versión 50: añade rp_id vacío a las existentes y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
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
    conn.execute("ALTER TABLE portal_passkeys DROP COLUMN IF EXISTS rp_id")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 50")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _columna(conn):
    return conn.execute("SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_passkeys' AND column_name = 'rp_id' AND table_schema = current_schema()").fetchone()


def test_la_migracion_anade_rp_id_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert _columna(conn) is None
    assert 51 in migraciones.pendientes(conn)
    migraciones.aplicar(conn)
    assert "''" in str(_columna(conn)[0])
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 51")
    conn.commit()
    migraciones.aplicar(conn)
    assert _columna(conn) is not None
