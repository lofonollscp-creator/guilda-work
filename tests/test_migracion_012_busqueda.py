"""Migración 012 (índices trigram de la búsqueda de clientes y expedientes) sobre una base que YA está en producción (versión 11): crea los índices, `plano()` pasa a poder indexarse y repetirla no rompe nada.
Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
INDICES = {"idx_trgm_clientes_nombre", "idx_trgm_clientes_nif", "idx_trgm_clientes_email", "idx_trgm_clientes_telefono", "idx_trgm_contactos_nombre", "idx_trgm_contactos_email",
           "idx_trgm_expedientes_titulo", "idx_trgm_expedientes_referencia"}


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for i in INDICES:
        conn.execute(f"DROP INDEX IF EXISTS {i}")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 11")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _indices(conn) -> set[str]:
    return {f[0] for f in conn.execute("SELECT indexname FROM pg_indexes WHERE indexname LIKE 'idx_trgm_%'").fetchall()} & INDICES


def test_la_migracion_crea_los_indices_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 12 in migraciones.pendientes(conn) and not _indices(conn)
    migraciones.aplicar(conn)
    assert _indices(conn) == INDICES
    assert conn.execute("SELECT plano('María')").fetchone()[0] == "maria"
    conn.execute("DELETE FROM bd_esquema_version WHERE version = 12")
    conn.commit()
    migraciones.aplicar(conn)                                                                       # repetirla no falla ni duplica
    assert _indices(conn) == INDICES
