"""El MCP trabaja con el despacho de quien llama cuando el motor es PostgreSQL (mcp_tools/__init__.py:_fijar_despacho_en_bd): rol sin privilegios, RLS y filtro de despacho, como la web.
Pruebas unitarias (sin base de datos): lo que se comprueba es qué despacho se fija, no las consultas."""
import inspect

import pytest

import mcp_tools as mt
from app import bd
from app.bd import contexto


def _firma(con_tenant: bool):
    def con(tenant: str | None = None): ...
    def sin(): ...
    return inspect.signature(con if con_tenant else sin)


def _herramienta(nombre):
    def f(): ...
    f.__name__ = nombre
    return f


@pytest.fixture
def postgres(monkeypatch):
    monkeypatch.setattr(bd, "MOTOR", "postgres")
    monkeypatch.setattr(mt.db, "tenant_de_usuario", lambda uid: {"id": 7, "nombre": "Despacho MCP"} if uid == 5 else None)
    monkeypatch.setattr(mt, "_tenant_autorizado_por_nombre", lambda nombre: {"id": 7, "nombre": nombre} if nombre == "Despacho MCP" else None)


def test_con_sqlite_no_se_toca_nada(monkeypatch):
    monkeypatch.setattr(bd, "MOTOR", "sqlite")
    assert mt._fijar_despacho_en_bd(_herramienta("listar_tareas"), _firma(False), 5, {}) is None and contexto.despacho_actual() is None


def test_con_postgres_fija_el_despacho_principal_y_se_restaura(postgres):
    testigos = mt._fijar_despacho_en_bd(_herramienta("listar_tareas"), _firma(False), 5, {})
    try:
        assert contexto.despacho_actual() == 7 and contexto.usuario_actual() == 5 and not contexto.es_plataforma()
    finally:
        contexto.restaurar(testigos)
    assert contexto.despacho_actual() is None and contexto.usuario_actual() is None


def test_una_persona_sin_despacho_trabaja_en_plataforma_0(postgres):
    testigos = mt._fijar_despacho_en_bd(_herramienta("listar_tareas"), _firma(False), 99, {})
    try:
        assert contexto.despacho_actual() == 0
    finally:
        contexto.restaurar(testigos)


def test_con_tenant_manda_ese_despacho_si_se_puede_operar_en_el(postgres):
    testigos = mt._fijar_despacho_en_bd(_herramienta("listar_clientes_despacho"), _firma(True), 5, {"tenant": "Despacho MCP"})
    try:
        assert contexto.despacho_actual() == 7
    finally:
        contexto.restaurar(testigos)
    assert mt._fijar_despacho_en_bd(_herramienta("listar_clientes_despacho"), _firma(True), 5, {"tenant": "Otro"}) is None, "un despacho ajeno no se fija: la herramienta lo rechaza"


def test_lo_que_es_de_toda_la_plataforma_o_no_tiene_persona_no_fija_nada(postgres):
    assert mt._fijar_despacho_en_bd(_herramienta("webhooks_listar"), _firma(True), 5, {}) is None, "`tenant` vacío en una herramienta que lo admite = toda la plataforma"
    assert mt._fijar_despacho_en_bd(_herramienta("backoffice_listar_tenants"), _firma(False), 5, {}) is None, "las del backoffice siguen con la conexión de la plataforma"
    assert mt._fijar_despacho_en_bd(_herramienta("listar_tareas"), _firma(False), None, {}) is None, "sin persona identificada no se fija nada"


def test_si_la_peticion_ya_tiene_despacho_no_se_pisa(postgres):
    """El asistente de la web ejecuta estas herramientas dentro de una petición con el despacho ACTIVO de la persona (puede no ser el principal)."""
    testigos = contexto.fijar_para_la_peticion(9, 5)
    try:
        assert mt._fijar_despacho_en_bd(_herramienta("listar_tareas"), _firma(False), 5, {}) is None
        assert contexto.despacho_actual() == 9
    finally:
        contexto.restaurar(testigos)
