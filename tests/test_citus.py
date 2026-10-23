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


def test_toda_tabla_distribuida_tiene_clave_primaria_para_poder_moverse_entre_nodos(citus):
    """Hallazgo de la fase 9: Citus mueve los fragmentos con replicación lógica, que exige clave primaria o identidad de réplica (`tenants_herramientas_ocultas` solo tenía UNIQUE)."""
    with psycopg.connect(citus, autocommit=True) as c:
        sin = c.execute("SELECT p.logicalrelid::text FROM pg_dist_partition p JOIN pg_class k ON k.oid = p.logicalrelid WHERE k.relreplident = 'd' "
                        "AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = k.oid AND i.indisprimary) ORDER BY 1").fetchall()
    assert not sin, f"sin clave primaria (no se pueden reequilibrar sin parar): {[r[0] for r in sin]}"


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


def test_unir_una_tabla_distribuida_con_usuarios_funciona_con_el_rol_de_la_aplicacion(citus, como_app):
    """Hallazgo de la fase 9: la política de `usuarios` llama a una función que lee `usuarios_tenants`; al unirla con una tabla distribuida se evalúa DENTRO de la consulta del
    fragmento y Citus la rechazaba ("cannot execute a distributed query from a query on a shard") salvo que la función permita la ejecución anidada (solo lee tablas de referencia)."""
    _sembrar(citus)
    with psycopg.connect(citus, autocommit=True) as c:
        for u, t in ((10, 1), (20, 2)):
            c.execute("INSERT INTO usuarios_tenants (usuario_id, tenant_id, creado_en) VALUES (%s, %s, 'x') ON CONFLICT DO NOTHING", (u, t))
            c.execute("INSERT INTO correo_cuentas (tenant_id, usuario_id, nombre, protocolo, host, puerto, usuario, creada_en) VALUES (%s, %s, 'c', 'imap', 'h', 993, 'u', 'x')", (t, u))
    a = como_app()
    try:
        a.execute("SET LOCAL citus.propagate_set_commands = 'local'")
        a.execute("SET LOCAL app.tenant_id = '1'")
        a.execute("SET LOCAL app.usuario_id = '10'")
        assert a.execute("SELECT c.tenant_id FROM correo_cuentas c JOIN usuarios u ON u.id = c.usuario_id AND c.tenant_id = 1").fetchall() == [(1,)]
        assert a.execute("SELECT EXISTS(SELECT 1 FROM correo_cuentas c JOIN usuarios u ON u.id = c.usuario_id WHERE u.tenant_id = 2 AND c.tenant_id = 1)").fetchone()[0] is False, \
            "las personas de otro despacho no se ven en la unión"
        a.rollback()
    finally:
        a.close()


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


def _planificar(citus, **kw):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "migracion"))
    import validar_sql_citus
    ok, router, repartidas, fallos, inserciones = validar_sql_citus.validar(citus, valor="1", **kw)
    reales = [f for f in fallos if "cannot be coerced" not in f[2]]                 # los de «bytea» son del propio planificador de pruebas (pasa un entero)
    return ok, router, repartidas, reales


def test_ninguna_consulta_de_la_aplicacion_es_rechazada_por_citus_con_una_conexion_de_despacho(citus):
    """Planifica (sin ejecutar) todo el SQL de la aplicación como lo envía una conexión de la aplicación con despacho: reescrito y con el filtro de despacho."""
    ok, router, repartidas, reales = _planificar(citus, con_despacho=True)
    assert ok > 1700
    assert router > ok * 0.95, f"solo {router} de {ok} van a un solo shard"
    assert not reales, f"{len(reales)} consultas rechazadas por Citus:\n" + "\n".join(f"  {r}:{l}  {e}\n      {q}" for r, l, e, q in sorted(reales)[:15])


def test_las_consultas_de_la_plataforma_solo_fallan_las_conocidas(citus):
    """Una conexión de la plataforma (sin despacho) lleva solo las igualdades de tenant_id; las 4 de «participantes» con OR + vista se usan siempre desde una petición con despacho."""
    ok, router, repartidas, reales = _planificar(citus, reescribir=True)
    assert len(reales) <= 4, "\n".join(f"  {r}:{l}  {e}" for r, l, e, q in sorted(reales)[:10])


@pytest.fixture
def aplicacion_en_citus(citus, como_app, monkeypatch):
    """La aplicación entera apuntando a Citus: pool de la aplicación con el rol sujeto a RLS, pool de la plataforma con el que se la salta, y la reescritura activada."""
    from psycopg.conninfo import make_conninfo
    from app import bd
    from app.bd import postgres as pg
    with psycopg.connect(citus, autocommit=True) as c:
        c.execute("ALTER ROLE guilda_app PASSWORD 'prueba-app'")
        c.execute("ALTER ROLE guilda_plataforma PASSWORD 'prueba-plataforma'")
    pg.fijar_url(make_conninfo(citus, user="guilda_app", password="prueba-app"), make_conninfo(citus, user="guilda_plataforma", password="prueba-plataforma"))
    pg.activar_citus(True)
    monkeypatch.setattr(bd, "MOTOR", "postgres")
    yield
    pg.activar_citus(False)
    pg.fijar_url(None)


def test_la_aplicacion_corre_en_citus_con_su_despacho_y_los_trabajos_con_el_de_la_fila(citus, aplicacion_en_citus):
    from app import db
    from app.bd import contexto
    _sembrar(citus)
    with psycopg.connect(citus, autocommit=True) as c:
        c.execute("INSERT INTO usuarios_tenants (usuario_id, tenant_id, creado_en) VALUES (10, 1, 'x'), (20, 2, 'x') ON CONFLICT DO NOTHING")
    with contexto.en_despacho(1):
        conn = db.get_connection()
        nid = conn.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (?, ?, ?)", (10, "del despacho 1", "x")).lastrowid
        conn.execute("INSERT INTO categorias (usuario_id, nombre, creada_en) VALUES (?, 'P1', 'x')", (10,))
        conn.commit()
        fila = conn.execute("SELECT n.id, c.nombre FROM notas n LEFT JOIN categorias c ON c.usuario_id = n.usuario_id WHERE n.id = ?", (nid,)).fetchone()   # join sin tenant_id: lo añade la capa
        assert fila["id"] == nid and fila["nombre"] == "P1"
        conn.close()
    with contexto.en_despacho(2):
        conn = db.get_connection()
        assert conn.execute("SELECT COUNT(*) FROM notas WHERE id = ?", (nid,)).fetchone()[0] == 0, "el despacho 2 no ve la nota del 1"
        conn.close()
    with contexto.como_plataforma():                                                  # un trabajo en segundo plano: ve todo y no tiene despacho
        conn = db.get_connection()
        assert conn.execute("SELECT COUNT(*) FROM notas WHERE id = ?", (nid,)).fetchone()[0] == 1
        # inserta una fila de una persona SIN despacho en la conexión: el despacho sale de la persona (modelo de tenant_modelo.json)
        conn.execute("INSERT INTO notificaciones (usuario_id, tipo, titulo, creado_en) VALUES (?, 'aviso', 'hola', 'x')", (20,))
        conn.commit()
        assert conn.execute("SELECT tenant_id FROM notificaciones WHERE usuario_id = 20").fetchone()[0] == 2
        conn.close()
        # una fila que no se puede atribuir a ningún despacho se rechaza con un mensaje que dice qué hacer
        conn = db.get_connection()
        with pytest.raises(RuntimeError, match="sin despacho"):
            conn.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (?, 'huérfana', 'x')", (99999,))
        conn.close()


def test_borrar_un_despacho_borra_todo_lo_suyo_incluido_lo_personal(citus, aplicacion_en_citus):
    from app import db
    from app.bd import contexto
    with psycopg.connect(citus, autocommit=True) as c:
        c.execute("INSERT INTO tenants (id, nombre, creado_en) VALUES (77, 'A borrar', 'x') ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO usuarios (id, email, contrasena_hash, creado_en, tenant_id) VALUES (770, 'borrar@x.es', 'x', 'x', 77) ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO usuarios_tenants (usuario_id, tenant_id, creado_en) VALUES (770, 77, 'x') ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO notas (tenant_id, usuario_id, texto, creada_en) VALUES (77, 770, 'n', 'x')")
        c.execute("INSERT INTO clientes (tenant_id, nombre, creado_en) VALUES (77, 'Cliente', 'x')")
    db.borrar_tenant(77)
    with psycopg.connect(citus, autocommit=True) as c:
        assert c.execute("SELECT count(*) FROM tenants WHERE id = 77").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM notas WHERE tenant_id = 77").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM clientes WHERE tenant_id = 77").fetchone()[0] == 0
        assert c.execute("SELECT tenant_id FROM usuarios WHERE id = 770").fetchone()[0] is None, "la persona no se borra: se queda sin despacho"
