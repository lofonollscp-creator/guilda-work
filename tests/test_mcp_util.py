"""MCP más útil: respuestas recortadas con aviso, `tenant` opcional, HTML de correo opcional, herramientas nuevas, prompts y recursos."""
import asyncio
import json
import re

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP

import mcp_tools as mt
from app import auth, db, mcp_utilidad as mu


@pytest.fixture(autouse=True)
def _limpio():
    auth.reiniciar_limite_api()


def _servidor(**kw):
    s = FastMCP("t")
    mt.registrar_tools(s, **({"grupos": None, "solo_lectura": False} | kw))
    return s


def _tools(s):
    return {n: t.fn for n, t in s._tool_manager._tools.items()}


def _como(usuario_id, kratos):
    return auth_context_var.set(AuthenticatedUser(AccessToken(token="t", client_id="chatgpt", scopes=[], subject=kratos)))


# --- Recorte ------------------------------------------------------------------------------------------------------------------------

def test_los_textos_largos_se_recortan_diciendo_cuanto_habia(monkeypatch):
    largo = "a" * 30000
    r = mu.recortar_resultado({"asunto": "ok", "cuerpo_texto": largo})
    assert r["asunto"] == "ok" and len(r["cuerpo_texto"]) < 12200 and "30000 caracteres en total" in r["cuerpo_texto"]
    monkeypatch.setenv("GUILDA_MCP_MAX_TEXTO", "500")
    assert len(mu.recortar_resultado("x" * 2000)) < 700
    assert mu.recortar_resultado({"n": 1, "ok": True, "l": [1, 2]}) == {"n": 1, "ok": True, "l": [1, 2]}      # lo que cabe, intacto


def test_un_listado_enorme_se_corta_con_aviso_y_los_pequenos_no(monkeypatch):
    filas = [{"id": i, "texto": "x" * 1000} for i in range(200)]
    r = mu.recortar_resultado(filas, max_total=20000)
    assert r[-1]["_truncado"] is True and r[-1]["total"] == 200 and r[-1]["mostrados"] == len(r) - 1 < 200 and "filtro" in r[-1]["aviso"]
    assert all("_truncado" not in x for x in r[:-1])
    assert mu.recortar_resultado(filas[:5], max_total=20000) == filas[:5]
    assert mu.recortar_resultado(["a"] * 10, max_total=5) == ["a"] * 10                                      # no son filas: no se inventa un marcador
    assert mu.recortar_resultado(None) is None and mu.recortar_resultado(3) == 3


def test_las_herramientas_registradas_recortan(monkeypatch):
    monkeypatch.setenv("GUILDA_MCP_MAX_CHARS", "3000")
    u = db.crear_usuario_vinculado_a_kratos("r@x.com", "k-r")
    for i in range(40):
        db.crear_nota(u, "n" * 400)
    ctx = _como(u, "k-r")
    try:
        r = _tools(_servidor())["listar_notas"]()
    finally:
        auth_context_var.reset(ctx)
    assert r[-1].get("_truncado") and r[-1]["total"] == 40 and len(json.dumps(r)) < 4000


# --- tenant opcional ------------------------------------------------------------------------------------------------------------------------

def test_tenant_es_opcional_en_el_esquema_y_por_defecto_es_tu_despacho(monkeypatch):
    t = db.crear_tenant("Despacho Opcional")
    u = db.crear_usuario_vinculado_a_kratos("o@x.com", "k-o"); db.asignar_tenant(u, t)
    sin = db.crear_usuario_vinculado_a_kratos("s@x.com", "k-s")
    otro = db.crear_tenant("Despacho Ajeno")
    conn = db.get_connection(); conn.execute("UPDATE tenants SET facturascripts_url = 'http://fs', facturascripts_api_key = 'k' WHERE id IN (?, ?)", (t, otro)); conn.commit(); conn.close()
    llamadas = []
    monkeypatch.setattr(mt.facturascripts, "listar_clientes", lambda url, key, **k: llamadas.append(url) or [{"ok": True}])
    servidor = _servidor()
    herramienta = servidor._tool_manager._tools["facturas_listar_clientes"]
    esquema = herramienta.parameters
    assert "tenant" in esquema["properties"] and "tenant" not in esquema.get("required", []) and "tu propio despacho" in herramienta.description
    assert "tenant" not in servidor._tool_manager._tools["facturas_crear_cliente"].parameters.get("required", []) and "nombre" in servidor._tool_manager._tools["facturas_crear_cliente"].parameters["required"]
    ctx = _como(u, "k-o")
    try:
        assert _tools(servidor)["facturas_listar_clientes"]() == [{"ok": True}]                      # sin tenant: el suyo
        assert _tools(servidor)["facturas_listar_clientes"](tenant="Despacho Opcional") == [{"ok": True}]
        with pytest.raises(ValueError, match="No existe ningún tenant"):
            _tools(servidor)["facturas_listar_clientes"](tenant="Despacho Ajeno")                  # el de otro sigue vetado
    finally:
        auth_context_var.reset(ctx)
    ctx = _como(sin, "k-s")
    try:
        with pytest.raises(ValueError, match="ninguno asignado"):
            _tools(servidor)["facturas_listar_clientes"]()                                          # sin despacho: hay que nombrarlo
    finally:
        auth_context_var.reset(ctx)
    assert db.mcp_auditoria_listar(10, usuario_id=sin)[0]["resultado"] == "error"


def test_herramientas_que_ya_tenian_tenant_opcional_no_cambian():
    servidor = _servidor()
    assert "tenant" not in servidor._tool_manager._tools["webhooks_listar"].parameters.get("required", [])
    assert "tu propio despacho" not in servidor._tool_manager._tools["webhooks_listar"].description


# --- Correo y herramientas nuevas ---------------------------------------------------------------------------------------------------------

def test_leer_correo_no_repite_el_html_salvo_que_se_pida():
    u = db.crear_usuario_vinculado_a_kratos("c@x.com", "k-c")
    cuenta = db.crear_cuenta_correo(u, "T", "imap", "h", 993, "c@x.com")
    mid = db.guardar_mensaje_correo(cuenta, "1", "Hola", "a@b.com", "c@x.com", "2026-10-01", "texto " * 5000, "<p>" + "html " * 5000 + "</p>")
    ctx = _como(u, "k-c")
    try:
        m = _tools(_servidor())["leer_correo"](mensaje_id=mid)
        assert "cuerpo_html" not in m and "caracteres en total" in m["cuerpo_texto"]
        assert "cuerpo_html" in _tools(_servidor())["leer_correo"](mensaje_id=mid, incluir_html=True)
    finally:
        auth_context_var.reset(ctx)


def test_consumo_ia_comunicados_y_entregas_de_webhook():
    t = db.crear_tenant("Despacho Nuevas")
    sup = db.crear_usuario_vinculado_a_kratos("n@x.com", "k-n"); db.asignar_tenant(sup, t)
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (sup,)); conn.commit(); conn.close()
    from app import comunicados, ia_consumo
    ia_consumo.fijar_limite(t, 10); ia_consumo.reservar(sup)
    comunicados.crear("Mantenimiento", nivel="aviso")
    w = db.crear_webhook(sup, t, "https://h.example/x", ["nota.creada"], origen="mcp")
    db.cola_webhook_encolar(w["id"], "nota.creada", {})
    ctx = _como(sup, "k-n")
    try:
        tools = _tools(_servidor())
        assert tools["consumo_ia"]()["usadas"] == 1 and tools["consumo_ia"]()["limite"] == 10
        assert [c["titulo"] for c in tools["listar_comunicados"]()] == ["Mantenimiento"]
        assert tools["webhooks_entregas"](webhook_id=w["id"])["cola"][0]["evento"] == "nota.creada"
        with pytest.raises(ValueError, match="No existe el webhook"):
            tools["webhooks_entregas"](webhook_id=9999)
    finally:
        auth_context_var.reset(ctx)
    normal = db.crear_usuario_vinculado_a_kratos("nn@x.com", "k-nn"); db.asignar_tenant(normal, t)
    ctx = _como(normal, "k-nn")
    try:
        with pytest.raises(ValueError, match="supervisor"):
            _tools(_servidor())["webhooks_entregas"](webhook_id=w["id"])
    finally:
        auth_context_var.reset(ctx)


# --- Prompts y recursos ---------------------------------------------------------------------------------------------------------------------

def test_los_prompts_estan_registrados_y_solo_nombran_herramientas_que_existen():
    servidor = _servidor()
    nombres = {p.name for p in asyncio.run(servidor.list_prompts())}
    assert nombres == {n for n, _ in mu.PROMPTS} and len(nombres) == 5
    existentes = {t.__name__ for t in mt.TOOLS}
    for nombre, fn in mu.PROMPTS:
        texto = fn(*["Acme"] * (fn.__code__.co_argcount))
        citadas = set(re.findall(r"`([a-z_]+)`", texto))
        assert citadas and citadas <= existentes, (nombre, citadas - existentes)
    r = asyncio.run(servidor.get_prompt("ficha_cliente", {"cliente": "Acme SL"}))
    assert "Acme SL" in r.messages[0].content.text and "resumen_cliente_fiscal" in r.messages[0].content.text
    assert "marcar_presentado_vencimiento_fiscal" in asyncio.run(servidor.get_prompt("preparar_vencimiento", {"cliente": "X", "modelo": "303"})).messages[0].content.text


def test_los_recursos_leen_con_las_mismas_garantias_que_las_herramientas():
    u = db.crear_usuario_vinculado_a_kratos("res@x.com", "k-res")
    db.crear_categoria(u, "Proyecto recurso", None)
    servidor = _servidor()
    uris = {str(r.uri) for r in asyncio.run(servidor.list_resources())}
    assert uris == {uri for uri, *_ in mu.RECURSOS}
    ctx = _como(u, "k-res")
    try:
        contenido = asyncio.run(servidor.read_resource("guilda://proyectos"))
        assert "Proyecto recurso" in next(iter(contenido)).content
        assert "mi_dia" in next(iter(asyncio.run(servidor.read_resource("guilda://resumen-del-dia")))).content
    finally:
        auth_context_var.reset(ctx)
    # un token personal limitado a notas no puede leer lo transversal por la puerta de los recursos
    token = db.crear_token_api(u, "solo notas", "completo", areas=["notas"])
    import asyncio as aio, mcp_server_remoto as remoto
    verificado = aio.run(remoto.VerificadorHydra().verify_token(token))
    ctx = auth_context_var.set(AuthenticatedUser(verificado))
    try:
        with pytest.raises(Exception, match="solo tiene acceso"):
            asyncio.run(servidor.read_resource("guilda://resumen-del-dia"))
    finally:
        auth_context_var.reset(ctx)
    assert any(r["resultado"] == "denegado" and r["herramienta"] == "resumen_del_dia" for r in db.mcp_auditoria_listar(20, usuario_id=u))
    # perfil restringido: un recurso solo existe si su herramienta está expuesta
    solo_fiscal = {str(r.uri) for r in asyncio.run(_servidor(grupos={"fiscal"}, solo_lectura=True).list_resources())}
    assert "guilda://fiscal/clientes" in solo_fiscal and "guilda://consumo-ia" not in solo_fiscal
