"""Tests del backoffice (Fase 7c): rol admin y gestión de tenants/usuarios,
tanto a nivel de app/db.py como de las rutas de app/rutas_backoffice.py.
"""
import pytest

from app import db
from tests.conftest import iniciar_sesion_de_prueba


# --- app/db.py -----------------------------------------------------------

def test_usuario_nuevo_no_es_admin_por_defecto(usuario_id):
    assert db.es_admin(usuario_id) is False


def test_hacer_admin_y_quitar_admin(usuario_id):
    usuario = db.obtener_usuario(usuario_id)
    db.hacer_admin(usuario["email"])
    assert db.es_admin(usuario_id) is True
    db.quitar_admin(usuario["email"])
    assert db.es_admin(usuario_id) is False


def test_hacer_admin_email_inexistente_lanza_value_error():
    with pytest.raises(ValueError):
        db.hacer_admin("no-existe@ejemplo.com")


def test_listar_usuarios_incluye_tenant(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    usuarios = db.listar_usuarios()
    fila = next(u for u in usuarios if u["id"] == usuario_id)
    assert fila["tenant_nombre"] == "Lueira"


def test_listar_tenants_con_conteo(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.crear_tenant("Guilda")
    db.asignar_tenant(usuario_id, tenant_id)
    tenants = {t["nombre"]: t["n_usuarios"] for t in db.listar_tenants_con_conteo()}
    assert tenants["Lueira"] == 1
    assert tenants["Guilda"] == 0


def test_renombrar_tenant():
    tenant_id = db.crear_tenant("Lueira")
    db.renombrar_tenant(tenant_id, "Lueira SL")
    assert db.obtener_tenant(tenant_id)["nombre"] == "Lueira SL"


def test_borrar_tenant_desasigna_a_sus_usuarios(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    db.borrar_tenant(tenant_id)
    assert db.obtener_tenant(tenant_id) is None
    assert db.tenant_de_usuario(usuario_id) is None


def test_desasignar_tenant(usuario_id):
    tenant_id = db.crear_tenant("Lueira")
    db.asignar_tenant(usuario_id, tenant_id)
    db.desasignar_tenant(usuario_id)
    assert db.tenant_de_usuario(usuario_id) is None


# --- app/rutas_backoffice.py ----------------------------------------------

def test_backoffice_sin_admin_devuelve_403(cliente):
    iniciar_sesion_de_prueba(cliente, "usuario-normal@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/")
    assert resp.status_code == 403


def test_backoffice_sin_sesion_redirige_a_login(cliente):
    resp = cliente.get("/backoffice/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_backoffice_con_admin_permite_entrar(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.get("/backoffice/")
    assert resp.status_code == 200


def test_backoffice_crear_tenant_y_asignar_usuario(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "Lueira"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("Lueira")
    assert tenant is not None

    cliente.post(f"/backoffice/usuarios/{usuario_id}/tenant", data={"tenant_id": str(tenant["id"])})
    assert db.tenant_de_usuario(usuario_id)["nombre"] == "Lueira"

    cliente.post(f"/backoffice/usuarios/{usuario_id}/tenant", data={"tenant_id": ""})
    assert db.tenant_de_usuario(usuario_id) is None


def test_backoffice_crear_tenant_provisiona_equipo_en_espocrm(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-crm@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    llamadas = {}

    def fake_crear_equipo(nombre):
        llamadas["nombre"] = nombre
        return "equipo-id-1"

    monkeypatch.setattr(rutas_backoffice.espocrm, "crear_equipo", fake_crear_equipo)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "Lueira"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "Lueira"
    assert db.obtener_tenant_por_nombre("Lueira") is not None


def test_backoffice_crear_tenant_sin_espocrm_configurado_no_falla(cliente):
    """Sin ESPOCRM_API_KEY (caso normal en tests), espocrm.crear_equipo
    devuelve None sin más — el tenant se crea igual en Guilda Work."""
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-crm2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "Guilda"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("Guilda") is not None


def test_backoffice_crear_tenant_un_fallo_en_espocrm_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-crm3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_crear_equipo_falla(nombre):
        raise rutas_backoffice.espocrm.ErrorEspoCRM("fallo simulado de EspoCRM")

    monkeypatch.setattr(rutas_backoffice.espocrm, "crear_equipo", fake_crear_equipo_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "Guilda2"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("Guilda2") is not None


def test_backoffice_crear_tenant_provisiona_espacio_en_nextcloud(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-drive@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    llamadas = {}

    def fake_crear_espacio_tenant(nombre):
        llamadas["nombre"] = nombre

    monkeypatch.setattr(rutas_backoffice.nextcloud, "crear_espacio_tenant", fake_crear_espacio_tenant)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "LueiraDrive"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "LueiraDrive"
    assert db.obtener_tenant_por_nombre("LueiraDrive") is not None


def test_backoffice_crear_tenant_un_fallo_en_nextcloud_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-drive2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_crear_espacio_tenant_falla(nombre):
        raise rutas_backoffice.nextcloud.ErrorNextcloud("fallo simulado de Nextcloud")

    monkeypatch.setattr(rutas_backoffice.nextcloud, "crear_espacio_tenant", fake_crear_espacio_tenant_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "GuildaDrive"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("GuildaDrive") is not None


def test_backoffice_crear_tenant_aprovisiona_facturascripts_y_lo_muestra_una_vez(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-fs@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar(tenant_id, nombre):
        return {"url": "http://127.0.0.1:8199/", "admin_user": "admin", "admin_pass": "clave-generada"}

    monkeypatch.setattr(rutas_backoffice.facturascripts, "aprovisionar_tenant", fake_aprovisionar)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "Lueira FS"})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "clave-generada" in html
    assert "http://127.0.0.1:8199/" in html

    tenant = db.obtener_tenant_por_nombre("Lueira FS")
    assert tenant["facturascripts_url"] == "http://127.0.0.1:8199/"
    assert tenant["facturascripts_admin_pass"] == "clave-generada"

    # Un segundo GET al panel ya NO debe volver a mostrar la contraseña.
    resp2 = cliente.get("/backoffice/")
    assert "clave-generada" not in resp2.get_data(as_text=True)


def test_backoffice_crear_tenant_un_fallo_en_facturascripts_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-fs2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar_falla(tenant_id, nombre):
        raise rutas_backoffice.facturascripts.ErrorFacturaScripts("fallo simulado de FacturaScripts")

    monkeypatch.setattr(rutas_backoffice.facturascripts, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinFS"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinFS") is not None


def test_backoffice_guardar_facturascripts_api_key(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-fs3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    monkeypatch.setattr(
        rutas_backoffice.facturascripts, "aprovisionar_tenant",
        lambda tid, n: {"url": "http://127.0.0.1:8199/", "admin_user": "admin", "admin_pass": "x"},
    )
    cliente.post("/backoffice/tenants", data={"nombre": "ConApiKey"})
    tenant = db.obtener_tenant_por_nombre("ConApiKey")

    resp = cliente.post(
        f"/backoffice/tenants/{tenant['id']}/facturascripts-api-key",
        data={"api_key": "clave-api-real"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert db.obtener_tenant(tenant["id"])["facturascripts_api_key"] == "clave-api-real"


def test_backoffice_guardar_documenso_api_key(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-doc@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ConFirmas")

    resp = cliente.post(
        f"/backoffice/tenants/{tenant_id}/documenso-api-key",
        data={"api_key": "api_token_real"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert db.obtener_tenant(tenant_id)["documenso_api_key"] == "api_token_real"


def test_backoffice_guardar_documenso_api_key_tenant_inexistente_da_404(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-doc2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants/999999/documenso-api-key", data={"api_key": "x"})
    assert resp.status_code == 404


def test_backoffice_borrar_tenant_desaprovisiona_facturascripts(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-fs4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ABorrar")

    llamadas = {}

    def fake_desaprovisionar(tid):
        llamadas["tenant_id"] = tid

    monkeypatch.setattr(rutas_backoffice.facturascripts, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["tenant_id"] == tenant_id
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_paperless(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-pl@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    llamadas = {}

    def fake_aprovisionar(nombre):
        llamadas["nombre"] = nombre
        return {"group_id": 5, "user_id": 9, "api_key": "token-real"}

    monkeypatch.setattr(rutas_backoffice.paperless, "aprovisionar_tenant", fake_aprovisionar)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "ConPaperless"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "ConPaperless"
    tenant = db.obtener_tenant_por_nombre("ConPaperless")
    assert tenant["paperless_group_id"] == 5
    assert tenant["paperless_user_id"] == 9
    assert tenant["paperless_api_key"] == "token-real"


def test_backoffice_crear_tenant_sin_paperless_configurado_no_falla(cliente):
    """Sin PAPERLESS_ADMIN_USER/PASSWORD (caso normal en tests),
    paperless.aprovisionar_tenant devuelve None sin más."""
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-pl2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinPaperless"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinPaperless") is not None


def test_backoffice_crear_tenant_un_fallo_en_paperless_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-pl3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar_falla(nombre):
        raise rutas_backoffice.paperless.ErrorPaperless("fallo simulado de Paperless-ngx")

    monkeypatch.setattr(rutas_backoffice.paperless, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinPaperless2"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinPaperless2") is not None


def test_backoffice_borrar_tenant_desaprovisiona_paperless(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-pl4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ABorrarPaperless")
    db.guardar_paperless(tenant_id, 5, 9, "token-real")

    llamadas = {}

    def fake_desaprovisionar(user_id, group_id):
        llamadas["args"] = (user_id, group_id)

    monkeypatch.setattr(rutas_backoffice.paperless, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["args"] == (9, 5)
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_usuario_muestra_contrasena_temporal(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/usuarios", data={"email": "cliente-nuevo@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    assert "cliente-nuevo@ejemplo.com" in resp.get_data(as_text=True)
    nuevo = db.obtener_usuario_por_email("cliente-nuevo@ejemplo.com")
    assert nuevo is not None


def test_backoffice_crear_usuario_sin_tokens_solo_da_error_en_openproject_y_chatwoot(cliente):
    """Sin OPENPROJECT_API_TOKEN/CHATWOOT_PLATFORM_API_TOKEN configurados
    (caso normal en tests), las tres integraciones deben fallar de forma
    aislada (o, para Metabase, omitirse sin más) sin tumbar el alta del
    usuario en Guilda Work."""
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-integraciones@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/usuarios", data={"email": "sin-tokens@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Guilda Work" in html
    assert "OpenProject" in html
    assert "Chatwoot" in html
    assert "Metabase" not in html  # se omite sin más, sin API key configurada
    assert db.obtener_usuario_por_email("sin-tokens@ejemplo.com") is not None


def test_backoffice_crear_usuario_da_de_alta_en_openproject_y_chatwoot(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-integraciones2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    llamadas = {}

    def fake_openproject_crear_usuario(email, contrasena, nombre="", apellidos=""):
        llamadas["openproject"] = (email, contrasena)
        return 42

    def fake_chatwoot_crear_usuario(email, contrasena, nombre=""):
        llamadas["chatwoot"] = (email, contrasena)
        return 7

    def fake_metabase_crear_usuario(email, nombre="", apellidos=""):
        llamadas["metabase"] = email
        return 3

    monkeypatch.setattr(rutas_backoffice.openproject, "crear_usuario", fake_openproject_crear_usuario)
    monkeypatch.setattr(rutas_backoffice.chatwoot, "crear_usuario", fake_chatwoot_crear_usuario)
    monkeypatch.setattr(rutas_backoffice.metabase, "crear_usuario", fake_metabase_crear_usuario)

    resp = cliente.post("/backoffice/usuarios", data={"email": "multi-alta@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "creado" in html

    assert llamadas["openproject"][0] == "multi-alta@ejemplo.com"
    assert llamadas["chatwoot"][0] == "multi-alta@ejemplo.com"
    # OpenProject y Chatwoot comparten LA MISMA contraseña temporal que Kratos.
    assert llamadas["openproject"][1] == llamadas["chatwoot"][1]
    assert llamadas["metabase"] == "multi-alta@ejemplo.com"


def test_backoffice_crear_usuario_un_fallo_en_una_integracion_no_bloquea_las_demas(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-integraciones3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_openproject_falla(email, contrasena, nombre="", apellidos=""):
        raise rutas_backoffice.openproject.ErrorOpenProject("fallo simulado de OpenProject")

    llamadas = {}

    def fake_chatwoot_ok(email, contrasena, nombre=""):
        llamadas["chatwoot"] = email
        return 9

    monkeypatch.setattr(rutas_backoffice.openproject, "crear_usuario", fake_openproject_falla)
    monkeypatch.setattr(rutas_backoffice.chatwoot, "crear_usuario", fake_chatwoot_ok)

    resp = cliente.post("/backoffice/usuarios", data={"email": "fallo-parcial@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "fallo simulado de OpenProject" in html
    assert llamadas["chatwoot"] == "fallo-parcial@ejemplo.com"
    # El usuario de Guilda Work se crea igual, pese al fallo de OpenProject.
    assert db.obtener_usuario_por_email("fallo-parcial@ejemplo.com") is not None


def test_backoffice_admin_no_puede_quitarse_el_rol_a_si_mismo(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post(f"/backoffice/usuarios/{usuario_id}/rol")
    assert resp.status_code == 400
    assert db.es_admin(usuario_id) is True
