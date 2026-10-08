"""El listado de vencimientos va paginado (con miles de filas la página tardaba segundos)."""
from datetime import date, timedelta

from app import db
from app.rutas_fiscal import VENCIMIENTOS_POR_PAGINA
from tests.conftest import iniciar_sesion_de_prueba


def test_listar_con_limite_y_offset_en_orden_estable():
    tenant = db.crear_tenant("Despacho paginación")
    cid = db.crear_cliente_fiscal(tenant, "C")
    for i in range(7):
        db.crear_vencimiento_fiscal(tenant, cid, f"M{i}", "1T", "2026-12-01")          # misma fecha: el orden tiene que ser estable
    todos = [v["id"] for v in db.listar_vencimientos_fiscales(tenant)]
    assert [v["id"] for v in db.listar_vencimientos_fiscales(tenant, limite=3)] == todos[:3]
    assert [v["id"] for v in db.listar_vencimientos_fiscales(tenant, limite=3, offset=3)] == todos[3:6]
    assert [v["id"] for v in db.listar_vencimientos_fiscales(tenant, limite=3, offset=6)] == todos[6:]
    assert db.listar_vencimientos_fiscales(tenant, limite=3, offset=-5) and len(db.listar_vencimientos_fiscales(tenant)) == 7


def test_pantalla_pagina_y_conserva_los_filtros(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "fp-1@x.com", "contrasena123")
    tenant = db.crear_tenant("Despacho pantalla paginación")
    db.asignar_tenant(uid, tenant)
    cid = db.crear_cliente_fiscal(tenant, "Cliente Único")
    base = date(2026, 12, 1)
    for i in range(VENCIMIENTOS_POR_PAGINA + 20):
        db.crear_vencimiento_fiscal(tenant, cid, f"M{i:03d}", "1T", (base + timedelta(days=i)).isoformat())
    p1 = cliente.get("/fiscal/vencimientos?estado=pendiente").get_data(as_text=True)
    assert p1.count('class="log-item vencimiento-fiscal-item') == VENCIMIENTOS_POR_PAGINA and "Página 1" in p1
    assert "M000" in p1 and "M099" in p1 and "M100" not in p1 and "pagina=2" in p1 and "estado=pendiente" in p1.split("pagina=2")[0][-200:]
    p2 = cliente.get("/fiscal/vencimientos?estado=pendiente&pagina=2").get_data(as_text=True)
    assert p2.count('class="log-item vencimiento-fiscal-item') == 20 and "M100" in p2 and "M119" in p2 and "pagina=1" in p2 and "Página 2" in p2
    assert "pagina=3" not in p2
    assert cliente.get("/fiscal/vencimientos?pagina=basura").status_code == 200
    assert cliente.get("/fiscal/vencimientos?pagina=99").status_code == 200                   # fuera de rango: página vacía, no un error
    corto = cliente.get(f"/fiscal/vencimientos?cliente_id={cid}&desde=2026-12-01&hasta=2026-12-03").get_data(as_text=True)
    assert corto.count('class="log-item vencimiento-fiscal-item') == 3 and "Anterior" not in corto
