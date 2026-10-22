"""API REST del módulo Comercial (app/rutas_api_comercial.py): oportunidades, embudo, actividades y reuniones con acta. Mismas reglas que la web."""
import json

import pytest

from app import acceso, api_areas, comercial as co, db, ia_asistente, nucleo, reuniones as ru, verticales
from tests.test_rutas_api import _auth, _registrar

ACTA = {"resumen": "Se acordó empezar en enero.", "temas": ["Alcance"], "decisiones": ["Empezar en enero"], "tareas": [{"texto": "Enviar la propuesta", "responsable": "", "fecha": "2026-11-03"}], "proximos_pasos": ["Seguimiento"]}


def _despacho(cliente, email, modulo=True):
    d = _registrar(cliente, email=email)
    u = d["usuario"]["id"]
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(u, t)
    db.asignar_supervisor_tenant(u, True)
    if modulo:
        verticales.fijar_activo(t, "comercial", True)
    return _auth(d["token"]), t, u


def _oportunidad(cliente, h, **kw):
    r = cliente.post("/api/v1/comercial/oportunidades", json={"titulo": "Contabilidad", "contacto_nombre": "Ana", "empresa": "Panadería Sol", "importe": "1.200,50", **kw}, headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["data"]


def test_el_area_comercial_existe_y_acota_los_tokens():
    assert api_areas.area_de_ruta("/api/v1/comercial/oportunidades") == "comercial" and "comercial" in api_areas.AREAS
    assert api_areas.permite(["comercial"], "/api/v1/comercial/embudo") and not api_areas.permite(["notas"], "/api/v1/comercial/embudo")


def test_sin_el_modulo_es_404_y_sin_token_401(cliente):
    h, _t, _u = _despacho(cliente, "sinmod-co@ejemplo.com", modulo=False)
    for ruta in ("/api/v1/comercial/oportunidades", "/api/v1/comercial/embudo", "/api/v1/comercial/reuniones", "/api/v1/comercial/etapas"):
        r = cliente.get(ruta, headers=h)
        assert r.status_code == 404 and r.get_json()["codigo"] == "no_encontrado", ruta
        assert cliente.get(ruta).status_code == 401
    assert cliente.post("/api/v1/comercial/oportunidades", json={"titulo": "x", "empresa": "y"}, headers=h).status_code == 404


def test_oportunidad_de_principio_a_fin(cliente):
    h, t, u = _despacho(cliente, "ciclo-co@ejemplo.com")
    etapas = cliente.get("/api/v1/comercial/etapas", headers=h).get_json()["data"]
    assert [e["clave"] for e in etapas][:2] == ["nuevo", "contactado"] and "ganada" in [e["clave"] for e in etapas]
    o = _oportunidad(cliente, h, notas="Viene por recomendación")
    assert o["etapa"] == "nuevo" and o["estado"] == "abierta" and o["importe_centimos"] == 120050
    assert cliente.post("/api/v1/comercial/oportunidades", json={"empresa": "x"}, headers=h).status_code == 400
    assert cliente.post("/api/v1/comercial/oportunidades", json={"titulo": "sin quién"}, headers=h).status_code == 400
    oid = o["id"]
    e = cliente.patch(f"/api/v1/comercial/oportunidades/{oid}", json={"titulo": "Contabilidad y fiscal", "cierre_previsto": "2026-12-15"}, headers=h)
    assert e.status_code == 200 and e.get_json()["data"]["titulo"] == "Contabilidad y fiscal" and e.get_json()["data"]["cierre_previsto"] == "2026-12-15"
    assert cliente.patch(f"/api/v1/comercial/oportunidades/{oid}", json={"cierre_previsto": "ayer"}, headers=h).status_code == 400
    m = cliente.put(f"/api/v1/comercial/oportunidades/{oid}/etapa", json={"etapa": "propuesta"}, headers=h)
    assert m.status_code == 200 and m.get_json()["data"]["etapa"] == "propuesta"
    assert cliente.put(f"/api/v1/comercial/oportunidades/{oid}/etapa", json={"etapa": "perdida"}, headers=h).status_code == 400, "perder exige motivo"
    assert cliente.put(f"/api/v1/comercial/oportunidades/{oid}/etapa", json={"etapa": "no_existe"}, headers=h).status_code == 400
    assert cliente.put(f"/api/v1/comercial/oportunidades/{oid}/etapa", json={}, headers=h).status_code == 400
    a = cliente.post(f"/api/v1/comercial/oportunidades/{oid}/actividades", json={"tipo": "llamada", "asunto": "Primera llamada", "proxima_accion": "Enviar la propuesta", "proxima_fecha": "2026-11-03"}, headers=h)
    assert a.status_code == 201 and a.get_json()["data"]["id"]
    assert cliente.post(f"/api/v1/comercial/oportunidades/{oid}/actividades", json={"tipo": "llamada"}, headers=h).status_code == 400
    assert cliente.post(f"/api/v1/comercial/oportunidades/{oid}/actividades", json={"tipo": "telepatia", "asunto": "x"}, headers=h).status_code == 400
    ficha = cliente.get(f"/api/v1/comercial/oportunidades/{oid}", headers=h).get_json()["data"]
    assert ficha["id"] == oid and any(c["asunto"] == "Primera llamada" for c in ficha["cronologia"])
    lista = cliente.get("/api/v1/comercial/oportunidades?q=Panadería", headers=h)
    assert [x["id"] for x in lista.get_json()["data"]] == [oid] and lista.headers["X-Total-Count"] == "1"
    assert cliente.get("/api/v1/comercial/oportunidades?etapa=nuevo", headers=h).get_json()["data"] == []
    emb = cliente.get("/api/v1/comercial/embudo", headers=h).get_json()["data"]
    assert emb["abiertas"]["n"] == 1 and emb["tasa_exito"] is None and emb["abiertas"]["importe"] == 1200.5
    c = cliente.post(f"/api/v1/comercial/oportunidades/{oid}/convertir", json={"nif": "B12345678"}, headers=h)
    assert c.status_code == 201 and c.get_json()["data"]["cliente_id"]
    final = cliente.get(f"/api/v1/comercial/oportunidades/{oid}", headers=h).get_json()["data"]
    assert final["estado"] == "ganada" and final["cliente_id"] == c.get_json()["data"]["cliente_id"]
    assert cliente.post(f"/api/v1/comercial/oportunidades/{oid}/convertir", json={}, headers=h).status_code == 400, "ya es cliente"
    assert cliente.delete(f"/api/v1/comercial/oportunidades/{oid}", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/comercial/oportunidades/{oid}", headers=h).status_code == 404
    assert cliente.get("/api/v1/comercial/oportunidades?estado=todas", headers=h).get_json()["data"] == []


def test_perder_con_motivo_y_el_embudo_cuenta_el_cierre(cliente):
    h, _t, _u = _despacho(cliente, "perdida-co@ejemplo.com")
    oid = _oportunidad(cliente, h)["id"]
    r = cliente.put(f"/api/v1/comercial/oportunidades/{oid}/etapa", json={"etapa": "perdida", "motivo": "Precio"}, headers=h)
    assert r.status_code == 200 and r.get_json()["data"]["estado"] == "perdida" and r.get_json()["data"]["motivo_perdida"] == "Precio"
    assert [x["id"] for x in cliente.get("/api/v1/comercial/oportunidades?estado=perdida", headers=h).get_json()["data"]] == [oid]
    assert cliente.get("/api/v1/comercial/oportunidades", headers=h).get_json()["data"] == []
    assert cliente.get("/api/v1/comercial/embudo?desde=2000-01-01&hasta=2999-01-01", headers=h).status_code == 200
    assert cliente.get("/api/v1/comercial/embudo?desde=ayer", headers=h).status_code == 400


def test_un_despacho_ajeno_no_ve_ni_toca(cliente):
    h1, _t1, _u1 = _despacho(cliente, "uno-co@ejemplo.com")
    h2, _t2, _u2 = _despacho(cliente, "dos-co@ejemplo.com")
    oid = _oportunidad(cliente, h1)["id"]
    rid = cliente.post("/api/v1/comercial/reuniones", json={"titulo": "Reunión", "plantilla": "comercial", "oportunidad_id": oid}, headers=h1).get_json()["data"]["id"]
    assert cliente.get("/api/v1/comercial/oportunidades", headers=h2).get_json()["data"] == []
    for metodo, ruta, cuerpo in (("get", f"/oportunidades/{oid}", None), ("patch", f"/oportunidades/{oid}", {"titulo": "x"}), ("put", f"/oportunidades/{oid}/etapa", {"etapa": "contactado"}),
                                 ("post", f"/oportunidades/{oid}/actividades", {"tipo": "nota", "asunto": "x"}), ("post", f"/oportunidades/{oid}/convertir", {}), ("delete", f"/oportunidades/{oid}", None),
                                 ("get", f"/reuniones/{rid}", None), ("patch", f"/reuniones/{rid}", {"titulo": "x"}), ("delete", f"/reuniones/{rid}", None)):
        r = getattr(cliente, metodo)("/api/v1/comercial" + ruta, headers=h2, **({"json": cuerpo} if cuerpo is not None else {}))
        assert r.status_code == 404, (metodo, ruta, r.status_code)
    assert cliente.get(f"/api/v1/comercial/oportunidades/{oid}", headers=h1).status_code == 200


def test_el_auditor_solo_lee_por_api(cliente):
    h, t, u = _despacho(cliente, "dir-aud-co@ejemplo.com")
    oid = _oportunidad(cliente, h)["id"]
    d = _registrar(cliente, email="auditor-co@ejemplo.com")
    db.asignar_tenant(d["usuario"]["id"], t)
    acceso.dar_membresia(t, u, d["usuario"]["id"], "auditor", "organizacion")
    ha = _auth(d["token"])
    assert cliente.get(f"/api/v1/comercial/oportunidades/{oid}", headers=ha).status_code == 200
    assert cliente.get("/api/v1/comercial/embudo", headers=ha).status_code == 200
    for metodo, ruta, cuerpo in (("post", "/oportunidades", {"titulo": "x", "empresa": "y"}), ("patch", f"/oportunidades/{oid}", {"titulo": "x"}), ("put", f"/oportunidades/{oid}/etapa", {"etapa": "contactado"}),
                                 ("post", f"/oportunidades/{oid}/actividades", {"tipo": "nota", "asunto": "x"}), ("delete", f"/oportunidades/{oid}", None), ("post", "/reuniones", {"titulo": "x"})):
        r = getattr(cliente, metodo)("/api/v1/comercial" + ruta, headers=ha, **({"json": cuerpo} if cuerpo is not None else {}))
        assert r.status_code == 403 and r.get_json()["codigo"] == "prohibido", (metodo, ruta, r.status_code)
    assert cliente.get(f"/api/v1/comercial/oportunidades/{oid}", headers=h).get_json()["data"]["titulo"] == "Contabilidad"


def test_reunion_notas_transcripcion_y_acta(cliente, monkeypatch):
    h, t, u = _despacho(cliente, "reunion-co@ejemplo.com")
    monkeypatch.setattr(ru, "configurada", lambda uid: False)
    rid = cliente.post("/api/v1/comercial/reuniones", json={"titulo": "Revisión", "plantilla": "cliente", "participantes": "Ana, Luis", "notas": "Quiere empezar en enero"}, headers=h).get_json()["data"]["id"]
    assert cliente.post("/api/v1/comercial/reuniones", json={}, headers=h).status_code == 400
    assert cliente.post("/api/v1/comercial/reuniones", json={"titulo": "x", "plantilla": "rara"}, headers=h).status_code == 400
    ficha = cliente.get(f"/api/v1/comercial/reuniones/{rid}", headers=h).get_json()["data"]
    assert ficha["notas"] == "Quiere empezar en enero" and ficha["acta"] is None and ficha["tiene_transcripcion"] is False
    assert cliente.patch(f"/api/v1/comercial/reuniones/{rid}", json={"titulo": "Revisión trimestral", "fecha": "2026-10-22"}, headers=h).get_json()["data"]["titulo"] == "Revisión trimestral"
    assert cliente.patch(f"/api/v1/comercial/reuniones/{rid}", json={"fecha": "ayer"}, headers=h).status_code == 400
    sin_aviso = cliente.put(f"/api/v1/comercial/reuniones/{rid}/transcripcion", json={"texto": "Hola"}, headers=h)
    assert sin_aviso.status_code == 400
    ok = cliente.put(f"/api/v1/comercial/reuniones/{rid}/transcripcion", json={"texto": "SECRETO-DE-LA-TRANSCRIPCION", "aviso_grabacion": True}, headers=h)
    assert ok.status_code == 200
    for ruta in (f"/api/v1/comercial/reuniones/{rid}", "/api/v1/comercial/reuniones"):
        cuerpo = cliente.get(ruta, headers=h).get_data(as_text=True)
        assert "SECRETO-DE-LA-TRANSCRIPCION" not in cuerpo and "transcripcion\"" not in cuerpo.replace("tiene_transcripcion", ""), ruta
    assert cliente.get(f"/api/v1/comercial/reuniones/{rid}", headers=h).get_json()["data"]["tiene_transcripcion"] is True
    sin_ia = cliente.post(f"/api/v1/comercial/reuniones/{rid}/acta", headers=h)
    assert sin_ia.status_code == 409 and sin_ia.get_json()["codigo"] == "ia_no_configurada"
    monkeypatch.setattr(ru, "configurada", lambda uid: True)
    monkeypatch.setattr(ia_asistente, "completar_texto", lambda uid, s, c: json.dumps(ACTA))
    g = cliente.post(f"/api/v1/comercial/reuniones/{rid}/acta", headers=h)
    assert g.status_code == 200 and g.get_json()["data"]["acta"]["resumen"] == ACTA["resumen"]
    assert cliente.delete(f"/api/v1/comercial/reuniones/{rid}/transcripcion", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/comercial/reuniones/{rid}", headers=h).get_json()["data"]["tiene_transcripcion"] is False
    assert cliente.get(f"/api/v1/comercial/reuniones/{rid}", headers=h).get_json()["data"]["acta"]["tareas"][0]["texto"] == "Enviar la propuesta"
    assert cliente.post(f"/api/v1/comercial/reuniones/{rid}/tareas", json={}, headers=h).status_code == 400
    assert cliente.post(f"/api/v1/comercial/reuniones/{rid}/tareas", json={"tareas": [{"indice": 9}]}, headers=h).status_code == 400
    c = cliente.post(f"/api/v1/comercial/reuniones/{rid}/tareas", json={"tareas": [{"indice": 0, "responsable_id": u, "fecha": "2026-11-03"}]}, headers=h)
    assert c.status_code == 201 and len(c.get_json()["data"]["tarea_ids"]) == 1
    manual = cliente.put(f"/api/v1/comercial/reuniones/{rid}/acta", json={"resumen": "Corregido a mano", "decisiones": [], "tareas": [], "proximos_pasos": []}, headers=h)
    assert manual.status_code == 200 and manual.get_json()["data"]["acta"]["resumen"] == "Corregido a mano"
    assert cliente.delete(f"/api/v1/comercial/reuniones/{rid}", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/comercial/reuniones/{rid}", headers=h).status_code == 404


def test_una_reunion_interna_solo_la_ve_quien_la_creo_y_la_direccion(cliente):
    h, t, u = _despacho(cliente, "interna-co@ejemplo.com")
    otro = db.crear_usuario_vinculado_a_kratos("otro-co@ejemplo.com", "k-otro-co")
    db.asignar_tenant(otro, t)
    rid = ru.crear(t, otro, "Reunión interna del equipo", plantilla="interna")
    assert [r["id"] for r in cliente.get("/api/v1/comercial/reuniones", headers=h).get_json()["data"]] == [rid], "la dirección la ve"
    ajeno = db.crear_usuario_vinculado_a_kratos("ajeno-co@ejemplo.com", "k-ajeno-co")
    db.asignar_tenant(ajeno, t)
    assert ru.obtener(t, ajeno, rid) is None


def test_el_openapi_documenta_el_comercial_con_sus_cuerpos(base_de_datos_temporal):
    from app import openapi
    from app.main import app as flask_app
    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    with flask_app.test_request_context():
        spec = openapi.generar_spec()
    rutas = [r for r in spec["paths"] if r.startswith("/api/v1/comercial")]
    assert len(rutas) >= 12, rutas
    crear = spec["paths"]["/api/v1/comercial/oportunidades"]["post"]
    cuerpo = crear["requestBody"]["content"]["application/json"]["schema"]
    assert "titulo" in cuerpo["properties"] and cuerpo.get("required") == ["titulo"], cuerpo
    assert "aviso_grabacion" in spec["paths"]["/api/v1/comercial/reuniones/{reunion_id}/transcripcion"]["put"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "comercial" in [t["name"] for t in spec["tags"]]
