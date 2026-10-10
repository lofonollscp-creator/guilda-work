"""Fase 0 de OAuth2: consentimiento real para apps de terceros, MCP solo para clientes pensados para él y despachos
aislados en las herramientas MCP."""
import asyncio

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP

import mcp_tools as mt
import mcp_server_remoto as remoto
from app import db, hydra, mcp_acceso
from tests.conftest import iniciar_sesion_de_prueba


# --- Pantalla de consentimiento ----------------------------------------------------------------------------------------

@pytest.fixture
def hydra_falso(monkeypatch):
    estado = {"aceptado": [], "rechazado": [], "consent": {}}
    monkeypatch.setattr(hydra, "obtener_consent_request", lambda challenge: estado["consent"])
    monkeypatch.setattr(hydra, "aceptar_consent_request", lambda challenge, **k: estado["aceptado"].append((challenge, k)) or "https://app-ext.example/cb?code=ok")
    monkeypatch.setattr(hydra, "rechazar_consent_request", lambda challenge, motivo="": estado["rechazado"].append(challenge) or "https://app-ext.example/cb?error=access_denied")
    return estado


def _consent(subject, *, skip_consent=False, skip=False, nombre="App de terceros"):
    return {"subject": subject, "skip": skip, "requested_scope": ["openid", "offline_access"],
            "client": {"client_id": "abc", "client_name": nombre, "skip_consent": skip_consent, "redirect_uris": ["https://app-ext.example/cb"]}}


def test_cliente_propio_no_pregunta(cliente, hydra_falso):
    uid = iniciar_sesion_de_prueba(cliente, "propio@ejemplo.com", "una-clave-larga-1234")
    hydra_falso["consent"] = _consent(db.obtener_usuario(uid)["kratos_identity_id"], skip_consent=True, nombre="outline")
    r = cliente.get("/hydra/consent?consent_challenge=c1")
    assert r.status_code == 302 and len(hydra_falso["aceptado"]) == 1


def test_cliente_de_terceros_muestra_pantalla_y_decide_la_persona(cliente, hydra_falso):
    uid = iniciar_sesion_de_prueba(cliente, "tercero@ejemplo.com", "una-clave-larga-1234")
    hydra_falso["consent"] = _consent(db.obtener_usuario(uid)["kratos_identity_id"])
    r = cliente.get("/hydra/consent?consent_challenge=c2")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "App de terceros" in html and "tercero@ejemplo.com" in html and "app-ext.example" in html
    assert hydra_falso["aceptado"] == []                                     # nada se acepta solo
    r = cliente.post("/hydra/consent", data={"consent_challenge": "c2", "decision": "denegar"})
    assert r.status_code == 302 and "access_denied" in r.headers["Location"] and hydra_falso["rechazado"] == ["c2"] and hydra_falso["aceptado"] == []
    r = cliente.post("/hydra/consent", data={"consent_challenge": "c2", "decision": "permitir"})
    assert r.status_code == 302 and len(hydra_falso["aceptado"]) == 1
    assert "oauth.consentimiento" in [a["accion"] for a in db.listar_auditoria_backoffice()]
    assert cliente.post("/hydra/consent", data={"consent_challenge": "c2"}).headers["Location"].endswith("access_denied")   # sin decisión = denegar


def test_consentimiento_ya_dado_no_vuelve_a_preguntar(cliente, hydra_falso):
    uid = iniciar_sesion_de_prueba(cliente, "recordado@ejemplo.com", "una-clave-larga-1234")
    hydra_falso["consent"] = _consent(db.obtener_usuario(uid)["kratos_identity_id"], skip=True)
    assert cliente.get("/hydra/consent?consent_challenge=c3").status_code == 302 and len(hydra_falso["aceptado"]) == 1


def test_el_challenge_de_otra_persona_se_rechaza(cliente, hydra_falso):
    iniciar_sesion_de_prueba(cliente, "yo@ejemplo.com", "una-clave-larga-1234")
    otro = db.crear_usuario_vinculado_a_kratos("otro@ejemplo.com", "kratos-otro-id")
    hydra_falso["consent"] = _consent("kratos-otro-id")
    assert cliente.get("/hydra/consent?consent_challenge=c4").status_code == 403
    assert cliente.post("/hydra/consent", data={"consent_challenge": "c4", "decision": "permitir"}).status_code == 403
    assert hydra_falso["aceptado"] == []


def test_sin_sesion_va_al_login_y_no_se_acepta_nada(cliente, hydra_falso):
    hydra_falso["consent"] = _consent("alguien")
    r = cliente.get("/hydra/consent?consent_challenge=c5")
    assert r.status_code == 302 and "/self-service/login" in r.headers["Location"] and hydra_falso["aceptado"] == []


# --- MCP remoto: qué clientes OAuth valen -----------------------------------------------------------------------------

def test_solo_clientes_pensados_para_el_mcp(monkeypatch):
    mcp_acceso._CACHE_CLIENTES.clear()
    clientes = {
        "outline": {"client_name": "outline", "skip_consent": True},
        "drive": {"client_name": "drive", "skip_consent": True, "metadata": {}},
        "claude": {"client_name": "claude-desktop", "skip_consent": True},
        "marcado": {"client_name": "otro", "skip_consent": True, "metadata": {"mcp": True}},
        "chatgpt": {"client_name": "ChatGPT", "skip_consent": False},
    }
    monkeypatch.setattr(hydra, "obtener_cliente", lambda cid: clientes.get(cid))
    esperado = {"outline": False, "drive": False, "claude": True, "marcado": True, "chatgpt": True, "desconocido": False, "": False}
    assert {cid: mcp_acceso.cliente_hydra_permitido(cid) for cid in esperado} == esperado
    monkeypatch.setenv("MCP_REMOTO_CLIENTES", "claude-desktop,drive")
    mcp_acceso._CACHE_CLIENTES.clear()
    assert mcp_acceso.cliente_hydra_permitido("drive")
    mcp_acceso._CACHE_CLIENTES.clear()
    monkeypatch.setattr(hydra, "obtener_cliente", lambda cid: (_ for _ in ()).throw(hydra.ErrorHydra("caído")))
    assert not mcp_acceso.cliente_hydra_permitido("chatgpt")                   # sin poder comprobarlo, cerrado


def test_verificador_acepta_personal_y_filtra_clientes_oauth(monkeypatch):
    mcp_acceso._CACHE_CLIENTES.clear()
    u = db.crear_usuario_vinculado_a_kratos("v@ejemplo.com", "k-v")
    tok = db.crear_token_api(u, "integración", "solo_lectura", areas=["fiscal"])
    v = remoto.VerificadorHydra()
    r = asyncio.run(v.verify_token(tok))
    assert r.client_id == "token-personal" and set(r.scopes) == {f"usuario:{u}", f"token:{db.id_de_token(tok)}", "area:fiscal", "solo_lectura"}
    assert asyncio.run(v.verify_token("inventado")) is None
    monkeypatch.setattr(hydra, "verificar_token", lambda t: {"active": True, "client_id": "outline", "scope": "openid", "sub": "k-v", "exp": 9999999999})
    monkeypatch.setattr(hydra, "obtener_cliente", lambda cid: {"client_name": "outline", "skip_consent": True})
    assert asyncio.run(v.verify_token("token-de-outline")) is None             # token de un servicio satélite: fuera
    monkeypatch.setattr(hydra, "verificar_token", lambda t: {"active": True, "client_id": "gpt", "scope": "openid", "sub": "k-v", "exp": 9999999999})
    mcp_acceso._CACHE_CLIENTES.clear()
    monkeypatch.setattr(hydra, "obtener_cliente", lambda cid: {"client_name": "ChatGPT", "skip_consent": False})
    assert asyncio.run(v.verify_token("token-de-chatgpt")).subject == "k-v"


# --- MCP: un despacho no puede operar sobre otro ---------------------------------------------------------------------

def _como(usuario_id):
    return mt._usuario_id_actual.set(usuario_id)


def test_mcp_no_opera_sobre_otro_despacho(monkeypatch):
    a, b = db.crear_tenant("Gestoría A"), db.crear_tenant("Gestoría B")
    ua = db.crear_usuario_vinculado_a_kratos("a@x.com", "k-a"); db.asignar_tenant(ua, a)
    admin = db.crear_usuario_vinculado_a_kratos("adm@x.com", "k-adm"); db.hacer_admin("adm@x.com")
    conn = db.get_connection()
    conn.execute("UPDATE tenants SET facturascripts_url = 'http://fs', facturascripts_api_key = 'k' WHERE id IN (?, ?)", (a, b)); conn.commit(); conn.close()
    monkeypatch.setattr(mt.facturascripts, "listar_clientes", lambda url, key, **k: [{"ok": True}])
    t = _como(ua)
    try:
        assert mt.facturas_listar_clientes("Gestoría A") == [{"ok": True}]                       # el suyo
        with pytest.raises(ValueError, match="No existe ningún tenant"):
            mt.facturas_listar_clientes("Gestoría B")                                          # el de otro: como si no existiera
        with pytest.raises(ValueError, match="No existe ningún tenant"):
            mt.webhooks_listar("Gestoría B")
    finally:
        mt._usuario_id_actual.reset(t)
    t = _como(admin)
    try:
        assert mt.facturas_listar_clientes("Gestoría B") == [{"ok": True}]                       # un administrador sí
    finally:
        mt._usuario_id_actual.reset(t)


def test_mcp_webhooks_exigen_supervisor_url_publica_y_pertenencia(monkeypatch):
    a, b = db.crear_tenant("Gestoría A2"), db.crear_tenant("Gestoría B2")
    normal = db.crear_usuario_vinculado_a_kratos("n@x.com", "k-n"); db.asignar_tenant(normal, a)
    sup = db.crear_usuario_vinculado_a_kratos("s@x.com", "k-s"); db.asignar_tenant(sup, a)
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (sup,)); conn.commit(); conn.close()
    ajeno = db.crear_webhook(sup, b, "https://b.example/h", ["nota.creada"])
    monkeypatch.setattr(mt.eventos, "validar_url_publica", lambda url: (url.startswith("https://ok."), "no pública"))
    t = _como(normal)
    try:
        with pytest.raises(ValueError, match="supervisor"):
            mt.webhooks_crear("https://ok.example/h", ["nota.creada"], "Gestoría A2")
    finally:
        mt._usuario_id_actual.reset(t)
    t = _como(sup)
    try:
        creado = mt.webhooks_crear("https://ok.example/h", ["nota.creada"], "Gestoría A2")
        assert creado["origen"] == "mcp" and creado["secreto"]
        with pytest.raises(ValueError, match="no pública"):
            mt.webhooks_crear("http://127.0.0.1:5678/h", ["nota.creada"], "Gestoría A2")
        with pytest.raises(ValueError):
            mt.webhooks_borrar(ajeno["id"])                                                   # webhook de otro despacho
        assert db.obtener_webhook(ajeno["id"]) is not None
        mt.webhooks_borrar(creado["id"])
    finally:
        mt._usuario_id_actual.reset(t)


# --- MCP: anotaciones y alcance de los tokens personales ------------------------------------------------------------

def _servidor(**kw):
    s = FastMCP("t")
    mt.registrar_tools(s, **kw)
    return s


def test_anotaciones_estandar_en_cada_herramienta():
    tools = _servidor(grupos=None, solo_lectura=False)._tool_manager._tools
    assert len(tools) == len(mt.TOOLS)
    a = {n: t.annotations for n, t in tools.items()}
    assert a["listar_notas"].readOnlyHint is True and a["listar_notas"].destructiveHint is False
    assert a["crear_nota"].readOnlyHint is False and a["crear_nota"].destructiveHint is False
    assert a["eliminar_nota"].destructiveHint is True and a["editar_nota"].idempotentHint is True
    assert a["enviar_borrador_correo"].destructiveHint is True and a["backoffice_listar_tenants"].readOnlyHint is True
    assert a["drive_subir_archivo"].openWorldHint is True and a["listar_notas"].openWorldHint is False
    assert all(x is not None for x in a.values())


def _con_token(scopes, client_id="token-personal"):
    return auth_context_var.set(AuthenticatedUser(AccessToken(token="t", client_id=client_id, scopes=scopes)))


def test_token_personal_con_areas_y_solo_lectura_limita_las_herramientas():
    u = db.crear_usuario_vinculado_a_kratos("g@x.com", "k-g")
    tools = _servidor(grupos=None, solo_lectura=False)._tool_manager._tools
    ctx = _con_token([f"usuario:{u}", "area:notas"])
    try:
        assert tools["crear_nota"].fn(texto="hola")["texto"] == "hola"                          # y se crea como ESE usuario
        assert [n["usuario_id"] for n in db.listar_notas(u)] == [u]
        for prohibida in ("listar_tareas", "listar_bandeja_entrada", "buscar_semantico", "resumen_del_dia", "backoffice_listar_tenants"):
            with pytest.raises(ValueError, match="solo tiene acceso"):
                tools[prohibida].fn(**({"texto": "x"} if prohibida == "buscar_semantico" else {}))
    finally:
        auth_context_var.reset(ctx)
    ctx = _con_token([f"usuario:{u}", "solo_lectura"])
    try:
        assert tools["listar_notas"].fn() != []
        with pytest.raises(ValueError, match="solo lectura"):
            tools["crear_nota"].fn(texto="no")
    finally:
        auth_context_var.reset(ctx)
    ctx = _con_token([f"usuario:{u}"], client_id="chatgpt")                                      # token OAuth: sin restricción
    try:
        assert tools["listar_tareas"].fn() == []
    finally:
        auth_context_var.reset(ctx)


def test_cada_herramienta_tiene_area_conocida_y_las_restringidas_no_cruzan_areas():
    from app import herramientas_grupos as hg
    from app.api_areas import AREAS
    for n in [t.__name__ for t in mt.TOOLS]:
        assert hg.area_de_herramienta(n) in set(AREAS) | {"transversal"}
    for n in ("buscar_semantico", "resumen_del_dia", "exportar_historial", "crear_tarea_desde_correo", "guardar_nota_desde_correo", "listar_papelera"):
        assert hg.area_de_herramienta(n) == "transversal", n
    assert hg.area_de_herramienta("crm_crear_lead") == "transversal" and hg.area_de_herramienta("webhooks_crear") == "webhooks"
