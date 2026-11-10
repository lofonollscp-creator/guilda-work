"""Migración 050 (portal nuevo encendido por defecto) sobre una base que YA está en versión 49: los despachos con la configuración a 0 pasan a 1, las bases nuevas nacen con 1 y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
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
    conn.execute("ALTER TABLE portal_recordatorios_config ALTER COLUMN portal_nuevo SET DEFAULT 0")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 49")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _valores(conn):
    return sorted(r[0] for r in conn.execute("SELECT portal_nuevo FROM portal_recordatorios_config").fetchall())


def test_la_migracion_enciende_lo_que_estaba_a_cero_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 50 in migraciones.pendientes(conn)
    migraciones.aplicar(conn)
    assert all(v == 1 for v in _valores(conn))
    default = conn.execute("SELECT column_default FROM information_schema.columns WHERE table_name = 'portal_recordatorios_config' AND column_name = 'portal_nuevo' AND table_schema = current_schema()").fetchone()[0]
    assert str(default).strip() == "1"
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 50")
    conn.commit()
    migraciones.aplicar(conn)
    assert all(v == 1 for v in _valores(conn))
