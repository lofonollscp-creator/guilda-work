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


def test_papelera_fiscal_restaurar_y_eliminar_definitivamente(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "papelera@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Papelera")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Papelera")

    resp = cliente.post(f"/fiscal/clientes/{cliente_id}/eliminar")
    assert resp.status_code == 302
    assert db.obtener_cliente_fiscal(tenant_id, cliente_id) is None

    resp = cliente.get("/fiscal/papelera")
    assert "Cliente Papelera" in resp.get_data(as_text=True)

    resp = cliente.post(f"/fiscal/papelera/cliente_fiscal/{cliente_id}/restaurar")
    assert resp.status_code == 302
    assert db.obtener_cliente_fiscal(tenant_id, cliente_id) is not None

    cliente.post(f"/fiscal/clientes/{cliente_id}/eliminar")
    resp = cliente.post(f"/fiscal/papelera/cliente_fiscal/{cliente_id}/eliminar-definitivamente")
    assert resp.status_code == 302
    assert db.listar_clientes_fiscales(tenant_id) == []
    assert db.papelera_fiscal(tenant_id) == []


def test_papelera_fiscal_tipo_desconocido_da_404(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "papelera-tipo@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Papelera Tipo")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.post("/fiscal/papelera/no-existe/1/restaurar")
    assert resp.status_code == 404


def test_papelera_fiscal_no_toca_lo_de_otro_tenant(cliente):
    usuario_a = iniciar_sesion_de_prueba(cliente, "papelera-a@ejemplo.com", "contrasena123")
    tenant_a = db.crear_tenant("Gestoria Papelera A")
    db.asignar_tenant(usuario_a, tenant_a)
    cliente_a_id = db.crear_cliente_fiscal(tenant_a, "Cliente Papelera A")
    db.eliminar_cliente_fiscal(tenant_a, cliente_a_id)

    from app.auth import limiter
    from app.main import app as flask_app

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as cliente_b_http:
        usuario_b = iniciar_sesion_de_prueba(cliente_b_http, "papelera-b@ejemplo.com", "contrasena123")
        tenant_b = db.crear_tenant("Gestoria Papelera B")
        db.asignar_tenant(usuario_b, tenant_b)

        # El WHERE tenant_id de restaurar_cliente_fiscal simplemente no
        # afecta ninguna fila -- redirige igual (mismo criterio que el
        # resto de rutas de papelera, ver app/main.py), pero el cliente de
        # A sigue en su papelera, no se restaura para B.
        resp = cliente_b_http.post(f"/fiscal/papelera/cliente_fiscal/{cliente_a_id}/restaurar")
        assert resp.status_code == 302

    assert db.obtener_cliente_fiscal(tenant_a, cliente_a_id) is None
    assert {i["id"] for i in db.papelera_fiscal(tenant_a)} == {cliente_a_id}


def test_crear_editar_cliente_con_modelos_fiscales_y_generacion_automatica(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "modelos@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Modelos Ruta")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.post("/fiscal/clientes", data={"nombre": "Panadería SL", "modelos_fiscales": ["303", "130"]})
    assert resp.status_code == 302
    cliente_id = db.listar_clientes_fiscales(tenant_id)[0]["id"]
    assert db.modelos_fiscales_de_cliente(db.obtener_cliente_fiscal(tenant_id, cliente_id)) == ["303", "130"]

    resp = cliente.post(
        f"/fiscal/clientes/{cliente_id}/editar",
        data={"nombre": "Panadería SL", "modelos_fiscales": ["390"], "generacion_automatica": "on"},
    )
    assert resp.status_code == 302
    fila = db.obtener_cliente_fiscal(tenant_id, cliente_id)
    assert db.modelos_fiscales_de_cliente(fila) == ["390"]
    assert fila["generacion_automatica"] == 1


def test_ficha_cliente_muestra_sus_vencimientos_y_aisla_por_tenant(cliente):
    usuario_a = iniciar_sesion_de_prueba(cliente, "ficha-a@ejemplo.com", "contrasena123")
    tenant_a = db.crear_tenant("Gestoria Ficha A")
    db.asignar_tenant(usuario_a, tenant_a)
    cliente_a_id = db.crear_cliente_fiscal(tenant_a, "Cliente Ficha A")
    db.crear_vencimiento_fiscal(tenant_a, cliente_a_id, "303", "2026-T1", "2026-04-20")

    resp = cliente.get(f"/fiscal/clientes/{cliente_a_id}")
    assert resp.status_code == 200
    assert "303" in resp.get_data(as_text=True)

    from app.auth import limiter
    from app.main import app as flask_app

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as cliente_b_http:
        usuario_b = iniciar_sesion_de_prueba(cliente_b_http, "ficha-b@ejemplo.com", "contrasena123")
        tenant_b = db.crear_tenant("Gestoria Ficha B")
        db.asignar_tenant(usuario_b, tenant_b)
        resp = cliente_b_http.get(f"/fiscal/clientes/{cliente_a_id}")
        assert resp.status_code == 404


def test_generar_vencimientos_usa_modelos_fiscales_del_cliente_por_defecto(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "defecto@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Defecto")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Defecto", modelos_fiscales=["390"])

    # Sin `modelo` en la query, debe partir de los modelos guardados del
    # cliente (390 anual, una sola propuesta) y no de TODOS los modelos
    # disponibles (que darían varias filas de trimestrales + anuales).
    resp = cliente.get(f"/fiscal/clientes/{cliente_id}/generar-vencimientos")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "2027-01-30" in html  # fecha límite de 390
    assert html.count('name="fecha_limite_') == 1


def test_generar_vencimientos_masivo_crea_para_todos_los_clientes_con_modelos(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "masivo@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Masivo")
    db.asignar_tenant(usuario_id, tenant_id)
    db.crear_cliente_fiscal(tenant_id, "Con modelos", modelos_fiscales=["390"])
    db.crear_cliente_fiscal(tenant_id, "Sin modelos")  # no debe generar nada

    resp = cliente.get("/fiscal/generar-vencimientos-masivo?anio=2026")
    assert resp.status_code == 200
    assert "Con modelos" in resp.get_data(as_text=True)
    assert "Sin modelos" not in resp.get_data(as_text=True)

    resp = cliente.post("/fiscal/generar-vencimientos-masivo", data={"anio": "2026"})
    assert resp.status_code == 302
    vencimientos = db.listar_vencimientos_fiscales(tenant_id)
    assert len(vencimientos) == 1
    assert vencimientos[0]["modelo"] == "390"


def test_export_csv_y_json(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "export@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Export")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Export")
    db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")

    resp = cliente.get("/fiscal/vencimientos/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "Cliente Export" in resp.get_data(as_text=True)

    resp = cliente.get("/fiscal/vencimientos/export.json")
    assert resp.status_code == 200
    datos = resp.get_json() if resp.is_json else __import__("json").loads(resp.get_data(as_text=True))
    assert datos[0]["cliente"] == "Cliente Export"
    assert datos[0]["modelo"] == "303"


def test_crear_cliente_sin_espocrm_api_key_no_falla_ni_rellena_nada(cliente, monkeypatch):
    from app import espocrm

    monkeypatch.setattr(espocrm, "ESPOCRM_API_KEY", None)
    usuario_id = iniciar_sesion_de_prueba(cliente, "sin-espocrm@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Sin EspoCRM")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.post("/fiscal/clientes", data={"nombre": "Sin EspoCRM SL"})
    assert resp.status_code == 302
    cliente_id = db.listar_clientes_fiscales(tenant_id)[0]["id"]
    assert db.obtener_cliente_fiscal(tenant_id, cliente_id)["espocrm_cuenta_id"] is None

    resp = cliente.get(f"/fiscal/clientes/{cliente_id}/espocrm")
    assert resp.status_code == 404


def test_crear_cliente_con_espocrm_disponible_guarda_cuenta_y_enlaza(cliente, monkeypatch):
    from app import espocrm

    monkeypatch.setattr(espocrm, "ESPOCRM_API_KEY", "fake-key")
    monkeypatch.setattr(espocrm, "buscar_cuenta_por_nombre", lambda nombre: None)
    monkeypatch.setattr(espocrm, "crear_cuenta", lambda nombre, sitio_web="": {"id": "espo123"})
    monkeypatch.setattr(espocrm, "url_cuenta", lambda cuenta_id: f"https://crm.ejemplo.com/#Account/view/{cuenta_id}")

    usuario_id = iniciar_sesion_de_prueba(cliente, "con-espocrm@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Con EspoCRM")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.post("/fiscal/clientes", data={"nombre": "Con EspoCRM SL"})
    assert resp.status_code == 302
    cliente_id = db.listar_clientes_fiscales(tenant_id)[0]["id"]
    assert db.obtener_cliente_fiscal(tenant_id, cliente_id)["espocrm_cuenta_id"] == "espo123"

    resp = cliente.get(f"/fiscal/clientes/{cliente_id}")
    assert "Ver en EspoCRM" in resp.get_data(as_text=True)

    resp = cliente.get(f"/fiscal/clientes/{cliente_id}/espocrm", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://crm.ejemplo.com/#Account/view/espo123"


def test_crear_cliente_con_espocrm_inalcanzable_no_bloquea_el_alta(cliente, monkeypatch):
    from app import espocrm

    def _falla(*args, **kwargs):
        raise espocrm.ErrorEspoCRM("no se ha podido conectar")

    monkeypatch.setattr(espocrm, "ESPOCRM_API_KEY", "fake-key")
    monkeypatch.setattr(espocrm, "buscar_cuenta_por_nombre", _falla)

    usuario_id = iniciar_sesion_de_prueba(cliente, "espocrm-caido@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria EspoCRM Caido")
    db.asignar_tenant(usuario_id, tenant_id)

    resp = cliente.post("/fiscal/clientes", data={"nombre": "EspoCRM Caído SL"})
    assert resp.status_code == 302
    cliente_id = db.listar_clientes_fiscales(tenant_id)[0]["id"]
    assert db.obtener_cliente_fiscal(tenant_id, cliente_id) is not None


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
