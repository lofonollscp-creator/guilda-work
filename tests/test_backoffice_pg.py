"""El backoffice sobre PostgreSQL (fase 11): su esquema propio y quién puede tocarlo."""
import pytest

from tests import pg_ayudas

pytestmark = [pytest.mark.solo_sqlite, pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")]
psycopg = pytest.importorskip("psycopg")


def test_cada_rol_ve_solo_lo_suyo_y_la_auditoria_del_backoffice_es_de_solo_anexado():
    from psycopg.conninfo import make_conninfo
    url, limpiar = pg_ayudas.crear_base_con_esquema("multitenant")
    try:
        with psycopg.connect(url, autocommit=True) as admin:
            for rol in ("guilda_app", "guilda_plataforma", "guilda_backoffice"):
                admin.execute(f"ALTER ROLE {rol} PASSWORD 'x'")
            admin.execute("INSERT INTO backoffice.admins (usuario, nombre, password_hash, creado_en) VALUES ('ana', 'Ana', 'hash', 'hoy')")

        def como(rol):
            return psycopg.connect(make_conninfo(url, user=rol, password="x", options="-c search_path=backoffice,public"), autocommit=True)
        for rol in ("guilda_app", "guilda_plataforma"):
            with como(rol) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM backoffice.admins")                                  # ni la aplicación ni la plataforma ven los administradores del backoffice
        with como("guilda_backoffice") as c:
            assert c.execute("SELECT usuario FROM admins").fetchone()[0] == "ana", "con su search_path nombra las tablas sin esquema"
            c.execute("INSERT INTO auditoria (accion, creado_en) VALUES ('entrar', 'hoy')")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("UPDATE auditoria SET accion = 'otra'")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("DELETE FROM auditoria")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM public.notas")                                       # y el backoffice no lee los datos de los despachos con su propio rol
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM public.usuarios")
    finally:
        limpiar()
