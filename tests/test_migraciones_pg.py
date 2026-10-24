"""Migraciones numeradas del esquema de PostgreSQL (fase 12, app/bd/migraciones.py) en PostgreSQL llano y en Citus."""
import threading

import pytest

from app.bd import migraciones
from tests import pg_ayudas

pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
psycopg = pytest.importorskip("psycopg")


@pytest.fixture(params=["multitenant", "citus"])
def entorno(request, tmp_path, monkeypatch):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    monkeypatch.setattr(migraciones, "DIRECTORIO_MIGRACIONES", tmp_path)
    try:
        yield request.param, url, tmp_path, pg
    finally:
        pg.cerrar_pool()
        limpiar()


def _escribir(directorio, nombre, texto):
    (directorio / nombre).write_text(texto, encoding="utf-8")


def _conectar(pg, url):
    pg.fijar_url(url)
    return pg.conectar()


def test_sin_ficheros_la_version_esperada_es_la_base_y_no_hay_nada_pendiente(entorno):
    _modo, url, _dir, pg = entorno
    conn = _conectar(pg, url)
    assert migraciones.version_esperada() == 1 and migraciones.version_actual(conn) == 1 and migraciones.pendientes(conn) == [] and migraciones.aplicar(conn) == []
    migraciones.comprobar(conn)


def test_aplica_en_orden_anota_las_versiones_y_es_repetible(entorno):
    modo, url, directorio, pg = entorno
    _escribir(directorio, "002_columna_de_prueba.sql", "-- Una columna de prueba\nALTER TABLE usuarios ADD COLUMN IF NOT EXISTS prueba_fase12 text;\n")
    _escribir(directorio, "003_tabla_de_prueba.sql", "-- Una tabla de prueba\nCREATE TABLE IF NOT EXISTS prueba_fase12 (id bigint PRIMARY KEY, nota text);\n")
    conn = _conectar(pg, url)
    assert migraciones.version_esperada() == 3 and migraciones.pendientes(conn) == [2, 3]
    with pytest.raises(migraciones.ErrorDeMigracion, match="necesita el 3"):
        migraciones.comprobar(conn)
    assert migraciones.aplicar(conn) == [2, 3]
    migraciones.comprobar(conn)
    assert migraciones.version_actual(conn) == 3 and migraciones.aplicar(conn) == []
    assert conn.execute("SELECT descripcion FROM bd_esquema_version WHERE version = 2").fetchone()[0] == "Una columna de prueba"
    assert conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_name = 'usuarios' AND column_name = 'prueba_fase12'").fetchone()[0] == 1
    assert conn.execute("SELECT to_regclass('prueba_fase12') IS NOT NULL").fetchone()[0]


def test_los_ficheros_mt_y_citus_solo_se_aplican_en_su_modo(entorno):
    modo, url, directorio, pg = entorno
    _escribir(directorio, "002_x.sql", "-- Base\nCREATE TABLE IF NOT EXISTS prueba_modos (tenant_id bigint NOT NULL DEFAULT 0, id bigint, PRIMARY KEY (tenant_id, id));\n")
    _escribir(directorio, "002_x.mt.sql", "ALTER TABLE prueba_modos ADD COLUMN IF NOT EXISTS solo_mt text;\n")
    _escribir(directorio, "002_x.citus.sql", "SELECT create_distributed_table('prueba_modos', 'tenant_id', colocate_with => 'tenants_herramientas_ocultas');\n")
    conn = _conectar(pg, url)
    assert migraciones.aplicar(conn) == [2]
    assert conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_name = 'prueba_modos' AND column_name = 'solo_mt'").fetchone()[0] == 1
    distribuida = conn.execute("SELECT count(*) FROM pg_dist_partition WHERE logicalrelid = 'prueba_modos'::regclass").fetchone()[0] if modo == "citus" else 0
    assert distribuida == (1 if modo == "citus" else 0)


def test_una_migracion_que_falla_nombra_el_fichero_y_deja_anotadas_solo_las_anteriores(entorno):
    modo, url, directorio, pg = entorno
    _escribir(directorio, "002_buena.sql", "-- Buena\nCREATE TABLE IF NOT EXISTS prueba_buena (id bigint PRIMARY KEY);\n")
    _escribir(directorio, "003_mala.sql", "-- Mala\nCREATE TABLE IF NOT EXISTS prueba_mala (id bigint PRIMARY KEY);\nALTER TABLE tabla_que_no_existe ADD COLUMN x text;\n")
    conn = _conectar(pg, url)
    with pytest.raises(migraciones.ErrorDeMigracion, match="003_mala.sql"):
        migraciones.aplicar(conn)
    assert migraciones.version_actual(conn) == 2
    if modo != "citus":                                          # (en Citus las sentencias van una a una: la primera de la mala sí queda hecha, de ahí lo de «idempotentes»)
        assert conn.execute("SELECT to_regclass('prueba_mala') IS NULL").fetchone()[0], "en PostgreSQL llano la migración fallida se deshace entera"


def test_dos_procesos_a_la_vez_aplican_una_sola_vez(entorno):
    modo, url, directorio, pg = entorno
    _escribir(directorio, "002_lenta.sql", "-- Lenta\nSELECT pg_sleep(1.5);\nCREATE TABLE IF NOT EXISTS prueba_carrera (id bigint PRIMARY KEY);\n")
    resultados = []

    def correr():
        with psycopg.connect(url, autocommit=True) as c:
            c.execute("SELECT 1")
        pg2 = pg.conectar()
        try:
            resultados.append(migraciones.aplicar(pg2))
        finally:
            pg2.close()
    pg.fijar_url(url)
    hilos = [threading.Thread(target=correr) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(60)
    assert sorted(resultados, key=len) == [[], [2]], resultados


def test_los_nombres_y_los_huecos_se_rechazan(entorno):
    _modo, _url, directorio, _pg = entorno
    _escribir(directorio, "004_salto.sql", "SELECT 1;")
    with pytest.raises(migraciones.ErrorDeMigracion, match="huecos"):
        migraciones.ficheros()
    _escribir(directorio, "mala-nomenclatura.sql", "SELECT 1;")
    with pytest.raises(migraciones.ErrorDeMigracion, match="nombre de migración no válido"):
        migraciones.ficheros()
