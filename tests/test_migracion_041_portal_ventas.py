"""Migración 041 (mis ventas del portal) sobre una base que YA está en versión 40: añade la columna con su valor por defecto y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
COLUMNAS = ("ventas_portal", "facturascripts_idempresa", "facturascripts_serie")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for c in COLUMNAS:
        conn.execute(f"ALTER TABLE clientes_fiscales DROP COLUMN IF EXISTS {c}")
    conn.execute("DROP TABLE IF EXISTS portal_ventas_facturas CASCADE")
    conn.execute("DROP TABLE IF EXISTS portal_ventas_clientes CASCADE")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 40")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay_columna(conn) -> bool:
    cols = all(conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'clientes_fiscales' AND column_name = ? AND table_schema = current_schema()", (c,)).fetchone() is not None for c in COLUMNAS)
    tablas = all(conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", (t,)).fetchone() is not None for t in ("portal_ventas_facturas", "portal_ventas_clientes"))
    return cols and tablas


def test_la_migracion_anade_la_columna_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 41 in migraciones.pendientes(conn) and not _hay_columna(conn)
    migraciones.aplicar(conn)
    assert _hay_columna(conn)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 41")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay_columna(conn)
