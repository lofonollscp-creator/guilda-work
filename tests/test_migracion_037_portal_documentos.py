"""Migración 037 (documentos del portal) sobre una base que YA está en versión 36: añade la columna con su valor por defecto y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
COLUMNAS = ("portal_visible", "portal_carpeta", "portal_origen", "portal_vence", "portal_texto")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for c in COLUMNAS:
        conn.execute(f"ALTER TABLE cliente_documentos DROP COLUMN IF EXISTS {c}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 36")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay_columna(conn) -> bool:
    return all(conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'cliente_documentos' AND column_name = ? AND table_schema = current_schema()", (c,)).fetchone() is not None for c in COLUMNAS)


def test_la_migracion_anade_la_columna_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 37 in migraciones.pendientes(conn) and not _hay_columna(conn)
    migraciones.aplicar(conn)
    assert _hay_columna(conn)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 37")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay_columna(conn)
