"""API REST del Asistente jurídico (app/rutas_api_juridico.py) — modelo de IA SIMULADO; corpus SINTÉTICO."""
import io
import json

import pytest

from app import acceso, api_areas, db, verticales
from app.juridico import ingesta
from tests.juridico_ayudas import conector_consolidada, conector_diario, habilitar, transporte_boe
from tests.test_juridico_asistente import ok_articulo1
from tests.test_rutas_api import _auth, _registrar


def _despacho(cliente, email, modulo=True, directivo=True):
    d = _registrar(cliente, email=email)
    u = d["usuario"]["id"]
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(u, t)
    if directivo:
        db.asignar_supervisor_tenant(u, True)
    if modulo:
        verticales.fijar_activo(t, "juridico", True)
    return _auth(d["token"]), t, u


def _cargar():
    habilitar("boe-consolidada")
    habilitar("boe-diario-tc")
    tr = transporte_boe()
    ingesta.sincronizar("boe-consolidada", conector_consolidada(tr), "2099-01-01", "2099-01-31")
    ingesta.sincronizar("boe-diario-tc", conector_diario(tr), "2099-01-10", "2099-01-10")


@pytest.fixture
def ia(monkeypatch):
    from app import ia_asistente
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda u, s, contenido: json.dumps(ok_articulo1(contenido)))


def test_el_area_juridico_existe_y_acota_los_tokens():
    assert api_areas.area_de_ruta("/api/v1/juridico/buscar") == "juridico" and "juridico" in api_areas.AREAS
    assert api_areas.permite(["juridico"], "/api/v1/juridico/colecciones") and not api_areas.permite(["notas"], "/api/v1/juridico/colecciones")


def test_sin_el_modulo_o_apagado_es_404_y_sin_token_401(cliente, monkeypatch):
    h, t, u = _despacho(cliente, "sinmod-ju@ejemplo.com", modulo=False)
    for metodo, ruta in (("get", "/api/v1/juridico/colecciones"), ("post", "/api/v1/juridico/buscar"), ("post", "/api/v1/juridico/conversaciones"), ("get", "/api/v1/juridico/informes")):
        r = getattr(cliente, metodo)(ruta, headers=h, json={}) if metodo == "post" else getattr(cliente, metodo)(ruta, headers=h)
        assert r.status_code == 404 and r.get_json()["codigo"] == "no_encontrado", ruta
    assert cliente.get("/api/v1/juridico/colecciones").status_code == 401
    verticales.fijar_activo(t, "juridico", True)
    assert cliente.get("/api/v1/juridico/colecciones", headers=h).status_code == 200
    monkeypatch.delenv("LEGAL_AI_ENABLED")
    assert cliente.get("/api/v1/juridico/colecciones", headers=h).status_code == 404


def test_colecciones_enseñan_la_cobertura_real_y_lo_no_disponible(cliente):
    h, t, u = _despacho(cliente, "col-ju@ejemplo.com")
    vacio = cliente.get("/api/v1/juridico/colecciones", headers=h).get_json()["data"]
    assert [c["clave"] for c in vacio] == ["legislacion", "jurisprudencia", "doctrina"] and not any(c["disponible"] for c in vacio)
    _cargar()
    c = {x["clave"]: x for x in cliente.get("/api/v1/juridico/colecciones", headers=h).get_json()["data"]}
    assert c["legislacion"]["disponible"] and c["legislacion"]["fuentes"][0]["documentos"] == 2 and c["legislacion"]["fuentes"][0]["ultimo_exito_en"]
    assert c["jurisprudencia"]["fuentes"][0]["documentos"] == 2 and not c["doctrina"]["disponible"]


def test_buscar_documentos_y_versiones_con_fecha_juridica(cliente):
    h, t, u = _despacho(cliente, "bus-ju@ejemplo.com")
    _cargar()
    r = cliente.post("/api/v1/juridico/buscar", headers=h, json={"consulta": "deducción de gastos", "colecciones": ["legislacion"]}).get_json()["data"]
    x = next(y for y in r["resultados"] if y["localizador"] == "Artículo 1")
    assert x["vigente_desde"] == "2022-07-01" and r["modo"] == "texto" and x["capturada_en"]
    old = cliente.post("/api/v1/juridico/buscar", headers=h, json={"consulta": "objeto deducción", "fecha_juridica": "2019-01-01", "colecciones": ["legislacion"]}).get_json()["data"]
    assert old["resultados"] == [] and any("primera versión recogida" in x for x in old["huecos"])
    assert cliente.post("/api/v1/juridico/buscar", headers=h, json={"consulta": "x", "colecciones": ["otra"]}).status_code == 400
    assert cliente.post("/api/v1/juridico/buscar", headers=h, json={"consulta": ""}).status_code == 400
    assert cliente.post("/api/v1/juridico/buscar", headers=h, json={"consulta": "x", "desde": "ayer"}).status_code == 400
    did, vid = x["documento_id"], x["version_id"]
    d = cliente.get(f"/api/v1/juridico/documentos/{did}", headers=h).get_json()["data"]
    assert d["id_externo"] == "BOE-A-2099-0001" and d["versiones"][0]["activa"] == 1 and d["relaciones"]
    v = cliente.get(f"/api/v1/juridico/documentos/{did}/versiones/{vid}?fecha_juridica=2021-06-01", headers=h).get_json()["data"]
    assert "diez" in next(f for f in v["fragmentos"] if f["bloque_id"] == "a1")["texto"]
    assert cliente.get("/api/v1/juridico/documentos/99999", headers=h).status_code == 404
    assert cliente.get(f"/api/v1/juridico/documentos/{did}/versiones/99999", headers=h).status_code == 404


def test_otro_despacho_sin_la_fuente_no_ve_el_documento(cliente):
    h, t, u = _despacho(cliente, "aj-ju@ejemplo.com")
    _cargar()
    from app.juridico import corpus
    corpus.fijar_fuente_despacho(t, "boe-diario-tc", False)
    did = db.get_connection().execute("SELECT id FROM jur_documentos WHERE fuente_id = 'boe-diario-tc' LIMIT 1").fetchone()["id"]
    assert cliente.get(f"/api/v1/juridico/documentos/{did}", headers=h).status_code == 404


def test_consulta_completa_por_api_con_idempotencia_y_informe(cliente, ia):
    h, t, u = _despacho(cliente, "con-ju@ejemplo.com")
    _cargar()
    conv = cliente.post("/api/v1/juridico/conversaciones", headers=h, json={"titulo": "Gastos"})
    assert conv.status_code == 201
    cid = conv.get_json()["data"]["id"]
    cuerpo = {"pregunta": "¿Qué límite tiene la deducción de gastos?", "colecciones": ["legislacion"], "fecha_juridica": "2099-01-15"}
    r = cliente.post(f"/api/v1/juridico/conversaciones/{cid}/ejecuciones", headers={**h, "Idempotency-Key": "k-1"}, json=cuerpo)
    assert r.status_code == 200
    a = r.get_json()["data"]
    assert a["status"] == "answered" and a["claims"][0]["citationIds"] and a["citations"][0]["locator"] == "Artículo 1" and a["citations"][0]["canonicalUrl"] and a["coverage"]["legalAsOf"] == "2099-01-15"
    b = cliente.post(f"/api/v1/juridico/conversaciones/{cid}/ejecuciones", headers={**h, "Idempotency-Key": "k-1"}, json=cuerpo).get_json()["data"]
    assert b == a, "misma clave: misma ejecución, sin repetir el gasto"
    assert cliente.get(f"/api/v1/juridico/ejecuciones/{a['runId']}", headers=h).get_json()["data"] == a
    inf = cliente.post(f"/api/v1/juridico/ejecuciones/{a['runId']}/informe", headers=h, json={"titulo": "Límite"})
    assert inf.status_code == 201 and inf.get_json()["data"]["estado"] == "borrador" and inf.get_json()["data"]["instantanea"]["respuesta"]["citations"][0]["captura"]
    iid = inf.get_json()["data"]["id"]
    assert [i["id"] for i in cliente.get("/api/v1/juridico/informes", headers=h).get_json()["data"]] == [iid]
    rev = cliente.patch(f"/api/v1/juridico/informes/{iid}/revision", headers=h, json={"decision": "revisado"})
    assert rev.status_code == 200 and rev.get_json()["data"]["estado"] == "revisado" and rev.get_json()["data"]["revisado_por"] == u
    assert cliente.get(f"/api/v1/juridico/informes/{iid}", headers=h).get_json()["data"]["instantanea"]["pregunta"].startswith("¿Qué límite")


def test_errores_tipados_de_la_consulta(cliente, ia, monkeypatch):
    h, t, u = _despacho(cliente, "err-ju@ejemplo.com")
    _cargar()
    cid = cliente.post("/api/v1/juridico/conversaciones", headers=h, json={}).get_json()["data"]["id"]
    ruta = f"/api/v1/juridico/conversaciones/{cid}/ejecuciones"
    assert cliente.post(ruta, headers=h, json={"pregunta": " "}).get_json()["codigo"] == "peticion_invalida"
    r = cliente.post(ruta, headers=h, json={"pregunta": "x" * 5000})
    assert r.status_code == 413 and r.get_json()["codigo"] == "consulta_extensa"
    assert cliente.post(ruta, headers=h, json={"pregunta": "hola", "colecciones": ["raras"]}).status_code == 400
    assert cliente.post(ruta, headers=h, json={"pregunta": "hola", "adjunto_ids": ["a"]}).status_code == 400
    assert cliente.post(ruta, headers=h, json={"pregunta": "hola", "adjunto_ids": [424242]}).get_json()["codigo"] == "no_encontrado"
    assert cliente.post("/api/v1/juridico/conversaciones/99999/ejecuciones", headers=h, json={"pregunta": "hola"}).status_code == 404
    assert cliente.get("/api/v1/juridico/ejecuciones/99999", headers=h).status_code == 404
    monkeypatch.setenv("LEGAL_AI_MAX_DIARIO", "0")
    r = cliente.post(ruta, headers=h, json={"pregunta": "deducción de gastos"})
    assert r.status_code == 429 and r.get_json()["codigo"] == "limite_uso"


def test_fallo_del_proveedor_es_503_tipado(cliente, monkeypatch):
    from app import ia_asistente
    def cae(u, s, c):
        raise ia_asistente.ErrorIA("sin modelo")
    monkeypatch.setattr(ia_asistente, "completar_texto", cae)
    h, t, u = _despacho(cliente, "prov-ju@ejemplo.com")
    _cargar()
    cid = cliente.post("/api/v1/juridico/conversaciones", headers=h, json={}).get_json()["data"]["id"]
    r = cliente.post(f"/api/v1/juridico/conversaciones/{cid}/ejecuciones", headers=h, json={"pregunta": "deducción de gastos", "colecciones": ["legislacion"]})
    assert r.status_code == 503 and r.get_json()["codigo"] == "proveedor_no_disponible"


def test_adjuntos_por_api_y_sus_errores(cliente):
    h, t, u = _despacho(cliente, "adj-ju@ejemplo.com")
    r = cliente.post("/api/v1/juridico/adjuntos", headers=h, data={"archivo": (io.BytesIO("Hechos del cliente.".encode()), "hechos.txt")}, content_type="multipart/form-data")
    assert r.status_code == 201 and r.get_json()["data"]["estado"] == "lista"
    aid = r.get_json()["data"]["id"]
    assert cliente.get(f"/api/v1/juridico/adjuntos/{aid}/estado", headers=h).get_json()["data"]["fragmentos"] == 1
    m = cliente.post("/api/v1/juridico/adjuntos", headers=h, data={"archivo": (io.BytesIO(b"MZ\x00\x00\x00binario"), "x.txt")}, content_type="multipart/form-data")
    assert m.status_code == 415 and m.get_json()["codigo"] == "tipo_no_admitido"
    assert cliente.post("/api/v1/juridico/adjuntos", headers=h, data={}, content_type="multipart/form-data").status_code == 400
    assert cliente.post("/api/v1/juridico/adjuntos", headers=h, data={"archivo": (io.BytesIO(b"hola"), "a.txt"), "cliente_id": "99999"}, content_type="multipart/form-data").get_json()["codigo"] == "no_encontrado"
    otro_h, _t2, _u2 = _despacho(cliente, "adj2-ju@ejemplo.com")
    assert cliente.get(f"/api/v1/juridico/adjuntos/{aid}/estado", headers=otro_h).status_code == 404
    assert cliente.delete(f"/api/v1/juridico/adjuntos/{aid}", headers=otro_h).status_code == 404
    assert cliente.delete(f"/api/v1/juridico/adjuntos/{aid}", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/juridico/adjuntos/{aid}/estado", headers=h).status_code == 404


def test_una_consulta_y_un_informe_ajenos_no_se_ven_ni_con_el_id(cliente, ia):
    h1, t1, u1 = _despacho(cliente, "uno-ju@ejemplo.com")
    h2, t2, u2 = _despacho(cliente, "dos-ju@ejemplo.com")
    _cargar()
    cid = cliente.post("/api/v1/juridico/conversaciones", headers=h1, json={}).get_json()["data"]["id"]
    a = cliente.post(f"/api/v1/juridico/conversaciones/{cid}/ejecuciones", headers=h1, json={"pregunta": "deducción de gastos límite", "colecciones": ["legislacion"]}).get_json()["data"]
    iid = cliente.post(f"/api/v1/juridico/ejecuciones/{a['runId']}/informe", headers=h1, json={}).get_json()["data"]["id"]
    assert cliente.get(f"/api/v1/juridico/ejecuciones/{a['runId']}", headers=h2).status_code == 404
    assert cliente.post(f"/api/v1/juridico/ejecuciones/{a['runId']}/informe", headers=h2, json={}).status_code == 404
    assert cliente.get(f"/api/v1/juridico/informes/{iid}", headers=h2).status_code == 404
    assert cliente.patch(f"/api/v1/juridico/informes/{iid}/revision", headers=h2, json={"decision": "revisado"}).status_code == 404
    assert cliente.post(f"/api/v1/juridico/conversaciones/{cid}/ejecuciones", headers=h2, json={"pregunta": "hola"}).status_code == 404
    assert cliente.get("/api/v1/juridico/informes", headers=h2).get_json()["data"] == []


def test_un_miembro_no_revisa_y_el_auditor_no_consulta(cliente, ia):
    h, t, u = _despacho(cliente, "dir2-ju@ejemplo.com")
    _cargar()
    d = _registrar(cliente, email="miembro-ju@ejemplo.com")
    db.asignar_tenant(d["usuario"]["id"], t)
    hm = _auth(d["token"])
    cid = cliente.post("/api/v1/juridico/conversaciones", headers=hm, json={}).get_json()["data"]["id"]
    a = cliente.post(f"/api/v1/juridico/conversaciones/{cid}/ejecuciones", headers=hm, json={"pregunta": "deducción de gastos límite", "colecciones": ["legislacion"]}).get_json()["data"]
    iid = cliente.post(f"/api/v1/juridico/ejecuciones/{a['runId']}/informe", headers=hm, json={}).get_json()["data"]["id"]
    r = cliente.patch(f"/api/v1/juridico/informes/{iid}/revision", headers=hm, json={"decision": "revisado"})
    assert r.status_code == 403 and r.get_json()["codigo"] == "permiso"
    au = _registrar(cliente, email="auditor-ju@ejemplo.com")
    db.asignar_tenant(au["usuario"]["id"], t)
    acceso.dar_membresia(t, u, au["usuario"]["id"], "auditor", "organizacion")
    ha = _auth(au["token"])
    cida = cliente.post("/api/v1/juridico/conversaciones", headers=ha, json={}).get_json()["data"]["id"]
    r = cliente.post(f"/api/v1/juridico/conversaciones/{cida}/ejecuciones", headers=ha, json={"pregunta": "hola"})
    assert r.status_code == 403 and r.get_json()["codigo"] == "permiso"


def test_diagnostico_de_fuentes_solo_para_el_administrador(cliente):
    h, t, u = _despacho(cliente, "adm-ju@ejemplo.com")
    assert cliente.get("/api/v1/juridico/admin/fuentes", headers=h).status_code == 403
    db.hacer_admin("adm-ju@ejemplo.com")
    _cargar()
    fuentes = {f["id"]: f for f in cliente.get("/api/v1/juridico/admin/fuentes", headers=h).get_json()["data"]}
    assert fuentes["boe-consolidada"]["habilitada"] and fuentes["boe-consolidada"]["politica"]["version"] == 1 and fuentes["boe-consolidada"]["cobertura"]["documentos"] == 2
    assert fuentes["cendoj-licenciado"]["habilitada"] is False and "Solo el contrato" in fuentes["cendoj-licenciado"]["verificacion"]


def test_el_openapi_documenta_el_asistente_juridico(base_de_datos_temporal):
    from app import openapi
    from app.main import app as flask_app
    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    with flask_app.test_request_context():
        spec = openapi.generar_spec()
    rutas = [r for r in spec["paths"] if r.startswith("/api/v1/juridico")]
    assert len(rutas) >= 12, rutas
    cuerpo = spec["paths"]["/api/v1/juridico/conversaciones/{conversacion_id}/ejecuciones"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert cuerpo["required"] == ["pregunta"] and cuerpo["properties"]["adjunto_ids"]["type"] == "array" and cuerpo["properties"]["modo_temporal"]["enum"] == ["actual", "historico"]
    assert "juridico" in [t["name"] for t in spec["tags"]]
