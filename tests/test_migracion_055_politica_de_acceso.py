"""Migración 055 (política de acceso del despacho: exigir segundo factor o passkey) sobre una base que YA está en versión 54: añade las dos columnas con la política desactivada y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
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
    conn.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS exigir_segundo_factor")
    conn.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS segundo_factor_limite")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 54")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _columna(conn):
    return conn.execute("SELECT column_default FROM information_schema.columns WHERE table_name = 'tenants' AND column_name = 'exigir_segundo_factor' AND table_schema = current_schema()").fetchone()


def test_la_migracion_anade_exigir_segundo_factor_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert _columna(conn) is None
    assert 55 in migraciones.pendientes(conn)
    migraciones.aplicar(conn)
    assert "0" in str(_columna(conn)[0])
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 55")
    conn.commit()
    migraciones.aplicar(conn)
    assert _columna(conn) is not None
