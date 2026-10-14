"""Auditoría unificada (app/auditoria.py): solo de anexado, en la misma transacción que el cambio y sin cruzar despachos."""
import sqlite3

import pytest

from app import auditoria as au, db


def test_registrar_y_listar_con_filtros_y_cursor(usuario_id):
    t = db.crear_tenant("Despacho Auditoría")
    u = db.crear_usuario_vinculado_a_kratos("audit@ejemplo.com", "k-audit"); db.asignar_tenant(u, t)
    for i in range(5):
        au.registrar(t, u, "cliente.editar", "cliente_fiscal", 10 + i, {"campo": "nif", "i": i})
    au.registrar(t, u, "obligacion.transicion", "obligacion", 99, "texto plano")
    todos = au.listar(t)
    assert len(todos) == 6 and todos[0]["entidad"] == "obligacion" and todos[0]["detalle"] == "texto plano" and todos[0]["actor"] == "audit@ejemplo.com"
    assert [e["entidad_id"] for e in au.listar(t, entidad="cliente_fiscal")] == ["14", "13", "12", "11", "10"]
    assert [e["detalle"]["i"] for e in au.listar(t, entidad="cliente_fiscal", entidad_id=12)] == [2]
    pagina = au.listar(t, limite=2)
    assert [e["id"] for e in au.listar(t, limite=2, antes_de_id=pagina[-1]["id"])] == [e["id"] for e in todos[2:4]]
    assert au.listar(db.crear_tenant("Otro despacho")) == [], "cada despacho ve lo suyo"


def test_no_se_puede_modificar_ni_borrar(usuario_id):
    t = db.crear_tenant("Despacho Auditoría 2")
    eid = au.registrar(t, None, "x", "y", 1)
    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.DatabaseError, match="solo de anexado"):
            conn.execute("UPDATE auditoria_eventos SET accion = 'otra' WHERE id = ?", (eid,))
        with pytest.raises(sqlite3.DatabaseError, match="solo de anexado"):
            conn.execute("DELETE FROM auditoria_eventos WHERE id = ?", (eid,))
        conn.rollback()
        assert conn.execute("SELECT accion FROM auditoria_eventos WHERE id = ?", (eid,)).fetchone()["accion"] == "x"
    finally:
        conn.close()


def test_el_evento_va_en_la_misma_transaccion_que_el_cambio(usuario_id):
    t = db.crear_tenant("Despacho Auditoría 3")
    conn = db.get_connection()
    try:
        au.registrar(t, None, "cambio", "cosa", 1, conn=conn)
        conn.rollback()                                    # el cambio se deshace: el rastro también
    finally:
        conn.close()
    assert au.listar(t) == []
    conn = db.get_connection()
    try:
        au.registrar(t, None, "cambio", "cosa", 2, conn=conn)
        conn.commit()
    finally:
        conn.close()
    assert [e["entidad_id"] for e in au.listar(t)] == ["2"]


def test_borrar_el_despacho_borra_su_rastro_y_el_permiso_no_se_queda_abierto(usuario_id):
    t = db.crear_tenant("Despacho a borrar")
    au.registrar(t, None, "x", "y", 1)
    otro = db.crear_tenant("Despacho que se queda"); au.registrar(otro, None, "x", "y", 2)
    db.borrar_tenant(t)
    assert au.listar(t) == [] and len(au.listar(otro)) == 1
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT valor FROM auditoria_control WHERE clave = 'permitir_borrado'").fetchone()["valor"] == "0"
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM auditoria_eventos")
    finally:
        conn.close()


def test_los_cambios_de_certificados_quedan_en_la_auditoria_unificada(usuario_id):
    from app import certificados as ce
    from tests.test_certificados import hacer_cert, pem
    t = db.crear_tenant("Despacho Auditoría Certs")
    u = db.crear_usuario_vinculado_a_kratos("sup-audit@ejemplo.com", "k-sup-audit"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    cid = ce.importar(t, u, pem(hacer_cert()))["id"]
    ce.cambiar_estado_operativo(t, u, cid, "autorizado")
    ev = au.listar(t, entidad="certificado", entidad_id=cid)
    assert [e["accion"] for e in ev] == ["certificado.estado_autorizado", "certificado.importado"] and ev[0]["actor"] == "sup-audit@ejemplo.com"
