"""Asistente jurídico — herramientas del MCP y del asistente de IA (modelo SIMULADO; corpus SINTÉTICO)."""
import json

import pytest

import mcp_tools
from app import acceso, db, herramientas_grupos as hg, ia_asistente, ia_herramientas as ih, verticales
from app.juridico import corpus, ingesta
from tests.juridico_ayudas import conector_consolidada, conector_diario, habilitar, transporte_boe
from tests.test_juridico_asistente import ok_articulo1

pytestmark = pytest.mark.usefixtures("base_de_datos_temporal")


@pytest.fixture
def d(base_de_datos_temporal, monkeypatch):
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    tr = transporte_boe()
    ingesta.sincronizar("boe-consolidada", conector_consolidada(tr), "2099-01-01", "2099-01-31")
    ingesta.sincronizar("boe-diario-tc", conector_diario(tr), "2099-01-10", "2099-01-10")
    class E: pass
    e = E()
    e.t = db.crear_tenant("Despacho herramientas jurídicas")
    verticales.fijar_activo(e.t, "juridico", True)
    def u(mail, sup=False):
        i = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(i, e.t)
        if sup:
            db.asignar_supervisor_tenant(i, True)
        return i
    e.dir, e.ana, e.aud = u("dir-jh@ejemplo.com", True), u("ana-jh@ejemplo.com"), u("aud-jh@ejemplo.com")
    acceso.dar_membresia(e.t, e.dir, e.aud, "auditor", "organizacion")
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda uid, s, contenido: json.dumps(ok_articulo1(contenido)))
    return e


def test_clasificacion_grupo_y_registro_de_las_herramientas():
    lectura = ("juridico_buscar", "juridico_ver_documento", "juridico_listar_informes", "juridico_ver_informe")
    escritura = ("juridico_consultar", "juridico_guardar_informe")
    en_mcp = {t.__name__ for t in mcp_tools.TOOLS}
    for n in lectura + escritura:
        assert n in en_mcp and hg.grupo_de(n) == "juridico", n
    for n in lectura:
        assert n in ih.LECTURA and not ih.necesita_confirmacion(n, modo_autonomo=False)
    for n in escritura:
        assert n in ih.ESCRITURA and ih.necesita_confirmacion(n, modo_autonomo=False), "gastar IA o guardar un informe lo confirma la persona"


def test_sin_el_modulo_las_herramientas_dicen_que_no(d, monkeypatch):
    otro = db.crear_tenant("Sin jurídico")
    u = db.crear_usuario_vinculado_a_kratos("sj-jh@ejemplo.com", "k-sj-jh"); db.asignar_tenant(u, otro)
    with pytest.raises(ih.ErrorHerramientaIA, match="no tiene el Asistente jurídico"):
        ih.ejecutar(u, "juridico_buscar", {"consulta": "deducción"})
    monkeypatch.delenv("LEGAL_AI_ENABLED")
    with pytest.raises(ih.ErrorHerramientaIA, match="no tiene el Asistente jurídico"):
        ih.ejecutar(d.ana, "juridico_buscar", {"consulta": "deducción"})


def test_buscar_y_ver_documento_con_fecha_y_localizadores(d):
    r = ih.ejecutar(d.ana, "juridico_buscar", {"consulta": "deducción de gastos", "colecciones": ["legislacion"]})
    x = next(y for y in r["resultados"] if y["localizador"] == "Artículo 1")
    assert x["vigente_desde"] == "2022-07-01" and x["capturada_en"] and "texto_completo" not in x and r["modo"] == "texto"
    ficha = ih.ejecutar(d.ana, "juridico_ver_documento", {"documento_id": x["documento_id"], "fecha_juridica": "2021-06-01"})
    assert ficha["documento"]["titulo"].startswith("Ley sintética") and ficha["relaciones"] and "diez" in next(f for f in ficha["fragmentos"] if f["localizador"] == "Artículo 1")["texto"]
    antes = ih.ejecutar(d.ana, "juridico_ver_documento", {"documento_id": x["documento_id"], "fecha_juridica": "2019-01-01"})
    assert antes["fragmentos"] == [] and antes["huecos"]
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe el documento"):
        ih.ejecutar(d.ana, "juridico_ver_documento", {"documento_id": 99999})
    with pytest.raises(ih.ErrorHerramientaIA, match="AAAA-MM-DD"):
        ih.ejecutar(d.ana, "juridico_buscar", {"consulta": "x", "fecha_juridica": "ayer"})


def test_el_documento_se_recorta_para_no_desbordar_el_contexto(d, monkeypatch):
    monkeypatch.setattr(mcp_tools.herramientas_juridico, "MAX_CARACTERES_DOCUMENTO", 300)
    did = db.get_connection().execute("SELECT id FROM jur_documentos WHERE id_externo = 'BOE-A-2099-0001'").fetchone()["id"]
    f = ih.ejecutar(d.ana, "juridico_ver_documento", {"documento_id": did})
    assert f["recortado"] is True and sum(len(x["texto"]) for x in f["fragmentos"]) <= 300


def test_consultar_guardar_y_leer_informes(d):
    a = ih.ejecutar(d.ana, "juridico_consultar", {"pregunta": "¿Qué límite tiene la deducción de gastos?", "colecciones": ["legislacion"], "fecha_juridica": "2099-01-15"})
    assert a["status"] == "answered" and a["citations"][0]["locator"] == "Artículo 1" and a["coverage"]["legalAsOf"] == "2099-01-15"
    inf = ih.ejecutar(d.ana, "juridico_guardar_informe", {"ejecucion_id": a["runId"], "titulo": "Límite"})
    assert inf["estado"] == "borrador"
    assert [i["id"] for i in ih.ejecutar(d.ana, "juridico_listar_informes", {})] == [inf["id"]]
    v = ih.ejecutar(d.ana, "juridico_ver_informe", {"informe_id": inf["id"]})
    assert v["estado"] == "borrador" and v["claims"] and v["citations"][0]["captura"]["capturada_en"] and v["pregunta"].startswith("¿Qué límite")
    otro = db.crear_tenant("Ajeno"); verticales.fijar_activo(otro, "juridico", True)
    u = db.crear_usuario_vinculado_a_kratos("aj-jh@ejemplo.com", "k-aj-jh"); db.asignar_tenant(u, otro)
    with pytest.raises(ih.ErrorHerramientaIA, match="No existe el informe"):
        ih.ejecutar(u, "juridico_ver_informe", {"informe_id": inf["id"]})
    assert ih.ejecutar(u, "juridico_listar_informes", {}) == []
    with pytest.raises(ih.ErrorHerramientaIA, match="No encuentras"):
        ih.ejecutar(u, "juridico_guardar_informe", {"ejecucion_id": a["runId"]})


def test_consulta_sin_fuentes_no_se_inventa_ni_se_guarda(d):
    a = ih.ejecutar(d.ana, "juridico_consultar", {"pregunta": "supercalifragilístico inexistente"})
    assert a["status"] == "insufficient_evidence" and a["claims"] == []
    with pytest.raises(ih.ErrorHerramientaIA, match="respondida"):
        ih.ejecutar(d.ana, "juridico_guardar_informe", {"ejecucion_id": a["runId"]})


def test_el_auditor_lee_pero_no_consulta_ni_guarda(d):
    assert ih.ejecutar(d.aud, "juridico_buscar", {"consulta": "deducción de gastos"})["resultados"]
    with pytest.raises(ih.ErrorHerramientaIA, match="solo permite consultar"):
        ih.ejecutar(d.aud, "juridico_consultar", {"pregunta": "hola"})


def test_fallos_de_la_consulta_llegan_como_error_de_herramienta(d, monkeypatch):
    def cae(uid, s, c):
        raise ia_asistente.ErrorIA("sin clave")
    monkeypatch.setattr(ia_asistente, "completar_texto", cae)
    with pytest.raises(ih.ErrorHerramientaIA, match="proveedor de IA"):
        ih.ejecutar(d.ana, "juridico_consultar", {"pregunta": "deducción de gastos", "colecciones": ["legislacion"]})
    with pytest.raises(ih.ErrorHerramientaIA, match="demasiado extensa"):
        ih.ejecutar(d.ana, "juridico_consultar", {"pregunta": "x" * 5000})
