"""Panel de salud de la base de datos PostgreSQL (fase 10, app/salud_postgres.py): cada alerta se provoca de verdad y tiene que ponerse ámbar o roja."""
import json
import threading
import time
from datetime import datetime, timedelta

import pytest

from app import salud_postgres as sp
from tests import pg_ayudas

pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
psycopg = pytest.importorskip("psycopg")


@pytest.fixture(scope="module")
def base():
    url, limpiar = pg_ayudas.crear_base_con_esquema("multitenant")
    try:
        yield url
    finally:
        limpiar()


def _por_clave(items):
    return {i["clave"]: i for i in items}


def _comprobar(base, tmp_path, **kw):
    with psycopg.connect(base, autocommit=True) as c:
        return _por_clave(sp.comprobaciones(c, ruta_estado=tmp_path / "pg_estado.json", **kw))


def test_una_base_sana_sale_verde_o_gris_y_dice_que_no_hay_archivo_de_wal(base, tmp_path):
    r = _comprobar(base, tmp_path)
    assert r["pg_conexiones"]["estado"] == sp.VERDE and r["pg_bloqueos"]["estado"] == sp.VERDE and r["pg_ranuras"]["estado"] == sp.VERDE
    assert r["pg_copia_base"]["estado"] == sp.GRIS, "sin scripts/backup_postgres.sh ejecutado todavía"
    assert r["pg_archivo_wal"]["estado"] == sp.ROJO and "desactivado" in r["pg_archivo_wal"]["detalle"], "la instancia de pruebas no archiva WAL: en producción eso es un rojo"
    assert all(i["grupo"] == sp.GRUPO for i in r.values())


def test_la_copia_base_vieja_o_fallida_avisa(base, tmp_path):
    ruta = tmp_path / "pg_estado.json"
    ahora = datetime(2026, 10, 25, 12, 0, 0)

    def con(**e):
        ruta.write_text(json.dumps({"bases": 7, "tamano_bases": 5e9, "tamano_wal": 1e9, **e}))
        return _comprobar(base, tmp_path, ahora=ahora)["pg_copia_base"]
    assert con(ultimo_ok=(ahora - timedelta(hours=10)).isoformat())["estado"] == sp.VERDE
    assert con(ultimo_ok=(ahora - timedelta(hours=50)).isoformat())["estado"] == sp.AMBAR
    assert con(ultimo_ok=(ahora - timedelta(days=5)).isoformat())["estado"] == sp.ROJO
    fallo = con(ultimo_ok=(ahora - timedelta(hours=10)).isoformat(), error="pg_basebackup falló", ultimo_error=(ahora - timedelta(hours=1)).isoformat())
    assert fallo["estado"] == sp.ROJO and "pg_basebackup falló" in fallo["detalle"]
    assert con(error="contenedor parado")["estado"] == sp.ROJO


def test_una_sesion_esperando_un_bloqueo_y_una_transaccion_olvidada_avisan(base, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "BLOQUEO_AMBAR_SEG", 1)
    monkeypatch.setattr(sp, "BLOQUEO_ROJO_SEG", 3)
    monkeypatch.setattr(sp, "INACTIVA_AMBAR_MIN", 0.02)         # 1,2 s
    monkeypatch.setattr(sp, "INACTIVA_ROJO_MIN", 100)
    with psycopg.connect(base, autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS bloqueo_prueba")
        c.execute("CREATE TABLE bloqueo_prueba (id int PRIMARY KEY)")
        c.execute("INSERT INTO bloqueo_prueba VALUES (1)")
    dueno = psycopg.connect(base)                                                                    # abre una transacción y se queda con la fila
    dueno.execute("UPDATE bloqueo_prueba SET id = 1")
    espera = psycopg.connect(base)

    def esperar():
        try:
            espera.execute("SET lock_timeout = '8s'")
            espera.execute("UPDATE bloqueo_prueba SET id = 1")
        except psycopg.Error:
            pass
    hilo = threading.Thread(target=esperar, daemon=True)
    hilo.start()
    try:
        time.sleep(2.2)
        r = _comprobar(base, tmp_path)
        assert r["pg_bloqueos"]["estado"] in (sp.AMBAR, sp.ROJO) and "1 sesión(es) esperando" in r["pg_bloqueos"]["detalle"]
        assert r["pg_transacciones_abiertas"]["estado"] in (sp.AMBAR, sp.ROJO), r["pg_transacciones_abiertas"]
        time.sleep(1.5)
        assert _comprobar(base, tmp_path)["pg_bloqueos"]["estado"] == sp.ROJO
    finally:
        dueno.rollback()
        hilo.join(10)
        espera.close()
        dueno.close()
    assert _comprobar(base, tmp_path)["pg_bloqueos"]["estado"] == sp.VERDE


def test_una_ranura_de_replicacion_sin_lector_que_retiene_wal_avisa(base, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "RANURA_AMBAR_BYTES", 1000)
    monkeypatch.setattr(sp, "RANURA_ROJO_BYTES", 10_000_000)
    with psycopg.connect(base, autocommit=True) as c:
        if c.execute("SHOW wal_level").fetchone()[0] != "logical":
            pytest.skip("la instancia no tiene wal_level=logical")
        c.execute("SELECT pg_create_logical_replication_slot('ranura_prueba', 'pgoutput')")
        try:
            c.execute("CREATE TABLE IF NOT EXISTS wal_prueba (x text)")
            c.execute("INSERT INTO wal_prueba SELECT repeat('x', 500) FROM generate_series(1, 200)")
            r = _comprobar(base, tmp_path)["pg_ranuras"]
            assert r["estado"] == sp.AMBAR and "ranura_prueba" in r["detalle"]
        finally:
            c.execute("SELECT pg_drop_replication_slot('ranura_prueba')")
    assert _comprobar(base, tmp_path)["pg_ranuras"]["estado"] == sp.VERDE


def test_muchas_conexiones_avisan(base, tmp_path, monkeypatch):
    with psycopg.connect(base, autocommit=True) as c:
        maximo = c.execute("SELECT current_setting('max_connections')::int").fetchone()[0]
    monkeypatch.setattr(sp, "CONEXIONES_AMBAR_PCT", 1)
    monkeypatch.setattr(sp, "CONEXIONES_ROJO_PCT", 100 * 3 / maximo)                                  # con 3 sesiones abiertas ya es rojo
    abiertas = [psycopg.connect(base) for _ in range(3)]
    try:
        assert _comprobar(base, tmp_path)["pg_conexiones"]["estado"] == sp.ROJO
    finally:
        for a in abiertas:
            a.close()


def test_un_nodo_de_citus_inactivo_se_pone_rojo(tmp_path):
    url, limpiar = pg_ayudas.crear_base_con_esquema("citus")
    try:
        with psycopg.connect(url, autocommit=True) as c:
            assert _por_clave(sp.comprobaciones(c, ruta_estado=tmp_path / "x.json"))["pg_citus"]["estado"] == sp.VERDE
            c.execute("UPDATE pg_dist_node SET isactive = false")
            r = _por_clave(sp.comprobaciones(c, ruta_estado=tmp_path / "x.json"))["pg_citus"]
            c.execute("UPDATE pg_dist_node SET isactive = true")
        assert r["estado"] == sp.ROJO and "inactivo" in r["detalle"]
    finally:
        limpiar()


def test_el_panel_general_incluye_la_base_de_datos_solo_con_el_motor_postgres(monkeypatch):
    from app import salud
    monkeypatch.setattr(salud, "_motor_postgres", lambda: False)
    assert not any(i["clave"] == "postgres" or i["clave"].startswith("pg_") for i in salud.panel())
