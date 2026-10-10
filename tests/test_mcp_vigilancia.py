"""MCP: cada llamada queda medida, limitada y auditada (sin guardar contenidos), y se ve en el backoffice."""
import asyncio
import json

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP

import mcp_server_remoto as remoto
import mcp_tools as mt
from app import auth, db, mcp_acceso
from tests.test_backoffice_app import bo, entrar  # noqa: F401 -- fixture


@pytest.fixture(autouse=True)
def _ventanas_limpias():
    auth.reiniciar_limite_api()
    yield
    auth.reiniciar_limite_api()


def _herramientas():
    return {n: t.fn for n, t in _servidor()._tool_manager._tools.items()}


def _servidor():
    s = FastMCP("t")
    mt.registrar_tools(s, grupos=None, solo_lectura=False)
    return s


def _con(scopes, client_id="chatgpt", subject=None):
    return auth_context_var.set(AuthenticatedUser(AccessToken(token="t", client_id=client_id, scopes=scopes, subject=subject)))


def _auditoria(**f):
    return db.mcp_auditoria_listar(200, **f)


def test_llamada_local_se_audita_con_la_forma_de_los_argumentos_y_sin_contenidos():
    tools = _herramientas()
    texto, titulo = "Contenido MUY privado del cliente García", "Asunto reservado"
    tools["crear_nota"](texto=texto, titulo=titulo)
    tools["listar_notas"]()
    a = {r["herramienta"]: r for r in _auditoria()}
    assert a["crear_nota"]["cliente"] == "local" and a["crear_nota"]["resultado"] == "ok" and a["crear_nota"]["lectura"] == 0
    assert a["listar_notas"]["lectura"] == 1 and a["crear_nota"]["duracion_ms"] is not None
    assert json.loads(a["crear_nota"]["argumentos"]) == {"texto": f"texto({len(texto)})", "titulo": f"texto({len(titulo)})"}
    volcado = json.dumps(_auditoria())
    assert "García" not in volcado and "privado" not in volcado and "reservado" not in volcado          # privacidad: nunca el contenido


def test_los_errores_y_los_ids_se_registran():
    tools = _herramientas()
    with pytest.raises(ValueError):
        tools["eliminar_nota"](nota_id=99999)
    r = _auditoria(resultado="error")[0]
    assert r["herramienta"] == "eliminar_nota" and "No existe la nota" in r["detalle"] and json.loads(r["argumentos"]) == {"nota_id": 99999}
    uso = db.mcp_resumen(7)
    assert uso["llamadas"] == 1 and uso["errores"] == 1 and uso["por_herramienta"][0]["herramienta"] == "eliminar_nota"


def test_limite_por_persona_para_conexiones_remotas(monkeypatch):
    monkeypatch.setenv("GUILDA_MCP_LIMITE_POR_MINUTO", "3")
    monkeypatch.setenv("GUILDA_MCP_LIMITE_ESCRITURAS_POR_MINUTO", "2")
    u = db.crear_usuario_vinculado_a_kratos("l@x.com", "k-l")
    otro = db.crear_usuario_vinculado_a_kratos("o@x.com", "k-o")
    tools = _herramientas()
    ctx = _con([], subject="k-l")
    try:
        tools["crear_nota"](texto="1"); tools["crear_nota"](texto="2")
        with pytest.raises(ValueError, match="límite de llamadas al MCP"):
            tools["crear_nota"](texto="3")                                 # 2 escrituras por minuto
        tools["listar_notas"]()                                              # la tercera llamada total (la escritura rechazada no gastó cupo)
        with pytest.raises(ValueError, match="límite"):
            tools["listar_notas"]()                                          # 3 por minuto en total
    finally:
        auth_context_var.reset(ctx)
    assert len(db.listar_notas(u)) == 2                                      # la rechazada no se ejecutó
    assert [r["resultado"] for r in _auditoria(usuario_id=u, resultado="limite")] == ["limite", "limite"]
    ctx = _con([], subject="k-o")
    try:
        assert tools["listar_notas"]() == []                                 # otra persona: su propio cupo
    finally:
        auth_context_var.reset(ctx)
    tools["listar_notas"](); tools["listar_notas"](); tools["listar_notas"](); tools["listar_notas"]()   # stdio local: sin límite
    assert all(r["cliente"] == "local" for r in _auditoria()[:4])


def test_token_personal_cuenta_en_su_uso_y_las_denegaciones_tambien(monkeypatch):
    u = db.crear_usuario_vinculado_a_kratos("p@x.com", "k-p")
    token = db.crear_token_api(u, "integración", "solo_lectura", areas=["notas"])
    verificado = asyncio.run(remoto.VerificadorHydra().verify_token(token))
    assert any(s.startswith("token:") for s in verificado.scopes) and mcp_acceso.token_de_scopes(verificado.scopes) == db.id_de_token(token)
    tools = _herramientas()
    ctx = auth_context_var.set(AuthenticatedUser(verificado))
    try:
        tools["listar_notas"]()
        with pytest.raises(ValueError, match="solo lectura"):
            tools["crear_nota"](texto="x")
        with pytest.raises(ValueError, match="solo tiene acceso"):
            tools["listar_tareas"]()
    finally:
        auth_context_var.reset(ctx)
    uso = db.uso_de_token(db.id_de_token(token))
    assert uso[0]["llamadas"] == 3 and uso[0]["errores"] == 2                  # el MCP suma al uso del token (visible en /tokens-api)
    assert [r["resultado"] for r in _auditoria(usuario_id=u)] == ["denegado", "denegado", "ok"]
    assert {r["cliente"] for r in _auditoria(usuario_id=u)} == {"token-personal"} and _auditoria(usuario_id=u)[0]["token_id"] == db.id_de_token(token)
    assert db.listar_notas(u) == []                                              # lo denegado no se ejecutó


def test_filtros_de_la_auditoria_y_tenant():
    t1, t2 = db.crear_tenant("Despacho M1"), db.crear_tenant("Despacho M2")
    a = db.crear_usuario_vinculado_a_kratos("a@x.com", "k-a"); db.asignar_tenant(a, t1)
    b = db.crear_usuario_vinculado_a_kratos("b@x.com", "k-b"); db.asignar_tenant(b, t2)
    db.mcp_registrar_llamada(a, "chatgpt", None, "listar_notas", True, "ok")
    db.mcp_registrar_llamada(a, "chatgpt", None, "crear_nota", False, "ok", argumentos={"texto": "texto(3)"})
    db.mcp_registrar_llamada(b, "claude-desktop", None, "crear_nota", False, "error", "boom")
    assert len(_auditoria(tenant_id=t1)) == 2 and len(_auditoria(tenant_id=t2)) == 1
    assert [r["herramienta"] for r in _auditoria(solo_escrituras=True, tenant_id=t1)] == ["crear_nota"]
    assert len(_auditoria(herramienta="crear_nota")) == 2 and len(_auditoria(resultado="error")) == 1
    r = db.mcp_resumen(30, tenant_id=t1)
    assert (r["llamadas"], r["errores"], r["usuarios"]) == (2, 0, 1) and r["por_usuario"][0]["email"] == "a@x.com"
    assert db.mcp_resumen(30)["llamadas"] == 3


def test_pagina_de_actividad_mcp_en_el_backoffice(bo):
    assert bo.get("/actividad-mcp").status_code == 302                            # exige sesión
    entrar(bo)
    t = db.crear_tenant("Despacho Pantalla")
    u = db.crear_usuario_vinculado_a_kratos("pantalla@x.com", "k-pant"); db.asignar_tenant(u, t)
    db.mcp_registrar_llamada(u, "chatgpt", None, "crear_nota", False, "ok", argumentos={"texto": "texto(12)"}, duracion_ms=7)
    db.mcp_registrar_llamada(u, "token-personal", 5, "listar_tareas", True, "denegado", "Esta credencial solo tiene acceso a: notas.")
    html = bo.get("/actividad-mcp").get_data(as_text=True)
    assert "crear_nota" in html and "pantalla@x.com" in html and "ESCRIBE" in html and "DENEGADO" in html and "solo tiene acceso" in html and "texto(12)" in html
    assert "listar_tareas" not in bo.get("/actividad-mcp?resultado=ok").get_data(as_text=True).split("Registro de llamadas")[1]
    assert "crear_nota" not in bo.get("/actividad-mcp?escrituras=0&herramienta=listar_tareas").get_data(as_text=True).split("Registro de llamadas")[1]
    assert bo.get(f"/actividad-mcp?usuario={u}&dias=7").status_code == 200 and bo.get("/actividad-mcp?dias=999&resultado=raro").status_code == 200
    assert "Actividad MCP" in bo.get("/buscar?q=mcp").get_data(as_text=True)
