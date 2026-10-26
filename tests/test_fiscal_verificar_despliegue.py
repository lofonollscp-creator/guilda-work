"""scripts/fiscal/verificar_despliegue.py: pasa sobre una base recién migrada (multitenant y Citus) y avisa cuando falta algo. Necesita GUILDA_TEST_PG_URL."""
import sys
from pathlib import Path

import pytest

from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "fiscal"))


@pytest.fixture(params=["multitenant", "citus"])
def base(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def test_una_base_migrada_pasa_todas_las_comprobaciones_y_una_incompleta_no(base):
    import verificar_despliegue as vd
    modo, conn = base
    fallos = [t for ok, t in vd.comprobar(conn) if not ok]
    assert fallos == [], fallos
    conn.execute("DROP TABLE fiscal_artefactos CASCADE")
    conn.execute("DELETE FROM bd_esquema_version WHERE version = 3")
    conn.commit()
    fallos = [t for ok, t in vd.comprobar(conn) if not ok]
    assert any("tabla fiscal_artefactos" in t for t in fallos) and any("versión del esquema" in t for t in fallos)
