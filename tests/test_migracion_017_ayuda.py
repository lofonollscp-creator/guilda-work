"""Migración 017 (votos y búsquedas sin resultado del centro de ayuda) sobre una base que YA está en versión 16: crea las dos tablas de plataforma y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLAS = ("ayuda_valoraciones", "ayuda_busquedas_vacias")


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in TABLAS:
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 16")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _existen(conn) -> set[str]:
    return {f[0] for f in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()").fetchall()} & set(TABLAS)


def test_la_migracion_crea_las_tablas_y_es_repetible(base_antigua):
    _, conn = base_antigua
    assert 17 in migraciones.pendientes(conn) and not _existen(conn)
    migraciones.aplicar(conn)
    assert _existen(conn) == set(TABLAS)
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 17")
    conn.commit()
    migraciones.aplicar(conn)
    conn.execute("INSERT INTO ayuda_busquedas_vacias (idioma, consulta, veces, primera_en, ultima_en) VALUES ('es', 'x1', 1, 'a', 'a') ON CONFLICT (idioma, consulta) DO UPDATE SET veces = ayuda_busquedas_vacias.veces + 1")
    conn.execute("INSERT INTO ayuda_busquedas_vacias (idioma, consulta, veces, primera_en, ultima_en) VALUES ('es', 'x1', 1, 'a', 'a') ON CONFLICT (idioma, consulta) DO UPDATE SET veces = ayuda_busquedas_vacias.veces + 1")
    assert conn.execute("SELECT veces FROM ayuda_busquedas_vacias WHERE consulta = 'x1'").fetchone()[0] == 2
