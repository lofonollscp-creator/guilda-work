"""Capa ruta del calendario fiscal: guard de tenant y aislamiento entre
tenants (misma garantía que tests/test_aislamiento_tenants.py, ahora para
la primera tabla filtrada por tenant_id en vez de usuario_id)."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def test_sin_sesion_redirige_a_login(cliente):
    resp = cliente.get("/fiscal/vencimientos")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_con_sesion_pero_sin_tenant_da_403(cliente):
    iniciar_sesion_de_prueba(cliente, "sin-tenant@ejemplo.com", "contrasena123")
    resp = cliente.get("/fiscal/vencimientos")
    assert resp.status_code == 403
    resp = cliente.get("/fiscal/clientes")
    assert resp.status_code == 403


def test_con_tenant_puede_crear_y_ver_sus_clientes(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "con-tenant@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Ruta")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.post("/fiscal/clientes", data={"nombre": "Panadería SL", "nif": "B1"})
    assert resp.status_code == 302

    resp = cliente.get("/fiscal/clientes")
    assert resp.status_code == 200
    assert "Panadería SL" in resp.get_data(as_text=True)


def test_usuario_de_un_tenant_no_ve_clientes_fiscales_de_otro(cliente):
    usuario_a = iniciar_sesion_de_prueba(cliente, "fiscal-a@ejemplo.com", "contrasena123")
    tenant_a = db.crear_tenant("Gestoria A")
    db.asignar_tenant(usuario_a, tenant_a)
    cliente_a_id = db.crear_cliente_fiscal(tenant_a, "Cliente de A")

    from app.auth import limiter
    from app.main import app as flask_app

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as cliente_b_http:
        usuario_b = iniciar_sesion_de_prueba(cliente_b_http, "fiscal-b@ejemplo.com", "contrasena123")
        tenant_b = db.crear_tenant("Gestoria B")
        db.asignar_tenant(usuario_b, tenant_b)

        # Ni en el listado...
        resp_lista = cliente_b_http.get("/fiscal/clientes")
        assert "Cliente de A" not in resp_lista.get_data(as_text=True)

        # ...ni adivinando la URL de edición del cliente de A.
        resp_editar = cliente_b_http.get(f"/fiscal/clientes/{cliente_a_id}/editar")
        assert resp_editar.status_code == 404

        resp_eliminar = cliente_b_http.post(f"/fiscal/clientes/{cliente_a_id}/eliminar")
        assert resp_eliminar.status_code == 404

    # El cliente de A sigue intacto.
    assert db.obtener_cliente_fiscal(tenant_a, cliente_a_id) is not None


def test_usuario_de_un_tenant_no_ve_vencimientos_de_otro(cliente):
    usuario_a = iniciar_sesion_de_prueba(cliente, "venc-a@ejemplo.com", "contrasena123")
    tenant_a = db.crear_tenant("Gestoria Venc A")
    db.asignar_tenant(usuario_a, tenant_a)
    cliente_a_id = db.crear_cliente_fiscal(tenant_a, "Cliente Venc A")
    v_a_id = db.crear_vencimiento_fiscal(tenant_a, cliente_a_id, "303", "2026-T1", "2026-04-20")

    from app.auth import limiter
    from app.main import app as flask_app

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as cliente_b_http:
        usuario_b = iniciar_sesion_de_prueba(cliente_b_http, "venc-b@ejemplo.com", "contrasena123")
        tenant_b = db.crear_tenant("Gestoria Venc B")
        db.asignar_tenant(usuario_b, tenant_b)

        resp = cliente_b_http.get(f"/fiscal/vencimientos/{v_a_id}/editar")
        assert resp.status_code == 404

        resp = cliente_b_http.post(f"/fiscal/vencimientos/{v_a_id}/presentado")
        assert resp.status_code == 404

        resp = cliente_b_http.post(f"/fiscal/vencimientos/{v_a_id}/eliminar")
        assert resp.status_code == 404

    v_tras_intentos = db.obtener_vencimiento_fiscal(tenant_a, v_a_id)
    assert v_tras_intentos is not None
    assert v_tras_intentos["estado"] == "pendiente"


def test_generar_vencimientos_formulario_y_confirmacion(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "generar@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Generar")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Generar")

    resp = cliente.get(f"/fiscal/clientes/{cliente_id}/generar-vencimientos?modelo=303&anio=2026")
    assert resp.status_code == 200
    assert "2026-04-20" in resp.get_data(as_text=True)

    resp = cliente.post(
        f"/fiscal/clientes/{cliente_id}/generar-vencimientos",
        data={"modelo_0": "303", "periodo_0": "2026-T1", "fecha_limite_0": "2026-04-20"},
    )
    assert resp.status_code == 302
    vencimientos = db.listar_vencimientos_fiscales(tenant_id)
    assert len(vencimientos) == 1
    assert vencimientos[0]["modelo"] == "303"
