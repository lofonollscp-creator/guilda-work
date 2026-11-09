"""Migraciones 039 (contadores de salud del portal) y 040 (activarlos por despacho) sobre una base que YA está en versión 38. Necesita GUILDA_TEST_PG_URL."""
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
    conn.execute("ALTER TABLE portal_recordatorios_config DROP COLUMN IF EXISTS telemetria")
    conn.execute("DROP TABLE IF EXISTS portal_telemetria_diaria CASCADE")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 38")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay(conn) -> bool:
    col = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'portal_recordatorios_config' AND column_name = 'telemetria' AND table_schema = current_schema()").fetchone() is not None
    tabla = conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'portal_telemetria_diaria'").fetchone() is not None
    return col and tabla


def test_las_migraciones_son_repetibles_y_la_tabla_queda_aislada_por_despacho(base_antigua):
    modo, conn = base_antigua
    assert {39, 40} <= set(migraciones.pendientes(conn)) and not _hay(conn)
    migraciones.aplicar(conn)
    assert _hay(conn) and conn.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'portal_telemetria_diaria'").fetchone()[0]
    if modo == "citus":
        assert conn.execute("SELECT 1 FROM pg_dist_partition WHERE logicalrelid = 'portal_telemetria_diaria'::regclass").fetchone() is not None
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 39")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay(conn)
