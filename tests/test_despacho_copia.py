"""Copia y restauración de un despacho (fase 10, app/bd/despacho_copia.py) en PostgreSQL llano y en Citus."""
import pytest

from app.bd import despacho_copia as dc
from tests import pg_ayudas

pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
psycopg = pytest.importorskip("psycopg")


def _sembrar(url):
    with psycopg.connect(url, autocommit=True) as c:
        for t in (1, 2):
            c.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (%s, %s, 'x')", (t, f"Despacho {t}"))
        for u, t in ((10, 1), (11, 1), (20, 2)):
            c.execute("INSERT INTO usuarios (id, email, contrasena_hash, creado_en, tenant_id) VALUES (%s, %s, 'x', 'x', %s)", (u, f"u{u}@x.es", t))
            c.execute("INSERT INTO usuarios_tenants (usuario_id, tenant_id, creado_en) VALUES (%s, %s, 'x')", (u, t))
            c.execute("INSERT INTO usuario_perfil (usuario_id, nombre_mostrado) VALUES (%s, %s)", (u, f"Persona {u}"))
        for t, u in ((1, 10), (2, 20)):
            for i in range(5):
                c.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (%s, %s, %s, 'x')", (t, u, f"nota {t}-{i} con ñ y \x01 raro"))
            c.execute("INSERT INTO correo_cuentas (tenant_id, usuario_id, nombre, protocolo, host, puerto, usuario, creada_en) VALUES (%s, %s, 'c', 'imap', 'h', 993, 'u', 'x')", (t, u))
            c.execute("INSERT INTO auditoria_eventos (tenant_id, accion, entidad, creado_en) VALUES (%s, 'x', 'y', 'ahora')", (t,))


@pytest.fixture(params=["multitenant", "citus"])
def base(request):
    url, limpiar = pg_ayudas.crear_base_con_esquema(request.param)
    try:
        _sembrar(url)
        yield url
    finally:
        limpiar()


def _cuenta(url, sql, *args):
    with psycopg.connect(url, autocommit=True) as c:
        return c.execute(sql, args).fetchone()[0]


def test_exportar_e_importar_en_otra_base_deja_el_despacho_igual_y_no_trae_los_demas(base, tmp_path):
    destino_url, limpiar = pg_ayudas.crear_base_con_esquema("multitenant")
    try:
        fichero = str(tmp_path / "despacho-1.tar.gz")
        with psycopg.connect(base, autocommit=True) as raw:
            m = dc.exportar(raw, 1, fichero)
        assert m["tablas"]["notas"]["filas"] == 5 and "notas" in m["tablas"] and m["referencia"]["usuarios"]["filas"] == 2
        assert (tmp_path / "despacho-1.tar.gz").stat().st_mode & 0o777 == 0o600
        with psycopg.connect(destino_url, autocommit=True) as raw:
            r = dc.importar(raw, fichero)
            assert r["ok"], r["discrepancias"]
            assert raw.execute("SELECT count(*) FROM notas WHERE tenant_id = 1").fetchone()[0] == 5
            assert raw.execute("SELECT count(*) FROM notas WHERE tenant_id = 2").fetchone()[0] == 0, "no trae nada de otros despachos"
            assert raw.execute("SELECT count(*) FROM usuarios").fetchone()[0] == 2 and raw.execute("SELECT count(*) FROM usuarios_tenants").fetchone()[0] == 2
            assert raw.execute("SELECT texto FROM notas WHERE tenant_id = 1 ORDER BY id LIMIT 1").fetchone()[0] == "nota 1-0 con ñ y \x01 raro"
            assert raw.execute("SELECT count(*) FROM auditoria_eventos WHERE tenant_id = 1").fetchone()[0] == 1
    finally:
        limpiar()


def test_recuperar_un_despacho_estropeado_sin_tocar_a_los_demas(base, tmp_path):
    fichero = str(tmp_path / "d1.tar.gz")
    with psycopg.connect(base, autocommit=True) as raw:
        dc.exportar(raw, 1, fichero)
        # el desastre: se pierde lo del despacho 1 y, a la vez, el despacho 2 sigue trabajando
        raw.execute("DELETE FROM notas WHERE tenant_id = 1")
        raw.execute("DELETE FROM correo_cuentas WHERE tenant_id = 1")
        raw.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (2, 20, 'posterior al desastre', 'x')")
        with pytest.raises(dc.ErrorDeCopia, match="ya tiene datos") as e:
            raw.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (1, 10, 'algo nuevo', 'x')")
            dc.importar(raw, fichero)                                 # sin «reemplazar» se niega si hay datos
        assert "notas" in str(e.value)
        r = dc.importar(raw, fichero, reemplazar=True)
        assert r["ok"], r["discrepancias"]
        assert raw.execute("SELECT count(*) FROM notas WHERE tenant_id = 1").fetchone()[0] == 5, "recuperado tal como estaba, sin lo posterior que se reemplaza"
        assert raw.execute("SELECT count(*) FROM correo_cuentas WHERE tenant_id = 1").fetchone()[0] == 1
        assert raw.execute("SELECT count(*) FROM notas WHERE tenant_id = 2").fetchone()[0] == 6, "el otro despacho conserva incluso lo escrito después del desastre"
        assert raw.execute("SELECT count(*) FROM auditoria_eventos WHERE tenant_id = 1").fetchone()[0] == 1, "la auditoría ni se borra ni se duplica"
        # los identificadores siguen: la siguiente nota no choca con las recuperadas
        raw.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (1, 10, 'después de recuperar', 'x')")
        assert raw.execute("SELECT count(DISTINCT id) FROM notas WHERE tenant_id = 1").fetchone()[0] == 6


def test_un_despacho_que_no_existe_o_una_copia_de_otro_esquema_se_rechazan(base, tmp_path):
    with psycopg.connect(base, autocommit=True) as raw:
        with pytest.raises(dc.ErrorDeCopia, match="no existe"):
            dc.exportar(raw, 99, str(tmp_path / "x.tar.gz"))
        fichero = str(tmp_path / "d2.tar.gz")
        dc.exportar(raw, 2, fichero)
        raw.execute("UPDATE bd_esquema_version SET version = version + 1")
        with pytest.raises(dc.ErrorDeCopia, match="esquema"):
            dc.importar(raw, fichero, reemplazar=True)
        assert dc.importar(raw, fichero, reemplazar=True, permitir_otra_version=True)["ok"]
