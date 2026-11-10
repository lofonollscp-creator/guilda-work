"""Migración 048 (compromiso con el cliente, voz, escalada y documentos periódicos del portal) sobre una base que YA está en versión 47: crea la tabla, añade las columnas y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
TABLAS = ("portal_peticiones_recurrentes",)
COLUMNAS = ("plazo_respuesta_dias", "mostrar_ausencias", "voz_cliente", "escalada_avisos")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in TABLAS:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for col in COLUMNAS:
        conn.execute(f"ALTER TABLE portal_recordatorios_config DROP COLUMN IF EXISTS {col}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 47")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay_tablas(conn) -> bool:
    columnas = all(conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'portal_recordatorios_config' AND column_name = ? AND table_schema = current_schema()", (c,)).fetchone() is not None for c in COLUMNAS)
    return columnas and all(conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", (t,)).fetchone() is not None for t in TABLAS)


def test_la_migracion_crea_las_tablas_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 48 in migraciones.pendientes(conn) and not _hay_tablas(conn)
    migraciones.aplicar(conn)
    assert _hay_tablas(conn)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 48")
    conn.commit()
    migraciones.aplicar(conn)
    assert _hay_tablas(conn)
