"""La herramienta de migración de datos (fase 8): carga SQLite -> PostgreSQL y los controles que la acompañan.

Usan su propia base de PostgreSQL (GUILDA_TEST_PG_URL) y se ejecutan con el motor SQLite de las pruebas; con GUILDA_TEST_MOTOR=postgres se saltan."""
import sqlite3

import pytest

from app import db, nucleo
from app.bd import migrar_datos, tenant, verificar_migracion
from tests import pg_ayudas

pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def migrada(tmp_path):
    """Una base de SQLite con datos, migrada a un PostgreSQL multitenant. Devuelve (copia de SQLite con el despacho rellenado, conexión psycopg, informe)."""
    t = db.crear_tenant("Despacho migrado")
    nucleo.crear_cliente(t, "Cliente Uno", email="uno@ejemplo.com")
    nucleo.crear_cliente(t, "Cliente Dos", email="dos@ejemplo.com", etiquetas=["vip"])
    url, limpiar = pg_ayudas.crear_base_con_esquema("multitenant")
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            informe: dict = {}
            migrar_datos.copiar(db.DB_PATH, conn, informe=informe)
            copia = tmp_path / "copia.db"
            origen = sqlite3.connect(copia)
            fuente = sqlite3.connect(db.DB_PATH)
            fuente.backup(origen)                                   # (la API de copia, no el fichero: los últimos cambios pueden estar aún en el WAL)
            fuente.close()
            tenant.rellenar(origen, crear_columnas=True, por_defecto=tenant.TENANT_PLATAFORMA)
            yield origen, conn, informe
            origen.close()
    finally:
        limpiar()


def test_la_migracion_cuadra_y_lo_cuenta(migrada):
    _origen, conn, informe = migrada
    assert informe["ok"], informe["discrepancias"]
    assert informe["tablas"]["clientes"] == {"origen": 2, "destino": 2}
    assert conn.execute("SELECT count(*) FROM clientes WHERE tenant_id = (SELECT id FROM tenants WHERE nombre = 'Despacho migrado')").fetchone()[0] == 2
    assert informe["roles"]["comprobaciones"] > 0, "el rol de la aplicación solo ve lo de su despacho"


def test_un_valor_cambiado_se_delata_con_su_tabla_y_columna(migrada):
    origen, conn, _ = migrada
    conn.execute("UPDATE clientes SET nombre = 'Otro' WHERE nombre = 'Cliente Uno'")
    cols = [r[1] for r in origen.execute("PRAGMA table_info(clientes)")]
    informe = verificar_migracion.verificar(origen, conn, {"clientes": cols})
    assert not informe["ok"] and any("clientes" in d and "nombre" in d for d in informe["discrepancias"]), informe["discrepancias"]


def test_una_fila_que_falta_se_delata(migrada):
    origen, conn, _ = migrada
    conn.execute("DELETE FROM clientes WHERE nombre = 'Cliente Dos'")
    cols = [r[1] for r in origen.execute("PRAGMA table_info(clientes)")]
    informe = verificar_migracion.verificar(origen, conn, {"clientes": cols})
    assert any("2 filas en SQLite y 1 en PostgreSQL" in d for d in informe["discrepancias"])
    assert any("recuento por despacho" in d for d in informe["discrepancias"])


def test_un_hijo_sin_padre_se_delata(migrada):
    origen, conn, _ = migrada
    conn.execute("SET session_replication_role = replica")
    conn.execute("DELETE FROM clientes WHERE nombre = 'Cliente Dos'")
    conn.execute("SET session_replication_role = DEFAULT")
    informe = verificar_migracion.verificar(origen, conn, {"cliente_etiquetas": ["cliente_id", "etiqueta", "tenant_id"]})
    assert any("huérfanas" in d for d in informe["discrepancias"])


def test_los_bytes_nul_se_quitan_y_se_anotan():
    avisos: dict = {}
    assert migrar_datos._sin_nul(("a\x00b", 3, None), ["texto", "n", "x"], "t", avisos) == ("ab", 3, None)
    assert avisos == {"t": {"texto": 1}}
    assert verificar_migracion.huella([("a\x00b",)], 1) == verificar_migracion.huella([("ab",)], 1), "la suma de control compara lo que se carga"
    assert verificar_migracion.huella([("ab",), ("c",)], 1) == verificar_migracion.huella([("c",), ("ab",)], 1), "no depende del orden"
    assert verificar_migracion.huella([(1,)], 1) != verificar_migracion.huella([("1",)], 1), "distingue un entero de un texto"


def test_el_orden_de_carga_respeta_las_claves_foraneas_reales(migrada):
    _origen, conn, _ = migrada
    orden = migrar_datos.orden_de_carga(conn, ["certificados", "clientes_fiscales", "tenants"])
    assert orden.index("tenants") < orden.index("clientes_fiscales") < orden.index("certificados")
