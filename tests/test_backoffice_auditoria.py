"""Auditoría global del backoffice (K4): búsqueda y exportación de los eventos de todos los despachos y cadena de integridad de las acciones del backoffice."""
import csv
import io

import pytest

from app import auditoria, db
from backoffice import auditoria_global as ag, auth
from tests.test_backoffice_app import bo, entrar, post  # noqa: F401 -- fixture


def _despachos():
    a, b = db.crear_tenant("Despacho Alfa"), db.crear_tenant("Despacho Beta")
    ua = db.crear_usuario_vinculado_a_kratos("alfa@ejemplo.com", "k-alfa")
    ub = db.crear_usuario_vinculado_a_kratos("beta@ejemplo.com", "k-beta")
    db.asignar_tenant(ua, a); db.asignar_tenant(ub, b)
    auditoria.registrar(a, ua, "portal.entrada", "cliente_fiscal", 1, {"quien": "x"})
    auditoria.registrar(a, ua, "factura.crear", "factura", 7)
    auditoria.registrar(b, ub, "portal.entrada", "cliente_fiscal", 2)
    return a, b


def test_busca_en_todos_los_despachos_y_filtra():
    a, b = _despachos()
    assert {f["despacho"] for f in ag.buscar()} >= {"Despacho Alfa", "Despacho Beta"}
    assert [f["despacho"] for f in ag.buscar(accion="portal.")] == ["Despacho Beta", "Despacho Alfa"]
    assert {f["accion"] for f in ag.buscar(tenant_id=a)} == {"portal.entrada", "factura.crear"}
    assert [f["actor"] for f in ag.buscar(actor="BETA@")] == ["beta@ejemplo.com"]
    assert ag.buscar(accion="no_existe") == []


def test_los_comodines_del_buscador_no_se_interpretan():
    _despachos()
    assert ag.buscar(accion="%") == [] and ag.buscar(accion="_") == []


def test_paginacion_por_cursor():
    a, b = _despachos()
    todas = ag.buscar(tenant_id=a)
    primera = ag.buscar(tenant_id=a, limite=1)
    segunda = ag.buscar(tenant_id=a, antes_de_id=primera[-1]["id"], limite=1)
    assert [primera[0]["id"], segunda[0]["id"]] == [f["id"] for f in todas[:2]]


def test_el_csv_no_ejecuta_formulas():
    texto = ag.a_csv([{"id": 1, "creado_en": "2026-11-01", "despacho": "=HYPERLINK(\"x\")", "actor": "+a", "accion": "ok", "entidad": "@b", "entidad_id": "-1", "detalle": "texto, con coma"}])
    filas = list(csv.reader(io.StringIO(texto)))
    assert filas[0][:3] == ["id", "creado_en", "despacho"]
    assert filas[1][2].startswith("'=") and filas[1][3].startswith("'+") and filas[1][4] == "ok" and filas[1][7] == "texto, con coma"


def test_la_cadena_detecta_cambios_y_borrados_en_medio(bo):
    entrar(bo)
    for i in range(4):
        bo.get("/auditoria/backoffice.csv")                              # cada exportación deja su apunte
    assert auth.verificar_cadena()["ok"] and auth.verificar_cadena()["comprobados"] >= 3
    conn = auth.conectar()
    ids = [r["id"] for r in conn.execute("SELECT id FROM auditoria WHERE hash IS NOT NULL ORDER BY id").fetchall()]
    conn.execute("UPDATE auditoria SET detalle = 'manipulado' WHERE id = ?", (ids[1],)); conn.commit(); conn.close()
    r = auth.verificar_cadena()
    assert not r["ok"] and r["rota_en"] == ids[1]


def test_borrar_un_apunte_intermedio_rompe_la_cadena(bo):
    entrar(bo)
    for i in range(4):
        bo.get("/auditoria/backoffice.csv")
    conn = auth.conectar()
    ids = [r["id"] for r in conn.execute("SELECT id FROM auditoria WHERE hash IS NOT NULL ORDER BY id").fetchall()]
    conn.execute("DELETE FROM auditoria WHERE id = ?", (ids[1],)); conn.commit(); conn.close()
    r = auth.verificar_cadena()
    assert not r["ok"] and r["rota_en"] == ids[2]


def test_los_apuntes_anteriores_a_la_cadena_no_la_rompen(bo):
    entrar(bo)
    conn = auth.conectar()
    conn.execute("INSERT INTO auditoria (admin_usuario, accion, detalle, creado_en) VALUES ('viejo', 'antigua', 'sin hash', '2020-01-01T00:00:00')"); conn.commit(); conn.close()
    bo.get("/auditoria/backoffice.csv")
    r = auth.verificar_cadena()
    assert r["ok"] and r["sin_hash"] >= 1


def test_pantalla_y_exportaciones(bo):
    a, b = _despachos()
    entrar(bo)
    html = bo.get("/auditoria").get_data(as_text=True)
    assert "Cadena íntegra" in html and "Despacho Alfa" in html and "portal.entrada" in html
    filtrada = bo.get(f"/auditoria?tenant_id={a}&accion=factura").get_data(as_text=True)
    assert "factura.crear" in filtrada and "<td>Despacho Beta</td>" not in filtrada
    r = bo.get("/auditoria.csv?accion=portal.")
    assert r.status_code == 200 and r.mimetype == "text/csv" and "portal.entrada" in r.get_data(as_text=True) and "factura.crear" not in r.get_data(as_text=True)
    r2 = bo.get("/auditoria/backoffice.csv")
    assert r2.status_code == 200 and "hash_previo" in r2.get_data(as_text=True)
    assert bo.get("/auditoria", follow_redirects=False).status_code == 200
