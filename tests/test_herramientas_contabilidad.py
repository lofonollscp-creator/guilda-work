"""Herramientas MCP y del asistente de IA de «Facturas para contabilizar» (mcp_tools/herramientas_contabilidad.py)."""
import pytest

import mcp_tools
from app import db, facturas_contables as fc, herramientas_grupos as hg, ia_herramientas as ih, verticales
from app.db_fiscal import crear_cliente_fiscal

LECTURA = ("contabilidad_listar_facturas", "contabilidad_ver_factura", "contabilidad_resumen", "contabilidad_comprobar_exportacion", "contabilidad_avisos_factura", "contabilidad_comprobar_vies", "contabilidad_siguiente_pendiente",
           "contabilidad_revisables_en_lote", "contabilidad_mapa_de_cuentas", "contabilidad_calidad_lectura", "contabilidad_comprobar_retorno_a3", "contabilidad_panel_cierre", "contabilidad_mensajes_factura", "contabilidad_cierre_cliente", "contabilidad_cuadre_303", "contabilidad_historial_factura", "contabilidad_listar_ficheros", "contabilidad_listar_reglas", "contabilidad_configuracion_a3")
ESCRITURA = ("contabilidad_anotar_factura", "contabilidad_cambiar_estado_factura", "contabilidad_leer_factura_con_ia", "contabilidad_exportar", "contabilidad_revisar_seguras", "contabilidad_fijar_cuenta_tercero", "contabilidad_confirmar_retorno_a3", "contabilidad_mover_factura", "contabilidad_fijar_estado_fichero", "contabilidad_guardar_regla", "contabilidad_subir_factura")
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


# --- Controles, lote, mapa de cuentas y retorno de a3 ----------------------------------------------------------------------------------------------------

LISTADO = "Fecha;Nº Factura;NIF;Base imponible;Cuota IVA;Total\n15/08/2026;F-1;B87654321;1.000,00;210,00;1.210,00\n"


def test_avisos_de_una_factura_y_sus_duplicados():
    t, u, c = _despacho("Despacho herr avisos")
    f = _anotar(u, c)
    r = ih.ejecutar(u, "contabilidad_avisos_factura", {"factura_id": f["id"]})
    assert r["factura_id"] == f["id"] and any("dígito de control" in a for a in r["avisos"]) and r["duplicados"] == []
    g = _anotar(u, c, numero="F-1")                                  # mismo número, mismo NIF
    assert [d["id"] for d in ih.ejecutar(u, "contabilidad_avisos_factura", {"factura_id": g["id"]})["duplicados"]] == [f["id"]]


def test_vies_y_siguiente_pendiente(monkeypatch):
    from app import vies
    t, u, c = _despacho("Despacho herr vies")
    monkeypatch.setattr(vies, "valido", lambda nif, ahora=None: True)
    assert ih.ejecutar(u, "contabilidad_comprobar_vies", {"nif": "FR12345678901"})["valido"] is True
    assert ih.ejecutar(u, "contabilidad_comprobar_vies", {"nif": "12345678"})["valido"] is None
    a, b = _anotar(u, c, numero="A-1"), _anotar(u, c, numero="A-2", fecha="2026-08-16", tercero_nif="A58818501")
    sig = ih.ejecutar(u, "contabilidad_siguiente_pendiente", {"factura_id": a["id"]})["factura_id"]
    assert sig == b["id"]


def test_lote_solo_con_lo_seguro_y_pide_confirmacion():
    t, u, c = _despacho("Despacho herr lote")
    _anotar(u, c)                                                    # anotada a mano: nunca es «segura»
    r = ih.ejecutar(u, "contabilidad_revisables_en_lote", {"cliente_fiscal_id": c})
    assert r["total"] == 0 and r["umbral"] == fc.UMBRAL_REVISION_EN_LOTE
    assert ih.ejecutar(u, "contabilidad_revisar_seguras", {"cliente_fiscal_id": c}) == {"revisadas": 0, "omitidas": 0}


def test_mapa_de_cuentas_y_fijar_una_a_mano():
    t, u, c = _despacho("Despacho herr mapa")
    _anotar(u, c, tercero_nif="A58818501")
    m = ih.ejecutar(u, "contabilidad_mapa_de_cuentas", {"cliente_fiscal_id": c})
    assert [x["nif"] for x in m["terceros"]] == ["A58818501"]
    r = ih.ejecutar(u, "contabilidad_fijar_cuenta_tercero", {"cliente_fiscal_id": c, "tipo_tercero": "proveedor", "nif": "A58818501", "cuenta": "40000123"})
    assert r["ok"]
    assert ih.ejecutar(u, "contabilidad_mapa_de_cuentas", {"cliente_fiscal_id": c})["terceros"][0]["cuenta"] == "40000123"
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u, "contabilidad_fijar_cuenta_tercero", {"cliente_fiscal_id": c, "tipo_tercero": "otro", "nif": "A58818501", "cuenta": "40000123"})


def test_calidad_de_la_lectura():
    t, u, c = _despacho("Despacho herr calidad")
    r = ih.ejecutar(u, "contabilidad_calidad_lectura", {})
    assert {"por_fuente", "por_tipo", "campos"} <= set(r)


def test_retorno_de_a3_informa_y_confirma_por_separado():
    import json
    t, u, c = _despacho("Despacho herr retorno")
    f = _anotar(u, c)
    ih.ejecutar(u, "contabilidad_cambiar_estado_factura", {"factura_id": f["id"], "estado": "revisada"})
    ih.ejecutar(u, "contabilidad_exportar", {"cliente_fiscal_id": c})
    r = ih.ejecutar(u, "contabilidad_comprobar_retorno_a3", {"cliente_fiscal_id": c, "contenido": LISTADO})
    json.dumps(r)                                                    # lo que sale tiene que poder viajar como JSON
    assert fc.obtener(t, u, f["id"])["confirmada_en"] is None        # solo informa
    ih.ejecutar(u, "contabilidad_confirmar_retorno_a3", {"cliente_fiscal_id": c, "contenido": LISTADO})
    assert fc.obtener(t, u, f["id"])["confirmada_en"]
    with pytest.raises(ih.ErrorHerramientaIA, match="listado de a3"):
        ih.ejecutar(u, "contabilidad_comprobar_retorno_a3", {"cliente_fiscal_id": c})


def test_las_nuevas_de_escritura_no_las_usa_quien_solo_audita(monkeypatch):
    from app import acceso
    t, u, c = _despacho("Despacho herr auditor 2")
    monkeypatch.setattr(acceso, "es_solo_auditor", lambda tenant, usuario: True)
    for n, args in (("contabilidad_revisar_seguras", {}), ("contabilidad_fijar_cuenta_tercero", {"cliente_fiscal_id": c, "tipo_tercero": "proveedor", "nif": "A58818501", "cuenta": "40000123"}),
                    ("contabilidad_confirmar_retorno_a3", {"cliente_fiscal_id": c, "contenido": LISTADO})):
        with pytest.raises(ih.ErrorHerramientaIA, match="solo permite consultar"):
            ih.ejecutar(u, n, args)
    assert ih.ejecutar(u, "contabilidad_comprobar_retorno_a3", {"cliente_fiscal_id": c, "contenido": LISTADO})["leidas"] == 1


def test_panel_de_cierre_por_trimestre():
    t, u, c = _despacho("Despacho herr panel")
    _anotar(u, c)
    r = ih.ejecutar(u, "contabilidad_panel_cierre", {"trimestre": "2026-T3"})
    assert r["trimestre"] == "2026-T3" and r["plazo"] == "2026-10-20" and r["clientes"][0]["por_revisar"] == 1
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u, "contabilidad_panel_cierre", {"trimestre": "mal"})


def test_retorno_de_a3_con_las_columnas_indicadas_por_la_ia():
    t, u, c = _despacho("Despacho herr columnas")
    f = _anotar(u, c)
    ih.ejecutar(u, "contabilidad_cambiar_estado_factura", {"factura_id": f["id"], "estado": "revisada"})
    ih.ejecutar(u, "contabilidad_exportar", {"cliente_fiscal_id": c})
    sin_titulos = "Registro\nB;15/08/2026;F-1;1.210,00\n"
    with pytest.raises(ih.ErrorHerramientaIA, match="No encuentro las columnas"):
        ih.ejecutar(u, "contabilidad_comprobar_retorno_a3", {"cliente_fiscal_id": c, "contenido": sin_titulos})
    r = ih.ejecutar(u, "contabilidad_confirmar_retorno_a3", {"cliente_fiscal_id": c, "contenido": sin_titulos, "columnas": {"numero": "C", "fecha": "B", "total": "D"}, "fila_de_titulos": 0})
    assert r["leidas"] == 1 and len(r["confirmadas"]) == 1


def test_el_asistente_sabe_que_factura_tiene_abierta_la_persona():
    from app import ia_asistente, ia_soporte
    t, u, c = _despacho("Despacho herr ficha")
    f = _anotar(u, c)
    ia_soporte.recordar_pantalla(u, "contabilidad.ver", {"factura_id": f["id"]})
    assert ia_soporte.ficha_de(u) == ("factura_contable", f["id"])
    texto = ia_asistente._contexto_soporte(u, False)
    assert f"id {f['id']}" in texto and "contabilidad_ver_factura" in texto and "contabilidad_avisos_factura" in texto and "esta factura" in texto
    ia_soporte.recordar_pantalla(u, "contabilidad.lista", {})
    assert ia_soporte.ficha_de(u) is None


def test_esta_factura_ofrece_las_herramientas_de_contabilidad():
    ofrecidas = {t["function"]["name"] for t in ih.herramientas_para([{"role": "user", "content": "¿por qué tiene avisos esta factura?"}])}
    assert "contabilidad_avisos_factura" in ofrecidas


def test_preguntar_al_cliente_pide_siempre_confirmacion_y_deja_el_mensaje_en_la_factura():
    t, u, c = _despacho("Despacho herr preguntas")
    f = _anotar(u, c)
    assert "contabilidad_preguntar_al_cliente" in ih.SIEMPRE_CONFIRMAR
    assert ih.necesita_confirmacion("contabilidad_preguntar_al_cliente", modo_autonomo=True)         # es un mensaje a una persona de fuera: nunca solo
    assert not ih.necesita_confirmacion("contabilidad_mensajes_factura", modo_autonomo=False)
    assert ih.ejecutar(u, "contabilidad_mensajes_factura", {"factura_id": f["id"]})["mensajes"] == []
    r = ih.ejecutar(u, "contabilidad_preguntar_al_cliente", {"factura_id": f["id"], "texto": "¿Para qué fue este gasto?"})
    assert [(m["autor"], m["texto"], m["leido"]) for m in r["mensajes"]] == [("despacho", "¿Para qué fue este gasto?", False)] and "@" not in str(r)       # sin correos de empleados
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u, "contabilidad_preguntar_al_cliente", {"factura_id": f["id"], "texto": "  "})
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe"):
        ih.ejecutar(u, "contabilidad_mensajes_factura", {"factura_id": 999999})


def test_quien_solo_audita_no_puede_escribir_al_cliente(monkeypatch):
    from app import acceso
    t, u, c = _despacho("Despacho herr auditor 3")
    f = _anotar(u, c)
    monkeypatch.setattr(acceso, "es_solo_auditor", lambda tenant, usuario: True)
    with pytest.raises(ih.ErrorHerramientaIA, match="solo permite consultar"):
        ih.ejecutar(u, "contabilidad_preguntar_al_cliente", {"factura_id": f["id"], "texto": "Hola"})


def test_cierre_de_un_cliente_para_redactar_el_resumen():
    t, u, c = _despacho("Despacho herr cierre cliente")
    _anotar(u, c)
    r = ih.ejecutar(u, "contabilidad_cierre_cliente", {"cliente_fiscal_id": c, "trimestre": "2026-T3"})
    puntos = {p["punto"]: p for p in r["puntos"]}
    assert r["trimestre"] == "2026-T3" and r["plazo"] == "2026-10-20" and r["facturas"] == 1 and not r["listo_para_cerrar"] and not r["cerrado"]
    assert puntos["por_revisar"]["estado"] == "pendiente" and puntos["por_revisar"]["cuantos"] == 1 and r["exportadas_sin_confirmar_en_a3"] is None
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u, "contabilidad_cierre_cliente", {"cliente_fiscal_id": 999999, "trimestre": "2026-T3"})


def test_anotar_con_impreso_y_datos_de_ampliacion_por_la_ia():
    t, u, c = _despacho("Despacho herr ampliacion")
    f = _anotar(u, c, datos_a3={"bien_inversion": True, "clave_340": "3"}, lineas=[{"base": "100,00", "pct_iva": 21, "pct_retencion": 15, "impreso": "05"}])
    assert f["datos_a3"] == {"bien_inversion": True, "clave_340": "3"} and f["lineas"][0]["impreso"] == "05"
    with pytest.raises(ih.ErrorHerramientaIA):
        _anotar(u, c, numero="F-2", datos_a3={"clave_340": "9"})


def test_cuadre_con_el_303_por_la_ia(monkeypatch):
    from app import consultas_fiscal
    t, u, c = _despacho("Despacho herr cuadre")
    r = ih.ejecutar(u, "contabilidad_cuadre_303", {"cliente_fiscal_id": c, "trimestre": "2026-T3"})
    assert r["trimestre"] == "2026-T3" and not r["disponible"] and r["facturas"] == {"repercutido": 0.0, "soportado": 0.0, "facturas": 0}
    monkeypatch.setattr(consultas_fiscal, "simular_303", lambda *a, **k: {"bloqueos": [], "casillas": {"27": 10.5, "45": 4.0}})
    r = ih.ejecutar(u, "contabilidad_cuadre_303", {"cliente_fiscal_id": c, "trimestre": "2026-T3"})
    assert r["disponible"] and r["modelo_303"] == {"devengado": 10.5, "deducible": 4.0} and r["diferencia"] == {"repercutido": -10.5, "soportado": -4.0}


# --- M4: catálogo completo ---------------------------------------------------------------------------------------------------------------------------------

def test_historial_ficheros_y_su_estado_por_la_ia():
    t, u, c = _despacho("Despacho herr m4 uno")
    f = _anotar(u, c)
    ih.ejecutar(u, "contabilidad_cambiar_estado_factura", {"factura_id": f["id"], "estado": "revisada"})
    ih.ejecutar(u, "contabilidad_exportar", {"cliente_fiscal_id": c})
    h = ih.ejecutar(u, "contabilidad_historial_factura", {"factura_id": f["id"]})
    assert [e["que"] for e in h["eventos"]][:2] == ["Exportada a a3", "Dada por revisada"]
    ficheros = ih.ejecutar(u, "contabilidad_listar_ficheros", {"cliente_fiscal_id": c})
    assert len(ficheros) == 1 and ficheros[0]["facturas"] == 1 and ficheros[0]["estado_a3"] is None and "contenido" not in ficheros[0]
    r = ih.ejecutar(u, "contabilidad_fijar_estado_fichero", {"lote_id": ficheros[0]["id"], "estado": "rechazado", "motivo": "falta la cuenta"})
    assert (r["estado_a3"], r["motivo_a3"]) == ("rechazado", "falta la cuenta")
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u, "contabilidad_fijar_estado_fichero", {"lote_id": ficheros[0]["id"], "estado": "raro"})
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe"):
        ih.ejecutar(u, "contabilidad_historial_factura", {"factura_id": 999999})


def test_reglas_y_configuracion_por_la_ia():
    t, u, c = _despacho("Despacho herr m4 dos")
    assert ih.ejecutar(u, "contabilidad_listar_reglas", {"cliente_fiscal_id": c}) == []
    r = ih.ejecutar(u, "contabilidad_guardar_regla", {"cliente_fiscal_id": c, "tipo": "proveedor", "nif": "A58818501", "nombre": "Gasolinera", "cuenta": "62800000", "pct_iva": 21, "pct_retencion": 0})
    assert r["cuenta"] == "62800000" and r["pct_iva"] == 21.0 and r["aprendida"] is False
    f = _anotar(u, c, tercero_nif="A58818501", lineas=[{"base": "50,00"}])
    assert ih.ejecutar(u, "contabilidad_ver_factura", {"factura_id": f["id"]})["lineas"][0]["cuenta"] == "62800000"       # la regla rellena la línea
    cfg = ih.ejecutar(u, "contabilidad_configuracion_a3", {"cliente_fiscal_id": c})
    assert cfg["a3_empresa"] == "7" and cfg["formato_enlace"] == "512" and cfg["digitos"] == 8 and cfg["cuenta_gasto"]
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u, "contabilidad_guardar_regla", {"cliente_fiscal_id": c, "tipo": "otro", "nif": "A58818501"})


def test_mover_y_subir_facturas_por_la_ia():
    import base64
    from app.db_fiscal import crear_cliente_fiscal
    from tests.test_facturas_contables import PDF
    t, u, c = _despacho("Despacho herr m4 tres")
    otro = crear_cliente_fiscal(t, "Otro SL", nif="A58818501")
    r = ih.ejecutar(u, "contabilidad_subir_factura", {"cliente_fiscal_id": c, "tipo": "recibida", "nombre_archivo": "f.pdf", "contenido_base64": base64.b64encode(PDF + b"9").decode()})
    assert r["factura_id"] and not r["ya_estaba"]
    m = ih.ejecutar(u, "contabilidad_mover_factura", {"factura_id": r["factura_id"], "cliente_destino_id": otro})
    assert m["cliente_fiscal_id"] == otro and m["tiene_archivo"]
    with pytest.raises(ih.ErrorHerramientaIA, match="base64"):
        ih.ejecutar(u, "contabilidad_subir_factura", {"cliente_fiscal_id": c, "tipo": "recibida", "nombre_archivo": "f.pdf", "contenido_base64": "@@@"})
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(u, "contabilidad_subir_factura", {"cliente_fiscal_id": c, "tipo": "recibida", "nombre_archivo": "f.exe", "contenido_base64": base64.b64encode(b"MZ").decode()})


def test_las_nuevas_que_escriben_no_las_usa_quien_solo_audita(monkeypatch):
    from app import acceso
    t, u, c = _despacho("Despacho herr m4 cuatro")
    f = _anotar(u, c)
    monkeypatch.setattr(acceso, "es_solo_auditor", lambda tenant, usuario: True)
    for n, args in (("contabilidad_mover_factura", {"factura_id": f["id"], "cliente_destino_id": c}), ("contabilidad_fijar_estado_fichero", {"lote_id": 1, "estado": "importado"}),
                    ("contabilidad_guardar_regla", {"cliente_fiscal_id": c, "tipo": "proveedor", "nif": "A58818501"}), ("contabilidad_subir_factura", {"cliente_fiscal_id": c, "tipo": "recibida", "nombre_archivo": "f.pdf", "contenido_base64": ""})):
        with pytest.raises(ih.ErrorHerramientaIA, match="solo permite consultar"):
            ih.ejecutar(u, n, args)
    assert ih.ejecutar(u, "contabilidad_listar_reglas", {"cliente_fiscal_id": c}) == []
