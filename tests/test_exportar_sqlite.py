"""La vuelta atrás del corte (fase 11, app/bd/exportar_sqlite.py): SQLite -> PostgreSQL -> SQLite tiene que devolver exactamente lo mismo, y lo escrito en PostgreSQL entre medias también."""
import sqlite3

import pytest

from app import db, nucleo
from app.bd import exportar_sqlite, migrar_datos, tenant
from app.bd.verificar_migracion import huella
from tests import pg_ayudas

pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
psycopg = pytest.importorskip("psycopg")


def _tablas(c):
    return {n: [r[1] for r in c.execute(f'PRAGMA table_info("{n}")')] for (n,) in
            c.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND sql NOT LIKE 'CREATE VIRTUAL%' AND name NOT LIKE '%\\_fts%' ESCAPE '\\'")}


def _huellas(c):
    salida = {}
    for t, cols in _tablas(c).items():
        lista = ", ".join(f'"{x}"' for x in cols)
        salida[t] = (cols, huella(c.execute(f'SELECT {lista} FROM "{t}"'), len(cols)))
    return salida


@pytest.fixture
def ida_y_vuelta(tmp_path):
    t = db.crear_tenant("Despacho de ida y vuelta")
    u = db.crear_usuario_vinculado_a_kratos("iv@ejemplo.com", "k-iv")
    db.asignar_tenant(u, t)
    nucleo.crear_cliente(t, "Cliente Uno", email="uno@ejemplo.com", etiquetas=["vip"])
    db.crear_nota(u, "una nota con ñ y 日本") if hasattr(db, "crear_nota") else None
    db.crear_webhook(u, None, "https://ejemplo.com/hook", ["tarea.creada"])               # de toda la plataforma: tenant_id NULL en SQLite
    original = sqlite3.connect(tmp_path / "original.db")
    fuente = sqlite3.connect(db.DB_PATH)
    fuente.backup(original)
    fuente.close()
    url, limpiar = pg_ayudas.crear_base_con_esquema("multitenant")
    try:
        with psycopg.connect(url, autocommit=True) as pg:
            informe: dict = {}
            migrar_datos.copiar(tmp_path / "original.db", pg, informe=informe)
            assert informe["ok"], informe["discrepancias"]
            yield original, pg, tmp_path
        original.close()
    finally:
        limpiar()


def test_sqlite_postgres_sqlite_devuelve_exactamente_lo_mismo(ida_y_vuelta):
    original, pg, tmp = ida_y_vuelta
    informe = exportar_sqlite.exportar(pg, tmp / "vuelta.db")
    assert informe["ok"], informe["discrepancias"]
    assert informe["integrity_check"] == "ok"
    vuelta = sqlite3.connect(tmp / "vuelta.db")
    a, b = _huellas(original), _huellas(vuelta)
    assert set(a) == set(b)
    distintas = [t for t in a if a[t][1][0] != b[t][1][0] or a[t][1][1] != b[t][1][1]]
    assert not distintas, f"tablas distintas tras la vuelta: {distintas}"
    assert vuelta.execute("SELECT count(*) FROM webhooks WHERE tenant_id IS NULL").fetchone()[0] == 1, "lo de toda la plataforma vuelve a ser NULL, no 0"
    assert vuelta.execute("SELECT count(*) FROM tenants WHERE id = 0").fetchone()[0] == 0, "«Plataforma» es cosa de PostgreSQL"
    vuelta.close()


def test_lo_escrito_en_postgres_despues_del_corte_llega_a_sqlite_y_los_indices_de_busqueda_funcionan(ida_y_vuelta):
    original, pg, tmp = ida_y_vuelta
    despacho = pg.execute("SELECT id FROM tenants WHERE nombre = 'Despacho de ida y vuelta'").fetchone()[0]
    usuario = pg.execute("SELECT id FROM usuarios WHERE email = 'iv@ejemplo.com'").fetchone()[0]
    cuenta = pg.execute("INSERT INTO correo_cuentas (tenant_id, usuario_id, nombre, protocolo, host, puerto, usuario, creada_en) VALUES (%s, %s, 'c', 'imap', 'h', 993, 'u', 'x') RETURNING id", (despacho, usuario)).fetchone()[0]
    pg.execute("INSERT INTO correo_mensajes (tenant_id, cuenta_id, carpeta, uid, asunto, remitente, destinatarios, fecha, cuerpo_texto, message_id, leido, descargado_en) "
               "VALUES (%s, %s, 'INBOX', '1', 'Factura de octubre', 'a@b.c', 'd@e.f', 'x', 'adjunto la factura pendiente', '<1@x>', 0, 'x')", (despacho, cuenta))
    pg.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (%s, %s, 'escrita ya en PostgreSQL', 'x')", (despacho, usuario))
    informe = exportar_sqlite.exportar(pg, tmp / "vuelta.db")
    assert informe["ok"], informe["discrepancias"]
    vuelta = sqlite3.connect(tmp / "vuelta.db")
    assert vuelta.execute("SELECT count(*) FROM notas WHERE texto = 'escrita ya en PostgreSQL'").fetchone()[0] == 1
    assert [r[0] for r in vuelta.execute("SELECT rowid FROM correo_fts WHERE correo_fts MATCH 'factura'")], "el índice FTS5 de SQLite se rellena al cargar"
    vuelta.close()


def test_no_sobrescribe_y_exporta_tambien_el_backoffice(ida_y_vuelta, monkeypatch):
    original, pg, tmp = ida_y_vuelta
    (tmp / "ya_existe.db").write_bytes(b"x")
    with pytest.raises(exportar_sqlite.ErrorDeExportacion, match="ya existe"):
        exportar_sqlite.exportar(pg, tmp / "ya_existe.db")
    pg.execute("INSERT INTO backoffice.admins (usuario, nombre, password_hash, creado_en) VALUES ('ana', 'Ana', 'hash', 'hoy')")
    pg.execute("INSERT INTO backoffice.cobros (tenant_id, concepto, importe_centimos, stripe_session_id, url, creado_en) VALUES (1, 'Alta', 4900, 's', 'u', 'hoy')")
    informe = exportar_sqlite.exportar(pg, tmp / "vuelta.db", backoffice=tmp / "bo.db")
    assert informe["ok"], informe["discrepancias"]
    bo = sqlite3.connect(tmp / "bo.db")
    assert bo.execute("SELECT usuario FROM admins").fetchone()[0] == "ana" and bo.execute("SELECT importe_centimos FROM cobros").fetchone()[0] == 4900
    bo.close()
