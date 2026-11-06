"""Migración 020 (justificantes del banco, honorarios visibles por cliente y firma de vencimientos) sobre una base que YA está en versión 19: crea la tabla del despacho con su aislamiento, añade las dos columnas y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLA = "justificantes_pendientes"
COLUMNAS = (("clientes_fiscales", "portal_honorarios"), ("vencimientos_fiscales", "documenso_firmado_en"))


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    conn.execute(f"DROP TABLE IF EXISTS {TABLA} CASCADE")
    for t, c in COLUMNAS:
        conn.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS {c}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 19")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay_tabla(conn) -> bool:
    return conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", (TABLA,)).fetchone() is not None


def _hay_columna(conn, tabla: str, columna: str) -> bool:
    return conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?", (tabla, columna)).fetchone() is not None


def test_la_migracion_crea_tabla_y_columnas_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 20 in migraciones.pendientes(conn) and not _hay_tabla(conn) and not any(_hay_columna(conn, t, c) for t, c in COLUMNAS)
    migraciones.aplicar(conn)
    assert _hay_tabla(conn) and all(_hay_columna(conn, t, c) for t, c in COLUMNAS)
    assert "tenant_id" in conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = ?::regclass AND contype = 'p'", (TABLA,)).fetchone()[0]
    assert conn.execute("SELECT relrowsecurity FROM pg_class WHERE relname = ?", (TABLA,)).fetchone()[0]
    if modo == "citus":
        assert conn.execute("SELECT 1 FROM pg_dist_partition WHERE logicalrelid = ?::regclass", (TABLA,)).fetchone() is not None
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 20")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay_tabla(conn)
