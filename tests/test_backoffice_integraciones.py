"""Backoffice independiente: aprovisionamiento y desaprovisionamiento de cada
integración, altas de usuario, claves de API, webhooks y exportación. Portados
de los tests del panel antiguo (retirado) para no perder cobertura por servicio."""
import pytest

from app import (baserow, calcom, chatwoot, db, espocrm, eventos, facturascripts, herramientas, kratos, listmonk,
                 metabase, nextcloud, ntfy, openproject, paperless, stalwart, umami)
from backoffice import aprovisionamiento, auth
from tests.test_backoffice_app import _csrf
from tests.test_backoffice_sistema import bo  # noqa: F401 -- fixture con sesión iniciada


def _borrar(bo, tenant_id):
    """El borrado exige escribir el nombre exacto del tenant."""
    nombre = db.obtener_tenant(tenant_id)["nombre"]
    return _post(bo, f"/tenants/{tenant_id}/borrar", data={"confirmacion": nombre}, follow_redirects=True)


def _post(bo, ruta, data=None, follow_redirects=False):
    token = _csrf(bo.get("/").get_data(as_text=True))
    return bo.post(ruta, data={**(data or {}), "_csrf": token}, follow_redirects=follow_redirects)


def test_backoffice_crear_tenant_provisiona_equipo_en_espocrm(bo, monkeypatch):
    from backoffice import aprovisionamiento

    llamadas = {}

    def fake_crear_equipo(nombre):
        llamadas["nombre"] = nombre
        return "equipo-id-1"

    monkeypatch.setattr(aprovisionamiento.espocrm, "crear_equipo", fake_crear_equipo)

    resp = _post(bo, "/tenants", data={"nombre": "Lueira"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "Lueira"
    assert db.obtener_tenant_por_nombre("Lueira") is not None


def test_backoffice_crear_tenant_sin_espocrm_configurado_no_falla(bo):
    """Sin ESPOCRM_API_KEY (caso normal en tests), espocrm.crear_equipo
    devuelve None sin más — el tenant se crea igual en Guilda Work."""

    resp = _post(bo, "/tenants", data={"nombre": "Guilda"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("Guilda") is not None


def test_backoffice_crear_tenant_un_fallo_en_espocrm_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_crear_equipo_falla(nombre):
        raise aprovisionamiento.espocrm.ErrorEspoCRM("fallo simulado de EspoCRM")

    monkeypatch.setattr(aprovisionamiento.espocrm, "crear_equipo", fake_crear_equipo_falla)

    resp = _post(bo, "/tenants", data={"nombre": "Guilda2"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("Guilda2") is not None


def test_backoffice_crear_tenant_provisiona_espacio_en_nextcloud(bo, monkeypatch):
    from backoffice import aprovisionamiento

    llamadas = {}

    def fake_crear_espacio_tenant(nombre):
        llamadas["nombre"] = nombre

    monkeypatch.setattr(aprovisionamiento.nextcloud, "crear_espacio_tenant", fake_crear_espacio_tenant)

    resp = _post(bo, "/tenants", data={"nombre": "LueiraDrive"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "LueiraDrive"
    assert db.obtener_tenant_por_nombre("LueiraDrive") is not None


def test_backoffice_crear_tenant_un_fallo_en_nextcloud_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_crear_espacio_tenant_falla(nombre):
        raise aprovisionamiento.nextcloud.ErrorNextcloud("fallo simulado de Nextcloud")

    monkeypatch.setattr(aprovisionamiento.nextcloud, "crear_espacio_tenant", fake_crear_espacio_tenant_falla)

    resp = _post(bo, "/tenants", data={"nombre": "GuildaDrive"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("GuildaDrive") is not None


def test_backoffice_crear_tenant_aprovisiona_facturascripts_y_lo_muestra_una_vez(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar(tenant_id, nombre):
        return {"url": "http://127.0.0.1:8199/", "admin_user": "admin", "admin_pass": "clave-generada"}

    monkeypatch.setattr(aprovisionamiento.facturascripts, "aprovisionar_tenant", fake_aprovisionar)

    resp = _post(bo, "/tenants", data={"nombre": "Lueira FS"})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "clave-generada" in html
    assert "http://127.0.0.1:8199/" in html

    tenant = db.obtener_tenant_por_nombre("Lueira FS")
    assert tenant["facturascripts_url"] == "http://127.0.0.1:8199/"
    assert tenant["facturascripts_admin_pass"] == "clave-generada"

    # Un segundo GET al panel ya NO debe volver a mostrar la contraseña.
    resp2 = bo.get("/")
    assert "clave-generada" not in resp2.get_data(as_text=True)


def test_backoffice_crear_tenant_un_fallo_en_facturascripts_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar_falla(tenant_id, nombre):
        raise aprovisionamiento.facturascripts.ErrorFacturaScripts("fallo simulado de FacturaScripts")

    monkeypatch.setattr(aprovisionamiento.facturascripts, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = _post(bo, "/tenants", data={"nombre": "SinFS"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinFS") is not None


def test_backoffice_guardar_facturascripts_api_key(bo, monkeypatch):
    from backoffice import aprovisionamiento

    monkeypatch.setattr(
        aprovisionamiento.facturascripts, "aprovisionar_tenant",
        lambda tid, n: {"url": "http://127.0.0.1:8199/", "admin_user": "admin", "admin_pass": "x"},
    )
    _post(bo, "/tenants", data={"nombre": "ConApiKey"})
    tenant = db.obtener_tenant_por_nombre("ConApiKey")

    resp = _post(bo, 
        f"/tenants/{tenant['id']}/claves/facturascripts",
        data={"api_key": "clave-api-real"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert db.obtener_tenant(tenant["id"])["facturascripts_api_key"] == "clave-api-real"


def test_backoffice_guardar_documenso_api_key(bo):

    tenant_id = db.crear_tenant("ConFirmas")

    resp = _post(bo, 
        f"/tenants/{tenant_id}/claves/documenso",
        data={"api_key": "api_token_real"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert db.obtener_tenant(tenant_id)["documenso_api_key"] == "api_token_real"


def test_backoffice_guardar_documenso_api_key_tenant_inexistente_da_404(bo):

    resp = _post(bo, "/tenants/999999/claves/documenso", data={"api_key": "x"})
    assert resp.status_code == 404


def test_backoffice_borrar_tenant_desaprovisiona_facturascripts(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrar")

    llamadas = {}

    def fake_desaprovisionar(tid):
        llamadas["tenant_id"] = tid

    monkeypatch.setattr(aprovisionamiento.facturascripts, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["tenant_id"] == tenant_id
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_paperless(bo, monkeypatch):
    from backoffice import aprovisionamiento

    llamadas = {}

    def fake_aprovisionar(nombre):
        llamadas["nombre"] = nombre
        return {"group_id": 5, "user_id": 9, "api_key": "token-real"}

    monkeypatch.setattr(aprovisionamiento.paperless, "aprovisionar_tenant", fake_aprovisionar)

    resp = _post(bo, "/tenants", data={"nombre": "ConPaperless"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "ConPaperless"
    tenant = db.obtener_tenant_por_nombre("ConPaperless")
    assert tenant["paperless_group_id"] == 5
    assert tenant["paperless_user_id"] == 9
    assert tenant["paperless_api_key"] == "token-real"


def test_backoffice_crear_tenant_sin_paperless_configurado_no_falla(bo):
    """Sin PAPERLESS_ADMIN_USER/PASSWORD (caso normal en tests),
    paperless.aprovisionar_tenant devuelve None sin más."""

    resp = _post(bo, "/tenants", data={"nombre": "SinPaperless"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinPaperless") is not None


def test_backoffice_crear_tenant_un_fallo_en_paperless_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar_falla(nombre):
        raise aprovisionamiento.paperless.ErrorPaperless("fallo simulado de Paperless-ngx")

    monkeypatch.setattr(aprovisionamiento.paperless, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = _post(bo, "/tenants", data={"nombre": "SinPaperless2"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinPaperless2") is not None


def test_backoffice_borrar_tenant_desaprovisiona_paperless(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrarPaperless")
    db.guardar_paperless(tenant_id, 5, 9, "token-real")

    llamadas = {}

    def fake_desaprovisionar(user_id, group_id):
        llamadas["args"] = (user_id, group_id)

    monkeypatch.setattr(aprovisionamiento.paperless, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["args"] == (9, 5)
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_baserow(bo, monkeypatch):
    from backoffice import aprovisionamiento

    llamadas = {}

    def fake_aprovisionar(nombre):
        llamadas["nombre"] = nombre
        return {"workspace_id": 5, "api_key": "token-real"}

    monkeypatch.setattr(aprovisionamiento.baserow, "aprovisionar_tenant", fake_aprovisionar)

    resp = _post(bo, "/tenants", data={"nombre": "ConBaserow"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "ConBaserow"
    tenant = db.obtener_tenant_por_nombre("ConBaserow")
    assert tenant["baserow_workspace_id"] == 5
    assert tenant["baserow_api_key"] == "token-real"


def test_backoffice_crear_tenant_sin_baserow_configurado_no_falla(bo):

    resp = _post(bo, "/tenants", data={"nombre": "SinBaserow"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinBaserow") is not None


def test_backoffice_crear_tenant_un_fallo_en_baserow_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar_falla(nombre):
        raise aprovisionamiento.baserow.ErrorBaserow("fallo simulado de Baserow")

    monkeypatch.setattr(aprovisionamiento.baserow, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = _post(bo, "/tenants", data={"nombre": "SinBaserow2"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinBaserow2") is not None


def test_backoffice_crear_usuario_invita_al_workspace_de_baserow(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ConWorkspace")
    db.guardar_baserow(tenant_id, 5, "token-real")

    llamadas = {}

    def fake_invitar(workspace_id, email):
        llamadas["args"] = (workspace_id, email)

    monkeypatch.setattr(aprovisionamiento.baserow, "invitar_usuario", fake_invitar)

    resp = _post(bo, 
        "/usuarios", data={"email": "ana@ejemplo.com", "tenant_id": tenant_id}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert llamadas["args"] == (5, "ana@ejemplo.com")


def test_backoffice_crear_usuario_sin_workspace_de_baserow_no_intenta_invitar(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("SinWorkspace")

    llamado = []
    monkeypatch.setattr(aprovisionamiento.baserow, "invitar_usuario", lambda *a: llamado.append(1))

    resp = _post(bo, 
        "/usuarios", data={"email": "ana2@ejemplo.com", "tenant_id": tenant_id}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert llamado == []


def test_backoffice_borrar_tenant_desaprovisiona_baserow(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrarBaserow")
    db.guardar_baserow(tenant_id, 5, "token-real")

    llamadas = {}
    monkeypatch.setattr(aprovisionamiento.baserow, "desaprovisionar_tenant", lambda wid: llamadas.setdefault("workspace_id", wid))

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["workspace_id"] == 5
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_borrar_tenant_desaprovisiona_espocrm(bo, monkeypatch):
    """Bloque 5 de la auditoría de 2026-09-30/10-01: sin esto, el Equipo
    de EspoCRM de un tenant borrado quedaba huérfano -- un tenant nuevo
    que reutilizara el mismo nombre lo heredaría."""
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrarEspoCRM")

    llamadas = {}
    monkeypatch.setattr(
        aprovisionamiento.espocrm, "desaprovisionar_tenant",
        lambda nombre: llamadas.setdefault("nombre", nombre),
    )

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "ABorrarEspoCRM"
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_borrar_tenant_desaprovisiona_nextcloud(bo, monkeypatch):
    """Mismo motivo que EspoCRM arriba, pero para el Grupo + Group Folder
    de Nextcloud."""
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrarNextcloud")

    llamadas = {}
    monkeypatch.setattr(
        aprovisionamiento.nextcloud, "desaprovisionar_tenant",
        lambda nombre: llamadas.setdefault("nombre", nombre),
    )

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["nombre"] == "ABorrarNextcloud"
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_usuario_muestra_contrasena_temporal(bo):

    resp = _post(bo, "/usuarios", data={"email": "cliente-nuevo@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    assert "cliente-nuevo@ejemplo.com" in resp.get_data(as_text=True)
    nuevo = db.obtener_usuario_por_email("cliente-nuevo@ejemplo.com")
    assert nuevo is not None


def test_backoffice_crear_usuario_muestra_boton_copiar_para_la_contrasena(bo):
    """La contraseña temporal solo se muestra esta vez -- copiarla a mano
    seleccionando texto es fácil de hacer mal, así que debe llevar un
    botón "Copiar" con la contraseña real en data-password."""

    resp = _post(bo, "/usuarios", data={"email": "copiar-pass@ejemplo.com", "tenant_id": ""})
    html = resp.get_data(as_text=True)
    assert 'id="clave-temporal"' in html
    assert 'data-copiar="clave-temporal"' in html


def test_backoffice_crear_usuario_sin_tokens_solo_da_error_en_openproject_y_chatwoot(bo):
    """Sin OPENPROJECT_API_TOKEN/CHATWOOT_PLATFORM_API_TOKEN configurados
    (caso normal en tests), las tres integraciones deben fallar de forma
    aislada (o, para Metabase, omitirse sin más) sin tumbar el alta del
    usuario en Guilda Work."""

    resp = _post(bo, "/usuarios", data={"email": "sin-tokens@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Guilda Work" in html
    assert "OpenProject" in html
    assert "Chatwoot" in html
    # Substring acotado a la fila de la propia tabla de resultados de alta
    # (no "Metabase" a secas): el backoffice renovado también muestra el
    # nombre de cada herramienta del catálogo como insignia en la tarjeta
    # de cada tenant -- "Metabase" sí puede aparecer en la página por eso,
    # legítimamente, sin que ese sea el caso que este test comprueba.
    assert "NO CONFIGURADO" in html  # sin API key, se informa sin tumbar el alta
    assert db.obtener_usuario_por_email("sin-tokens@ejemplo.com") is not None


def test_backoffice_crear_usuario_da_de_alta_en_openproject_y_chatwoot(bo, monkeypatch):
    from backoffice import aprovisionamiento

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

    monkeypatch.setattr(aprovisionamiento.openproject, "crear_usuario", fake_openproject_crear_usuario)
    monkeypatch.setattr(aprovisionamiento.chatwoot, "crear_usuario", fake_chatwoot_crear_usuario)
    monkeypatch.setattr(aprovisionamiento.metabase, "crear_usuario", fake_metabase_crear_usuario)

    resp = _post(bo, "/usuarios", data={"email": "multi-alta@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "creado" in html

    assert llamadas["openproject"][0] == "multi-alta@ejemplo.com"
    assert llamadas["chatwoot"][0] == "multi-alta@ejemplo.com"
    # OpenProject y Chatwoot comparten LA MISMA contraseña temporal que Kratos.
    assert llamadas["openproject"][1] == llamadas["chatwoot"][1]
    assert llamadas["metabase"] == "multi-alta@ejemplo.com"


def test_backoffice_crear_usuario_un_fallo_en_una_integracion_no_bloquea_las_demas(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_openproject_falla(email, contrasena, nombre="", apellidos=""):
        raise aprovisionamiento.openproject.ErrorOpenProject("fallo simulado de OpenProject")

    llamadas = {}

    def fake_chatwoot_ok(email, contrasena, nombre=""):
        llamadas["chatwoot"] = email
        return 9

    monkeypatch.setattr(aprovisionamiento.openproject, "crear_usuario", fake_openproject_falla)
    monkeypatch.setattr(aprovisionamiento.chatwoot, "crear_usuario", fake_chatwoot_ok)

    resp = _post(bo, "/usuarios", data={"email": "fallo-parcial@ejemplo.com", "tenant_id": ""})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "fallo simulado de OpenProject" in html
    assert llamadas["chatwoot"] == "fallo-parcial@ejemplo.com"
    # El usuario de Guilda Work se crea igual, pese al fallo de OpenProject.
    assert db.obtener_usuario_por_email("fallo-parcial@ejemplo.com") is not None


def test_backoffice_crear_tenant_aprovisiona_calcom_y_lo_muestra_una_vez(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar(tenant_id, nombre):
        return {"email": "tenant-lueira-cc@calcom.local", "admin_pass": "clave-generada-cc"}

    monkeypatch.setattr(aprovisionamiento.calcom, "aprovisionar_tenant", fake_aprovisionar)

    resp = _post(bo, "/tenants", data={"nombre": "Lueira CC"})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "clave-generada-cc" in html
    assert "tenant-lueira-cc@calcom.local" in html

    tenant = db.obtener_tenant_por_nombre("Lueira CC")
    assert tenant["calcom_email"] == "tenant-lueira-cc@calcom.local"
    assert tenant["calcom_admin_pass"] == "clave-generada-cc"

    # Un segundo GET al panel ya NO debe volver a mostrar la contraseña.
    resp2 = bo.get("/")
    assert "clave-generada-cc" not in resp2.get_data(as_text=True)


def test_backoffice_crear_tenant_un_fallo_en_calcom_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar_falla(tenant_id, nombre):
        raise aprovisionamiento.calcom.ErrorCalcom("fallo simulado de Cal.diy")

    monkeypatch.setattr(aprovisionamiento.calcom, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = _post(bo, "/tenants", data={"nombre": "SinCalcom"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinCalcom") is not None


def test_backoffice_guardar_calcom_api_key(bo):

    tenant_id = db.crear_tenant("ConCitas")

    resp = _post(bo, 
        f"/tenants/{tenant_id}/claves/calcom",
        data={"api_key": "cal_live_token_real"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert db.obtener_tenant(tenant_id)["calcom_api_key"] == "cal_live_token_real"


def test_backoffice_guardar_calcom_api_key_tenant_inexistente_da_404(bo):

    resp = _post(bo, "/tenants/999999/claves/calcom", data={"api_key": "x"})
    assert resp.status_code == 404


def test_backoffice_borrar_tenant_no_falla_aunque_calcom_no_tenga_desaprovisionar(bo):
    """Cal.diy no tiene desaprovisionar_tenant() (ver app/calcom.py) — el
    borrado del tenant no debe fallar por eso."""

    tenant_id = db.crear_tenant("ABorrarCC")
    db.guardar_calcom(tenant_id, "tenant-aborrarcc@calcom.local", "clave-x")

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_listmonk_sin_nada_que_mostrar(bo, monkeypatch):
    """A diferencia de Cal.diy/FacturaScripts, Listmonk no tiene ninguna
    contraseña humana que enseñar — el token queda guardado directamente."""
    from backoffice import aprovisionamiento

    def fake_aprovisionar(nombre):
        return {"list_id": 3, "list_role_id": 5, "api_key": "tenant-lueira-lm-api:tokengenerado"}

    monkeypatch.setattr(aprovisionamiento.listmonk, "aprovisionar_tenant", fake_aprovisionar)

    resp = _post(bo, "/tenants", data={"nombre": "Lueira LM"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "tokengenerado" not in resp.get_data(as_text=True)

    tenant = db.obtener_tenant_por_nombre("Lueira LM")
    assert tenant["listmonk_list_id"] == 3
    assert tenant["listmonk_list_role_id"] == 5
    assert tenant["listmonk_api_key"] == "tenant-lueira-lm-api:tokengenerado"


def test_backoffice_crear_tenant_un_fallo_en_listmonk_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar_falla(nombre):
        raise aprovisionamiento.listmonk.ErrorListmonk("fallo simulado de Listmonk")

    monkeypatch.setattr(aprovisionamiento.listmonk, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = _post(bo, "/tenants", data={"nombre": "SinListmonk"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinListmonk") is not None


def test_backoffice_crear_usuario_da_de_alta_en_listmonk_con_el_rol_de_lista_del_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ConListaLM")
    db.guardar_listmonk(tenant_id, 3, 5, "tenant-conlistalm-api:token")

    llamadas = {}

    def fake_crear_usuario_tenant(email, list_role_id):
        llamadas["args"] = (email, list_role_id)

    monkeypatch.setattr(aprovisionamiento.listmonk, "crear_usuario_tenant", fake_crear_usuario_tenant)

    resp = _post(bo, 
        "/usuarios", data={"email": "ana-lm@ejemplo.com", "tenant_id": tenant_id}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert llamadas["args"] == ("ana-lm@ejemplo.com", 5)


def test_backoffice_crear_usuario_sin_lista_de_listmonk_no_intenta_dar_de_alta(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("SinListaLM")

    llamado = []
    monkeypatch.setattr(aprovisionamiento.listmonk, "crear_usuario_tenant", lambda *a: llamado.append(1))

    resp = _post(bo, 
        "/usuarios", data={"email": "ana-lm2@ejemplo.com", "tenant_id": tenant_id}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert llamado == []


def test_backoffice_borrar_tenant_desaprovisiona_listmonk(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrarLM")
    db.guardar_listmonk(tenant_id, 3, 5, "token")

    llamadas = {}

    def fake_desaprovisionar(list_id, list_role_id):
        llamadas["args"] = (list_id, list_role_id)

    monkeypatch.setattr(aprovisionamiento.listmonk, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["args"] == (3, 5)
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_stalwart_solo_si_hay_dominio(bo, monkeypatch):
    """Stalwart es el único proveedor que necesita un dato manual (el
    dominio propio real del cliente) — sin él, se omite igual que si
    STALWART_ADMIN_USER/PASSWORD no estuvieran configuradas."""
    from backoffice import aprovisionamiento

    llamado = []
    monkeypatch.setattr(aprovisionamiento.stalwart, "aprovisionar_tenant", lambda *a: llamado.append(a))

    resp = _post(bo, "/tenants", data={"nombre": "SinDominioSW"}, follow_redirects=True)
    assert resp.status_code == 200
    assert llamado == []
    assert db.obtener_tenant_por_nombre("SinDominioSW") is not None


def test_backoffice_crear_tenant_aprovisiona_stalwart_con_dominio(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar(tenant_id, nombre, dominio_correo):
        return {
            "stalwart_tenant_id": "b", "domain_id": "c", "domain_name": dominio_correo,
            "account_id": "d", "api_key": "API_generado",
        }

    monkeypatch.setattr(aprovisionamiento.stalwart, "aprovisionar_tenant", fake_aprovisionar)

    resp = _post(bo, 
        "/tenants", data={"nombre": "ConDominioSW", "dominio_correo": "clientea.com"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    tenant = db.obtener_tenant_por_nombre("ConDominioSW")
    assert tenant["stalwart_tenant_id"] == "b"
    assert tenant["stalwart_domain_name"] == "clientea.com"
    assert tenant["stalwart_api_key"] == "API_generado"


def test_backoffice_crear_tenant_un_fallo_en_stalwart_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar_falla(tenant_id, nombre, dominio_correo):
        raise aprovisionamiento.stalwart.ErrorStalwart("fallo simulado de Stalwart")

    monkeypatch.setattr(aprovisionamiento.stalwart, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = _post(bo, 
        "/tenants", data={"nombre": "ConFalloSW", "dominio_correo": "clientea.com"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("ConFalloSW") is not None


def test_backoffice_borrar_tenant_desaprovisiona_stalwart(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrarSW")
    db.guardar_stalwart(tenant_id, "b", "c", "clientea.com", "d", "API_token")

    llamadas = {}

    def fake_desaprovisionar(stalwart_tenant_id, domain_id, account_id):
        llamadas["args"] = (stalwart_tenant_id, domain_id, account_id)

    monkeypatch.setattr(aprovisionamiento.stalwart, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["args"] == ("b", "c", "d")
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_ntfy(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar(tenant_id, nombre):
        return {"topic": f"guilda-{nombre.lower()}-{tenant_id}", "token": "tk_real"}

    monkeypatch.setattr(aprovisionamiento.ntfy, "aprovisionar_tenant", fake_aprovisionar)

    resp = _post(bo, "/tenants", data={"nombre": "ConNtfy"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("ConNtfy")
    assert tenant["ntfy_token"] == "tk_real"
    assert tenant["ntfy_topic"] == f"guilda-conntfy-{tenant['id']}"


def test_backoffice_crear_tenant_sin_ntfy_configurado_no_falla(bo):

    resp = _post(bo, "/tenants", data={"nombre": "SinNtfy"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("SinNtfy") is not None


def test_backoffice_crear_tenant_un_fallo_en_ntfy_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar_falla(tenant_id, nombre):
        raise aprovisionamiento.ntfy.ErrorNtfy("fallo simulado de ntfy")

    monkeypatch.setattr(aprovisionamiento.ntfy, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = _post(bo, "/tenants", data={"nombre": "NtfyFalla"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("NtfyFalla") is not None


def test_backoffice_borrar_tenant_desaprovisiona_ntfy(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrarNtfy")
    db.guardar_ntfy(tenant_id, "guilda-aborrarntfy-1", "tk_real")

    llamadas = {}

    def fake_desaprovisionar(t_id):
        llamadas["tenant_id"] = t_id

    monkeypatch.setattr(aprovisionamiento.ntfy, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["tenant_id"] == tenant_id
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_tenant_aprovisiona_umami(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar(tenant_id, nombre):
        return {"team_id": f"team-{tenant_id}", "website_id": f"site-{tenant_id}"}

    monkeypatch.setattr(aprovisionamiento.umami, "aprovisionar_tenant", fake_aprovisionar)

    resp = _post(bo, "/tenants", data={"nombre": "ConUmami"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("ConUmami")
    assert tenant["umami_team_id"] == f"team-{tenant['id']}"
    assert tenant["umami_website_id"] == f"site-{tenant['id']}"


def test_backoffice_crear_tenant_sin_umami_configurado_no_falla(bo, monkeypatch):
    from backoffice import aprovisionamiento

    monkeypatch.setattr(aprovisionamiento.umami, "aprovisionar_tenant", lambda tenant_id, nombre: None)

    resp = _post(bo, "/tenants", data={"nombre": "SinUmami"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("SinUmami")
    assert tenant is not None
    assert tenant["umami_team_id"] is None


def test_backoffice_crear_tenant_un_fallo_en_umami_no_bloquea_el_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento

    def fake_aprovisionar_falla(tenant_id, nombre):
        raise aprovisionamiento.umami.ErrorUmami("fallo simulado de umami")

    monkeypatch.setattr(aprovisionamiento.umami, "aprovisionar_tenant", fake_aprovisionar_falla)

    resp = _post(bo, "/tenants", data={"nombre": "UmamiFalla"}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_tenant_por_nombre("UmamiFalla") is not None


def test_backoffice_borrar_tenant_desaprovisiona_umami(bo, monkeypatch):
    from backoffice import aprovisionamiento

    tenant_id = db.crear_tenant("ABorrarUmami")
    db.guardar_umami(tenant_id, "team-1", "site-1")

    llamadas = {}

    def fake_desaprovisionar(team_id):
        llamadas["team_id"] = team_id

    monkeypatch.setattr(aprovisionamiento.umami, "desaprovisionar_tenant", fake_desaprovisionar)

    resp = _borrar(bo, tenant_id)
    assert resp.status_code == 200
    assert llamadas["team_id"] == "team-1"
    assert db.obtener_tenant(tenant_id) is None


def test_backoffice_crear_usuario_da_de_alta_en_umami_con_el_team_del_tenant(bo, monkeypatch):
    from backoffice import aprovisionamiento
    tenant_id = db.crear_tenant("TenantUmami")
    db.guardar_umami(tenant_id, "team-42", "site-42")

    llamadas = {}

    def fake_crear_usuario_tenant(email, team_id, contrasena):
        llamadas["args"] = (email, team_id, contrasena)

    monkeypatch.setattr(aprovisionamiento.umami, "crear_usuario_tenant", fake_crear_usuario_tenant)

    resp = _post(bo, 
        "/usuarios",
        data={"email": "nuevo-umami@ejemplo.com", "tenant_id": tenant_id},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    email, team_id, contrasena = llamadas["args"]
    assert email == "nuevo-umami@ejemplo.com"
    assert team_id == "team-42"
    assert contrasena  # contraseña temporal generada, no vacía


def test_backoffice_crear_usuario_sin_umami_del_tenant_no_intenta_dar_de_alta(bo, monkeypatch):
    from backoffice import aprovisionamiento
    tenant_id = db.crear_tenant("TenantSinUmami")

    def fake_crear_usuario_tenant(*a, **k):
        raise AssertionError("no debería llamarse")

    monkeypatch.setattr(aprovisionamiento.umami, "crear_usuario_tenant", fake_crear_usuario_tenant)

    resp = _post(bo, 
        "/usuarios",
        data={"email": "otro@ejemplo.com", "tenant_id": tenant_id},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_backoffice_crear_tenant_oculta_observabilidad_por_defecto(bo):

    resp = _post(bo, "/tenants", data={"nombre": "TenantObs"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("TenantObs")
    assert "observabilidad" in db.herramientas_ocultas_de_tenant(tenant["id"])


def test_backoffice_admin_puede_mostrar_observabilidad_a_mano(bo):

    resp = _post(bo, "/tenants", data={"nombre": "TenantObs2"}, follow_redirects=True)
    tenant = db.obtener_tenant_por_nombre("TenantObs2")
    assert "observabilidad" in db.herramientas_ocultas_de_tenant(tenant["id"])

    ruta = f"/tenants/{tenant['id']}/modulos/observabilidad"
    _post(bo, ruta, follow_redirects=True)
    assert "observabilidad" not in db.herramientas_ocultas_de_tenant(tenant["id"])


def test_backoffice_crear_tenant_oculta_portainer_por_defecto(bo):

    resp = _post(bo, "/tenants", data={"nombre": "TenantPort"}, follow_redirects=True)
    assert resp.status_code == 200
    tenant = db.obtener_tenant_por_nombre("TenantPort")
    assert "portainer" in db.herramientas_ocultas_de_tenant(tenant["id"])


def test_backoffice_admin_puede_mostrar_portainer_a_mano(bo):

    resp = _post(bo, "/tenants", data={"nombre": "TenantPort2"}, follow_redirects=True)
    tenant = db.obtener_tenant_por_nombre("TenantPort2")
    assert "portainer" in db.herramientas_ocultas_de_tenant(tenant["id"])

    ruta = f"/tenants/{tenant['id']}/modulos/portainer"
    _post(bo, ruta, follow_redirects=True)
    assert "portainer" not in db.herramientas_ocultas_de_tenant(tenant["id"])


def test_backoffice_crear_webhook_de_ambito_local(bo):

    resp = _post(bo, 
        "/webhooks",
        data={"tenant_id": "", "url": "https://ejemplo.com/hook", "eventos": ["tarea.finalizada", "nota.creada"]},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    webhooks = db.listar_webhooks(None)
    assert len(webhooks) == 1
    assert webhooks[0]["url"] == "https://ejemplo.com/hook"


def test_backoffice_crear_webhook_de_un_tenant(bo):
    tenant_id = db.crear_tenant("TenantWebhook")

    resp = _post(bo, 
        "/webhooks",
        data={"tenant_id": str(tenant_id), "url": "https://ejemplo.com/hook", "eventos": ["cita.reservada"]},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    webhooks = db.listar_webhooks(tenant_id)
    assert len(webhooks) == 1


def test_backoffice_crear_webhook_sin_eventos_no_lo_crea(bo):

    _post(bo, "/webhooks", data={"tenant_id": "", "url": "https://ejemplo.com/hook"}, follow_redirects=True)
    assert db.listar_webhooks(None) == []


def test_backoffice_crear_webhook_ignora_eventos_no_reconocidos(bo):

    _post(bo, 
        "/webhooks",
        data={"tenant_id": "", "url": "https://ejemplo.com/hook", "eventos": ["evento.inventado"]},
        follow_redirects=True,
    )
    assert db.listar_webhooks(None) == []


def test_backoffice_crear_webhook_tenant_inexistente_da_404(bo):

    resp = _post(bo, 
        "/webhooks",
        data={"tenant_id": "999999", "url": "https://ejemplo.com/hook", "eventos": ["nota.creada"]},
    )
    assert resp.status_code == 404


def test_backoffice_borrar_webhook(bo):
    usuario_id = db.crear_usuario_vinculado_a_kratos("wh-borrar@ejemplo.com", "k-wh-borrar")
    w = db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook", ["nota.creada"])

    resp = _post(bo, f"/webhooks/{w['id']}/borrar", follow_redirects=True)
    assert resp.status_code == 200
    assert db.obtener_webhook(w["id"]) is None


def test_backoffice_borrar_webhook_inexistente_da_404(bo):

    resp = _post(bo, "/webhooks/999999/borrar")
    assert resp.status_code == 404


def test_backoffice_exportar_datos_tenant_devuelve_json_descargable(bo):
    tenant_id = db.crear_tenant("Gestoria Export Ruta")
    db.crear_cliente_fiscal(tenant_id, "Cliente Export Ruta")

    resp = _post(bo, f"/tenants/{tenant_id}/exportar")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert "attachment" in resp.headers["Content-Disposition"]
    datos = resp.get_json()
    assert datos["tenant"]["nombre"] == "Gestoria Export Ruta"
    assert len(datos["clientes_fiscales"]) == 1


def test_backoffice_exportar_datos_tenant_deja_entrada_de_auditoria(bo):
    tenant_id = db.crear_tenant("Gestoria Export Auditoria")

    _post(bo, f"/tenants/{tenant_id}/exportar")

    assert any(r["accion"] == "tenant.exportar" for r in auth.listar_auditoria())


def test_backoffice_exportar_datos_tenant_inexistente_da_404(bo):

    resp = _post(bo, "/tenants/999999/exportar")
    assert resp.status_code == 404
