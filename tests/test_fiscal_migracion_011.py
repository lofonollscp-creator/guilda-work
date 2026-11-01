"""Migración 011 (plantillas recurrentes de Guilda Fiscal) sobre una base que YA está en producción (versión 10, sin la tabla): la crea, la distribuye en Citus, aísla por despacho y repetirla no rompe nada.
Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    """Una base como la de producción antes de la 011: el esquema actual sin `fiscal_apuntes_recurrentes` y anotada en la versión 10."""
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    conn.execute("DROP TABLE IF EXISTS fiscal_apuntes_recurrentes")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 10")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _existe(conn) -> bool:
    return bool(conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'fiscal_apuntes_recurrentes'").fetchone()[0])


def test_la_migracion_crea_distribuye_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 11 in migraciones.pendientes(conn) and not _existe(conn)
    migraciones.aplicar(conn)
    assert _existe(conn)
    if modo == "citus":
        assert conn.execute("SELECT count(*) FROM pg_dist_partition WHERE logicalrelid = 'fiscal_apuntes_recurrentes'::regclass").fetchone()[0] == 1
    pk = conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'fiscal_apuntes_recurrentes'::regclass AND contype = 'p'").fetchone()[0]
    assert "tenant_id" in pk
    assert conn.execute("SELECT count(*) FROM pg_policy WHERE polrelid = 'fiscal_apuntes_recurrentes'::regclass").fetchone()[0] == 1
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 11")                                 # repetir: nada se rompe
    conn.commit()
    assert 11 in migraciones.aplicar(conn)


def test_claves_foraneas_y_cascada_del_titular(base_antigua):
    modo, conn = base_antigua
    migraciones.aplicar(conn)
    for t in (9001, 9002):
        conn.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (?, 'T', '2026-01-01') ON CONFLICT DO NOTHING", (t,))
    conn.execute("INSERT INTO usuarios (id, email, contrasena_hash, creado_en, tenant_id) VALUES (9301, 'rec@ejemplo.com', 'x', '2026-01-01', 9001) ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO clientes_fiscales (tenant_id, id, nombre, creado_en) VALUES (9001, 9101, 'C', '2026-01-01')")
    conn.commit()
    ins = ("INSERT INTO fiscal_apuntes_recurrentes (tenant_id, cliente_fiscal_id, nombre, datos, frecuencia, creado_por, creado_en) VALUES (?, 9101, 'N', '{}', ?, 9301, '2026-01-01')")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(ins, (9002, "mensual"))                                                         # titular de otro despacho
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(ins, (9001, "anual"))
    conn.rollback()
    conn.execute(ins, (9001, "mensual"))
    conn.commit()
    conn.execute("DELETE FROM clientes_fiscales WHERE tenant_id = 9001 AND id = 9101")               # ON DELETE CASCADE
    conn.commit()
    assert conn.execute("SELECT count(*) FROM fiscal_apuntes_recurrentes WHERE tenant_id = 9001").fetchone()[0] == 0
