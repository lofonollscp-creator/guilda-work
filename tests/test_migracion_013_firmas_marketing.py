"""Migración 013 (documentos para firmar, cambios en lote y marketing del Comercial) sobre una base que YA está en producción (versión 12, sin esas tablas): las crea, las distribuye en Citus, las aísla por
despacho, impide enlazar a un cliente de otro despacho y repetirla no rompe nada. Necesita GUILDA_TEST_PG_URL."""
import pytest

from app.bd import migraciones
from tests import pg_ayudas

psycopg = pytest.importorskip("psycopg")
pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
TABLAS = ("documentos_plantillas", "documentos_firma", "crm_acciones_masivas", "marketing_contactos", "marketing_grupos", "marketing_plantillas", "marketing_envios", "marketing_envio_destinatarios")


@pytest.fixture(params=["multitenant", "citus"])
def base_antigua(request):
    from app.bd import postgres as pg
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    pg.fijar_url(url)
    conn = pg.conectar()
    for t in reversed(TABLAS):
        conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    conn.execute("DELETE FROM bd_esquema_version WHERE version > 12")
    conn.commit()
    try:
        yield request.param, conn
    finally:
        conn.close()
        pg.cerrar_pool()
        limpiar()


def _existentes(conn) -> set[str]:
    return {f[0] for f in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_name = ANY(?)", (list(TABLAS),)).fetchall()}


def test_la_migracion_crea_distribuye_y_es_repetible(base_antigua):
    modo, conn = base_antigua
    assert 13 in migraciones.pendientes(conn) and not _existentes(conn)
    migraciones.aplicar(conn)
    assert _existentes(conn) == set(TABLAS)
    for t in TABLAS:
        pk = conn.execute(f"SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = '{t}'::regclass AND contype = 'p'").fetchone()[0]
        assert "tenant_id" in pk, t
        assert conn.execute(f"SELECT count(*) FROM pg_policy WHERE polrelid = '{t}'::regclass").fetchone()[0] == 1, t
        if modo == "citus":
            assert conn.execute(f"SELECT count(*) FROM pg_dist_partition WHERE logicalrelid = '{t}'::regclass").fetchone()[0] == 1, t
    assert conn.execute("SELECT count(*) FROM pg_trigger WHERE tgname = 'fk_set_null' AND tgrelid = 'marketing_grupos'::regclass").fetchone()[0] == 1
    conn.execute("DELETE FROM bd_esquema_version WHERE version >= 13")                                 # repetir: nada se rompe
    conn.commit()
    assert 13 in migraciones.aplicar(conn)


def test_claves_foraneas_aislamiento_y_set_null(base_antigua):
    modo, conn = base_antigua
    migraciones.aplicar(conn)
    for t in (9001, 9002):
        conn.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (?, 'T', '2026-01-01') ON CONFLICT DO NOTHING", (t,))
    conn.execute("INSERT INTO usuarios (id, email, contrasena_hash, creado_en, tenant_id) VALUES (9301, 'fm@ejemplo.com', 'x', '2026-01-01', 9001) ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO clientes (tenant_id, id, nombre, creado_en) VALUES (9001, 9101, 'C', '2026-01-01')")
    conn.commit()
    firma = ("INSERT INTO documentos_firma (tenant_id, cliente_id, plantilla, titulo, texto, firmante_email, firmante_nombre, pdf_sha256, creado_por, creado_en) "
             "VALUES (?, 9101, 'hoja_encargo', 'T', 'x', 'a@b.c', 'A', 'h', 9301, '2026-01-01')")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(firma, (9002,))                                                                  # cliente de otro despacho
    conn.rollback()
    conn.execute(firma, (9001,))
    conn.execute("INSERT INTO marketing_contactos (tenant_id, email, cliente_id, estado, origen, evidencia, actualizado_en) VALUES (9001, 'a@b.c', 9101, 'consentido', 'verbal', 'x', '2026-01-01')")
    conn.execute("INSERT INTO marketing_grupos (tenant_id, nombre, creado_en) VALUES (9001, 'G', '2026-01-01')")
    conn.commit()
    gid = conn.execute("SELECT id FROM marketing_grupos WHERE tenant_id = 9001").fetchone()[0]
    conn.execute("INSERT INTO marketing_envios (tenant_id, nombre, grupo_id, asunto, creado_en) VALUES (9001, 'E', ?, 'A', '2026-01-01')", (gid,))
    conn.commit()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO marketing_contactos (tenant_id, email, estado, origen, evidencia, actualizado_en) VALUES (9001, 'z@b.c', 'otro', 'verbal', 'x', '2026-01-01')")
    conn.rollback()
    conn.execute("DELETE FROM marketing_grupos WHERE tenant_id = 9001")                                 # ON DELETE SET NULL del envío
    conn.execute("DELETE FROM clientes WHERE tenant_id = 9001 AND id = 9101")                          # cascada de la firma y SET NULL del contacto
    conn.commit()
    assert conn.execute("SELECT grupo_id FROM marketing_envios WHERE tenant_id = 9001").fetchone()[0] is None
    assert conn.execute("SELECT count(*) FROM documentos_firma WHERE tenant_id = 9001").fetchone()[0] == 0
    assert conn.execute("SELECT cliente_id FROM marketing_contactos WHERE tenant_id = 9001").fetchone()[0] is None
