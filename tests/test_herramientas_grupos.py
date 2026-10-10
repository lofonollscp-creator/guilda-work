"""Grupos de herramientas: catálogo dinámico del chat de IA y perfiles del servidor MCP."""
import json

import pytest
from mcp.server.fastmcp import FastMCP

import mcp_tools as mt
from app import db, herramientas_grupos as hg, ia_asistente, ia_herramientas as ih


def _nombres(herramientas):
    return {t["function"]["name"] for t in herramientas}


def _u(texto):
    return {"role": "user", "content": texto}


def test_cada_herramienta_del_chat_tiene_grupo_y_ninguna_se_repite():
    en_grupos = [n for nombres in hg.GRUPOS.values() for n in nombres]
    assert len(en_grupos) == len(set(en_grupos))
    sin_grupo = [n for n in _nombres(ih.HERRAMIENTAS) if hg.grupo_de(n) in ("otros", "integraciones", "backoffice")]
    assert sin_grupo == []


def test_cada_herramienta_del_mcp_tiene_grupo_conocido():
    desconocidas = [t.__name__ for t in mt.TOOLS if hg.grupo_de(t.__name__) == "otros"]
    assert desconocidas == []


def test_conversacion_sin_pistas_solo_ofrece_el_nucleo_y_ahorra_mucho():
    todas = ih.herramientas_para(None)
    basicas = ih.herramientas_para([{"role": "system", "content": "s"}, _u("hola, ¿qué tal?")])
    nombres = _nombres(basicas)
    assert "crear_tarea" in nombres and "activar_herramientas" in nombres and "resumen_del_dia" in nombres
    assert "enviar_borrador_correo" not in nombres and "crm_crear_lead" not in nombres
    assert len(json.dumps(basicas)) < len(json.dumps(todas)) * 0.4


def test_las_palabras_clave_activan_su_grupo():
    n = _nombres(ih.herramientas_para([_u("Mira si me ha escrito algo el cliente por correo")]))
    assert "listar_bandeja_entrada" in n and "listar_vencimientos_fiscales" in n and "crm_crear_lead" not in n
    assert "fichar" in _nombres(ih.herramientas_para([_u("ficha mi entrada")]))
    assert "crear_factura_cliente" in _nombres(ih.herramientas_para([_u("prepara la factura")]))


def test_solo_cuentan_los_ultimos_mensajes_del_usuario():
    mensajes = [_u("revisa el correo")] + [_u(f"vale {i}") for i in range(4)]
    assert "listar_bandeja_entrada" not in _nombres(ih.herramientas_para(mensajes))


def test_lo_ya_usado_se_mantiene_activo_y_activar_herramientas_funciona():
    usada = {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "function": {"name": "listar_bandeja_entrada", "arguments": "{}"}}]}
    assert "leer_correo" in _nombres(ih.herramientas_para([_u("sigue"), usada]))
    pide = {"role": "assistant", "content": None, "tool_calls": [{"id": "2", "function": {"name": "activar_herramientas", "arguments": json.dumps({"grupos": ["crm", "inventado"]})}}]}
    n = _nombres(ih.herramientas_para([_u("apunta un lead"), pide]))
    assert "crm_crear_lead" in n and "leer_correo" not in n


def test_solo_lectura_sigue_filtrando_dentro_del_catalogo_dinamico():
    n = _nombres(ih.herramientas_para([_u("correo y cliente fiscal")], solo_lectura=True))
    assert "listar_bandeja_entrada" in n and "crear_tarea" not in n and "enviar_borrador_correo" not in n


def test_activar_herramientas_responde_con_lo_que_se_activa(monkeypatch):
    assert "correo:" in ih.ejecutar(1, "activar_herramientas", {"grupos": ["correo"]})
    assert "Grupos disponibles" in ih.ejecutar(1, "activar_herramientas", {"grupos": ["nada"]})
    assert not ih.necesita_confirmacion("activar_herramientas", False)


def test_el_asistente_manda_el_catalogo_reducido(monkeypatch):
    u = db.crear_usuario_vinculado_a_kratos("g@x.com", "k-g")
    monkeypatch.setattr(ia_asistente, "obtener_api_keys", lambda uid: ["k"])
    monkeypatch.setattr(db, "obtener_preferencias_ia", lambda uid: {"modelo": "m/x", "modo_autonomo": 0, "solo_lectura": 0})
    enviados = []
    monkeypatch.setattr(ia_asistente, "_post_json_con_fallback", lambda url, payload, claves: enviados.append(payload) or {"choices": [{"message": {"content": "ok"}}]})
    ia_asistente.procesar_turno(u, "hola")
    assert len(enviados[0]["tools"]) < len(ih.HERRAMIENTAS) / 3
    ia_asistente.procesar_turno(u, "enséñame los correos sin leer")
    assert "listar_bandeja_entrada" in _nombres(enviados[1]["tools"])


# --- MCP externo ---------------------------------------------------------------------------------------

def test_es_lectura_nunca_confunde_escrituras():
    for t in mt.TOOLS:
        nombre = t.__name__
        if hg.es_lectura(nombre, ih.LECTURA):
            assert not hg._VERBOS_ESCRITURA.search(nombre) or nombre in ih.LECTURA, nombre
    assert not hg.es_lectura("crear_tarea") and not hg.es_lectura("enviar_borrador_correo") and hg.es_lectura("listar_notas")
    assert hg.es_lectura("backoffice_listar_tenants") and not hg.es_lectura("backoffice_crear_tenant")


def test_perfiles_del_mcp():
    todas = mt.tools_filtradas()
    assert len(todas) == len(mt.TOOLS)
    solo_fiscal = {t.__name__ for t in mt.tools_filtradas({"fiscal"})}
    assert "listar_clientes_fiscales" in solo_fiscal and "crear_nota" in solo_fiscal       # núcleo siempre
    assert "listar_bandeja_entrada" not in solo_fiscal and "backoffice_crear_tenant" not in solo_fiscal
    lectura = {t.__name__ for t in mt.tools_filtradas(solo_lectura=True)}
    assert "listar_notas" in lectura and "crear_nota" not in lectura and "backoffice_crear_usuario" not in lectura
    assert len(lectura) < len(todas) * 0.6


def test_registrar_tools_lee_el_perfil_del_entorno(monkeypatch):
    monkeypatch.setenv("GUILDA_MCP_GRUPOS", "fiscal")
    monkeypatch.setenv("GUILDA_MCP_SOLO_LECTURA", "1")
    servidor = FastMCP("t")
    mt.registrar_tools(servidor)
    registradas = set(servidor._tool_manager._tools)
    assert "listar_vencimientos_fiscales" in registradas and "crear_nota" not in registradas and "listar_notas" in registradas
    monkeypatch.delenv("GUILDA_MCP_GRUPOS"); monkeypatch.delenv("GUILDA_MCP_SOLO_LECTURA")
    completo = FastMCP("t2")
    mt.registrar_tools(completo)
    assert len(completo._tool_manager._tools) == len(mt.TOOLS)


# --- Herramientas nuevas ---------------------------------------------------------------------------------

def test_resumen_del_dia_detalle_y_completar_en_lote():
    u = db.crear_usuario_vinculado_a_kratos("r@x.com", "k-r")
    t = db.crear_tenant("Despacho R")
    db.asignar_tenant(u, t)
    token = mt._usuario_id_actual.set(u)
    try:
        a = db.crear_tarea_outlook(u, "Vencida", fecha_vencimiento="2020-01-01")
        b = db.crear_tarea_outlook(u, "Otra", fecha_vencimiento="2020-01-02")
        db.agregar_item_checklist(u, a, "Paso")
        r = mt.resumen_del_dia()
        assert set(r) == {"mi_dia", "vencimientos_7_dias", "correos_sin_leer", "notificaciones_sin_leer"}
        assert any(x["id"] == a for filas in r["mi_dia"].values() for x in filas)
        assert mt.detalle_tarea(a)["checklist"][0]["texto"] == "Paso"
        with pytest.raises(ValueError):
            mt.detalle_tarea(9999)
        res = mt.completar_tareas([a, b, b, 9999])
        assert res == {"completadas": [a, b], "no_encontradas": [9999]}
        assert mt.listar_notificaciones()["sin_leer"] == 0
    finally:
        mt._usuario_id_actual.reset(token)
