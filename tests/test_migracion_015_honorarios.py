"""Migración 015 (honorarios por tramos, cambios en lote fiscales y recordatorios de firma) sobre una base que YA está en versión 14 (sin esas tablas ni columnas): las crea, las distribuye en Citus, las aísla
por despacho y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLAS = ("honorarios_reglas", "honorarios_aplicados", "fiscal_acciones_masivas")
COLUMNAS = ("recordado_en", "recordatorios")


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in TABLAS:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for c in COLUMNAS:
        conn.execute(f"ALTER TABLE documentos_firma DROP COLUMN IF EXISTS {c}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 14")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _columnas(conn) -> set[str]:
    return {f[0] for f in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'documentos_firma'").fetchall()} & set(COLUMNAS)


def test_la_migracion_crea_distribuye_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 15 in migraciones.pendientes(conn) and not _columnas(conn)
    migraciones.aplicar(conn)
    assert _columnas(conn) == set(COLUMNAS)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 15")
    conn.commit()
    migraciones.aplicar(conn)
    for t in TABLAS:
        assert "tenant_id" in conn.execute(f"SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = '{t}'::regclass AND contype = 'p'").fetchone()[0], t
        assert conn.execute(f"SELECT count(*) FROM pg_policy WHERE polrelid = '{t}'::regclass").fetchone()[0] == 1, t
        if modo == "citus":
            assert conn.execute(f"SELECT count(*) FROM pg_dist_partition WHERE logicalrelid = '{t}'::regclass").fetchone()[0] == 1, t
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 15")
    conn.commit()
    assert 15 in migraciones.aplicar(conn)


def test_restricciones(base_antigua):
    modo, conn = base_antigua
    migraciones.aplicar(conn)
    conn.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (9501, 'T', '2026-01-01') ON CONFLICT DO NOTHING")
    conn.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO honorarios_reglas (tenant_id, nombre, calculo, creada_en) VALUES (9501, 'x', 'raro', '2026-01-01')")
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO honorarios_aplicados (tenant_id, vencimiento_id, cliente_fiscal_id, regla_nombre, concepto, importe_centimos, estado, confirmado_en) VALUES (9501, 1, 1, 'r', 'c', 1, 'otro', '2026-01-01')")
    conn.rollback()
    conn.execute("INSERT INTO honorarios_reglas (tenant_id, nombre, calculo, creada_en) VALUES (9501, 'x', 'fijo', '2026-01-01')")
    conn.commit()
    conn.execute("DELETE FROM tenants WHERE id = 9501")                                               # ON DELETE CASCADE
    conn.commit()
    assert conn.execute("SELECT count(*) FROM honorarios_reglas WHERE tenant_id = 9501").fetchone()[0] == 0
