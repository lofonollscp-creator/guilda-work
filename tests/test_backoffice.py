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


def test_backoffice_crear_tenant_aprovisiona_baserow(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-br@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    llamadas = {}

    def fake_aprovisionar(nombre):
        llamadas["nombre"] = nombre
        return {"workspace_id": 5, "api_key": "token-real"}

    monkeypatch.setattr(rutas_backoffice.baserow, "aprovisionar_tenant", fake_aprovisionar)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "ConBaserow"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "ConBaserow"
    tenant = db.obtener_tenant_por_nombre("ConBaserow")
    assert tenant["baserow_workspace_id"] == 5
    assert tenant["baserow_api_key"] == "token-real"


def test_backoffice_crear_tenant_sin_baserow_configurado_no_falla(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-br2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinBaserow"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinBaserow") is not None


def test_backoffice_crear_tenant_un_fallo_en_baserow_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-br3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar_falla(nombre):
        raise rutas_backoffice.baserow.ErrorBaserow("fallo simulado de Baserow")

    monkeypatch.setattr(rutas_backoffice.baserow, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinBaserow2"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinBaserow2") is not None


def test_backoffice_crear_usuario_invita_al_workspace_de_baserow(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-br4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ConWorkspace")
    db.guardar_baserow(tenant_id, 5, "token-real")

    llamadas = {}

    def fake_invitar(workspace_id, email):
        llamadas["args"] = (workspace_id, email)

    monkeypatch.setattr(rutas_backoffice.baserow, "invitar_usuario", fake_invitar)

    resp = cliente.post(
        "/backoffice/usuarios", data={"email": "ana@ejemplo.com", "tenant_id": tenant_id}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert llamadas["args"] == (5, "ana@ejemplo.com")


def test_backoffice_crear_usuario_sin_workspace_de_baserow_no_intenta_invitar(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-br5@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("SinWorkspace")

    llamado = []
    monkeypatch.setattr(rutas_backoffice.baserow, "invitar_usuario", lambda *a: llamado.append(1))

    resp = cliente.post(
        "/backoffice/usuarios", data={"email": "ana2@ejemplo.com", "tenant_id": tenant_id}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert llamado == []


def test_backoffice_borrar_tenant_desaprovisiona_baserow(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-br6@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ABorrarBaserow")
    db.guardar_baserow(tenant_id, 5, "token-real")

    llamadas = {}
    monkeypatch.setattr(rutas_backoffice.baserow, "desaprovisionar_tenant", lambda wid: llamadas.setdefault("workspace_id", wid))

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["workspace_id"] == 5
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


def test_backoffice_crear_tenant_aprovisiona_calcom_y_lo_muestra_una_vez(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-cc@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar(tenant_id, nombre):
        return {"email": "tenant-lueira-cc@calcom.local", "admin_pass": "clave-generada-cc"}

    monkeypatch.setattr(rutas_backoffice.calcom, "aprovisionar_tenant", fake_aprovisionar)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "Lueira CC"})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "clave-generada-cc" in html
    assert "tenant-lueira-cc@calcom.local" in html

    tenant = db.obtener_tenant_por_nombre("Lueira CC")
    assert tenant["calcom_email"] == "tenant-lueira-cc@calcom.local"
    assert tenant["calcom_admin_pass"] == "clave-generada-cc"

    # Un segundo GET al panel ya NO debe volver a mostrar la contraseña.
    resp2 = cliente.get("/backoffice/")
    assert "clave-generada-cc" not in resp2.get_data(as_text=True)


def test_backoffice_crear_tenant_un_fallo_en_calcom_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-cc2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar_falla(tenant_id, nombre):
        raise rutas_backoffice.calcom.ErrorCalcom("fallo simulado de Cal.diy")

    monkeypatch.setattr(rutas_backoffice.calcom, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinCalcom"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinCalcom") is not None


def test_backoffice_guardar_calcom_api_key(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-cc3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ConCitas")

    resp = cliente.post(
        f"/backoffice/tenants/{tenant_id}/calcom-api-key",
        data={"api_key": "cal_live_token_real"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert db.obtener_tenant(tenant_id)["calcom_api_key"] == "cal_live_token_real"


def test_backoffice_guardar_calcom_api_key_tenant_inexistente_da_404(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-cc4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants/999999/calcom-api-key", data={"api_key": "x"})
    assert resp.status_code == 404


def test_backoffice_borrar_tenant_no_falla_aunque_calcom_no_tenga_desaprovisionar(cliente):
    """Cal.diy no tiene desaprovisionar_tenant() (ver app/calcom.py) — el
    borrado del tenant no debe fallar por eso."""
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-cc5@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ABorrarCC")
    db.guardar_calcom(tenant_id, "tenant-aborrarcc@calcom.local", "clave-x")

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_listmonk_sin_nada_que_mostrar(cliente, monkeypatch):
    """A diferencia de Cal.diy/FacturaScripts, Listmonk no tiene ninguna
    contraseña humana que enseñar — el token queda guardado directamente."""
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-lm1@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar(nombre):
        return {"list_id": 3, "list_role_id": 5, "api_key": "tenant-lueira-lm-api:tokengenerado"}

    monkeypatch.setattr(rutas_backoffice.listmonk, "aprovisionar_tenant", fake_aprovisionar)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "Lueira LM"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "tokengenerado" not in resp.get_data(as_text=True)

    tenant = db.obtener_tenant_por_nombre("Lueira LM")
    assert tenant["listmonk_list_id"] == 3
    assert tenant["listmonk_list_role_id"] == 5
    assert tenant["listmonk_api_key"] == "tenant-lueira-lm-api:tokengenerado"


def test_backoffice_crear_tenant_un_fallo_en_listmonk_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-lm2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar_falla(nombre):
        raise rutas_backoffice.listmonk.ErrorListmonk("fallo simulado de Listmonk")

    monkeypatch.setattr(rutas_backoffice.listmonk, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinListmonk"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinListmonk") is not None


def test_backoffice_crear_usuario_da_de_alta_en_listmonk_con_el_rol_de_lista_del_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-lm3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ConListaLM")
    db.guardar_listmonk(tenant_id, 3, 5, "tenant-conlistalm-api:token")

    llamadas = {}

    def fake_crear_usuario_tenant(email, list_role_id):
        llamadas["args"] = (email, list_role_id)

    monkeypatch.setattr(rutas_backoffice.listmonk, "crear_usuario_tenant", fake_crear_usuario_tenant)

    resp = cliente.post(
        "/backoffice/usuarios", data={"email": "ana-lm@ejemplo.com", "tenant_id": tenant_id}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert llamadas["args"] == ("ana-lm@ejemplo.com", 5)


def test_backoffice_crear_usuario_sin_lista_de_listmonk_no_intenta_dar_de_alta(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-lm4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("SinListaLM")

    llamado = []
    monkeypatch.setattr(rutas_backoffice.listmonk, "crear_usuario_tenant", lambda *a: llamado.append(1))

    resp = cliente.post(
        "/backoffice/usuarios", data={"email": "ana-lm2@ejemplo.com", "tenant_id": tenant_id}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert llamado == []


def test_backoffice_borrar_tenant_desaprovisiona_listmonk(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-lm5@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ABorrarLM")
    db.guardar_listmonk(tenant_id, 3, 5, "token")

    llamadas = {}

    def fake_desaprovisionar(list_id, list_role_id):
        llamadas["args"] = (list_id, list_role_id)

    monkeypatch.setattr(rutas_backoffice.listmonk, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["args"] == (3, 5)
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_stalwart_solo_si_hay_dominio(cliente, monkeypatch):
    """Stalwart es el único proveedor que necesita un dato manual (el
    dominio propio real del cliente) — sin él, se omite igual que si
    STALWART_ADMIN_USER/PASSWORD no estuvieran configuradas."""
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-sw1@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    llamado = []
    monkeypatch.setattr(rutas_backoffice.stalwart, "aprovisionar_tenant", lambda *a: llamado.append(a))

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinDominioSW"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamado == []
    assert db.obtener_tenant_por_nombre("SinDominioSW") is not None


def test_backoffice_crear_tenant_aprovisiona_stalwart_con_dominio(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-sw2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar(tenant_id, nombre, dominio_correo):
        return {
            "stalwart_tenant_id": "b", "domain_id": "c", "domain_name": dominio_correo,
            "account_id": "d", "api_key": "API_generado",
        }

    monkeypatch.setattr(rutas_backoffice.stalwart, "aprovisionar_tenant", fake_aprovisionar)

    resp = cliente.post(
        "/backoffice/tenants", data={"nombre": "ConDominioSW", "dominio_correo": "clientea.com"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    tenant = db.obtener_tenant_por_nombre("ConDominioSW")
    assert tenant["stalwart_tenant_id"] == "b"
    assert tenant["stalwart_domain_name"] == "clientea.com"
    assert tenant["stalwart_api_key"] == "API_generado"


def test_backoffice_crear_tenant_un_fallo_en_stalwart_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-sw3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar_falla(tenant_id, nombre, dominio_correo):
        raise rutas_backoffice.stalwart.ErrorStalwart("fallo simulado de Stalwart")

    monkeypatch.setattr(rutas_backoffice.stalwart, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = cliente.post(
        "/backoffice/tenants", data={"nombre": "ConFalloSW", "dominio_correo": "clientea.com"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("ConFalloSW") is not None


def test_backoffice_borrar_tenant_desaprovisiona_stalwart(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-sw4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ABorrarSW")
    db.guardar_stalwart(tenant_id, "b", "c", "clientea.com", "d", "API_token")

    llamadas = {}

    def fake_desaprovisionar(stalwart_tenant_id, domain_id, account_id):
        llamadas["args"] = (stalwart_tenant_id, domain_id, account_id)

    monkeypatch.setattr(rutas_backoffice.stalwart, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["args"] == ("b", "c", "d")
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_ntfy(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-ntfy1@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar(tenant_id, nombre):
        return {"topic": f"guilda-{nombre.lower()}-{tenant_id}", "token": "tk_real"}

    monkeypatch.setattr(rutas_backoffice.ntfy, "aprovisionar_tenant", fake_aprovisionar)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "ConNtfy"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("ConNtfy")
    assert tenant["ntfy_token"] == "tk_real"
    assert tenant["ntfy_topic"] == f"guilda-conntfy-{tenant['id']}"


def test_backoffice_crear_tenant_sin_ntfy_configurado_no_falla(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-ntfy2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinNtfy"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinNtfy") is not None


def test_backoffice_crear_tenant_un_fallo_en_ntfy_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-ntfy3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar_falla(tenant_id, nombre):
        raise rutas_backoffice.ntfy.ErrorNtfy("fallo simulado de ntfy")

    monkeypatch.setattr(rutas_backoffice.ntfy, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "NtfyFalla"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("NtfyFalla") is not None


def test_backoffice_borrar_tenant_desaprovisiona_ntfy(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-ntfy4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ABorrarNtfy")
    db.guardar_ntfy(tenant_id, "guilda-aborrarntfy-1", "tk_real")

    llamadas = {}

    def fake_desaprovisionar(t_id):
        llamadas["tenant_id"] = t_id

    monkeypatch.setattr(rutas_backoffice.ntfy, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["tenant_id"] == tenant_id
    assert db.obtener_tenant(tenant_id) is None


# --- Umami (analítica web) --------------------------------------------------

def test_backoffice_crear_tenant_aprovisiona_umami(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-umami1@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar(tenant_id, nombre):
        return {"team_id": f"team-{tenant_id}", "website_id": f"site-{tenant_id}"}

    monkeypatch.setattr(rutas_backoffice.umami, "aprovisionar_tenant", fake_aprovisionar)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "ConUmami"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("ConUmami")
    assert tenant["umami_team_id"] == f"team-{tenant['id']}"
    assert tenant["umami_website_id"] == f"site-{tenant['id']}"


def test_backoffice_crear_tenant_sin_umami_configurado_no_falla(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-umami2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    monkeypatch.setattr(rutas_backoffice.umami, "aprovisionar_tenant", lambda tenant_id, nombre: None)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "SinUmami"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("SinUmami")
    assert tenant is not None
    assert tenant["umami_team_id"] is None


def test_backoffice_crear_tenant_un_fallo_en_umami_no_bloquea_el_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-umami3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    def fake_aprovisionar_falla(tenant_id, nombre):
        raise rutas_backoffice.umami.ErrorUmami("fallo simulado de umami")

    monkeypatch.setattr(rutas_backoffice.umami, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = cliente.post("/backoffice/tenants", data={"nombre": "UmamiFalla"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("UmamiFalla") is not None


def test_backoffice_borrar_tenant_desaprovisiona_umami(cliente, monkeypatch):
    from app import rutas_backoffice

    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-umami4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    tenant_id = db.crear_tenant("ABorrarUmami")
    db.guardar_umami(tenant_id, "team-1", "site-1")

    llamadas = {}

    def fake_desaprovisionar(team_id):
        llamadas["team_id"] = team_id

    monkeypatch.setattr(rutas_backoffice.umami, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["team_id"] == "team-1"
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_usuario_da_de_alta_en_umami_con_el_team_del_tenant(cliente, monkeypatch):
    from app import rutas_backoffice

    admin_id = iniciar_sesion_de_prueba(cliente, "admin-umami5@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(admin_id)["email"])

    tenant_id = db.crear_tenant("TenantUmami")
    db.guardar_umami(tenant_id, "team-42", "site-42")

    llamadas = {}

    def fake_crear_usuario_tenant(email, team_id, contrasena):
        llamadas["args"] = (email, team_id, contrasena)

    monkeypatch.setattr(rutas_backoffice.umami, "crear_usuario_tenant", fake_crear_usuario_tenant)

    resp = cliente.post(
        "/backoffice/usuarios",
        data={"email": "nuevo-umami@ejemplo.com", "tenant_id": tenant_id},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    email, team_id, contrasena = llamadas["args"]
    assert email == "nuevo-umami@ejemplo.com"
    assert team_id == "team-42"
    assert contrasena  # contraseña temporal generada, no vacía


def test_backoffice_crear_usuario_sin_umami_del_tenant_no_intenta_dar_de_alta(cliente, monkeypatch):
    from app import rutas_backoffice

    admin_id = iniciar_sesion_de_prueba(cliente, "admin-umami6@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(admin_id)["email"])

    tenant_id = db.crear_tenant("TenantSinUmami")

    def fake_crear_usuario_tenant(*a, **k):
        raise AssertionError("no debería llamarse")

    monkeypatch.setattr(rutas_backoffice.umami, "crear_usuario_tenant", fake_crear_usuario_tenant)

    resp = cliente.post(
        "/backoffice/usuarios",
        data={"email": "otro@ejemplo.com", "tenant_id": tenant_id},
        follow_redirects=True,
    )
    assert resp.status_code == 200


# --- Observabilidad (Grafana+Loki) — oculta por defecto ---------------------

def test_backoffice_crear_tenant_oculta_observabilidad_por_defecto(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-obs1@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "TenantObs"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("TenantObs")
    assert "observabilidad" in db.herramientas_ocultas_de_tenant(tenant["id"])


def test_backoffice_admin_puede_mostrar_observabilidad_a_mano(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-obs2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "TenantObs2"}, follow_redirects=True)
    tenant = db.obtener_tenant_por_nombre("TenantObs2")
    assert "observabilidad" in db.herramientas_ocultas_de_tenant(tenant["id"])

    ruta = f"/backoffice/tenants/{tenant['id']}/herramientas/observabilidad/alternar"
    cliente.post(ruta, follow_redirects=True)
    assert "observabilidad" not in db.herramientas_ocultas_de_tenant(tenant["id"])


# --- Portainer — oculta por defecto ------------------------------------------

def test_backoffice_crear_tenant_oculta_portainer_por_defecto(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-port1@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "TenantPort"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("TenantPort")
    assert "portainer" in db.herramientas_ocultas_de_tenant(tenant["id"])


def test_backoffice_admin_puede_mostrar_portainer_a_mano(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-port2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/tenants", data={"nombre": "TenantPort2"}, follow_redirects=True)
    tenant = db.obtener_tenant_por_nombre("TenantPort2")
    assert "portainer" in db.herramientas_ocultas_de_tenant(tenant["id"])

    ruta = f"/backoffice/tenants/{tenant['id']}/herramientas/portainer/alternar"
    cliente.post(ruta, follow_redirects=True)
    assert "portainer" not in db.herramientas_ocultas_de_tenant(tenant["id"])


# --- Webhooks ------------------------------------------------------------

def test_backoffice_crear_webhook_de_ambito_local(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh1@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post(
        "/backoffice/webhooks",
        data={"tenant_id": "", "url": "https://ejemplo.com/hook", "eventos": ["tarea.finalizada", "nota.creada"]},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    webhooks = db.listar_webhooks(None)
    assert len(webhooks) == 1
    assert webhooks[0]["url"] == "https://ejemplo.com/hook"


def test_backoffice_crear_webhook_de_un_tenant(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh2@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])
    tenant_id = db.crear_tenant("TenantWebhook")

    resp = cliente.post(
        "/backoffice/webhooks",
        data={"tenant_id": str(tenant_id), "url": "https://ejemplo.com/hook", "eventos": ["cita.reservada"]},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    webhooks = db.listar_webhooks(tenant_id)
    assert len(webhooks) == 1


def test_backoffice_crear_webhook_sin_eventos_no_lo_crea(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh3@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    cliente.post("/backoffice/webhooks", data={"tenant_id": "", "url": "https://ejemplo.com/hook"}, follow_redirects=True)
    assert db.listar_webhooks(None) == []


def test_backoffice_crear_webhook_ignora_eventos_no_reconocidos(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh4@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    cliente.post(
        "/backoffice/webhooks",
        data={"tenant_id": "", "url": "https://ejemplo.com/hook", "eventos": ["evento.inventado"]},
        follow_redirects=True,
    )
    assert db.listar_webhooks(None) == []


def test_backoffice_crear_webhook_tenant_inexistente_da_404(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh5@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post(
        "/backoffice/webhooks",
        data={"tenant_id": "999999", "url": "https://ejemplo.com/hook", "eventos": ["nota.creada"]},
    )
    assert resp.status_code == 404


def test_backoffice_borrar_webhook(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh6@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])
    w = db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook", ["nota.creada"])

    resp = cliente.post(f"/backoffice/webhooks/{w['id']}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_webhook(w["id"]) is None


def test_backoffice_borrar_webhook_inexistente_da_404(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh7@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])

    resp = cliente.post("/backoffice/webhooks/999999/borrar")
    assert resp.status_code == 404


def test_backoffice_webhooks_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "usuario-normal-wh@ejemplo.com", "contrasena123")
    resp = cliente.post("/backoffice/webhooks", data={"tenant_id": "", "url": "https://x.com", "eventos": ["nota.creada"]})
    assert resp.status_code == 403


def test_backoffice_panel_muestra_los_webhooks(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "admin-wh8@ejemplo.com", "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])
    db.crear_webhook(usuario_id, None, "https://ejemplo.com/mi-webhook-unico", ["nota.creada"])

    resp = cliente.get("/backoffice/")
    assert b"ejemplo.com/mi-webhook-unico" in resp.data
