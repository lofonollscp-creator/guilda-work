"""Herramientas de solo lectura del núcleo para la IA y el MCP (clientes, expedientes, plazos) y el contexto de la ficha abierta."""
from datetime import date, timedelta

import pytest

import mcp_tools
from app import db, herramientas_grupos as hg, ia_asistente, ia_herramientas as ih, ia_soporte, nucleo

HERRAMIENTAS = ("listar_clientes_despacho", "resumen_cliente_despacho", "listar_expedientes_despacho", "resumen_expediente_despacho", "listar_plazos_despacho")


def _despacho(nombre, n=2):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    return t, us


def test_son_de_lectura_no_piden_confirmacion_y_estan_en_su_grupo():
    for n in HERRAMIENTAS:
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False)
        assert hg.grupo_de(n) == "despacho"
        assert any(t.__name__ == n for t in mcp_tools.TOOLS)


def test_sin_despacho_dan_error_legible(usuario_id):
    with pytest.raises(ih.ErrorHerramientaIA, match="tenant"):
        ih.ejecutar(usuario_id, "listar_clientes_despacho", {})


def test_resumen_de_un_cliente_con_sus_expedientes_y_plazos(usuario_id):
    t, (u1, _u2) = _despacho("Despacho IA")
    c = nucleo.crear_cliente(t, "Carmen Soler", nif="12345678Z", email="c@ejemplo.com")
    x = nucleo.crear_expediente(t, u1, c, "Reclamación de cantidad", referencia="12/2026")
    manana = (date.today() + timedelta(days=1)).isoformat()
    nucleo.crear_plazo(t, u1, "Contestar demanda", manana, expediente_id=x)
    nucleo.anotar_expediente(t, u1, x, "Llamada con la clienta")

    assert [f["nombre"] for f in ih.ejecutar(u1, "listar_clientes_despacho", {"q": "soler"})] == ["Carmen Soler"]
    r = ih.ejecutar(u1, "resumen_cliente_despacho", {"cliente_id": c})
    assert r["cliente"]["nombre"] == "Carmen Soler" and r["total_expedientes"] == 1
    assert r["expedientes"][0]["titulo"] == "Reclamación de cantidad" and r["plazos_abiertos"][0]["titulo"] == "Contestar demanda"
    e = ih.ejecutar(u1, "resumen_expediente_despacho", {"expediente_id": x})
    assert e["expediente"]["referencia"] == "12/2026" and e["plazos_abiertos"][0]["dias_restantes"] == 1
    assert any("Llamada" in a["texto"] for a in e["ultimas_anotaciones"])
    assert [p["titulo"] for p in ih.ejecutar(u1, "listar_plazos_despacho", {"dias": 7})] == ["Contestar demanda"]
    assert ih.ejecutar(u1, "listar_plazos_despacho", {"dias": 0, "estado": "cumplido"}) == []


def test_un_despacho_no_ve_lo_de_otro(usuario_id):
    t1, (u1,) = _despacho("Despacho Uno", 1)
    t2, (u2,) = _despacho("Despacho Dos", 1)
    c = nucleo.crear_cliente(t1, "Cliente de uno")
    x = nucleo.crear_expediente(t1, u1, c, "Asunto de uno")
    assert ih.ejecutar(u2, "listar_clientes_despacho", {}) == []
    for nombre, args in (("resumen_cliente_despacho", {"cliente_id": c}), ("resumen_expediente_despacho", {"expediente_id": x})):
        with pytest.raises(ih.ErrorHerramientaIA):
            ih.ejecutar(u2, nombre, args)


def test_la_ia_no_ve_expedientes_confidenciales_ajenos(usuario_id):
    t, (u1, u2) = _despacho("Despacho Conf IA")
    c = nucleo.crear_cliente(t, "Cliente")
    x = nucleo.crear_expediente(t, u1, c, "Reservado", confidencial=True)
    nucleo.crear_plazo(t, u1, "Plazo reservado", (date.today() + timedelta(days=2)).isoformat(), expediente_id=x)
    assert [e["titulo"] for e in ih.ejecutar(u1, "listar_expedientes_despacho", {})] == ["Reservado"]
    assert ih.ejecutar(u2, "listar_expedientes_despacho", {}) == []
    assert ih.ejecutar(u2, "listar_plazos_despacho", {}) == []
    assert ih.ejecutar(u2, "resumen_cliente_despacho", {"cliente_id": c})["expedientes"] == []
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u2, "resumen_expediente_despacho", {"expediente_id": x})


def test_la_ficha_abierta_llega_al_prompt_solo_en_turnos_de_datos(usuario_id):
    ia_soporte.recordar_pantalla(usuario_id, "clientes.ficha", {"cliente_id": 42})
    datos = ia_asistente._prompt_sistema(usuario_id, "es", soporte=False)
    assert "ficha del cliente con id 42" in datos and "resumen_cliente_despacho" in datos
    assert "ficha del cliente con id 42" not in ia_asistente._prompt_sistema(usuario_id, "es", soporte=True)
    ia_soporte.recordar_pantalla(usuario_id, "expedientes.ficha", {"expediente_id": 7})
    assert "ficha del expediente con id 7" in ia_asistente._prompt_sistema(usuario_id, "es")
    ia_soporte.recordar_pantalla(usuario_id, "fiscal.ficha_cliente", {"cliente_id": 3})
    assert "resumen_cliente_fiscal" in ia_asistente._prompt_sistema(usuario_id, "es")
    ia_soporte.recordar_pantalla(usuario_id, "correo.cuentas", {})
    assert "ficha del" not in ia_asistente._prompt_sistema(usuario_id, "es")


def test_la_ficha_se_deduce_de_la_url_del_navegador(cliente):
    from app.main import app
    assert ia_soporte.pantalla_de_url("https://x.test/clientes/15", app) == ("clientes.ficha", {"cliente_id": 15})
    assert ia_soporte.pantalla_de_url("https://x.test/expedientes/9", app) == ("expedientes.ficha", {"expediente_id": 9})
    assert ia_soporte.pantalla_de_url(None, app) == (None, {})
