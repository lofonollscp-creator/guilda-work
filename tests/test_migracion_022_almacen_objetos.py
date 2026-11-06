"""Migración 022 (registro del almacén de objetos) sobre una base que YA está en versión 21: crea la tabla con su aislamiento por despacho y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLA = "objetos_almacenados"


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    conn.execute(f"DROP TABLE IF EXISTS {TABLA} CASCADE")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 21")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay_tabla(conn) -> bool:
    return conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", (TABLA,)).fetchone() is not None


def test_la_migracion_crea_la_tabla_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 22 in migraciones.pendientes(conn) and not _hay_tabla(conn)
    migraciones.aplicar(conn)
    assert _hay_tabla(conn)
    assert "tenant_id" in conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = ?::regclass AND contype = 'p'", (TABLA,)).fetchone()[0]
    assert conn.execute("SELECT relrowsecurity FROM pg_class WHERE relname = ?", (TABLA,)).fetchone()[0]
    if modo == "citus":
        assert conn.execute("SELECT 1 FROM pg_dist_partition WHERE logicalrelid = ?::regclass", (TABLA,)).fetchone() is not None
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 22")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay_tabla(conn)
