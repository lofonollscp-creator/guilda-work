"""Reescritura de consultas para Citus (app/bd/citus.py): sin servidor, solo el analizador de PostgreSQL (pglast)."""
import pytest

pytest.importorskip("pglast")

from app.bd import citus  # noqa: E402


def r(sql):
    return citus.reescribir_sqlite(sql)


def test_un_join_entre_tablas_distribuidas_se_une_tambien_por_el_despacho():
    q = r("SELECT t.id FROM tareas_outlook t JOIN categorias c ON c.id = t.categoria_id WHERE t.usuario_id = ?")
    assert "t.tenant_id = c.tenant_id" in q and q.count("?") == 1


def test_no_se_toca_lo_que_ya_esta_unido_ni_lo_que_no_es_distribuido():
    assert r("SELECT t.id FROM tareas_outlook t JOIN categorias c ON c.id = t.categoria_id AND c.tenant_id = t.tenant_id") is None
    assert r("SELECT * FROM usuarios u JOIN tenants t ON t.id = u.tenant_id") is None               # referencia
    assert r("SELECT id FROM notas WHERE id = ?") is None
    assert r("PRAGMA foreign_keys = ON") is None                                                     # no es SQL de PostgreSQL: se deja
    uno = r("SELECT t.id FROM tareas_outlook t JOIN categorias c ON c.id = t.categoria_id")
    assert citus.reescribir_sqlite(uno) is None, "reescribir dos veces no añade nada"


def test_las_subconsultas_correlacionadas_con_una_tabla_distribuida_llevan_el_despacho():
    q = r("SELECT c.id, (SELECT COUNT(*) FROM ia_mensajes m WHERE m.conversacion_id = c.id) AS n FROM ia_conversaciones c WHERE c.usuario_id = ?")
    assert "m.tenant_id = c.tenant_id" in q
    q = r("UPDATE tareas_outlook SET vencimiento_id = (SELECT g.vencimiento_id FROM tareas_por_vencimiento_generadas g WHERE g.tarea_id = tareas_outlook.id) WHERE id = ?")
    assert "g.tenant_id = tareas_outlook.tenant_id" in q
    q = r("SELECT * FROM tareas_outlook t WHERE t.id IN (SELECT tarea_id FROM tareas_participantes WHERE usuario_id = ?)")
    assert "tareas_participantes.tenant_id = t.tenant_id" in q, "IN (...) también se correlaciona con la tabla exterior"


def test_from_con_coma_e_insert_select():
    assert "t.tenant_id = c.tenant_id" in r("SELECT * FROM tareas_outlook t, categorias c WHERE c.id = t.categoria_id")
    q = r("INSERT INTO cliente_etiquetas (cliente_id, etiqueta) SELECT ?, etiqueta FROM cliente_etiquetas WHERE cliente_id = ?")
    assert "(cliente_id, etiqueta, tenant_id)" in q and "cliente_etiquetas.tenant_id" in q


def test_los_marcadores_y_los_casts_sobreviven():
    q = r("SELECT t.id::text FROM tareas_outlook t JOIN categorias c ON c.id = t.categoria_id WHERE t.asunto = :asunto AND c.nombre = :nombre")
    assert ":asunto" in q and ":nombre" in q and "t.id::text" in q.replace("CAST", "") or "CAST(t.id AS text)" in q


def test_el_filtro_de_despacho_va_en_cada_consulta_y_en_sus_subconsultas():
    q = citus.reescribir_sqlite_con_despacho("SELECT c.id FROM ia_conversaciones c WHERE c.usuario_id = ? AND c.id IN (SELECT conversacion_id FROM ia_mensajes WHERE rol = ?)")
    assert q.count(citus.SENTINELA) == 2 and "c.tenant_id = " + citus.SENTINELA in q and "ia_mensajes.tenant_id = " + citus.SENTINELA in q
    assert citus.reescribir_sqlite_con_despacho("DELETE FROM notas WHERE id = ?").endswith("notas.tenant_id = " + citus.SENTINELA)
    assert citus.reescribir_sqlite_con_despacho("SELECT * FROM usuarios WHERE id = ?") is None
    assert citus.reescribir_sqlite_con_despacho("INSERT INTO notas (texto) VALUES (?)") is None
    # un grupo de tablas unidas lleva UN filtro; dos grupos sin unir, dos
    unido = citus.reescribir_sqlite_con_despacho("SELECT 1 FROM tareas_outlook t JOIN categorias c ON c.id = t.categoria_id")
    assert unido.count(citus.SENTINELA) == 1
