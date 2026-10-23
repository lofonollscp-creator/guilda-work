"""Conexiones reutilizadas de `db.get_connection` (ver el comentario de «Conexiones reutilizadas» en app/db.py)."""
import threading

import pytest

from app import db


def _crear(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS pool_prueba (id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()


@pytest.mark.solo_sqlite
def test_close_devuelve_la_conexion_y_la_siguiente_la_reutiliza():
    a = db.get_connection(); _crear(a); a.close()
    b = db.get_connection()
    assert b is a, "debería reutilizarla en el mismo hilo"
    assert b.execute("SELECT COUNT(*) FROM pool_prueba").fetchone()[0] == 0
    b.close()


@pytest.mark.solo_sqlite
def test_dos_usos_a_la_vez_nunca_comparten_conexion():
    a = db.get_connection()
    b = db.get_connection()
    assert a is not b
    a.close(); b.close()
    c, d = db.get_connection(), db.get_connection()
    assert c is not d and {c, d} == {a, b}
    c.close(); d.close()


@pytest.mark.solo_sqlite
def test_lo_no_confirmado_se_descarta_al_devolverla_como_al_cerrarla():
    a = db.get_connection(); _crear(a)
    a.execute("INSERT INTO pool_prueba (v) VALUES ('sin confirmar')")
    assert a.in_transaction
    a.close()
    b = db.get_connection()
    assert not b.in_transaction and b.execute("SELECT COUNT(*) FROM pool_prueba").fetchone()[0] == 0
    b.close()


@pytest.mark.solo_sqlite
def test_lo_confirmado_se_conserva_y_se_ve_desde_otra_conexion():
    a = db.get_connection(); _crear(a)
    a.execute("INSERT INTO pool_prueba (v) VALUES ('ok')"); a.commit()
    b = db.get_connection()
    assert b is not a and b.execute("SELECT v FROM pool_prueba").fetchone()["v"] == "ok"
    a.close(); b.close()


def test_doble_close_no_duplica_la_conexion_en_el_pool():
    a = db.get_connection(); a.close(); a.close()
    b, c = db.get_connection(), db.get_connection()
    assert b is not c
    b.close(); c.close()


@pytest.mark.solo_sqlite
def test_cada_hilo_tiene_las_suyas_y_las_del_pool_no_cruzan_hilos():
    principal = db.get_connection(); principal.close()
    vistas = {}

    def trabajo():
        c = db.get_connection()
        vistas["hilo"] = c
        c.execute("SELECT 1").fetchone()
        c.close()
    t = threading.Thread(target=trabajo); t.start(); t.join()
    assert vistas["hilo"] is not principal
    assert db.get_connection() is principal


@pytest.mark.solo_sqlite
def test_el_pool_tiene_tope_y_las_sobrantes_se_cierran(monkeypatch):
    monkeypatch.setattr(db, "MAX_LIBRES_POR_RUTA", 2)
    conns = [db.get_connection() for _ in range(4)]
    for c in conns:
        c.close()
    cerradas = [c for c in conns if c._cerrada]
    assert len(cerradas) == 2
    with pytest.raises(Exception):
        cerradas[0].execute("SELECT 1")


def test_cerrar_conexiones_compartidas_cierra_las_libres_y_no_las_usadas():
    en_uso = db.get_connection()
    otra = db.get_connection()
    otra.close()
    db.cerrar_conexiones_compartidas()
    assert otra._cerrada
    assert not en_uso._cerrada
    en_uso.execute("SELECT 1").fetchone()
    nueva = db.get_connection()
    assert not nueva._cerrada and nueva is not otra       # las cerradas que quedaban en la lista se descartan
    nueva.close(); en_uso.close()


def test_apagado_con_la_variable_cierra_de_verdad(monkeypatch):
    monkeypatch.setattr(db, "POOL_ACTIVO", False)
    a = db.get_connection(); a.close()
    assert a._cerrada
    assert db.get_connection() is not a


@pytest.mark.solo_sqlite
def test_cada_ruta_de_base_de_datos_tiene_su_pool(tmp_path, monkeypatch):
    a = db.get_connection(); a.close()
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "otra.db")
    b = db.get_connection()
    assert b is not a and b._ruta != a._ruta
    b.close(); db.cerrar_conexiones_compartidas()
