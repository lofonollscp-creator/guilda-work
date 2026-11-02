"""Migración 014 (rebotes de marketing y canales de envío) sobre una base que YA está en versión 13 (sin esas tablas ni las columnas de canal en los envíos): las crea, las distribuye en Citus, las aísla
por despacho y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLAS = ("marketing_rebotes", "marketing_proveedores")
COLUMNAS = ("canal", "proveedor_ref", "proveedor_estado")


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in TABLAS:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for c in COLUMNAS:
        conn.execute(f"ALTER TABLE marketing_envios DROP COLUMN IF EXISTS {c}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 13")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _columnas(conn) -> set[str]:
    return {f[0] for f in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'marketing_envios'").fetchall()} & set(COLUMNAS)


def test_la_migracion_crea_distribuye_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 14 in migraciones.pendientes(conn) and not _columnas(conn)
    migraciones.aplicar(conn)
    assert _columnas(conn) == set(COLUMNAS)
    for t in TABLAS:
        assert "tenant_id" in conn.execute(f"SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = '{t}'::regclass AND contype = 'p'").fetchone()[0], t
        assert conn.execute(f"SELECT count(*) FROM pg_policy WHERE polrelid = '{t}'::regclass").fetchone()[0] == 1, t
        if modo == "citus":
            assert conn.execute(f"SELECT count(*) FROM pg_dist_partition WHERE logicalrelid = '{t}'::regclass").fetchone()[0] == 1, t
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 14")
    conn.commit()
    assert 14 in migraciones.aplicar(conn)


def test_restricciones(base_antigua):
    modo, conn = base_antigua
    migraciones.aplicar(conn)
    conn.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (9501, 'T', '2026-01-01') ON CONFLICT DO NOTHING")
    conn.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO marketing_rebotes (tenant_id, email, tipo, origen, recibido_en) VALUES (9501, 'a@b.c', 'raro', 'dsn', '2026-01-01')")
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO marketing_proveedores (tenant_id, proveedor, clave, actualizado_en) VALUES (9501, 'otro', 'k', '2026-01-01')")
    conn.rollback()
    conn.execute("INSERT INTO marketing_proveedores (tenant_id, proveedor, clave, actualizado_en) VALUES (9501, 'brevo', 'k', '2026-01-01')")
    conn.execute("INSERT INTO marketing_rebotes (tenant_id, email, tipo, origen, recibido_en) VALUES (9501, 'a@b.c', 'duro', 'dsn', '2026-01-01')")
    conn.commit()
    conn.execute("DELETE FROM tenants WHERE id = 9501")                                               # ON DELETE CASCADE
    conn.commit()
    assert conn.execute("SELECT count(*) FROM marketing_proveedores WHERE tenant_id = 9501").fetchone()[0] == 0
