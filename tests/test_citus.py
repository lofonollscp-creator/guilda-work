"""Esquema multitenant y Citus (fase 6b): aislamiento por despacho (RLS), claves compuestas, triggers y planificación de las consultas de la aplicación.

Necesita el servidor de ensayo con Citus (GUILDA_TEST_PG_URL, superusuario). Se salta sin él.
"""
import json
import re
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

from tests import pg_ayudas  # noqa: E402

pytestmark = pytest.mark.skipif(not pg_ayudas.URL, reason="sin GUILDA_TEST_PG_URL")

MODELO = json.loads((Path(__file__).resolve().parents[1] / "app" / "bd" / "tenant_modelo.json").read_text(encoding="utf-8"))
DISTRIBUIDAS = sorted(t for t, v in MODELO.items() if v["clase"] in ("propio", "hija", "usuario"))
REFERENCIA = sorted(t for t, v in MODELO.items() if v["clase"] == "referencia")


@pytest.fixture(scope="module")
def citus():
    url, limpiar = pg_ayudas.crear_base_con_esquema("citus")
    yield url
    limpiar()


@pytest.fixture(scope="module")
def como_app(citus):
    """Conexión como guilda_app (sujeta a RLS). Fija una contraseña de prueba al rol; la base se borra al terminar."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    with psycopg.connect(citus, autocommit=True) as c:
        c.execute("ALTER ROLE guilda_app PASSWORD 'prueba-app'")
        c.execute("ALTER ROLE guilda_plataforma PASSWORD 'prueba-plataforma'")
    d = conninfo_to_dict(citus)

    def abrir(rol="guilda_app"):
        return psycopg.connect(make_conninfo(citus, user=rol, password="prueba-app" if rol == "guilda_app" else "prueba-plataforma"), autocommit=False)
    return abrir


def _sembrar(url):
    with psycopg.connect(url, autocommit=True) as c:
        for t in (1, 2):
            c.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (%s, %s, 'x') ON CONFLICT DO NOTHING", (t, f"Despacho {t}"))
        for u, t in ((10, 1), (20, 2)):
            c.execute("INSERT INTO usuarios (id, email, contrasena_hash, creado_en, tenant_id) VALUES (%s, %s, 'x', 'x', %s) ON CONFLICT DO NOTHING", (u, f"u{u}@x.es", t))


def test_el_esquema_multitenant_equivale_al_de_sqlite_salvo_lo_del_despacho(citus, _plantilla_bd):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "migracion"))
    import comparar_esquemas
    dif = comparar_esquemas.comparar(comparar_esquemas.esquema_sqlite(_plantilla_bd), comparar_esquemas.esquema_postgres(citus), multitenant=True)
    assert not dif, "\n".join(dif[:25])


def test_los_ficheros_multitenant_estan_al_dia(_plantilla_bd):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "migracion"))
    import generar_esquema_pg
    from app.bd import esquema
    generados, avisos = generar_esquema_pg.generar_multitenant(_plantilla_bd)
    assert not avisos, avisos
    atrasados = [f for f, texto in generados.items() if (esquema.DIRECTORIO / "mt" / f).read_text(encoding="utf-8") != texto]
    assert not atrasados, f"{atrasados} no coinciden: ejecuta scripts/migracion/generar_esquema_pg.py <base.db> --multitenant"


def test_el_esquema_citus_tiene_la_forma_esperada(citus):
    with psycopg.connect(citus, autocommit=True) as c:
        tipos = dict(c.execute("SELECT table_name::text, citus_table_type FROM citus_tables").fetchall())
        assert {t for t, k in tipos.items() if k == "distributed"} == set(DISTRIBUIDAS)
        assert {"tenants", "usuarios", "usuarios_tenants", "comunicados", "jur_fuentes", "auditoria_control"} <= {t for t, k in tipos.items() if k == "reference"}
        assert c.execute("SELECT count(DISTINCT colocation_id) FROM citus_tables WHERE citus_table_type = 'distributed'").fetchone()[0] == 1       # todas colocalizadas
        assert c.execute("SELECT count(*) FROM pg_class WHERE relrowsecurity AND relname = ANY(%s)", (DISTRIBUIDAS,)).fetchone()[0] == len(DISTRIBUIDAS)
        sin_tenant = c.execute("SELECT table_name FROM information_schema.columns WHERE table_name = ANY(%s) AND column_name = 'tenant_id' AND is_nullable = 'NO' AND table_schema = 'public'", (DISTRIBUIDAS,)).fetchall()
        assert len(sin_tenant) == len(DISTRIBUIDAS), "toda tabla distribuida tiene tenant_id NOT NULL"
        assert c.execute("SELECT nombre FROM tenants WHERE id = 0").fetchone()[0] == "Plataforma"


def test_cada_despacho_solo_ve_y_escribe_lo_suyo(citus, como_app):
    _sembrar(citus)
    a = como_app()
    try:
        a.execute("SELECT set_config('app.tenant_id', '1', true)")
        a.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (10, 'del despacho 1', 'x')")          # tenant_id sale del despacho de la conexión
        assert a.execute("SELECT tenant_id FROM notas").fetchall() == [(1,)]
        a.commit()
        a.execute("SELECT set_config('app.tenant_id', '2', true)")
        assert a.execute("SELECT count(*) FROM notas").fetchone()[0] == 0, "el despacho 2 no ve las notas del 1"
        with pytest.raises(psycopg.Error):
            a.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (1, 10, 'intruso', 'x')")  # escribir en otro despacho: la política lo impide
        a.rollback()
        a.execute("SELECT set_config('app.tenant_id', '2', true)")
        assert a.execute("UPDATE notas SET texto = 'hack'").rowcount == 0 and a.execute("DELETE FROM notas").rowcount == 0
        a.rollback()
        assert a.execute("SELECT count(*) FROM notas").fetchone()[0] == 0, "sin despacho (fuera de SET LOCAL) no se ve nada"
        a.rollback()
        with pytest.raises(psycopg.Error):                                                                       # sin contexto, ni siquiera se puede insertar (tenant_id NULL)
            a.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (10, 'sin despacho', 'x')")
        a.rollback()
    finally:
        a.close()
    p = como_app("guilda_plataforma")                               # la plataforma sí ve entre despachos
    try:
        assert p.execute("SELECT count(*) FROM notas").fetchone()[0] >= 1
    finally:
        p.close()


def test_las_claves_foraneas_compuestas_impiden_apuntar_a_otro_despacho(citus, como_app):
    _sembrar(citus)
    with psycopg.connect(citus, autocommit=True) as c:
        c.execute("INSERT INTO categorias (id, usuario_id, nombre, creada_en, tenant_id) VALUES (500, 10, 'proyecto del 1', 'x', 1) ON CONFLICT DO NOTHING")
        # una tarea del despacho 1 puede colgar de la categoría del 1...
        c.execute("INSERT INTO tareas (id, usuario_id, nombre, categoria_id, tipo, estado, inicio_en, tenant_id) VALUES (900, 10, 't', 500, 'duracion', 'finalizada', 'x', 1) ON CONFLICT DO NOTHING")
        # ...pero no de la del otro despacho, aunque la política no actúe (rol propietario): lo impide la clave foránea compuesta
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("INSERT INTO tareas (id, usuario_id, nombre, categoria_id, tipo, estado, inicio_en, tenant_id) VALUES (901, 20, 't', 500, 'duracion', 'finalizada', 'x', 2)")


def test_borrar_el_padre_anula_la_columna_de_los_hijos_con_set_null_y_arrastra_con_cascade(citus):
    _sembrar(citus)
    with psycopg.connect(citus, autocommit=True) as c:
        cid = c.execute("INSERT INTO clientes (tenant_id, nombre, creado_en) VALUES (1, 'Cliente SET NULL', 'x') RETURNING id").fetchone()[0]
        c.execute("INSERT INTO contactos (tenant_id, nombre, cliente_id, creado_en) VALUES (1, 'Ana', %s, 'x')", (cid,))
        c.execute("DELETE FROM clientes WHERE tenant_id = 1 AND id = %s", (cid,))
        assert c.execute("SELECT cliente_id FROM contactos WHERE nombre = 'Ana'").fetchone()[0] is None, "ON DELETE SET NULL (por trigger, Citus no lo admite en la clave foránea)"
        # CASCADE: la checklist de una tarea desaparece con la tarea
        tid = c.execute("INSERT INTO tareas_outlook (tenant_id, usuario_id, asunto, creada_en) VALUES (1, 10, 'a', 'x') RETURNING id").fetchone()[0]
        c.execute("INSERT INTO tarea_checklist (tenant_id, tarea_outlook_id, texto, orden) VALUES (1, %s, 'paso', 1)", (tid,))
        c.execute("DELETE FROM tareas_outlook WHERE tenant_id = 1 AND id = %s", (tid,))
        assert c.execute("SELECT count(*) FROM tarea_checklist WHERE tarea_outlook_id = %s", (tid,)).fetchone()[0] == 0


def test_los_triggers_de_historial_y_auditoria_funcionan_en_tablas_distribuidas(citus):
    _sembrar(citus)
    with psycopg.connect(citus, autocommit=True) as c:
        n = c.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (2, 20, 'n', 'x') RETURNING id").fetchone()[0]
        c.execute("UPDATE notas SET papelera_en = 'hoy' WHERE tenant_id = 2 AND id = %s", (n,))
        assert [r[0] for r in c.execute("SELECT accion FROM api_cambios WHERE tenant_id = 2 AND entidad = 'notas' AND entidad_id = %s ORDER BY id", (n,))] == ["upsert", "delete"]
        c.execute("INSERT INTO auditoria_eventos (tenant_id, accion, entidad, creado_en) VALUES (2, 'x', 'y', 'ahora')")
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="no se puede modificar"):
            c.execute("UPDATE auditoria_eventos SET accion = 'z' WHERE tenant_id = 2")
        t = c.execute("INSERT INTO tareas_outlook (tenant_id, usuario_id, asunto, creada_en) VALUES (2, 20, 'v', 'x') RETURNING id").fetchone()[0]
        v0 = c.execute("SELECT version FROM tareas_outlook WHERE tenant_id = 2 AND id = %s", (t,)).fetchone()[0]
        c.execute("UPDATE tareas_outlook SET asunto = 'w' WHERE tenant_id = 2 AND id = %s", (t,))
        assert c.execute("SELECT version FROM tareas_outlook WHERE tenant_id = 2 AND id = %s", (t,)).fetchone()[0] == v0 + 1


def test_la_aplicacion_no_puede_tocar_la_auditoria_ni_el_catalogo_de_despachos(citus, como_app):
    a = como_app()
    try:
        a.execute("SELECT set_config('app.tenant_id', '2', true)")
        for sentencia in ("UPDATE auditoria_eventos SET accion = 'z'", "DELETE FROM auditoria_eventos", "TRUNCATE auditoria_eventos", "INSERT INTO tenants (nombre, creado_en) VALUES ('x', 'x')",
                          "DELETE FROM tenants"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                a.execute(sentencia)
            a.rollback()
            a.execute("SELECT set_config('app.tenant_id', '2', true)")
    finally:
        a.close()


def test_las_consultas_de_un_despacho_van_a_un_solo_shard_y_el_join_colocalizado_funciona(citus):
    with psycopg.connect(citus, autocommit=True) as c:
        plan = "\n".join(r[0] for r in c.execute("EXPLAIN (COSTS OFF) SELECT t.asunto, k.texto FROM tareas_outlook t JOIN tarea_checklist k ON k.tenant_id = t.tenant_id AND k.tarea_outlook_id = t.id WHERE t.tenant_id = 1"))
        assert "Task Count: 1" in plan
        sin_filtro = "\n".join(r[0] for r in c.execute("EXPLAIN (COSTS OFF) SELECT * FROM tareas_outlook WHERE id = 5"))
        assert "Task Count: 16" in sin_filtro, "sin el despacho en la consulta se reparte por los 16 shards"


PENDIENTES_CITUS = 112          # consultas que Citus aún no sabe planificar (docs/migracion-citus-consultas-pendientes.txt): al arreglarlas, baja este número


def test_las_consultas_que_citus_rechaza_no_aumentan(citus):
    """Planifica (sin ejecutar) todo el SQL de la aplicación contra Citus. Una consulta nueva con un join sin `tenant_id` sube el número y hace fallar la prueba."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "migracion"))
    import validar_sql_citus
    ok, router, repartidas, fallos, inserciones = validar_sql_citus.validar(citus, valor="1")
    reales = [f for f in fallos if "cannot be coerced" not in f[2]]                 # los de «bytea» son del propio planificador de pruebas (pasa un entero)
    assert ok > 1500
    assert len(reales) <= PENDIENTES_CITUS, f"{len(reales)} consultas rechazadas por Citus (límite {PENDIENTES_CITUS}); las nuevas:\n" + "\n".join(f"  {r}:{l}  {e}\n      {q}" for r, l, e, q in sorted(reales)[:15])
