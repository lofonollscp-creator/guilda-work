"""Migraciones 004 a 010 (columnas de Guilda Fiscal y de las facturas) contra un PostgreSQL de verdad: sobre una base «antigua» (sin esas columnas) las migraciones las crean, en el orden, y repetirlas no hace nada.
Se ejecuta con GUILDA_TEST_PG_URL (la imagen con Citus y pgvector del ensayo)."""
import re

import pytest

from app.bd import migraciones
from tests import pg_ayudas

pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
pytest.importorskip("psycopg")

COLUMNA = re.compile(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", re.I)


def _columnas_de_migraciones(desde: int) -> list[tuple[str, str]]:
    salida = []
    for version, fichero in sorted((v, f) for v, f in ((int(f.name[:3]), f) for f in migraciones.DIRECTORIO_MIGRACIONES.glob("*.sql")) if v >= desde and fichero_base(f)):
        salida += COLUMNA.findall(fichero.read_text(encoding="utf-8"))
    return salida


def fichero_base(f) -> bool:
    return f.name.count(".") == 1                                   # NNN_x.sql, no .mt.sql ni .citus.sql


@pytest.fixture(params=["multitenant", "citus"])
def base(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    try:
        yield pg.conectar()
    finally:
        pg.cerrar_pool()
        limpiar()


def _existe(conn, tabla, columna) -> bool:
    return bool(conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ?", (tabla, columna)).fetchone())


def test_una_base_anterior_recibe_las_columnas_y_repetir_no_hace_nada(base):
    columnas = _columnas_de_migraciones(4)
    assert ("fiscal_declaraciones", "iban") in columnas and ("fiscal_apuntes", "cobros_json") in columnas and ("facturas_contables", "lectura_evidencia") in columnas and len(columnas) >= 8
    assert all(_existe(base, t, c) for t, c in columnas)            # una base nueva nace al día
    for tabla, columna in columnas:                                  # se deja como la de producción antes de aplicar 004 a 010
        base.execute(f"ALTER TABLE {tabla} DROP COLUMN {columna}")
    base.execute("DELETE FROM bd_esquema_version WHERE version >= 4")
    base.commit()
    assert not any(_existe(base, t, c) for t, c in columnas)
    assert migraciones.pendientes(base) == list(range(4, 11))
    assert migraciones.aplicar(base) == list(range(4, 11))
    assert all(_existe(base, t, c) for t, c in columnas)
    assert migraciones.aplicar(base) == [] and migraciones.version_actual(base) == 10
