"""Asistente jurídico — aislamiento entre despachos y clientes, borrado, evaluación y embeddings por defecto (modelo SIMULADO; corpus SINTÉTICO)."""
import json
from pathlib import Path

import pytest

from app import acceso, db, ia_asistente, nucleo, verticales
from app.juridico import adjuntos, asistente, corpus, evaluacion, informes, ingesta, modulo, privado
from tests.juridico_ayudas import conector_consolidada, conector_diario, habilitar, transporte_boe
from tests.test_juridico_asistente import ok_articulo1, modelo

pytestmark = pytest.mark.usefixtures("base_de_datos_temporal")


@pytest.fixture
def dos(base_de_datos_temporal):
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    tr = transporte_boe()
    ingesta.sincronizar("boe-consolidada", conector_consolidada(tr), "2099-01-01", "2099-01-31")
    ingesta.sincronizar("boe-diario-tc", conector_diario(tr), "2099-01-10", "2099-01-10")
    class E: pass
    e = E()
    def despacho(n):
        t = db.crear_tenant(f"Despacho {n}")
        u = db.crear_usuario_vinculado_a_kratos(f"u{n}-ai@ejemplo.com", f"k-u{n}-ai"); db.asignar_tenant(u, t)
        db.asignar_supervisor_tenant(u, True)
        verticales.fijar_activo(t, "juridico", True)
        return t, u
    (e.t1, e.u1), (e.t2, e.u2) = despacho(1), despacho(2)
    return e


def test_todas_las_tablas_privadas_llevan_tenant_id_no_nulo():
    conn = db.get_connection()
    try:
        for tabla in privado.TABLAS_DEL_DESPACHO:
            cols = {f["name"]: f for f in conn.execute(f"PRAGMA table_info({tabla})")}
            assert "tenant_id" in cols and cols["tenant_id"]["notnull"] == 1, tabla
        for tabla in ("jur_fuentes", "jur_documentos", "jur_versiones", "jur_fragmentos"):
            assert "tenant_id" not in {f["name"] for f in conn.execute(f"PRAGMA table_info({tabla})")}, f"{tabla} es corpus compartido"
    finally:
        conn.close()


def test_ids_adivinados_entre_despachos_no_dan_acceso_a_nada_privado(dos, monkeypatch):
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, c: json.dumps(ok_articulo1(c)))
    c1 = nucleo.crear_cliente(dos.t1, "Cliente de uno", nif="B11111111")
    conv = asistente.crear_conversacion(dos.t1, dos.u1, cliente_id=c1)
    adj = adjuntos.subir(dos.t1, dos.u1, "secreto.txt", "El secreto del despacho uno: zorrocotroco.".encode(), cliente_id=c1)
    r = asistente.consultar(dos.t1, dos.u1, conv, "deducción de gastos límite", colecciones=["legislacion"], adjunto_ids=[adj["id"]])
    inf = informes.guardar(dos.t1, dos.u1, r["runId"])
    assert asistente.listar_conversaciones(dos.t2, dos.u2) == []
    assert asistente.obtener_conversacion(dos.t2, dos.u2, conv) is None and asistente.ejecucion(dos.t2, dos.u2, r["runId"]) is None
    with pytest.raises(asistente.ErrorJuridico):
        asistente.respuesta_de(dos.t2, dos.u2, r["runId"])
    assert adjuntos.obtener(dos.t2, dos.u2, adj["id"]) is None and adjuntos.listar(dos.t2, dos.u2) == []
    assert adjuntos.fragmentos_para(dos.t2, [adj["id"]], "zorrocotroco") == []
    with pytest.raises(adjuntos.ErrorAdjunto):
        adjuntos.validar_para_consulta(dos.t2, dos.u2, [adj["id"]])
    assert adjuntos.borrar(dos.t2, dos.u2, adj["id"]) is False
    assert informes.obtener(dos.t2, dos.u2, inf["id"]) is None and informes.listar(dos.t2, dos.u2) == []
    with pytest.raises(informes.ErrorInforme):
        informes.guardar(dos.t2, dos.u2, r["runId"])
    with pytest.raises(informes.ErrorInforme):
        informes.revisar(dos.t2, dos.u2, inf["id"])
    with pytest.raises(asistente.ErrorJuridico):
        asistente.crear_conversacion(dos.t2, dos.u2, cliente_id=c1)
    nuevo = asistente.crear_conversacion(dos.t2, dos.u2)
    with pytest.raises(asistente.ErrorJuridico, match="No encuentras"):
        asistente.consultar(dos.t2, dos.u2, nuevo, "zorrocotroco", adjunto_ids=[adj["id"]])
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM jur_fragmentos_privados_fts WHERE jur_fragmentos_privados_fts MATCH 'zorrocotroco'").fetchone()[0] == 1, "el índice existe, pero solo se consulta acotado por tenant_id"
    finally:
        conn.close()


def test_los_informes_se_filtran_por_cliente_dentro_del_despacho(dos, monkeypatch):
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, c: json.dumps(ok_articulo1(c)))
    t = dos.t1
    c_a, c_b = nucleo.crear_cliente(t, "Cliente A", nif="B22222222"), nucleo.crear_cliente(t, "Cliente B", nif="B33333333")
    conv = asistente.crear_conversacion(t, dos.u1, cliente_id=c_b)
    r = asistente.consultar(t, dos.u1, conv, "deducción de gastos límite", colecciones=["legislacion"], generador=modelo(ok_articulo1))
    inf = informes.guardar(t, dos.u1, r["runId"])
    assert [i["id"] for i in informes.listar(t, dos.u1, cliente_id=c_b)] == [inf["id"]] and informes.listar(t, dos.u1, cliente_id=c_a) == []


def test_borrar_un_despacho_borra_lo_privado_y_deja_el_corpus(dos, monkeypatch):
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, c: json.dumps(ok_articulo1(c)))
    conv = asistente.crear_conversacion(dos.t1, dos.u1)
    adj = adjuntos.subir(dos.t1, dos.u1, "a.txt", b"documento privado")
    r = asistente.consultar(dos.t1, dos.u1, conv, "deducción de gastos límite", colecciones=["legislacion"], adjunto_ids=[adj["id"]])
    informes.guardar(dos.t1, dos.u1, r["runId"])
    corpus.fijar_fuente_despacho(dos.t1, "boe-consolidada", True)
    otro = asistente.crear_conversacion(dos.t2, dos.u2)
    adjuntos.subir(dos.t2, dos.u2, "b.txt", b"documento del otro")
    conn = db.get_connection()
    try:
        modulo.borrar_datos_de_tenant(conn, dos.t1)
        conn.commit()
        for tabla in privado.TABLAS_DEL_DESPACHO + ("jur_fuente_despacho",):
            assert conn.execute(f"SELECT COUNT(*) FROM {tabla} WHERE tenant_id = ?", (dos.t1,)).fetchone()[0] == 0, tabla
        assert conn.execute("SELECT COUNT(*) FROM jur_fragmentos_privados_fts WHERE jur_fragmentos_privados_fts MATCH 'privado'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM jur_adjuntos WHERE tenant_id = ?", (dos.t2,)).fetchone()[0] == 1, "los datos de otro despacho no se tocan"
        assert conn.execute("SELECT COUNT(*) FROM jur_documentos").fetchone()[0] == 4, "el corpus común no se borra"
    finally:
        conn.close()
    assert asistente.obtener_conversacion(dos.t2, dos.u2, otro) is not None


def test_el_corpus_compartido_nunca_recibe_texto_de_un_despacho(dos):
    adjuntos.subir(dos.t1, dos.u1, "a.txt", "palabra única privadísima pimpampum".encode())
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM jur_fragmentos_fts WHERE jur_fragmentos_fts MATCH 'pimpampum'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM jur_fragmentos WHERE texto LIKE '%pimpampum%'").fetchone()[0] == 0
    finally:
        conn.close()


def test_la_auditoria_no_guarda_el_texto_de_las_consultas(dos, monkeypatch):
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, c: json.dumps(ok_articulo1(c)))
    conv = asistente.crear_conversacion(dos.t1, dos.u1)
    asistente.consultar(dos.t1, dos.u1, conv, "pregunta confidencial zumbidoraro sobre deducción de gastos límite", colecciones=["legislacion"])
    conn = db.get_connection()
    try:
        volcado = " ".join(f"{r['accion']} {r['recurso']} {r['detalle']}" for r in conn.execute("SELECT * FROM jur_auditoria"))
        assert "zumbidoraro" not in volcado and "consulta.terminar" in volcado
    finally:
        conn.close()


def test_embeddings_por_defecto_solo_con_el_interruptor(monkeypatch):
    monkeypatch.delenv("LEGAL_EMBEDDINGS", raising=False)
    assert modulo.embedder() is None
    monkeypatch.setenv("LEGAL_EMBEDDINGS", "1")
    emb = modulo.embedder()
    assert emb.modelo
    from app import embeddings
    monkeypatch.setattr(embeddings, "generar_embedding", lambda t: [1.0, 0.0])
    assert emb("hola") == [1.0, 0.0]
    monkeypatch.setattr(embeddings, "generar_embedding", lambda t: None)
    assert emb("hola") is None, "Ollama caído: sin vector, la búsqueda degrada a texto"


def test_los_vectores_de_otro_modelo_no_se_mezclan(dos):
    from tests.test_juridico_busqueda import _Embedder
    from app.juridico import busqueda
    corpus.publicar(corpus.DocumentoNuevo("boe-consolidada", "VEC-1", "legislacion", "Norma vectorial de prueba"), [corpus.FragmentoNuevo("Artículo 1", "amparo y recurso de prueba")], embedder=_Embedder())
    r = busqueda.buscar(dos.t1, "recursos amparados", embedder=_Embedder())
    assert r["modo"] == "hibrido"
    class OtroModelo(_Embedder):
        modelo = "otro-modelo"
    assert busqueda.buscar(dos.t1, "recursos amparados", embedder=OtroModelo())["modo"] == "texto", "vectores de otro modelo: no se comparan"


def test_la_evaluacion_mide_recuperacion_y_no_inventa_calidad(dos):
    casos = evaluacion.cargar(str(Path(__file__).parent / "datos" / "juridico_evaluacion_plantilla.json"))
    r = evaluacion.recuperacion(dos.t1, casos)
    assert r["evaluables"] == 2 and r["recuperan_fuente_necesaria"] == 2 and r["porcentaje_recuperacion"] == 100.0 and r["insuficientes"] == 1 and r["insuficientes_correctos"] == 1
    assert "no mide la corrección jurídica" in r["aviso"] and all(d["sintetico"] for d in r["detalle"])
    rev = evaluacion.respuestas_para_revision(dos.t1, dos.u1, casos[:1], generador=modelo(ok_articulo1))
    assert rev[0]["respuesta"]["status"] == "answered" and rev[0]["puntuacion_profesional"]["correcta"] is None, "la puntuación la pone una persona"
    with pytest.raises(ValueError):
        evaluacion.cargar(str(Path(__file__).parent / "fixtures_juridico" / "README.md"))
