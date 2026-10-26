"""Herramientas MCP y del asistente de IA de Guilda Fiscal (mcp_tools/herramientas_guilda_fiscal.py): solo consulta y simulación."""
import pytest

import mcp_tools
from app import db, fiscal_nucleo as fn, fiscal_perfiles as fp, herramientas_grupos as hg, ia_herramientas as ih, verticales
from app.db_fiscal import crear_cliente_fiscal
from tests.escenarios_303 import ESCENARIOS

LECTURA = ("fiscal_listar_titulares", "fiscal_ver_perfil", "fiscal_listar_apuntes", "fiscal_comprobar_apuntes", "fiscal_proponer_apuntes_de_factura", "fiscal_simular_303", "fiscal_listar_declaraciones",
           "fiscal_ver_declaracion")


def _despacho(nombre, modulo=True):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}@ejemplo.com", f"kratos-{nombre}")
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    if modulo:
        verticales.fijar_activo(t, "fiscal", True)
    c = crear_cliente_fiscal(t, "Cliente Herr SL", nif="A12345674")
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    for a in ESCENARIOS["basico"][0]:
        fn.aprobar_apunte(t, u, c, a)
    return t, u, c


def test_estan_clasificadas_como_lectura_en_su_grupo_y_en_el_mcp():
    for n in LECTURA:
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False)
        assert hg.grupo_de(n) == "guilda_fiscal" and any(t.__name__ == n for t in mcp_tools.TOOLS)
        assert n in {t["function"]["name"] for t in ih.HERRAMIENTAS}
    ofrecidos = {t.__name__ for t in mcp_tools.TOOLS}
    assert not [n for n in ofrecidos if n.startswith("fiscal_") and any(v in n for v in ("aprobar", "presentar", "exportar", "revisar", "congelar"))]


def test_las_palabras_clave_ofrecen_el_grupo():
    ofrecidas = {t["function"]["name"] for t in ih.herramientas_para([{"role": "user", "content": "simula el modelo 303 de este cliente"}])}
    assert "fiscal_simular_303" in ofrecidas


def test_consulta_y_simulacion_a_traves_del_asistente():
    t, u, c = _despacho("Despacho Herr Fiscal")
    assert ih.ejecutar(u, "fiscal_listar_titulares", {})[0]["apuntes_del_anio"] == 2
    assert ih.ejecutar(u, "fiscal_listar_apuntes", {"cliente_fiscal_id": c, "ejercicio": 2026})[0]["base"] == 100.0
    assert ih.ejecutar(u, "fiscal_comprobar_apuntes", {"cliente_fiscal_id": c, "ejercicio": 2026})["ok"] is True
    s = ih.ejecutar(u, "fiscal_simular_303", {"cliente_fiscal_id": c, "ejercicio": 2026, "periodo": "2T"})
    assert s["resultado"] == 10.5 and s["simulacion"] is True
    assert fn.listar_declaraciones(t, u, c) == []


def test_sin_modulo_no_hay_acceso():
    t, u, c = _despacho("Despacho Herr Sin Modulo", modulo=False)
    with pytest.raises(Exception, match="no está activo"):
        mcp_tools._gfiscal().titulares(t, u)
