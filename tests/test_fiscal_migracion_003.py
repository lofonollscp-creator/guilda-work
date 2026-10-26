"""Migración 003 (núcleo de Guilda Fiscal) sobre una base que YA está en producción (versión 2, con F1 pero sin el núcleo): crea las cinco tablas, las distribuye en Citus, instala los triggers de
inmutabilidad y es repetible. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLAS = ("fiscal_apuntes", "fiscal_instantaneas", "fiscal_declaraciones", "fiscal_casillas", "fiscal_artefactos")


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in ("fiscal_artefactos", "fiscal_casillas", "fiscal_declaraciones", "fiscal_apuntes", "fiscal_instantaneas"):
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 2")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _tablas(conn):
    return {f[0] for f in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_name IN ('fiscal_apuntes','fiscal_instantaneas','fiscal_declaraciones','fiscal_casillas','fiscal_artefactos')").fetchall()}


def test_la_migracion_crea_distribuye_instala_triggers_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert migraciones.pendientes(conn) == [3] and not _tablas(conn)
    assert migraciones.aplicar(conn) == [3]
    assert _tablas(conn) == set(TABLAS)
    if modo == "citus":
        assert {f[0] for f in conn.execute("SELECT logicalrelid::text FROM pg_dist_partition WHERE logicalrelid::text LIKE 'fiscal\\_%'").fetchall()} >= set(TABLAS)
    assert conn.execute("SELECT count(*) FROM pg_policy WHERE polrelid::regclass::text = ANY(?)", (list(TABLAS),)).fetchone()[0] == 5
    triggers = {f[0] for f in conn.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'fiscal\\_%'").fetchall()}
    assert {"fiscal_instantaneas_inmutable", "fiscal_artefactos_inmutable", "fiscal_casillas_solo_borrador", "fiscal_declaraciones_reglas"} <= triggers
    conn.execute("DELETE FROM bd_esquema_version WHERE version = 3")
    conn.commit()
    assert migraciones.aplicar(conn) == [3]                                                          # repetir no rompe nada
