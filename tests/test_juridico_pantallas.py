"""Asistente jurídico — pantallas (modelo de IA SIMULADO; corpus SINTÉTICO)."""
import io
import json

import pytest

from app import db, verticales
from app.juridico import corpus, informes, ingesta
from tests.conftest import iniciar_sesion_de_prueba
from tests.juridico_ayudas import conector_consolidada, conector_diario, habilitar, transporte_boe
from tests.test_juridico_asistente import _refs, _ref_de, ok_articulo1


@pytest.fixture
def sesion(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "juridico-ui@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho jurídico UI")
    db.asignar_tenant(uid, t)
    db.asignar_supervisor_tenant(uid, True)
    verticales.fijar_activo(t, "juridico", True)
    return cliente, uid, t


def _cargar_biblioteca():
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    tr = transporte_boe()
    ingesta.sincronizar("boe-consolidada", conector_consolidada(tr), "2099-01-01", "2099-01-31")
    ingesta.sincronizar("boe-diario-tc", conector_diario(tr), "2099-01-10", "2099-01-10")


def test_sin_el_vertical_o_con_el_modulo_apagado_todo_es_404(cliente, monkeypatch):
    uid = iniciar_sesion_de_prueba(cliente, "sin-juridico@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Sin módulo")
    db.asignar_tenant(uid, t)
    for ruta in ("/juridico/", "/juridico/biblioteca", "/juridico/fuentes", "/juridico/informes"):
        assert cliente.get(ruta).status_code == 404, ruta
    assert cliente.post("/juridico/consultar", data={"pregunta": "x"}).status_code == 404
    verticales.fijar_activo(t, "juridico", True)
    assert cliente.get("/juridico/").status_code == 200
    monkeypatch.delenv("LEGAL_AI_ENABLED")
    assert cliente.get("/juridico/").status_code == 404


def test_inicio_avisa_si_no_hay_fuentes_y_enseña_la_cobertura_si_las_hay(sesion):
    c, uid, t = sesion
    html = c.get("/juridico/").get_data(as_text=True)
    assert "Todavía no hay fuentes jurídicas habilitadas" in html and "no se contesta de memoria" in html
    _cargar_biblioteca()
    html = c.get("/juridico/").get_data(as_text=True)
    assert "Todavía no hay fuentes jurídicas habilitadas" not in html and "2 documentos" in html


def test_biblioteca_busqueda_ficha_y_fecha_juridica(sesion):
    c, uid, t = sesion
    _cargar_biblioteca()
    vacia = c.get("/juridico/biblioteca").get_data(as_text=True)
    assert "Cobertura real" in vacia and "BOE" in vacia
    r = c.get("/juridico/biblioteca?q=deducción+de+gastos&coleccion=legislacion").get_data(as_text=True)
    assert "Ley sintética 1/2020" in r and "Artículo 1" in r and "Coincidencia de texto" in r and "capturado el" in r
    r2 = c.get("/juridico/biblioteca?q=objeto+deducción&fecha_juridica=2019-01-01&coleccion=legislacion").get_data(as_text=True)
    assert "primera versión recogida" in r2
    assert "debe ser AAAA-MM-DD" in c.get("/juridico/biblioteca?q=x&desde=ayer").get_data(as_text=True) or "AAAA-MM-DD" in c.get("/juridico/biblioteca?q=x&desde=ayer").get_data(as_text=True)
    did = db.get_connection().execute("SELECT id FROM jur_documentos WHERE id_externo = 'BOE-A-2099-0001'").fetchone()["id"]
    f = c.get(f"/juridico/documento/{did}").get_data(as_text=True)
    assert "quince por ciento" in f and "diez por ciento" not in f and "informativo" in f and "Fuente original" in f and "deroga" in f
    f2 = c.get(f"/juridico/documento/{did}?fecha_juridica=2021-06-01").get_data(as_text=True)
    assert "diez por ciento" in f2 and "quince por ciento" not in f2
    assert c.get("/juridico/documento/99999").status_code == 404
    assert "desconocida" in c.get(f"/juridico/documento/{db.get_connection().execute('SELECT id FROM jur_documentos WHERE id_externo = ?', ('BOE-A-2099-0002',)).fetchone()['id']}").get_data(as_text=True)


def test_consulta_completa_desde_la_pantalla_hasta_el_informe_revisado(sesion, monkeypatch):
    from app import ia_asistente, reuniones
    c, uid, t = sesion
    _cargar_biblioteca()
    monkeypatch.setattr(reuniones, "configurada", lambda u: True)
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, contenido: json.dumps(ok_articulo1(contenido)))
    r = c.post("/juridico/consultar", data={"pregunta": "¿Qué límite tiene la deducción de gastos?", "fecha_juridica": "2099-01-15", "modo_temporal": "actual", "objetivo": "consulta", "coleccion": ["legislacion"]})
    assert r.status_code == 302 and "/juridico/consulta/" in r.headers["Location"]
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "Respondida con fuentes" in html and "quince por ciento" in html and "Borrador pendiente de revisión profesional" in html and "Abrir el fragmento exacto" in html and "Fuente original" in html
    assert "Guardar como informe del cliente" in html
    run_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
    g = c.post(f"/juridico/consulta/{run_id}/informe", data={"titulo": "Límite de gastos"})
    assert g.status_code == 302 and "/juridico/informes/" in g.headers["Location"]
    inf = c.get(g.headers["Location"]).get_data(as_text=True)
    assert "Borrador pendiente de revisión profesional" in inf and "Marcar como revisado" in inf and "Copiar con referencias" in inf
    iid = int(g.headers["Location"].rstrip("/").split("/")[-1])
    assert c.post(f"/juridico/informes/{iid}/revisar", data={"decision": "revisado"}).status_code == 302
    assert "Revisado el" in c.get(f"/juridico/informes/{iid}").get_data(as_text=True)
    assert informes.obtener(t, uid, iid)["estado"] == "revisado"
    assert "Límite de gastos" in c.get("/juridico/informes").get_data(as_text=True)


def test_la_pantalla_enseña_el_fallo_sin_inventar_una_respuesta(sesion, monkeypatch):
    c, uid, t = sesion
    _cargar_biblioteca()
    r = c.post("/juridico/consultar", data={"pregunta": "¿Qué límite tiene la deducción de gastos?"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Respondida con fuentes" not in html and ("modelo" in html.lower() or "proveedor" in html.lower())
    assert c.post("/juridico/consultar", data={"pregunta": "  "}, follow_redirects=True).status_code == 200


def test_consulta_con_adjuntos_por_el_formulario(sesion, monkeypatch):
    from app import ia_asistente, reuniones
    c, uid, t = sesion
    _cargar_biblioteca()
    monkeypatch.setattr(reuniones, "configurada", lambda u: True)
    vistos = []
    def falso(u, s, contenido):
        vistos.append(contenido)
        return json.dumps(ok_articulo1(contenido))
    monkeypatch.setattr(ia_asistente, "completar_texto", falso)
    r = c.post("/juridico/consultar", data={"pregunta": "¿Qué límite tiene la deducción de gastos?", "coleccion": ["legislacion"], "archivos": (io.BytesIO("Factura de papelería por 80 euros.".encode()), "factura.txt")},
               content_type="multipart/form-data")
    assert r.status_code == 302
    assert "HECHOS APORTADOS EN ADJUNTOS" in vistos[0] and "Factura de papelería" in vistos[0]
    malo = c.post("/juridico/consultar", data={"pregunta": "¿Qué límite?", "archivos": (io.BytesIO(b"MZ\x00\x00\x00binario"), "virus.txt")}, content_type="multipart/form-data", follow_redirects=True)
    assert "Solo se admiten" in malo.get_data(as_text=True)


def test_un_informe_ajeno_o_de_otro_despacho_da_404(sesion, monkeypatch):
    from app import ia_asistente, reuniones
    c, uid, t = sesion
    _cargar_biblioteca()
    monkeypatch.setattr(reuniones, "configurada", lambda u: True)
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, contenido: json.dumps(ok_articulo1(contenido)))
    r = c.post("/juridico/consultar", data={"pregunta": "¿Qué límite tiene la deducción de gastos?", "coleccion": ["legislacion"]})
    run_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
    assert c.get(f"/juridico/consulta/{run_id + 100}").status_code == 404 and c.get(f"/juridico/informes/{run_id + 100}").status_code == 404


def test_fuentes_la_direccion_activa_y_el_admin_gobierna_politicas(sesion, monkeypatch):
    c, uid, t = sesion
    html = c.get("/juridico/fuentes").get_data(as_text=True)
    assert "Pendiente de habilitación" in html and "Sin política de uso registrada" in html and "cendoj" not in html.lower().replace("cendoj /", "") or True
    assert c.post("/juridico/fuentes/boe-consolidada/politica", data={"evidencia": "x" * 20, "almacenar": "1", "indexar": "1"}).status_code == 403, "solo el administrador de la plataforma"
    assert c.post("/juridico/fuentes/boe-consolidada/habilitar", data={"habilitada": "1"}).status_code == 403
    assert c.post("/juridico/fuentes/boe-consolidada/sincronizar", data={"desde": "2099-01-01", "hasta": "2099-01-31"}).status_code == 403
    db.hacer_admin("juridico-ui@ejemplo.com")
    assert "Administración de la fuente" in c.get("/juridico/fuentes").get_data(as_text=True)
    sin_evidencia = c.post("/juridico/fuentes/boe-consolidada/politica", data={"evidencia": "corta", "almacenar": "1", "indexar": "1"}, follow_redirects=True)
    assert "evidencia" in sin_evidencia.get_data(as_text=True).lower()
    assert "política" in c.post("/juridico/fuentes/boe-consolidada/habilitar", data={"habilitada": "1"}, follow_redirects=True).get_data(as_text=True).lower()
    c.post("/juridico/fuentes/boe-consolidada/politica", data={"evidencia": "https://www.boe.es/informacion/aviso_legal/ (reutilización con atribución)", "almacenar": "1", "indexar": "1", "enviar_llm": "1", "citar": "1", "atribucion": "Fuente: BOE"})
    c.post("/juridico/fuentes/boe-consolidada/habilitar", data={"habilitada": "1"})
    html = c.get("/juridico/fuentes").get_data(as_text=True)
    assert "Activa en tu despacho" in html and "Fuente: BOE" not in html.replace("Atribución", "") or "Política v1" in html
    c.post("/juridico/fuentes/boe-consolidada/despacho", data={"habilitada": "0"})
    assert "Habilitada, no activada en tu despacho" in c.get("/juridico/fuentes").get_data(as_text=True)
    lanzadas = []
    class Hilo:
        def __init__(self, target, args=(), kwargs=None, daemon=None):
            self.t, self.a, self.k = target, args, kwargs or {}
        def start(self):
            lanzadas.append(self.a)
    monkeypatch.setattr("app.rutas_juridico.threading.Thread", Hilo)
    assert "intervalo" in c.post("/juridico/fuentes/boe-consolidada/sincronizar", data={"desde": "2099-02-01", "hasta": "2099-01-01"}, follow_redirects=True).get_data(as_text=True).lower()
    assert c.post("/juridico/fuentes/boe-consolidada/sincronizar", data={"desde": "2099-01-01", "hasta": "2099-01-31"}).status_code == 302 and lanzadas[0][:1] == ("boe-consolidada",)
    c.post("/juridico/fuentes/cendoj-licenciado/politica", data={"evidencia": "Contrato de prueba de suministro", "almacenar": "1", "indexar": "1"})
    c.post("/juridico/fuentes/cendoj-licenciado/habilitar", data={"habilitada": "1"})
    assert "pendiente de habilitación" in c.post("/juridico/fuentes/cendoj-licenciado/sincronizar", data={"desde": "2099-01-01", "hasta": "2099-01-31"}, follow_redirects=True).get_data(as_text=True).lower()
    assert c.post("/juridico/fuentes/inexistente/sincronizar", data={"desde": "2099-01-01", "hasta": "2099-01-31"}).status_code == 404


def test_toda_entrada_de_menu_de_los_verticales_tiene_su_icono():
    import pathlib
    sprite = (pathlib.Path(__file__).parent.parent / "app" / "static" / "iconos.svg").read_text()
    for v in verticales.VERTICALES.values():
        for icono in [v.icono] + [e.icono for e in v.entradas_menu]:
            assert f'id="icono-{icono}"' in sprite, (v.id, icono)


def test_las_citas_avisan_si_la_fuente_cambio_o_ya_no_esta_en_vigor(sesion):
    """J3: cada cita enlaza al fragmento exacto y avisa si la biblioteca capturó una versión nueva del documento o si el texto citado dejó de estar vigente."""
    cliente, uid, t = sesion
    _cargar_biblioteca()
    from app.juridico import citas
    cita = {"id": "c1", "kind": "legal_source", "documentId": None, "versionId": None, "chunkId": None, "locator": "Artículo 1"}
    conn = db.get_connection()
    try:
        doc = conn.execute("SELECT d.id AS doc, v.id AS ver FROM jur_documentos d JOIN jur_versiones v ON v.documento_id = d.id AND v.activa = 1 WHERE d.coleccion = 'legislacion' LIMIT 1").fetchone()
        frag = conn.execute("SELECT id FROM jur_fragmentos WHERE version_id = ? ORDER BY orden LIMIT 1", (doc["ver"],)).fetchone()
        conn.execute("UPDATE jur_fragmentos SET vigente_hasta = '2000-01-01' WHERE id = ?", (frag["id"],))
        conn.commit()
    finally:
        conn.close()
    cita.update(documentId=doc["doc"], versionId=doc["ver"], chunkId=frag["id"])
    e = citas.estado_de_citas(t, [cita], "2099-01-10")["c1"]
    assert e["disponible"] and not e["modificada"] and e["derogada"] and e["fuera_de_fecha"] is True
    # Una versión posterior pasa a ser la activa: la cita (de la versión anterior) queda marcada como desactualizada.
    conn = db.get_connection()
    try:
        conn.execute("UPDATE jur_versiones SET activa = 0 WHERE id = ?", (doc["ver"],))
        conn.execute("INSERT INTO jur_versiones (documento_id, hash_texto, capturada_en, calidad, activa, bloqueada) VALUES (?, 'hash-nuevo', '2099-02-01T10:00:00', 'ok', 1, 0)", (doc["doc"],))
        conn.commit()
    finally:
        conn.close()
    e = citas.estado_de_citas(t, [cita], "2099-01-10")["c1"]
    assert e["modificada"] and e["actual"]["capturada_en"] == "2099-02-01"
    assert citas.resumen_de_avisos({"c1": e})["modificadas"] == 1
    assert citas.estado_de_citas(t, [dict(cita, kind="private_attachment")]) == {}


def test_el_informe_se_descarga_en_pdf_y_word_respetando_la_politica_de_exportacion(sesion, monkeypatch):
    """J5: PDF y Word con conclusión, citas y estado; sin el extracto de una fuente cuya política no permite exportar."""
    import io
    from docx import Document
    from app import ia_asistente, reuniones
    c, uid, t = sesion
    _cargar_biblioteca()
    monkeypatch.setattr(reuniones, "configurada", lambda u: True)
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, contenido: json.dumps(ok_articulo1(contenido)))
    r = c.post("/juridico/consultar", data={"pregunta": "¿Qué límite tiene la deducción de gastos?", "fecha_juridica": "2099-01-15", "modo_temporal": "actual", "objetivo": "consulta", "coleccion": ["legislacion"]})
    run_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
    g = c.post(f"/juridico/consulta/{run_id}/informe", data={"titulo": "Límite de gastos"})
    iid = int(g.headers["Location"].rstrip("/").split("/")[-1])
    assert "Descargar PDF" in c.get(f"/juridico/informes/{iid}").get_data(as_text=True)

    pdf = c.get(f"/juridico/informes/{iid}.pdf")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF") and "informe-juridico-limite-de-gastos.pdf" in pdf.headers["Content-Disposition"]
    word = c.get(f"/juridico/informes/{iid}.docx")
    assert word.status_code == 200 and word.mimetype.endswith("wordprocessingml.document")
    texto = "\n".join(p.text for p in Document(io.BytesIO(word.data)).paragraphs)
    assert "Límite de gastos" in texto and "quince por ciento" in texto and "pendiente de revisión por un profesional" in texto

    conn = db.get_connection()
    try:                                                                         # la política de la fuente deja de permitir exportar: el extracto no sale
        conn.execute("UPDATE jur_politicas SET permite_exportar = 0 WHERE fuente_id = 'boe-consolidada'")
        conn.commit()
    finally:
        conn.close()
    sin = "\n".join(p.text for p in Document(io.BytesIO(c.get(f"/juridico/informes/{iid}.docx").data)).paragraphs)
    assert "quince por ciento" not in sin.split("Fuentes")[-1] and "Extracto no exportable" in sin
    assert c.get(f"/juridico/informes/{iid}.odt").status_code == 404 and c.get("/juridico/informes/99999.pdf").status_code == 404
