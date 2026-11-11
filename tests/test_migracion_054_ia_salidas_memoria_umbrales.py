"""Migración 054 (contador de salidas de datos a la IA, memoria del cliente, umbrales de alertas y latencia/fallos por proveedor) sobre una base que YA está en versión 53: crea las tablas, añade las columnas y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
TABLAS = ("ia_salidas_datos", "cliente_memoria")
COLUMNAS = (("ia_config_despacho", "umbrales"), ("ia_uso_proveedor", "errores"), ("ia_uso_proveedor", "ms_total"))
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in TABLAS:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for tabla, col in COLUMNAS:
        conn.execute(f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS {col}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 53")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay_tablas(conn) -> bool:
    tablas = all(conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", (t,)).fetchone() is not None for t in TABLAS)
    columnas = all(conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ? AND table_schema = current_schema()", (t, c)).fetchone() is not None for t, c in COLUMNAS)
    return tablas and columnas


def test_la_migracion_crea_las_tablas_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 54 in migraciones.pendientes(conn) and not _hay_tablas(conn)
    migraciones.aplicar(conn)
    assert _hay_tablas(conn)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 54")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay_tablas(conn)
