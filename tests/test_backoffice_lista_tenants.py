"""Búsqueda/filtro/orden de la lista de tenants en el backoffice renovado
(app/rutas_backoffice.py:panel())."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def _admin(cliente, email="lista-tenants-admin@ejemplo.com"):
    admin_id = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.hacer_admin(db.obtener_usuario(admin_id)["email"])
    return admin_id


def test_panel_sin_filtros_lista_todos_ordenados_por_nombre(cliente):
    db.crear_tenant("Zeta Gestoria")
    db.crear_tenant("Alfa Gestoria")
    _admin(cliente)

    resp = cliente.get("/backoffice/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert html.index("Alfa Gestoria") < html.index("Zeta Gestoria")


def test_panel_busca_por_nombre(cliente):
    db.crear_tenant("Lueira Ski")
    db.crear_tenant("Guilda Fiscal")
    _admin(cliente)

    resp = cliente.get("/backoffice/?q=lueira")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Lueira Ski" in html
    assert "Guilda Fiscal" not in html


def test_panel_orden_por_usuarios(cliente):
    tenant_pocos = db.crear_tenant("Gestoria Pocos Usuarios")
    tenant_muchos = db.crear_tenant("Gestoria Muchos Usuarios")
    for i in range(3):
        u = db.crear_usuario_vinculado_a_kratos(f"lista-tenants-u{i}@ejemplo.com", f"kratos-lista-tenants-u{i}")
        db.asignar_tenant(u, tenant_muchos)
    u_solo = db.crear_usuario_vinculado_a_kratos("lista-tenants-solo@ejemplo.com", "kratos-lista-tenants-solo")
    db.asignar_tenant(u_solo, tenant_pocos)
    _admin(cliente)

    resp = cliente.get("/backoffice/?orden=usuarios")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert html.index("Gestoria Muchos Usuarios") < html.index("Gestoria Pocos Usuarios")


def test_panel_filtra_por_modulo_visible(cliente):
    from app import herramientas

    tenant_con = db.crear_tenant("Gestoria Con Modulo")
    tenant_sin = db.crear_tenant("Gestoria Sin Modulo")
    herramienta_id = herramientas.HERRAMIENTAS[0]["id"]
    db.ocultar_herramienta(tenant_sin, herramienta_id)
    _admin(cliente)

    resp = cliente.get(f"/backoffice/?modulo={herramienta_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Gestoria Con Modulo" in html
    assert "Gestoria Sin Modulo" not in html
