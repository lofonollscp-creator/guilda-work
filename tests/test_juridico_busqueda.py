"""Asistente jurídico — búsqueda híbrida, fecha jurídica, filtros, permisos y fichas (con fixtures SINTÉTICAS)."""
import pytest

from app import db
from app.juridico import busqueda, corpus, ingesta
from tests.juridico_ayudas import BASE_C, conector_consolidada, conector_diario, habilitar, transporte_boe

pytestmark = pytest.mark.usefixtures("base_de_datos_temporal")


@pytest.fixture
def biblioteca():
    """Corpus sintético cargado con el motor real: dos normas del BOE y dos resoluciones del TC. Devuelve el id de un despacho que puede usarlas."""
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    t = transporte_boe()
    ingesta.sincronizar("boe-consolidada", conector_consolidada(t), "2099-01-01", "2099-01-31")
    ingesta.sincronizar("boe-diario-tc", conector_diario(t), "2099-01-10", "2099-01-10")
    return db.crear_tenant("Despacho con biblioteca")


def test_busqueda_de_texto_devuelve_la_version_actual_con_localizador_y_motivo(biblioteca):
    r = busqueda.buscar(biblioteca, "deducción de gastos límite")
    assert r["modo"] == "texto" and r["total"] >= 1
    x = next(x for x in r["resultados"] if x["localizador"] == "Artículo 1")
    assert "quince" in x["extracto"] or "quince" in x["extracto"].lower() or x["motivo"] == "Coincidencia de texto"
    assert x["vigente_desde"] == "2022-07-01" and x["vigente_hasta"] is None and x["motivo"] == "Coincidencia de texto" and x["url_canonica"] and x["capturada_en"]
    assert not any("diez por ciento" in (y["extracto"] or "") for y in r["resultados"]), "sin fecha jurídica solo la versión actual"


def test_fecha_juridica_elige_la_version_vigente_en_esa_fecha(biblioteca):
    r = busqueda.buscar(biblioteca, "objeto deducción", fecha_juridica="2021-06-01", colecciones=["legislacion"])
    a1 = next(x for x in r["resultados"] if x["localizador"] == "Artículo 1")
    assert (a1["vigente_desde"], a1["vigente_hasta"]) == ("2020-01-01", "2022-06-30") and "diez" in a1["extracto"]
    r2 = busqueda.buscar(biblioteca, "objeto deducción", fecha_juridica="2023-01-01", colecciones=["legislacion"])
    assert next(x for x in r2["resultados"] if x["localizador"] == "Artículo 1")["vigente_desde"] == "2022-07-01"


def test_fecha_anterior_a_la_primera_version_es_un_hueco_explicito_no_el_ultimo_texto(biblioteca):
    r = busqueda.buscar(biblioteca, "objeto deducción gastos", fecha_juridica="2019-01-01", colecciones=["legislacion"])
    assert not any(x["titulo"].startswith("Ley sintética") for x in r["resultados"]), "no hay texto aplicable a 2019"
    r2 = busqueda.buscar(biblioteca, "texto derogado sintético", fecha_juridica="2019-01-01")
    assert any("sin fecha de vigencia" in h for h in r2["huecos"]) or r2["resultados"], "lo de vigencia desconocida se dice"


def test_vigencia_desconocida_pasa_el_filtro_pero_se_avisa(biblioteca):
    r = busqueda.buscar(biblioteca, "texto derogado sintético", fecha_juridica="2021-01-01")
    x = next(x for x in r["resultados"] if x["estado_normativo"] == "derogada")
    assert x["vigente_desde"] is None and x["vigencia_origen"] is None
    assert any("sin fecha de vigencia" in h for h in r["huecos"])


def test_identificadores_exactos_van_primero(biblioteca):
    r = busqueda.buscar(biblioteca, "BOE-A-2099-0001")
    assert r["resultados"][0]["motivo"].startswith("Identificador exacto") and r["resultados"][0]["fuente_id"] == "boe-consolidada"
    r2 = busqueda.buscar(biblioteca, "¿qué dice ECLI:ES:TC:2099:12 sobre el amparo?")
    assert r2["resultados"][0]["motivo"].startswith("Identificador exacto (ECLI:ES:TC:2099:12)") and r2["resultados"][0]["tipo"] == "sentencia"
    assert busqueda.buscar(biblioteca, "BOE-A-1111-9999")["resultados"] == []


def test_filtros_por_coleccion_tipo_emisor_y_fechas(biblioteca):
    r = busqueda.buscar(biblioteca, "sintético", colecciones=["jurisprudencia"])
    assert {x["coleccion"] for x in r["resultados"]} == {"jurisprudencia"} and {x["tipo"] for x in r["resultados"]} == {"sentencia", "auto"}
    assert [x["tipo"] for x in busqueda.buscar(biblioteca, "sintético", colecciones=["jurisprudencia"], tipo="auto")["resultados"]] == ["auto"]
    assert busqueda.buscar(biblioteca, "sintético", emisor="Tribunal Constitucional")["resultados"]
    assert busqueda.buscar(biblioteca, "sintético", emisor="Ministerio de Pruebas")["resultados"]
    assert busqueda.buscar(biblioteca, "sintético", colecciones=["jurisprudencia"], desde="2099-01-06")["resultados"][0]["tipo"] == "auto"
    assert busqueda.buscar(biblioteca, "sintético", colecciones=["jurisprudencia"], hasta="2099-01-01")["resultados"] == []
    solo_filtro = busqueda.buscar(biblioteca, "", colecciones=["legislacion"])
    assert solo_filtro["total"] == 2 and all(x["motivo"] == "Filtro" for x in solo_filtro["resultados"])
    with pytest.raises(busqueda.ErrorBusqueda):
        busqueda.buscar(biblioteca, "")
    with pytest.raises(busqueda.ErrorBusqueda, match="AAAA-MM-DD"):
        busqueda.buscar(biblioteca, "x", desde="ayer")


def test_una_coleccion_pedida_y_no_disponible_avisa_en_vez_de_desaparecer():
    habilitar("boe-consolidada")
    t = db.crear_tenant("Solo legislación")
    r = busqueda.buscar(t, "sintético", colecciones=["legislacion", "jurisprudencia"])
    assert any("jurisprudencia" in a and "no está disponible" in a for a in r["avisos"])


def test_sin_fuentes_habilitadas_no_hay_resultados_ni_se_simulan():
    t = db.crear_tenant("Sin nada")
    r = busqueda.buscar(t, "cualquier cosa")
    assert r["resultados"] == [] and r["modo"] == "sin_fuentes" and r["avisos"]


def test_un_despacho_que_desactiva_una_fuente_no_la_ve(biblioteca):
    corpus.fijar_fuente_despacho(biblioteca, "boe-diario-tc", False)
    r = busqueda.buscar(biblioteca, "sintético")
    assert {x["fuente_id"] for x in r["resultados"]} == {"boe-consolidada"}
    d = db.get_connection().execute("SELECT id FROM jur_documentos WHERE fuente_id = 'boe-diario-tc' LIMIT 1").fetchone()["id"]
    assert busqueda.documento(biblioteca, d) is None and busqueda.texto_de_version(biblioteca, d) is None
    otro = db.crear_tenant("Otro despacho")
    assert busqueda.documento(otro, d)["fuente_id"] == "boe-diario-tc"


def test_una_politica_que_deja_de_permitir_indexar_saca_la_fuente_de_la_busqueda(biblioteca):
    assert busqueda.buscar(biblioteca, "sintético", colecciones=["jurisprudencia"])["resultados"]
    corpus.registrar_politica("boe-diario-tc", evidencia="Contrato de prueba revocado: ya no se puede indexar", almacenar=True, indexar=False, enviar_llm=False, citar=False)
    assert busqueda.buscar(biblioteca, "sintético", colecciones=["jurisprudencia"])["resultados"] == []


def test_un_documento_retirado_deja_de_recuperarse_al_instante(biblioteca):
    assert busqueda.buscar(biblioteca, "amparo")["resultados"]
    corpus.retirar("boe-diario-tc", "BOE-A-2099-9101", "Corrección de anonimización")
    assert not any(x["fuente_id"] == "boe-diario-tc" and "amparo" in (x["extracto"] or "") for x in busqueda.buscar(biblioteca, "amparo")["resultados"])
    assert busqueda.buscar(biblioteca, "ECLI:ES:TC:2099:12")["resultados"] == []


def test_consultas_con_sintaxis_fts_o_comillas_no_rompen_la_busqueda(biblioteca):
    for q in ('"deducción" AND OR NOT', "gastos*", "NEAR(a b)", "a:b", "'; DROP TABLE jur_fragmentos; --", "((((", "gastos\"\"deducción"):
        r = busqueda.buscar(biblioteca, q)
        assert "resultados" in r
    assert busqueda.buscar(biblioteca, "de la")["modo"] == "texto"


def test_paginacion_con_cursor_sin_repetir_documentos(biblioteca):
    p1 = busqueda.buscar(biblioteca, "sintético", limite=1)
    assert len(p1["resultados"]) == 1 and p1["siguiente_cursor"] and p1["total"] >= 3
    vistos = [p1["resultados"][0]["documento_id"]]
    cur = p1["siguiente_cursor"]
    while cur:
        p = busqueda.buscar(biblioteca, "sintético", limite=1, cursor=cur)
        vistos.append(p["resultados"][0]["documento_id"])
        cur = p["siguiente_cursor"]
    assert len(vistos) == len(set(vistos)) == p1["total"]
    with pytest.raises(busqueda.ErrorBusqueda, match="cursor"):
        busqueda.buscar(biblioteca, "x", cursor="%%%no%%%")


class _Embedder:
    """Embedder de prueba determinista: 3 dimensiones por palabras clave. No es un modelo real."""
    modelo = "prueba-3d"

    def __call__(self, texto):
        t = texto.lower()
        return [float("amparo" in t or "recurso" in t), float("gasto" in t or "deduc" in t), float("derogado" in t) + 0.01]


def test_busqueda_hibrida_con_embeddings_y_degradacion_sin_ellos():
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    t = transporte_boe()
    emb = _Embedder()
    ingesta.sincronizar("boe-consolidada", conector_consolidada(t), "2099-01-01", "2099-01-31", embedder=emb)
    ingesta.sincronizar("boe-diario-tc", conector_diario(t), "2099-01-10", "2099-01-10", embedder=emb)
    tenant = db.crear_tenant("Híbrido")
    r = busqueda.buscar(tenant, "queja constitucional amparo", embedder=emb)
    assert r["modo"] == "hibrido" and r["resultados"]
    solo_vector = busqueda.buscar(tenant, "recursos amparados", embedder=emb)                      # sin coincidencia de texto exacta, sí semántica
    assert solo_vector["modo"] == "hibrido" and any(x["motivo"].startswith("Similitud") or "semántica" in x["motivo"] for x in solo_vector["resultados"])
    sin = busqueda.buscar(tenant, "amparo")
    assert sin["modo"] == "texto" and sin["resultados"]
    roto = busqueda.buscar(tenant, "amparo", embedder=lambda x: (_ for _ in ()).throw(RuntimeError("proveedor caído")))
    assert roto["modo"] == "texto" and roto["resultados"], "un fallo del embedder degrada a texto, no rompe"


def test_ficha_y_texto_de_version_con_fecha_y_huecos(biblioteca):
    d = db.get_connection().execute("SELECT id FROM jur_documentos WHERE id_externo = 'BOE-A-2099-0001'").fetchone()["id"]
    ficha = busqueda.documento(biblioteca, d)
    assert ficha["titulo"].startswith("Ley sintética") and ficha["versiones"][0]["activa"] == 1 and ficha["fuente_nombre"]
    assert {(r["tipo"], r["destino_externo"]) for r in ficha["relaciones"]} == {("deroga", "BOE-A-2099-0002"), ("modifica_por", "BOE-A-2099-0003")}
    assert next(r for r in ficha["relaciones"] if r["tipo"] == "deroga")["destino_titulo"].startswith("Real Decreto sintético"), "la relación se resuelve a un documento del corpus cuando existe"
    actual = busqueda.texto_de_version(biblioteca, d)
    a1 = [f for f in actual["fragmentos"] if f["bloque_id"] == "a1"]
    assert len(a1) == 1 and "quince" in a1[0]["texto"]
    en_2021 = busqueda.texto_de_version(biblioteca, d, fecha_juridica="2021-01-01")
    assert "diez" in next(f for f in en_2021["fragmentos"] if f["bloque_id"] == "a1")["texto"]
    antes = busqueda.texto_de_version(biblioteca, d, fecha_juridica="2019-01-01")
    assert antes["fragmentos"] == [] and antes["huecos"] and "posterior a 2019-01-01" in antes["huecos"][0]
    assert busqueda.documento(biblioteca, 99999) is None
