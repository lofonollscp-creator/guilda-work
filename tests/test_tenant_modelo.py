"""Modelo multitenant (fase 6a): a qué despacho pertenece cada fila, y personas en varios despachos."""
import json
import shutil
import sqlite3

import pytest

from app import db
from app.bd import tenant


def _conexion_plantilla(_plantilla_bd, tmp_path):
    ruta = tmp_path / "copia.db"
    shutil.copy(_plantilla_bd, ruta)
    return sqlite3.connect(ruta)


def test_el_modelo_del_repositorio_coincide_con_el_esquema_actual(_plantilla_bd, tmp_path):
    """Una tabla nueva obliga a decidir a qué despacho pertenece: regenera con app.bd.tenant.escribir_modelo(<base limpia de init_db>) y revisa el cambio."""
    con = _conexion_plantilla(_plantilla_bd, tmp_path)
    actual = {t: c.como_dict() for t, c in sorted(tenant.clasificar(con).items())}
    guardado = json.loads(tenant.FICHERO_MODELO.read_text(encoding="utf-8"))
    nuevas = sorted(set(actual) - set(guardado))
    assert not nuevas, f"tablas sin clasificar en app/bd/tenant_modelo.json: {nuevas}"
    assert actual == guardado, "el modelo guardado está desactualizado: regenéralo con tenant.escribir_modelo()"


def test_todas_las_tablas_tienen_una_clase_y_las_hijas_un_camino_hacia_un_despacho(_plantilla_bd, tmp_path):
    con = _conexion_plantilla(_plantilla_bd, tmp_path)
    clases = tenant.clasificar(con)
    assert not [t for t, c in clases.items() if c.nombre == "revisar"]
    assert all(c.via for t, c in clases.items() if c.nombre == "hija")
    assert all(c.via for t, c in clases.items() if c.nombre == "usuario")
    orden = tenant.orden_de_relleno(clases)                 # lanza si hubiera un ciclo
    pos = {t: i for i, t in enumerate(orden)}
    for t in orden:
        for v in clases[t].via:
            if v.padre in pos and v.padre != t:
                assert pos[v.padre] < pos[t], f"{t} se rellena antes que su padre {v.padre}"
    for t in ("tenants", "usuarios", "usuarios_tenants", "planes_guilda"):
        assert clases[t].nombre == "referencia"
    for t in ("tareas_outlook", "notas", "correo_cuentas", "ia_mensajes"):
        assert clases[t].nombre == "usuario"
    for t in ("correo_mensajes", "notas_adjuntos", "tarea_comentarios"):
        assert clases[t].nombre == "hija"
    assert clases["correo_mensajes"].via[0].columna == "cuenta_id"            # la clave OBLIGATORIA va primero


def test_el_relleno_deduce_el_despacho_de_la_persona_y_del_padre_y_es_idempotente():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE tenants (id INTEGER PRIMARY KEY);
        CREATE TABLE usuarios (id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id));
        CREATE TABLE notas (id INTEGER PRIMARY KEY, usuario_id INTEGER REFERENCES usuarios(id), texto TEXT);
        CREATE TABLE notas_adjuntos (id INTEGER PRIMARY KEY, nota_id INTEGER NOT NULL REFERENCES notas(id), usuario_id INTEGER REFERENCES usuarios(id));
        CREATE TABLE fichajes (id INTEGER PRIMARY KEY, tenant_id INTEGER REFERENCES tenants(id), usuario_id INTEGER REFERENCES usuarios(id));
        INSERT INTO tenants VALUES (1), (2);
        INSERT INTO usuarios VALUES (10, 1), (20, 2), (30, NULL);
        INSERT INTO notas VALUES (1, 10, 'a'), (2, 20, 'b'), (3, 30, 'c');
        INSERT INTO notas_adjuntos VALUES (1, 1, 20), (2, 2, 10), (3, 3, NULL);
        INSERT INTO fichajes VALUES (1, NULL, 10), (2, 2, 20), (3, NULL, 30);
    """)
    clases = {
        "tenants": tenant.Clase("referencia", ""), "usuarios": tenant.Clase("referencia", ""),
        "fichajes": tenant.Clase("propio", "", [tenant.Via("usuario_id", "usuarios", "id", False)]),
        "notas": tenant.Clase("usuario", "", [tenant.Via("usuario_id", "usuarios", "id", False)]),
        "notas_adjuntos": tenant.Clase("hija", "", [tenant.Via("nota_id", "notas", "id", True), tenant.Via("usuario_id", "usuarios", "id", False)]),
    }
    antes = tenant.cargar_modelo
    tenant.cargar_modelo = lambda: clases
    try:
        cambios = tenant.rellenar(con, crear_columnas=True)
        assert cambios == {"fichajes": 1, "notas": 2, "notas_adjuntos": 2}, cambios
        assert con.execute("SELECT id, tenant_id FROM notas ORDER BY id").fetchall() == [(1, 1), (2, 2), (3, None)]          # la persona 30 no tiene despacho
        assert con.execute("SELECT id, tenant_id FROM notas_adjuntos ORDER BY id").fetchall() == [(1, 1), (2, 2), (3, None)]  # del padre, no del autor (adjunto 1: autor del despacho 2)
        assert con.execute("SELECT id, tenant_id FROM fichajes ORDER BY id").fetchall() == [(1, 1), (2, 2), (3, None)]
        assert tenant.rellenar(con) == {"fichajes": 0, "notas": 0, "notas_adjuntos": 0}, "segunda pasada: no toca nada"
        inf = tenant.informe(con)
        assert inf["notas"]["sin_despacho"] == 1 and inf["notas_adjuntos"]["distinto_del_padre"] == 0
    finally:
        tenant.cargar_modelo = antes


def test_lo_que_no_tiene_despacho_va_al_despacho_plataforma():
    assert tenant.TENANT_PLATAFORMA == 0 and tenant.NOMBRE_PLATAFORMA == "Plataforma"
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE tenants (id INTEGER PRIMARY KEY);
        CREATE TABLE usuarios (id INTEGER PRIMARY KEY, tenant_id INTEGER);
        CREATE TABLE notas (id INTEGER PRIMARY KEY, usuario_id INTEGER REFERENCES usuarios(id));
        CREATE TABLE jur_auditoria (id INTEGER PRIMARY KEY, tenant_id INTEGER);
        INSERT INTO usuarios VALUES (10, 1), (30, NULL);
        INSERT INTO notas VALUES (1, 10), (2, 30);
        INSERT INTO jur_auditoria VALUES (1, NULL), (2, 7);
    """)
    clases = {"tenants": tenant.Clase("referencia", ""), "usuarios": tenant.Clase("referencia", ""), "jur_auditoria": tenant.Clase("propio", ""),
              "notas": tenant.Clase("usuario", "", [tenant.Via("usuario_id", "usuarios", "id", False)])}
    antes = tenant.cargar_modelo
    tenant.cargar_modelo = lambda: clases
    try:
        tenant.rellenar(con, crear_columnas=True, por_defecto=tenant.TENANT_PLATAFORMA)
        assert con.execute("SELECT tenant_id FROM notas ORDER BY id").fetchall() == [(1,), (0,)]
        assert con.execute("SELECT tenant_id FROM jur_auditoria ORDER BY id").fetchall() == [(0,), (7,)]
        assert sum(tenant.rellenar(con, por_defecto=0).values()) == 0
    finally:
        tenant.cargar_modelo = antes


def test_el_despacho_plataforma_no_se_puede_borrar():
    with pytest.raises(ValueError, match="Plataforma"):
        db.borrar_tenant(0)


def test_el_relleno_sobre_el_esquema_real_no_falla_ni_ensucia_el_historial(_plantilla_bd, tmp_path):
    con = _conexion_plantilla(_plantilla_bd, tmp_path)
    con.execute("PRAGMA foreign_keys = ON")
    t = con.execute("INSERT INTO tenants (nombre, creado_en) VALUES ('D', 'x')").lastrowid
    u = con.execute("INSERT INTO usuarios (email, contrasena_hash, creado_en, tenant_id) VALUES ('a@a.a', 'x', 'x', ?)", (t,)).lastrowid
    con.execute("INSERT INTO notas (usuario_id, texto, creada_en) VALUES (?, 'hola', 'x')", (u,))
    con.commit()
    cambios_previos = con.execute("SELECT COUNT(*) FROM api_cambios").fetchone()[0]
    disparadores = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'").fetchone()[0]
    tenant.rellenar(con, crear_columnas=True)
    assert con.execute("SELECT tenant_id FROM notas").fetchone()[0] == t
    assert con.execute("SELECT COUNT(*) FROM api_cambios").fetchone()[0] == cambios_previos, "el relleno no debe generar historial de cambios"
    assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'").fetchone()[0] == disparadores
    assert tenant.rellenar(con) and sum(tenant.rellenar(con).values()) == 0


# --- una persona en varios despachos -------------------------------------------------------------------------------------------------------------

def _usuario(email="p@x.es"):
    return db.crear_usuario(email, "contraseña-larga-123")


def test_el_despacho_principal_figura_siempre_entre_los_despachos_de_la_persona():
    t1 = db.crear_tenant("Uno")
    u = _usuario()
    assert db.tenants_de_usuario(u) == []
    db.asignar_tenant(u, t1)
    assert [(d["id"], d["principal"]) for d in db.tenants_de_usuario(u)] == [(t1, 1)]
    assert db.es_miembro_de_tenant(u, t1)


def test_una_persona_puede_pertenecer_a_varios_despachos():
    t1, t2, t3 = db.crear_tenant("Alfa"), db.crear_tenant("Beta"), db.crear_tenant("Gamma")
    u = _usuario()
    db.anadir_usuario_a_tenant(u, t1)                                   # sin despacho: el primero pasa a ser el principal
    db.anadir_usuario_a_tenant(u, t2)
    db.anadir_usuario_a_tenant(u, t2)                                   # repetirlo no duplica
    db.anadir_usuario_a_tenant(u, t3)
    assert [(d["nombre"], d["principal"]) for d in db.tenants_de_usuario(u)] == [("Alfa", 1), ("Beta", 0), ("Gamma", 0)]
    assert db.obtener_usuario(u)["tenant_id"] == t1              # el resto de la aplicación sigue viendo UN despacho
    db.fijar_tenant_principal(u, t3)
    assert db.obtener_usuario(u)["tenant_id"] == t3 and db.tenants_de_usuario(u)[0]["id"] == t3
    with pytest.raises(ValueError, match="no pertenece"):
        db.fijar_tenant_principal(u, db.crear_tenant("Delta"))
    db.quitar_usuario_de_tenant(u, t3)                                  # era el principal: pasa al siguiente
    assert db.obtener_usuario(u)["tenant_id"] == t1 and not db.es_miembro_de_tenant(u, t3)
    db.quitar_usuario_de_tenant(u, t1)
    db.quitar_usuario_de_tenant(u, t2)
    assert db.obtener_usuario(u)["tenant_id"] is None and db.tenants_de_usuario(u) == []
    with pytest.raises(ValueError):
        db.anadir_usuario_a_tenant(u, 99999)
    with pytest.raises(ValueError):
        db.anadir_usuario_a_tenant(99999, t1)


def test_asignar_tenant_sigue_moviendo_a_la_persona_y_desasignar_la_saca_de_todos():
    t1, t2 = db.crear_tenant("Uno"), db.crear_tenant("Dos")
    u = _usuario()
    db.asignar_tenant(u, t1)
    db.anadir_usuario_a_tenant(u, t2)
    db.asignar_tenant(u, t2)                                            # comportamiento de siempre: se muda, no se suma
    assert [d["id"] for d in db.tenants_de_usuario(u)] == [t2] and db.obtener_usuario(u)["tenant_id"] == t2
    db.anadir_usuario_a_tenant(u, t1)
    db.desasignar_tenant(u)
    assert db.tenants_de_usuario(u) == [] and db.obtener_usuario(u)["tenant_id"] is None


def test_borrar_un_despacho_pasa_a_sus_miembros_al_siguiente_que_tengan():
    t1, t2 = db.crear_tenant("Primero"), db.crear_tenant("Segundo")
    solo, doble = _usuario("solo@x.es"), _usuario("doble@x.es")
    db.asignar_tenant(solo, t1)
    db.anadir_usuario_a_tenant(doble, t1)
    db.anadir_usuario_a_tenant(doble, t2)
    db.borrar_tenant(t1)
    assert db.obtener_usuario(solo)["tenant_id"] is None and db.tenants_de_usuario(solo) == []
    assert db.obtener_usuario(doble)["tenant_id"] == t2 and [d["id"] for d in db.tenants_de_usuario(doble)] == [t2]


@pytest.mark.solo_sqlite
def test_init_db_incorpora_a_la_pertenencia_a_quien_ya_tenia_despacho(tmp_path):
    t1 = db.crear_tenant("Preexistente")
    u = _usuario()
    conn = db.get_connection()
    conn.execute("UPDATE usuarios SET tenant_id = ? WHERE id = ?", (t1, u))          # como estaban las bases anteriores a la tabla
    conn.execute("DELETE FROM usuarios_tenants")
    conn.commit()
    conn.close()
    db.init_db()
    db.init_db()                                                                       # idempotente
    assert [d["id"] for d in db.tenants_de_usuario(u)] == [t1]
