"""Asistente jurídico — corpus, políticas, conectores BOE (con fixtures SINTÉTICAS) y motor de ingesta."""
import pytest

from app import db
from app.juridico import catalogo, corpus, ingesta
from app.juridico.conectores.base import ConectorNoDisponible, ErrorConector, RefRegistro
from app.juridico.conectores.boe_diario import es_departamento_del_tc, tipo_de_titulo
from app.juridico.conectores.reservados import CendojLicenciado, EurLexCellar
from app.juridico.http import ClienteHTTP, ErrorHTTP
from tests.juridico_ayudas import BASE_C, TransporteFalso, cliente, conector_consolidada, conector_diario, fx, habilitar, transporte_boe

pytestmark = pytest.mark.usefixtures("base_de_datos_temporal")


def _doc(**kw):
    return corpus.DocumentoNuevo(**{"fuente_id": "boe-consolidada", "id_externo": "X-1", "coleccion": "legislacion", "titulo": "Norma de prueba", **kw})


def _frag(texto="Texto de prueba.", loc="Artículo 1", **kw):
    return corpus.FragmentoNuevo(loc, texto, **kw)


# --- Políticas y habilitación ----------------------------------------------------------------------------------------------------------------------------

def test_el_catalogo_existe_pero_nada_esta_habilitado_ni_tiene_politica():
    catalogo.asegurar_catalogo()
    fuentes = {f["id"]: f for f in corpus.listar_fuentes()}
    assert {"boe-consolidada", "boe-diario-tc", "cendoj-licenciado", "eurlex-cellar"} <= set(fuentes)
    assert all(not f["habilitada"] and f["estado"] == "pendiente" for f in fuentes.values())
    assert corpus.politica_vigente("boe-consolidada") is None and not corpus.operacion_permitida("boe-consolidada", "indexar")


def test_sin_evidencia_no_hay_politica_y_sin_politica_no_se_habilita():
    catalogo.asegurar_catalogo()
    with pytest.raises(corpus.ErrorCorpus, match="evidencia"):
        corpus.registrar_politica("boe-consolidada", evidencia=" ", almacenar=True, indexar=True, enviar_llm=True, citar=True)
    with pytest.raises(corpus.ErrorCorpus, match="política"):
        corpus.habilitar_fuente("boe-consolidada", True)
    with pytest.raises(corpus.ErrorCorpus, match="almacenar"):
        corpus.registrar_politica("boe-consolidada", evidencia="Condiciones de prueba largas", almacenar=False, indexar=True, enviar_llm=False, citar=False)


def test_las_politicas_son_versionadas_y_mandan_las_vigentes():
    habilitar("boe-consolidada")
    assert corpus.operacion_permitida("boe-consolidada", "enviar_llm")
    v2 = corpus.registrar_politica("boe-consolidada", evidencia="Nuevo contrato de prueba que prohíbe enviar al modelo", almacenar=True, indexar=True, enviar_llm=False, citar=True)
    assert v2 == 2 and not corpus.operacion_permitida("boe-consolidada", "enviar_llm") and corpus.operacion_permitida("boe-consolidada", "citar")


def test_fuentes_por_despacho_acceso_todos_y_explicito():
    t1, t2 = db.crear_tenant("Uno"), db.crear_tenant("Dos")
    habilitar("boe-consolidada")
    habilitar("cendoj-licenciado")
    assert corpus.fuentes_para_despacho(t1) == ["boe-consolidada"] == corpus.fuentes_para_despacho(t2), "pública: todos; licenciada: solo quien la activa"
    corpus.fijar_fuente_despacho(t1, "cendoj-licenciado", True)
    assert set(corpus.fuentes_para_despacho(t1)) == {"boe-consolidada", "cendoj-licenciado"} and corpus.fuentes_para_despacho(t2) == ["boe-consolidada"]
    corpus.fijar_fuente_despacho(t1, "boe-consolidada", False)
    assert corpus.fuentes_para_despacho(t1) == ["cendoj-licenciado"]
    assert corpus.fuentes_para_despacho(t1, "enviar_llm") == ["cendoj-licenciado"]


# --- Publicación atómica y versiones --------------------------------------------------------------------------------------------------------------------

def test_publicar_sin_politica_no_escribe_nada():
    catalogo.asegurar_catalogo()
    r = corpus.publicar(_doc(), [_frag()])
    assert r.estado == "bloqueada" and corpus.cobertura("boe-consolidada")[0]["documentos"] == 0


def test_versiones_inmutables_misma_version_no_duplica_y_solo_una_activa():
    habilitar("boe-consolidada")
    a = corpus.publicar(_doc(), [_frag("Uno.")])
    assert a.estado == "nueva"
    assert corpus.publicar(_doc(titulo="Solo cambian los metadatos"), [_frag("Uno.")]).estado == "sin_cambios"
    b = corpus.publicar(_doc(titulo="Solo cambian los metadatos"), [_frag("Dos.")])
    assert b.estado == "nueva" and b.version_id != a.version_id
    conn = db.get_connection()
    try:
        assert [r["activa"] for r in conn.execute("SELECT activa FROM jur_versiones WHERE documento_id = ? ORDER BY id", (a.documento_id,))] == [0, 1]
        assert conn.execute("SELECT titulo FROM jur_documentos WHERE id = ?", (a.documento_id,)).fetchone()["titulo"] == "Solo cambian los metadatos"
    finally:
        conn.close()
    c = corpus.publicar(_doc(), [_frag("Uno.")])                                    # vuelve un texto ya visto: se reactiva, no se duplica
    assert c.version_id == a.version_id


def test_un_texto_vacio_no_se_publica_y_una_coleccion_desconocida_tampoco():
    habilitar("boe-consolidada")
    with pytest.raises(corpus.ErrorCorpus, match="texto"):
        corpus.publicar(_doc(), [_frag("   ")])
    with pytest.raises(corpus.ErrorCorpus, match="Colección"):
        corpus.publicar(_doc(coleccion="otra"), [_frag()])


def test_un_fallo_a_mitad_de_la_publicacion_no_deja_versiones_a_medias(monkeypatch):
    habilitar("boe-consolidada")
    corpus.publicar(_doc(), [_frag("Original.")])
    def malo(texto):
        raise RuntimeError("no debe llegar al exterior")
    r = corpus.publicar(_doc(), [_frag("Nuevo texto.")], embedder=malo)               # el embedding opcional falla: se publica igual, sin vector
    assert r.estado == "nueva"
    class Roto:
        def __iter__(self):
            raise RuntimeError("boom")
    with pytest.raises(Exception):
        corpus.publicar(_doc(), [_frag("Otro."), Roto()])                              # fragmento imposible: aborta la transacción
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM jur_versiones WHERE activa = 1").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM jur_versiones").fetchone()[0] == 2
    finally:
        conn.close()


@pytest.mark.solo_sqlite
def test_retirar_bloquea_purga_y_marca_los_informes():
    habilitar("boe-consolidada")
    h = corpus.guardar_original("boe-consolidada", b"<x/>", "https://www.boe.es/x", "application/xml")
    p = corpus.publicar(_doc(), [_frag("Texto retirable.")], hash_original=h)
    assert corpus.leer_original(h) == b"<x/>"
    assert corpus.retirar("boe-consolidada", "X-1", "Anonimización corregida") is True
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT bloqueada, activa FROM jur_versiones WHERE id = ?", (p.version_id,)).fetchone()["bloqueada"] == 1
        assert conn.execute("SELECT COUNT(*) FROM jur_fragmentos").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM jur_fragmentos_fts WHERE jur_fragmentos_fts MATCH 'retirable'").fetchone()[0] == 0
    finally:
        conn.close()
    assert corpus.leer_original(h) is None
    assert corpus.retirar("boe-consolidada", "NO-EXISTE", "x") is False


def test_fechas_solo_se_normalizan_nunca_se_inventan():
    assert corpus.fecha_iso("20260130T123936Z") == "2026-01-30" and corpus.fecha_iso("2026-02-03") == "2026-02-03"
    assert corpus.fecha_iso("") is None and corpus.fecha_iso("2026-13-45") is None and corpus.fecha_iso("ayer") is None


# --- Cliente HTTP ----------------------------------------------------------------------------------------------------------------------------------------------

def test_http_solo_dominios_permitidos_y_https():
    c = ClienteHTTP({"www.boe.es"}, transporte=TransporteFalso())
    for url in ("https://evil.example/x", "http://www.boe.es/x", "https://www.boe.es@evil.example/x", "ftp://www.boe.es/x", "file:///etc/passwd"):
        with pytest.raises(ErrorHTTP):
            c.get(url)


def test_http_reintenta_429_y_5xx_con_espera_y_agota():
    t = TransporteFalso({"https://www.boe.es/ok": (200, b"hola")})
    t.fallos["https://www.boe.es/ok"] = [429, 503]
    esperas = []
    c = ClienteHTTP({"www.boe.es"}, transporte=t, dormir=esperas.append, espera_base=0.01, reintentos=3)
    assert c.get("https://www.boe.es/ok").cuerpo == b"hola" and len(esperas) == 2
    t2 = TransporteFalso()
    t2.fallos["https://www.boe.es/siempre"] = [500, 500, 500, 500]
    with pytest.raises(ErrorHTTP) as e:
        ClienteHTTP({"www.boe.es"}, transporte=t2, dormir=lambda s: None, reintentos=3).get("https://www.boe.es/siempre")
    assert e.value.transitorio and len(t2.llamadas) == 4
    t3 = TransporteFalso()
    t3.fallos["https://www.boe.es/red"] = [TimeoutError("lento")]
    t3.respuestas["https://www.boe.es/red"] = (200, b"ya")
    assert ClienteHTTP({"www.boe.es"}, transporte=t3, dormir=lambda s: None).get("https://www.boe.es/red").cuerpo == b"ya"


def test_http_respeta_retry_after_con_tope():
    c = ClienteHTTP({"www.boe.es"}, transporte=TransporteFalso())
    assert c._espera(0, {"Retry-After": "7"}) == 7.0 and c._espera(0, {"retry-after": "99999"}) == 120.0


# --- Conector BOE consolidada ----------------------------------------------------------------------------------------------------------------------------

def _lista_de_una(indice: int) -> bytes:
    """La fixture de lista con solo el ítem `indice` (0 o 1)."""
    texto = fx("boe_consolidada_lista.xml").decode("utf-8")
    cabeza, resto = texto.split("<item>", 1)
    items = ["<item>" + x.split("</item>")[0] + "</item>" for x in texto.split("<item>")[1:]]
    return (cabeza + items[indice] + "\n  </data>\n</response>\n").encode("utf-8")


def test_descubrir_consolidada_con_revision_de_origen_y_paginacion():
    t = transporte_boe()
    t.respuestas[f"{BASE_C}?from=20990101&to=20990131&offset=0&limit=1"] = (200, _lista_de_una(0))
    p = conector_consolidada(t, tamano_pagina=1).discover("2099-01-01", "2099-01-31", None)
    assert [r.id_externo for r in p.registros] == ["BOE-A-2099-0001"] and p.registros[0].actualizado_origen == "20990105T101500Z"
    assert p.siguiente_cursor == "1" and not p.agotada and p.evidencia
    p2 = conector_consolidada(t).discover("2099-01-01", "2099-01-31", None)
    assert [r.id_externo for r in p2.registros] == ["BOE-A-2099-0001", "BOE-A-2099-0002"] and p2.agotada


def test_parse_consolidada_versiones_por_bloque_vigencia_y_relaciones():
    con = conector_consolidada()
    ref = RefRegistro("boe-consolidada", "BOE-A-2099-0001", None, f"{BASE_C}/id/BOE-A-2099-0001")
    parsed = con.parse(ref, con.fetch(ref))
    d = parsed.documento
    assert (d.coleccion, d.rango, d.emisor, d.territorio, d.estado_normativo, d.eli) == ("legislacion", "Ley", "Ministerio de Pruebas Sintéticas", "ES", "vigente", "https://www.boe.es/eli/es/l/2020/01/10/1")
    assert (d.fecha_publicacion, d.fecha_resolucion) == ("2020-01-11", "2020-01-10") and "Pruebas sintéticas" in d.materia
    a1 = [f for f in parsed.fragmentos if f.bloque_id == "a1"]
    assert [(f.vigente_desde, f.vigente_hasta, f.vigencia_origen) for f in a1] == [("2020-01-01", "2022-06-30", "siguiente_version"), ("2022-07-01", None, "version_propia")]
    assert "diez por ciento" in a1[0].texto and "quince por ciento" in a1[1].texto and "Cita anidada" in a1[1].texto, "los <p> de un blockquote entran en orden"
    assert not any(f.bloque_id == "ci" for f in parsed.fragmentos), "los encabezados no son texto citable"
    a3 = [f for f in parsed.fragmentos if f.bloque_id == "a3"]
    assert len(a3) > 1 and all("parte" in f.localizador for f in a3) and max(len(f.texto) for f in a3) <= corpus.MAX_CARACTERES_FRAGMENTO
    assert {(r["tipo"], r["destino_externo"]) for r in parsed.relaciones} == {("deroga", "BOE-A-2099-0002"), ("modifica_por", "BOE-A-2099-0003")}


def test_parse_consolidada_vigencia_desconocida_se_dice_y_no_se_inventa():
    con = conector_consolidada()
    ref = RefRegistro("boe-consolidada", "BOE-A-2099-0002", None, f"{BASE_C}/id/BOE-A-2099-0002")
    parsed = con.parse(ref, con.fetch(ref))
    assert parsed.documento.estado_normativo == "derogada"
    assert all(f.vigente_desde is None and f.vigente_hasta is None and f.vigencia_origen is None for f in parsed.fragmentos)
    assert any("desconocida" in a for a in parsed.advertencias)


def test_consolidada_rechaza_respuestas_malas():
    ref = RefRegistro("boe-consolidada", "BOE-A-2099-0001", None, f"{BASE_C}/id/BOE-A-2099-0001")
    for cuerpo, patron in ((b"<html><body>Error</body></html>", "no es"), (b"no es xml", "XML"),
                           (b'<response><status><code>500</code><text>fallo</text></status></response>', "estado 500")):
        t = TransporteFalso({f"{BASE_C}/id/BOE-A-2099-0001": (200, cuerpo)})
        with pytest.raises(ErrorConector, match=patron):
            conector_consolidada(t).fetch(ref)
    t = TransporteFalso({f"{BASE_C}/id/BOE-A-2099-0001": (200, fx("boe_norma_sintetica_2.xml"))})
    con = conector_consolidada(t)
    with pytest.raises(ErrorConector, match="no coincide"):
        con.parse(ref, con.fetch(ref))


def test_xml_con_entidades_externas_no_se_resuelve():
    malo = ('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><response><status><code>200</code></status><data><metadatos><identificador>BOE-A-2099-0001</identificador>'
            '<titulo>&x;</titulo></metadatos><texto><bloque id="a1" tipo="precepto" titulo="Artículo 1"><version fecha_vigencia="20200101"><p>Hola</p></version></bloque></texto></data></response>').encode("utf-8")
    con = conector_consolidada()
    ref = RefRegistro("boe-consolidada", "BOE-A-2099-0001", None, "")
    try:
        parsed = con.parse(ref, type("O", (), {"contenido": malo})())
        assert "root:" not in parsed.documento.titulo
    except ErrorConector:
        pass


# --- Conector BOE diario (Tribunal Constitucional) -------------------------------------------------------------------------------------------------------

def test_clasificacion_de_resoluciones_del_tc():
    assert tipo_de_titulo("Sala Primera. Sentencia 12/2099, de 5 de enero.") == "sentencia" and tipo_de_titulo("Pleno. Auto 7/2099, de 8 de enero.") == "auto"
    assert tipo_de_titulo("Resolución por la que se nombra a un letrado del Tribunal Constitucional.") is None
    assert es_departamento_del_tc("TRIBUNAL CONSTITUCIONAL") and not es_departamento_del_tc("MINISTERIO DE JUSTICIA, Tribunal Constitucional") and not es_departamento_del_tc("ADMINISTRACIÓN DE JUSTICIA")


def test_descubrir_sumario_solo_resoluciones_del_tc_y_sin_edicion_no_es_error():
    con = conector_diario()
    p = con.discover("2099-01-10", "2099-01-11", None)
    assert [r.id_externo for r in p.registros] == ["BOE-A-2099-9101", "BOE-A-2099-9102"], "ni el nombramiento, ni el ministerio, ni el anuncio de un juzgado"
    assert p.notas["descartados"] == 1 and p.siguiente_cursor == "2099-01-11" and not p.agotada and p.evidencia
    p2 = con.discover("2099-01-10", "2099-01-11", p.siguiente_cursor)
    assert p2.registros == [] and p2.notas == {"dias_sin_edicion": 1} and p2.agotada


def test_parse_sentencia_del_tc_estructura_y_voto_particular_etiquetado():
    con = conector_diario()
    ref = RefRegistro("boe-diario-tc", "BOE-A-2099-9101", None, "https://www.boe.es/diario_boe/xml.php?id=BOE-A-2099-9101")
    parsed = con.parse(ref, con.fetch(ref))
    d = parsed.documento
    assert (d.coleccion, d.tipo, d.emisor, d.fecha_resolucion, d.fecha_publicacion, d.ecli) == ("jurisprudencia", "sentencia", "Tribunal Constitucional", "2099-01-05", "2099-01-10", "ECLI:ES:TC:2099:12")
    locs = [f.localizador for f in parsed.fragmentos]
    assert "Cabecera" in locs and "Antecedente 1" in locs and "FJ 1" in locs and "FJ 2" in locs and "Fallo" in locs
    voto = [f for f in parsed.fragmentos if f.localizador.startswith("Voto particular")]
    assert voto and all("no es el criterio de la mayoría" in f.localizador for f in voto)
    assert any("particular" in a for a in parsed.advertencias)


def test_el_ecli_no_se_compone_si_no_consta():
    con = conector_diario()
    ref = RefRegistro("boe-diario-tc", "BOE-A-2099-9102", None, "https://www.boe.es/diario_boe/xml.php?id=BOE-A-2099-9102")
    parsed = con.parse(ref, con.fetch(ref))
    assert parsed.documento.tipo == "auto" and parsed.documento.ecli is None and any("ECLI" in a for a in parsed.advertencias)
    assert "Fallo" not in [f.localizador for f in parsed.fragmentos] and "Acuerdo" in [f.localizador for f in parsed.fragmentos]


def test_diario_rechaza_una_pagina_de_error_y_un_documento_que_no_es_del_tc():
    ref = RefRegistro("boe-diario-tc", "BOE-A-2099-9101", None, "https://www.boe.es/diario_boe/xml.php?id=BOE-A-2099-9101")
    con = conector_diario(TransporteFalso({ref.localizador: (200, b"<html>Acceso denegado</html>")}))
    with pytest.raises(ErrorConector, match="no es un documento"):
        con.fetch(ref)
    otro = fx("boe_doc_tc_sentencia.xml").replace(b"<departamento codigo=\"9980\">Tribunal Constitucional", b"<departamento codigo=\"1\">Ministerio de Pruebas")
    con2 = conector_diario(TransporteFalso({ref.localizador: (200, otro)}))
    with pytest.raises(ErrorConector, match="no es una resolución del Tribunal Constitucional"):
        con2.parse(ref, con2.fetch(ref))


def test_los_conectores_reservados_no_inventan_nada():
    for c in (CendojLicenciado(), EurLexCellar()):
        assert not c.capacidades.descubrir and not c.capacidades.contenido
        with pytest.raises(ConectorNoDisponible):
            c.discover("2099-01-01", "2099-01-02", None)
        with pytest.raises(ConectorNoDisponible):
            c.fetch(RefRegistro(c.id, "x"))


# --- Motor de ingesta -----------------------------------------------------------------------------------------------------------------------------------------

def _ejecutar(con, **kw):
    return ingesta.sincronizar("boe-consolidada", con, "2099-01-01", "2099-01-31", **kw)


def test_ingesta_completa_publica_y_es_idempotente():
    habilitar("boe-consolidada")
    t = transporte_boe()
    r = _ejecutar(conector_consolidada(t))
    assert r["estado"] == "completa" and r["contadores"]["publicados"] == 2 and r["contadores"]["nuevos"] == 2
    cob = corpus.cobertura("boe-consolidada")[0]
    assert cob["documentos"] == 2 and cob["ultimo_exito_en"] and cob["pendientes"] == 0 and cob["cuarentena"] == 0 and cob["fragmentos"] > 3
    descargas = sum("/id/" in u for u in t.llamadas)
    r2 = _ejecutar(conector_consolidada(t))
    assert r2["estado"] == "completa" and r2["contadores"].get("iguales") == 2 and r2["contadores"].get("publicados", 0) == 0
    assert sum("/id/" in u for u in t.llamadas) == descargas, "misma revisión de origen ya publicada: no se vuelve a descargar"
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM jur_versiones").fetchone()[0] == 2 and conn.execute("SELECT COUNT(*) FROM jur_documentos").fetchone()[0] == 2
    finally:
        conn.close()


def test_ingesta_nueva_revision_con_mismo_texto_no_crea_version_y_con_texto_distinto_si():
    habilitar("boe-consolidada")
    t = transporte_boe()
    _ejecutar(conector_consolidada(t))
    lista = fx("boe_consolidada_lista.xml").replace(b"20990105T101500Z", b"20990120T101500Z")
    t.respuestas[f"{BASE_C}?from=20990101&to=20990131&offset=0&limit=100"] = (200, lista)
    r = _ejecutar(conector_consolidada(t))
    assert r["contadores"]["cambiados"] == 1 and r["contadores"].get("sin_cambios") == 1 and r["contadores"].get("publicados", 0) == 0, "revisión nueva, texto igual: sin versión nueva"
    nuevo = fx("boe_norma_sintetica_1.xml").replace("quince por ciento".encode(), "veinte por ciento".encode())
    t.respuestas[f"{BASE_C}/id/BOE-A-2099-0001"] = (200, nuevo)
    t.respuestas[f"{BASE_C}?from=20990101&to=20990131&offset=0&limit=100"] = (200, lista.replace(b"20990120T101500Z", b"20990125T101500Z"))
    r = _ejecutar(conector_consolidada(t))
    assert r["contadores"]["publicados"] == 1
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM jur_versiones WHERE documento_id = (SELECT id FROM jur_documentos WHERE id_externo = 'BOE-A-2099-0001')").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM jur_versiones WHERE activa = 1").fetchone()[0] == 2
    finally:
        conn.close()


def test_ingesta_bloqueada_sin_politica_o_sin_habilitar_no_toca_la_fuente():
    catalogo.asegurar_catalogo()
    t = transporte_boe()
    r = _ejecutar(conector_consolidada(t))
    assert r["estado"] == "bloqueada" and t.llamadas == [] and corpus.cobertura("boe-consolidada")[0]["documentos"] == 0


def test_un_conector_sin_descubrimiento_no_finge_sincronizar():
    habilitar("cendoj-licenciado")
    with pytest.raises(corpus.ErrorCorpus, match="no sabe descubrir"):
        ingesta.sincronizar("cendoj-licenciado", CendojLicenciado(), "2099-01-01", "2099-01-31")


def test_error_transitorio_reintenta_y_luego_cuarentena_sin_perder_lo_publicado():
    habilitar("boe-consolidada")
    t = transporte_boe()
    t.fallos[f"{BASE_C}/id/BOE-A-2099-0002"] = [503] * 100                                 # siempre 503 (cada get() ya reintenta 3 veces)
    r = _ejecutar(conector_consolidada(t))
    assert r["estado"] == "parcial" and r["contadores"]["publicados"] == 1 and r["contadores"]["reintentables"] == 1
    cob = corpus.cobertura("boe-consolidada")[0]
    assert cob["documentos"] == 1 and cob["reintentables"] == 1 and cob["ultimo_exito_en"] is None, "una ejecución parcial no se anota como éxito"
    for _ in range(2):
        r = _ejecutar(conector_consolidada(t))
    assert corpus.cobertura("boe-consolidada")[0]["cuarentena"] == 1 and corpus.cobertura("boe-consolidada")[0]["documentos"] == 1
    problemas = ingesta.registros_con_problemas("boe-consolidada")
    assert problemas[0]["id_externo"] == "BOE-A-2099-0002" and problemas[0]["estado"] == "QUARANTINED" and "503" in problemas[0]["ultimo_error"]


def test_error_permanente_va_directo_a_cuarentena_y_no_publica_a_medias():
    habilitar("boe-consolidada")
    t = transporte_boe()
    t.respuestas[f"{BASE_C}/id/BOE-A-2099-0002"] = (200, b"<html>no soy una norma</html>")
    r = _ejecutar(conector_consolidada(t))
    assert r["estado"] == "parcial" and r["contadores"]["cuarentena"] == 1
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM jur_documentos WHERE id_externo = 'BOE-A-2099-0002'").fetchone()[0] == 0
    finally:
        conn.close()


def test_el_checkpoint_sobrevive_a_un_caida_entre_descubrir_y_publicar():
    """Se registra el inventario (outbox + cursor) y el proceso 'muere' antes de publicar: al reanudar se completa sin duplicar ni perder nada."""
    habilitar("boe-consolidada")
    t = transporte_boe()
    con = conector_consolidada(t)
    r = _ejecutar(con, procesar=False)
    assert r["contadores"]["descubiertos"] == 2 and r["estado"] in ("completa", "parcial")
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM jur_outbox WHERE estado = 'pendiente'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM jur_documentos").fetchone()[0] == 0
    finally:
        conn.close()
    h = ingesta.procesar_pendientes("boe-consolidada", conector_consolidada(t))
    assert h["publicados"] == 2
    h2 = ingesta.procesar_pendientes("boe-consolidada", conector_consolidada(t))
    assert sum(h2.values()) == 0, "reprocesar el outbox ya consumido no hace nada"


def test_un_trabajo_duplicado_en_el_outbox_es_idempotente():
    habilitar("boe-consolidada")
    t = transporte_boe()
    _ejecutar(conector_consolidada(t))
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO jur_outbox (fuente_id, id_externo, creada_en) VALUES ('boe-consolidada', 'BOE-A-2099-0001', '2099-01-01')")
        conn.commit()
    finally:
        conn.close()
    n = sum("/id/" in u for u in t.llamadas)
    h = ingesta.procesar_pendientes("boe-consolidada", conector_consolidada(t))
    assert h["sin_cambios"] == 1 and sum("/id/" in u for u in t.llamadas) == n


def test_fallo_al_descubrir_conserva_lo_publicado_y_marca_incidencia():
    habilitar("boe-consolidada")
    t = transporte_boe()
    _ejecutar(conector_consolidada(t))
    t2 = TransporteFalso()
    t2.fallos[f"{BASE_C}?from=20990201&to=20990228&offset=0&limit=100"] = [500] * 8
    r = ingesta.sincronizar("boe-consolidada", conector_consolidada(t2), "2099-02-01", "2099-02-28")
    assert r["estado"] == "fallida" and "500" in r["error"]
    f = corpus.obtener_fuente("boe-consolidada")
    assert f["estado"] == "incidencia" and corpus.cobertura("boe-consolidada")[0]["documentos"] == 2, "sigue habiendo última versión utilizable"


def test_una_politica_retirada_a_mitad_bloquea_la_publicacion():
    habilitar("boe-consolidada")
    t = transporte_boe()
    _ejecutar(conector_consolidada(t), procesar=False)
    corpus.registrar_politica("boe-consolidada", evidencia="Contrato de prueba revocado: ya no se puede almacenar", almacenar=False, indexar=False, enviar_llm=False, citar=False)
    h = ingesta.procesar_pendientes("boe-consolidada", conector_consolidada(t))
    assert h["bloqueados"] == 2 and corpus.cobertura("boe-consolidada")[0]["bloqueados"] == 2 and corpus.cobertura("boe-consolidada")[0]["documentos"] == 0


def test_ingesta_del_tc_por_dias_con_descartados_y_dias_sin_edicion():
    habilitar("boe-diario-tc")
    t = transporte_boe()
    r = ingesta.sincronizar("boe-diario-tc", conector_diario(t), "2099-01-10", "2099-01-11")
    assert r["estado"] == "completa" and r["contadores"]["publicados"] == 2 and r["contadores"]["descartados"] == 1 and r["contadores"]["dias_sin_edicion"] == 1
    cob = corpus.cobertura("boe-diario-tc")[0]
    assert cob["documentos"] == 2 and cob["desde"] == "2099-01-10"
    conn = db.get_connection()
    try:
        assert {r["tipo"] for r in conn.execute("SELECT tipo FROM jur_documentos")} == {"sentencia", "auto"}
        assert conn.execute("SELECT COUNT(*) FROM jur_originales WHERE url LIKE '%sumario%'").fetchone()[0] == 1, "se conserva el sumario descargado como evidencia (el día sin edición no tiene)"
    finally:
        conn.close()


# --- Trabajador periódico ----------------------------------------------------------------------------------------------------------------------------------

def test_el_trabajador_solo_corre_si_se_pide_y_sincroniza_las_habilitadas(monkeypatch):
    from datetime import date
    from app.juridico import trabajador
    monkeypatch.delenv("LEGAL_AI_SYNC", raising=False)
    assert not trabajador.activo()
    monkeypatch.setenv("LEGAL_AI_SYNC", "1")
    assert trabajador.activo()
    monkeypatch.delenv("LEGAL_AI_ENABLED")
    assert not trabajador.activo(), "sin LEGAL_AI_ENABLED no hay nada"
    monkeypatch.setenv("LEGAL_AI_ENABLED", "1")
    catalogo.asegurar_catalogo()
    t = TransporteFalso({f"{BASE_C}?from=20990104&to=20990111&offset=0&limit=100": (200, fx("boe_consolidada_lista.xml")),
                         f"{BASE_C}/id/BOE-A-2099-0001": (200, fx("boe_norma_sintetica_1.xml")), f"{BASE_C}/id/BOE-A-2099-0002": (200, fx("boe_norma_sintetica_2.xml"))})
    r = trabajador.ejecutar_ciclo(date(2099, 1, 11), conectores={"boe-consolidada": conector_consolidada(t)})
    assert r["adjuntos_purgados"] == 0 and "boe-consolidada" not in r, "sin política ni habilitación no se sincroniza"
    habilitar("boe-consolidada")
    r = trabajador.ejecutar_ciclo(date(2099, 1, 11), conectores={"boe-consolidada": conector_consolidada(t)})
    assert r["boe-consolidada"]["estado"] == "completa" and r["boe-consolidada"]["contadores"]["publicados"] == 2
    habilitar("cendoj-licenciado")
    r = trabajador.ejecutar_ciclo(date(2099, 1, 11), conectores={"boe-consolidada": conector_consolidada(t)})
    assert "cendoj-licenciado" not in r, "un conector reservado (sin transporte) se salta, no falla el ciclo"


def test_una_fuente_rota_no_tumba_el_ciclo(monkeypatch):
    from datetime import date
    from app.juridico import trabajador
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    class Roto:
        capacidades = type("C", (), {"descubrir": True})()
        def discover(self, *a):
            raise RuntimeError("boom")
    r = trabajador.ejecutar_ciclo(date(2099, 1, 10), conectores={"boe-consolidada": Roto(), "boe-diario-tc": conector_diario()})
    assert r["boe-consolidada"]["estado"] in ("fallida", "error") and r["boe-diario-tc"]["estado"] == "completa"
