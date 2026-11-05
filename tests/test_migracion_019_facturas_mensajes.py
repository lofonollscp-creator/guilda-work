"""Migración 019 (mensajes por factura e índice de facturas duplicadas) sobre una base que YA está en versión 18: crea la tabla del despacho con su aislamiento y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLA = "facturas_contables_mensajes"
INDICE = "idx_facturas_contables_duplicadas"


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    conn.execute(f"DROP TABLE IF EXISTS {TABLA} CASCADE")
    conn.execute(f"DROP INDEX IF EXISTS {INDICE}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 18")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay(conn, nombre: str) -> bool:
    return conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", (nombre,)).fetchone() is not None


def test_la_migracion_crea_la_tabla_con_su_aislamiento_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 19 in migraciones.pendientes(conn) and not _hay(conn, TABLA)
    migraciones.aplicar(conn)
    assert _hay(conn, TABLA)
    assert conn.execute("SELECT 1 FROM pg_indexes WHERE indexname = ?", (INDICE,)).fetchone() is not None
    assert "tenant_id" in conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = ?::regclass AND contype = 'p'", (TABLA,)).fetchone()[0]
    assert conn.execute("SELECT relrowsecurity FROM pg_class WHERE relname = ?", (TABLA,)).fetchone()[0]
    if modo == "citus":
        assert conn.execute("SELECT 1 FROM pg_dist_partition WHERE logicalrelid = ?::regclass", (TABLA,)).fetchone() is not None
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 19")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay(conn, TABLA)
