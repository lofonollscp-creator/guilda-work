"""Herramientas MCP y del asistente de IA de «Facturas para contabilizar» (mcp_tools/herramientas_contabilidad.py)."""
import pytest

import mcp_tools
from app import db, facturas_contables as fc, herramientas_grupos as hg, ia_herramientas as ih, verticales
from app.db_fiscal import crear_cliente_fiscal

LECTURA = ("contabilidad_listar_facturas", "contabilidad_ver_factura", "contabilidad_resumen", "contabilidad_comprobar_exportacion")
ESCRITURA = ("contabilidad_anotar_factura", "contabilidad_cambiar_estado_factura", "contabilidad_leer_factura_con_ia", "contabilidad_exportar")
LINEAS = [{"base": "1.000,00", "pct_iva": "21"}]


def _despacho(nombre, modulo=True):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}@ejemplo.com", f"kratos-{nombre}")
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    if modulo:
        verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Herr SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    return t, u, c


def _anotar(u, c, **kw):
    args = {"cliente_fiscal_id": c, "tipo": "recibida", "fecha": "2026-08-15", "numero": "F-1", "tercero_nombre": "Papelería Sol", "tercero_nif": "B87654321", "lineas": LINEAS, **kw}
    return ih.ejecutar(u, "contabilidad_anotar_factura", args)


def test_estan_clasificadas_en_su_grupo_y_en_el_mcp():
    for n in LECTURA:
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False)
    for n in ESCRITURA:
        assert n in ih.ESCRITURA and ih.necesita_confirmacion(n, modo_autonomo=False) and not ih.necesita_confirmacion(n, modo_autonomo=True)
    for n in LECTURA + ESCRITURA:
        assert hg.grupo_de(n) == "contabilidad" and any(t.__name__ == n for t in mcp_tools.TOOLS)
        assert n in {t["function"]["name"] for t in ih.HERRAMIENTAS}


def test_las_palabras_clave_ofrecen_el_grupo():
    ofrecidas = {t["function"]["name"] for t in ih.herramientas_para([{"role": "user", "content": "comprueba el suenlace del cliente antes de llevarlo a a3"}])}
    assert set(LECTURA + ESCRITURA) <= ofrecidas


def test_sin_el_modulo_activo_no_funcionan():
    t, u, c = _despacho("Sin modulo conta", modulo=False)
    for n, args in (("contabilidad_resumen", {}), ("contabilidad_listar_facturas", {})):
        with pytest.raises(ih.ErrorHerramientaIA, match="no está activo"):
            ih.ejecutar(u, n, args)
    with pytest.raises(ih.ErrorHerramientaIA, match="no está activo"):
        _anotar(u, c)


def test_anotar_ver_listar_revisar_y_resumen():
    t, u, c = _despacho("Despacho herr")
    f = _anotar(u, c)
    assert (f["numero"], f["total"], f["estado"], f["tercero"]) == ("F-1", 1210.0, "pendiente", "Papelería Sol") and f["lineas"][0]["cuota_iva"] == 210.0
    assert ih.ejecutar(u, "contabilidad_ver_factura", {"factura_id": f["id"]})["problemas"] == []
    lista = ih.ejecutar(u, "contabilidad_listar_facturas", {"trimestre": "2026-T3", "estado": "pendiente"})
    assert [x["id"] for x in lista] == [f["id"]]
    assert ih.ejecutar(u, "contabilidad_resumen", {})["por_revisar"] == 1
    r = ih.ejecutar(u, "contabilidad_cambiar_estado_factura", {"factura_id": f["id"], "estado": "revisada"})
    assert r["estado"] == "revisada" and ih.ejecutar(u, "contabilidad_resumen", {})["para_exportar"] == 1


def test_comprobar_y_exportar():
    t, u, c = _despacho("Despacho herr export")
    f = _anotar(u, c)
    ih.ejecutar(u, "contabilidad_cambiar_estado_factura", {"factura_id": f["id"], "estado": "revisada"})
    chequeo = ih.ejecutar(u, "contabilidad_comprobar_exportacion", {"cliente_fiscal_id": c, "trimestre": "2026-T3"})
    assert chequeo["ok"] and chequeo["facturas"] == 1 and chequeo["errores"] == []
    r = ih.ejecutar(u, "contabilidad_exportar", {"cliente_fiscal_id": c})
    assert r["facturas"] == 1 and r["registros"] == 2 and r["lote"]
    assert ih.ejecutar(u, "contabilidad_ver_factura", {"factura_id": f["id"]})["estado"] == "exportada"
    with pytest.raises(ih.ErrorHerramientaIA, match="No hay facturas revisadas"):
        ih.ejecutar(u, "contabilidad_exportar", {"cliente_fiscal_id": c})


def test_un_periodo_cerrado_no_se_exporta_desde_la_ia():
    t, u, c = _despacho("Despacho herr cerrado")
    f = _anotar(u, c)
    ih.ejecutar(u, "contabilidad_cambiar_estado_factura", {"factura_id": f["id"], "estado": "revisada"})
    fc.cerrar_periodo(t, u, c, "2026-T3")
    with pytest.raises(ih.ErrorHerramientaIA, match="cerrados"):
        ih.ejecutar(u, "contabilidad_exportar", {"cliente_fiscal_id": c})
    assert ih.ejecutar(u, "contabilidad_ver_factura", {"factura_id": f["id"]})["estado"] == "revisada"


def test_datos_mal_puestos_dan_un_error_legible():
    t, u, c = _despacho("Despacho herr errores")
    for args in ({"lineas": []}, {"tipo": "otra"}, {"fecha": "ayer"}, {"cliente_fiscal_id": 999999}):
        with pytest.raises(ih.ErrorHerramientaIA):
            _anotar(u, c, **args)
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe"):
        ih.ejecutar(u, "contabilidad_ver_factura", {"factura_id": 999999})
    with pytest.raises(ih.ErrorHerramientaIA, match="estado"):
        ih.ejecutar(u, "contabilidad_listar_facturas", {"estado": "raro"})


def test_otro_despacho_no_ve_nada():
    t1, u1, c1 = _despacho("Despacho herr uno")
    t2, u2, c2 = _despacho("Despacho herr dos")
    f = _anotar(u1, c1)
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe"):
        ih.ejecutar(u2, "contabilidad_ver_factura", {"factura_id": f["id"]})
    assert ih.ejecutar(u2, "contabilidad_listar_facturas", {}) == []
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u2, "contabilidad_exportar", {"cliente_fiscal_id": c1})


def test_quien_solo_audita_no_puede_cambiar(monkeypatch):
    from app import acceso
    t, u, c = _despacho("Despacho herr auditor")
    f = _anotar(u, c)
    monkeypatch.setattr(acceso, "es_solo_auditor", lambda tenant, usuario: True)
    assert ih.ejecutar(u, "contabilidad_ver_factura", {"factura_id": f["id"]})["numero"] == "F-1"
    for n, args in (("contabilidad_cambiar_estado_factura", {"factura_id": f["id"], "estado": "revisada"}), ("contabilidad_exportar", {"cliente_fiscal_id": c}),
                    ("contabilidad_leer_factura_con_ia", {"factura_id": f["id"]})):
        with pytest.raises(ih.ErrorHerramientaIA, match="solo permite consultar"):
            ih.ejecutar(u, n, args)
    with pytest.raises(ih.ErrorHerramientaIA, match="solo permite consultar"):
        _anotar(u, c, numero="F-2")


def test_las_funciones_del_mcp_existen_con_documentacion():
    for n in LECTURA + ESCRITURA:
        f = getattr(mcp_tools, n)
        assert f.__doc__ and len(f.__doc__) > 40, n
