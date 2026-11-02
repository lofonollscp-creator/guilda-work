"""Migración 016 (excepciones de módulos con motivo e historial) sobre una base que YA está en versión 15 (sin esas tablas ni columnas): las crea, las distribuye en Citus, las aísla
por despacho y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLAS = ("tenants_verticales_historial",)
COLUMNAS = ("motivo", "fijado_por", "fijado_en")


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in TABLAS:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for c in COLUMNAS:
        conn.execute(f"ALTER TABLE tenants_verticales DROP COLUMN IF EXISTS {c}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 15")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _columnas(conn) -> set[str]:
    return {f[0] for f in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'tenants_verticales'").fetchall()} & set(COLUMNAS)


def test_la_migracion_crea_distribuye_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 16 in migraciones.pendientes(conn) and not _columnas(conn)
    migraciones.aplicar(conn)
    assert _columnas(conn) == set(COLUMNAS)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 16")
    conn.commit()
    migraciones.aplicar(conn)
    for t in TABLAS:
        assert "tenant_id" in conn.execute(f"SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = '{t}'::regclass AND contype = 'p'").fetchone()[0], t
        assert conn.execute(f"SELECT count(*) FROM pg_policy WHERE polrelid = '{t}'::regclass").fetchone()[0] == 1, t
        if modo == "citus":
            assert conn.execute(f"SELECT count(*) FROM pg_dist_partition WHERE logicalrelid = '{t}'::regclass").fetchone()[0] == 1, t
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 16")
    conn.commit()
    assert 16 in migraciones.aplicar(conn)


def test_restricciones(base_antigua):
    modo, conn = base_antigua
    migraciones.aplicar(conn)
    conn.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (9601, 'T', '2026-01-01') ON CONFLICT DO NOTHING")
    conn.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO tenants_verticales_historial (tenant_id, vertical_id, accion, motivo, por, creado_en) VALUES (9601, 'abogados', 'raro', 'x', 'y', '2026-01-01')")
    conn.rollback()
    conn.execute("INSERT INTO tenants_verticales_historial (tenant_id, vertical_id, accion, motivo, por, creado_en) VALUES (9601, 'abogados', 'prueba', 'x', 'y', '2026-01-01')")
    conn.commit()
    conn.execute("DELETE FROM tenants WHERE id = 9601")                                               # ON DELETE CASCADE
    conn.commit()
    assert conn.execute("SELECT count(*) FROM tenants_verticales_historial WHERE tenant_id = 9601").fetchone()[0] == 0
