"""Migraciones 035 (alta guiada en las plantillas) y 036 (cola de invitaciones al portal) sobre una base que YA está en versión 34: añaden lo suyo con su aislamiento por despacho y repetirlas no rompe nada. Necesita GUILDA_TEST_PG_URL."""
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
    conn.execute("ALTER TABLE plantillas_cliente DROP COLUMN IF EXISTS peticiones")
    conn.execute("ALTER TABLE plantillas_cliente DROP COLUMN IF EXISTS invitar_portal")
    conn.execute("DROP TABLE IF EXISTS portal_invitaciones_cola CASCADE")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 34")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _columnas(conn) -> bool:
    return all(conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'plantillas_cliente' AND column_name = ? AND table_schema = current_schema()", (c,)).fetchone() is not None for c in ("peticiones", "invitar_portal"))


def _tabla(conn) -> bool:
    return conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'portal_invitaciones_cola'").fetchone() is not None


def test_las_migraciones_anaden_columnas_y_tabla_y_son_repetibles(base_antigua):
    modo, conn = base_antigua
    assert {35, 36} <= set(migraciones.pendientes(conn)) and not _columnas(conn) and not _tabla(conn)
    migraciones.aplicar(conn)
    assert _columnas(conn) and _tabla(conn)
    assert conn.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'portal_invitaciones_cola'").fetchone()[0]
    if modo == "citus":
        assert conn.execute("SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_invitaciones_cola'::regclass").fetchone() is not None
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 35")
    conn.commit()
    migraciones.aplicar(conn)
    assert _columnas(conn) and _tabla(conn)
