"""Migración 030 (OCR local por despacho) sobre una base que YA está en versión 29: añade la columna con su valor por defecto y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
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
    conn.execute("ALTER TABLE ia_config_despacho DROP COLUMN IF EXISTS ocr_local")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 29")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay_columna(conn) -> bool:
    return conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'ia_config_despacho' AND column_name = 'ocr_local' AND table_schema = current_schema()").fetchone() is not None


def test_la_migracion_anade_la_columna_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 30 in migraciones.pendientes(conn) and not _hay_columna(conn)
    migraciones.aplicar(conn)
    assert _hay_columna(conn)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 30")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay_columna(conn)
