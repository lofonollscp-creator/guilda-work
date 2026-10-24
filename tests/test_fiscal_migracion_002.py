"""Migración 002 (Guilda Fiscal F1) sobre una base que YA está en producción (versión 1, sin las tablas fiscales): las crea, las distribuye en Citus, impone la no superposición de vigencias en la base,
y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    """Una base como la de producción antes de F1: el esquema base sin `fiscal_perfiles`/`fiscal_relaciones` y anotada en la versión 1."""
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    conn.execute("DROP TABLE IF EXISTS fiscal_relaciones")
    conn.execute("DROP TABLE IF EXISTS fiscal_perfiles")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 1")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _tablas(conn):
    return {f[0] for f in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_name IN ('fiscal_perfiles', 'fiscal_relaciones')").fetchall()}


def test_la_migracion_crea_distribuye_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert migraciones.pendientes(conn) == [2] and not _tablas(conn)
    assert migraciones.aplicar(conn) == [2]
    assert {"fiscal_perfiles", "fiscal_relaciones"} <= _tablas(conn)
    if modo == "citus":
        distribuidas = {f[0] for f in conn.execute("SELECT logicalrelid::text FROM pg_dist_partition WHERE logicalrelid::text IN ('fiscal_perfiles', 'fiscal_relaciones')").fetchall()}
        assert distribuidas == {"fiscal_perfiles", "fiscal_relaciones"}
    pk = conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'fiscal_perfiles'::regclass AND contype = 'p'").fetchone()[0]
    assert "tenant_id" in pk
    assert conn.execute("SELECT count(*) FROM pg_policy WHERE polrelid IN ('fiscal_perfiles'::regclass, 'fiscal_relaciones'::regclass)").fetchone()[0] == 2
    conn.execute("DELETE FROM bd_esquema_version WHERE version = 2")                                  # repetir: nada se rompe
    conn.commit()
    assert migraciones.aplicar(conn) == [2]


def test_la_base_impone_que_las_vigencias_de_un_titular_no_se_solapen(base_antigua):
    modo, conn = base_antigua
    migraciones.aplicar(conn)
    conn.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (9001, 'T', '2026-01-01') ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO clientes_fiscales (tenant_id, id, nombre, creado_en) VALUES (9001, 9101, 'C', '2026-01-01')")
    conn.commit()
    ins = "INSERT INTO fiscal_perfiles (tenant_id, cliente_fiscal_id, vigente_desde, vigente_hasta, forma_juridica, creado_en) VALUES (9001, 9101, ?, ?, 'sociedad', '2026-01-01')"
    conn.execute(ins, ("2026-01-01", "2026-06-30"))
    conn.execute(ins, ("2026-07-01", None))                                                           # contiguo: vale
    conn.commit()
    with pytest.raises(psycopg.errors.ExclusionViolation):
        conn.execute(ins, ("2026-06-15", "2026-07-15"))
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(ins, ("2027-05-01", "2027-04-01"))
    conn.rollback()


def test_las_claves_foraneas_impiden_apuntar_a_un_titular_de_otro_despacho(base_antigua):
    modo, conn = base_antigua
    migraciones.aplicar(conn)
    for t in (9001, 9002):
        conn.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (?, 'T', '2026-01-01') ON CONFLICT DO NOTHING", (t,))
    conn.execute("INSERT INTO clientes_fiscales (tenant_id, id, nombre, creado_en) VALUES (9001, 9101, 'C', '2026-01-01')")
    conn.commit()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO fiscal_perfiles (tenant_id, cliente_fiscal_id, vigente_desde, forma_juridica, creado_en) VALUES (9002, 9101, '2026-01-01', 'sociedad', '2026-01-01')")
    conn.rollback()
    conn.execute("INSERT INTO fiscal_perfiles (tenant_id, cliente_fiscal_id, vigente_desde, forma_juridica, creado_en) VALUES (9001, 9101, '2026-01-01', 'sociedad', '2026-01-01')")
    conn.commit()
    conn.execute("DELETE FROM clientes_fiscales WHERE tenant_id = 9001 AND id = 9101")                 # ON DELETE CASCADE
    conn.commit()
    assert conn.execute("SELECT count(*) FROM fiscal_perfiles WHERE tenant_id = 9001").fetchone()[0] == 0
