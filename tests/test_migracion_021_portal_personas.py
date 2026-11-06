"""Migración 021 (personas con acceso al portal, avisos enviados, avisos en el móvil, enlace de subida y respuestas rápidas) sobre una base que YA está en versión 20: crea las cinco tablas con su aislamiento por despacho, añade las
cuatro columnas y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLAS = ("portal_contactos", "portal_avisos_enviados", "portal_suscripciones_push", "portal_enlaces_subida", "portal_respuestas_rapidas")
COLUMNAS = (("clientes_fiscales", "portal_avisos"), ("clientes_fiscales", "portal_bienvenida_en"), ("clientes_fiscales_accesos", "email"), ("portal_recordatorios_config", "correo_facturas"))


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in TABLAS:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for t, c in COLUMNAS:
        conn.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS {c}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 20")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _hay_tabla(conn, tabla: str) -> bool:
    return conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", (tabla,)).fetchone() is not None


def _hay_columna(conn, tabla: str, columna: str) -> bool:
    return conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?", (tabla, columna)).fetchone() is not None


def test_la_migracion_crea_tablas_y_columnas_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 21 in migraciones.pendientes(conn) and not any(_hay_tabla(conn, t) for t in TABLAS) and not any(_hay_columna(conn, t, c) for t, c in COLUMNAS)
    migraciones.aplicar(conn)
    assert all(_hay_tabla(conn, t) for t in TABLAS) and all(_hay_columna(conn, t, c) for t, c in COLUMNAS)
    for t in TABLAS:
        assert "tenant_id" in conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = ?::regclass AND contype = 'p'", (t,)).fetchone()[0]
        assert conn.execute("SELECT relrowsecurity FROM pg_class WHERE relname = ?", (t,)).fetchone()[0]
        if modo == "citus":
            assert conn.execute("SELECT 1 FROM pg_dist_partition WHERE logicalrelid = ?::regclass", (t,)).fetchone() is not None
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 21")
    conn.commit()
    migraciones.aplicar(conn)
    assert all(_hay_tabla(conn, t) for t in TABLAS)
