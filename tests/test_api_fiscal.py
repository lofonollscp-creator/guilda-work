"""API fiscal completa (`app/rutas_api_fiscal.py`) y correcciones de paridad de la API fiscal existente."""
import io
from datetime import date

import pytest

from app import db, eventos
from tests.test_rutas_api import _auth, _registrar


def _despacho(cliente, email, supervisor=False, tenant_id=None):
    datos = _registrar(cliente, email=email)
    uid = datos["usuario"]["id"]
    t = tenant_id or db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    if supervisor:
        conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    return _auth(datos["token"]), uid, t


def _cliente_fiscal(cliente, h, nombre="Acme SL", **extra):
    return cliente.post("/api/v1/fiscal/clientes", json={"nombre": nombre, "modelos_fiscales": ["303", "130"], **extra}, headers=h).get_json()["data"]["id"]


def _venc(cliente, h, cid, modelo="303", periodo="3T 2030", fecha="2030-10-20"):
    return cliente.post("/api/v1/fiscal/vencimientos", json={"cliente_id": cid, "modelo": modelo, "periodo": periodo, "fecha_limite": fecha}, headers=h)


def test_generar_no_duplica_usa_modelos_del_cliente_y_valida(cliente):
    h, _, _ = _despacho(cliente, "g@ejemplo.com")
    cid = _cliente_fiscal(cliente, h)
    r1 = cliente.post(f"/api/v1/fiscal/clientes/{cid}/generar-vencimientos", json={"anio": 2031}, headers=h)            # sin `modelos`: los del cliente
    assert r1.status_code == 201 and r1.get_json()["data"]["creados"] > 0 and r1.get_json()["data"]["omitidos"] == 0
    r2 = cliente.post(f"/api/v1/fiscal/clientes/{cid}/generar-vencimientos", json={"anio": 2031}, headers=h).get_json()["data"]
    assert r2["creados"] == 0 and r2["omitidos"] == r1.get_json()["data"]["creados"]                                       # idempotente
    assert cliente.post(f"/api/v1/fiscal/clientes/{cid}/generar-vencimientos", json={"anio": 31}, headers=h).get_json()["campo"] == "anio"
    ver = cliente.get(f"/api/v1/fiscal/vencimientos/propuestas?cliente_id={cid}&anio=2031", headers=h).get_json()["data"]
    assert ver and all(p["ya_existe"] for p in ver)
    assert not any(p["ya_existe"] for p in cliente.get(f"/api/v1/fiscal/vencimientos/propuestas?cliente_id={cid}&anio=2032", headers=h).get_json()["data"])
    masivo = cliente.post("/api/v1/fiscal/vencimientos/generar-masivo", json={"anio": 2032}, headers=h).get_json()["data"]
    assert masivo["creados"] > 0 and cliente.post("/api/v1/fiscal/vencimientos/generar-masivo", json={"anio": 2032}, headers=h).get_json()["data"]["creados"] == 0


def test_alta_manual_detalle_y_filtros_con_paginacion_en_sql(cliente):
    h, _, t = _despacho(cliente, "a@ejemplo.com")
    cid = _cliente_fiscal(cliente, h)
    r = _venc(cliente, h, cid)
    assert r.status_code == 201
    vid = r.get_json()["data"]["id"]
    assert _venc(cliente, h, cid).get_json()["codigo"] == "vencimiento_duplicado"
    assert _venc(cliente, h, cid, fecha="no-fecha").get_json()["campo"] == "fecha_limite"
    assert cliente.post("/api/v1/fiscal/vencimientos", json={"cliente_id": 9999, "modelo": "303", "periodo": "x", "fecha_limite": "2030-01-01"}, headers=h).status_code == 404
    assert cliente.post("/api/v1/fiscal/vencimientos", json={"cliente_id": cid, "modelo": "111", "periodo": "x", "fecha_limite": "2030-01-01", "usuario_id": 99999}, headers=h).get_json()["campo"] == "usuario_id"
    for i, f in enumerate(("2030-11-05", "2030-12-05", "2031-01-05")):
        _venc(cliente, h, cid, modelo="115", periodo=f"P{i}", fecha=f)
    d = cliente.get(f"/api/v1/fiscal/vencimientos/{vid}", headers=h).get_json()["data"]
    assert d["documentos"] == 0 and d["tiene_constancia"] is False and d["cliente_nombre"] == "Acme SL"
    r = cliente.get("/api/v1/fiscal/vencimientos?limit=2&offset=1", headers=h)
    assert len(r.get_json()["data"]) == 2 and r.headers["X-Total-Count"] == "4"
    assert len(cliente.get("/api/v1/fiscal/vencimientos?desde=2030-11-01&hasta=2030-12-31", headers=h).get_json()["data"]) == 2
    assert cliente.get("/api/v1/fiscal/vencimientos?desde=2030-11-01&hasta=2030-12-31", headers=h).headers["X-Total-Count"] == "2"
    assert cliente.get("/api/v1/fiscal/vencimientos?pais=FR", headers=h).get_json()["data"] == []
    assert len(cliente.get("/api/v1/fiscal/vencimientos?estado=pendiente", headers=h).get_json()["data"]) == 4
    assert cliente.get("/api/v1/fiscal/modelos", headers=h).get_json()["data"]["modelos"]


def test_presentado_igual_que_la_web_constancia_justificante_y_evento(cliente):
    h, _, t = _despacho(cliente, "p@ejemplo.com")
    wh = db.crear_webhook(1, t, "https://hooks.example/h", ["vencimiento.presentado"])
    cid = _cliente_fiscal(cliente, h)
    vid = _venc(cliente, h, cid).get_json()["data"]["id"]
    pdf = (io.BytesIO(b"%PDF-1.4 justificante"), "justificante.pdf")
    r = cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/presentado", data={"justificante": (pdf[0], pdf[1], "application/pdf")}, headers=h, content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["data"]["estado"] == "presentado"
    docs = cliente.get(f"/api/v1/fiscal/vencimientos/{vid}/documentos", headers=h).get_json()["data"]
    assert {d["origen"] for d in docs} == {"constancia", "justificante"}
    assert [c["evento"] for c in db.cola_webhook_de(wh["id"])] == ["vencimiento.presentado"]                                  # la API ahora emite el evento
    d = cliente.get(f"/api/v1/fiscal/vencimientos/{vid}", headers=h).get_json()["data"]
    assert d["tiene_constancia"] and d["tiene_justificante"]
    just = next(x for x in docs if x["origen"] == "justificante")
    bajada = cliente.get(f"/api/v1/fiscal/vencimientos/{vid}/documentos/{just['id']}", headers=h)
    assert bajada.status_code == 200 and bajada.data == b"%PDF-1.4 justificante" and "attachment" in bajada.headers["Content-Disposition"]
    assert cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/constancia", headers=h).status_code == 201
    assert len([x for x in cliente.get(f"/api/v1/fiscal/vencimientos/{vid}/documentos", headers=h).get_json()["data"] if x["origen"] == "constancia"]) == 1
    malo = cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/justificante", data={"justificante": (io.BytesIO(b"<html>"), "x.html", "text/html")}, headers=h, content_type="multipart/form-data")
    assert malo.status_code == 400 and malo.get_json()["codigo"] == "justificante_invalido"
    assert cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/justificante", data={"justificante": (io.BytesIO(b"%PDF-1.4 otro"), "o.pdf", "application/pdf")}, headers=h, content_type="multipart/form-data").status_code == 201


def test_expediente_documental_y_registro_de_accesos(cliente):
    h, _, t = _despacho(cliente, "e@ejemplo.com", supervisor=True)
    otro, _, _ = _despacho(cliente, "e2@ejemplo.com")
    cid = _cliente_fiscal(cliente, h)
    assert cliente.post(f"/api/v1/fiscal/clientes/{cid}/documentos", headers=h, data={}, content_type="multipart/form-data").get_json()["codigo"] == "sin_archivos"
    r = cliente.post(f"/api/v1/fiscal/clientes/{cid}/documentos", headers=h, content_type="multipart/form-data",
                     data={"archivo": [(io.BytesIO(b"extracto enero"), "enero.txt", "text/plain"), (io.BytesIO(b""), "vacio.txt", "text/plain")], "categoria": "Extractos"})
    assert r.status_code == 201 and [x["resultado"] for x in r.get_json()["data"]] == ["ok", "vacio"]
    dup = cliente.post(f"/api/v1/fiscal/clientes/{cid}/documentos", headers=h, content_type="multipart/form-data", data={"archivo": (io.BytesIO(b"extracto enero"), "enero.txt", "text/plain")})
    assert dup.get_json()["data"][0]["resultado"] == "duplicado" and dup.status_code == 200
    docs = cliente.get(f"/api/v1/fiscal/clientes/{cid}/documentos", headers=h).get_json()["data"]
    assert len(docs) == 1 and docs[0]["categoria"] == "Extractos" and "contenido" not in docs[0]
    bajada = cliente.get(f"/api/v1/fiscal/clientes/{cid}/documentos/{docs[0]['id']}", headers=h)
    assert bajada.data == b"extracto enero" and bajada.headers["X-Content-Type-Options"] == "nosniff"
    html = cliente.post(f"/api/v1/fiscal/clientes/{cid}/documentos", headers=h, content_type="multipart/form-data", data={"archivo": (io.BytesIO(b"<script>x</script>"), "a.html", "text/html")}).get_json()["data"][0]
    peligroso = cliente.get(f"/api/v1/fiscal/clientes/{cid}/documentos/{html['id']}", headers=h)
    assert peligroso.mimetype == "application/octet-stream"                                                                   # nunca se sirve como página
    assert cliente.get(f"/api/v1/fiscal/clientes/{cid}/documentos", headers=otro).status_code == 404                           # otro despacho
    assert cliente.get(f"/api/v1/fiscal/clientes/{cid}/documentos/{docs[0]['id']}", headers=otro).status_code == 404
    assert cliente.delete(f"/api/v1/fiscal/clientes/{cid}/documentos/{docs[0]['id']}", headers=otro).status_code == 404
    cliente.get(f"/api/v1/fiscal/clientes/{cid}", headers=h)
    cliente.put(f"/api/v1/fiscal/clientes/{cid}", json={"notas": "x"}, headers=h)
    assert cliente.delete(f"/api/v1/fiscal/clientes/{cid}/documentos/{docs[0]['id']}", headers=h).status_code == 200
    acciones = [a["accion"] for a in cliente.get(f"/api/v1/fiscal/clientes/{cid}/accesos", headers=h).get_json()["data"]]
    assert {"documento_subido", "documento_descargado", "documento_eliminado", "ficha_vista", "cliente_editado"} <= set(acciones)
    detalles = [a["detalle"] for a in cliente.get(f"/api/v1/fiscal/clientes/{cid}/accesos", headers=h).get_json()["data"]]
    assert all("vía API" in d for d in detalles if d)
    sin_super, _, _ = _despacho(cliente, "e3@ejemplo.com", tenant_id=t)
    assert cliente.get(f"/api/v1/fiscal/clientes/{cid}/accesos", headers=sin_super).status_code == 403                          # solo supervisores


def test_mensajes_con_el_cliente_y_aviso_por_correo(cliente, monkeypatch):
    h, _, t = _despacho(cliente, "m@ejemplo.com")
    enviados = []
    monkeypatch.setattr("app.notificaciones_email.enviar_respuesta_portal", lambda email, texto, url: enviados.append((email, texto)))
    cid = _cliente_fiscal(cliente, h, email="cliente@acme.com")
    vid = _venc(cliente, h, cid).get_json()["data"]["id"]
    db.crear_mensaje_vencimiento(vid, "cliente", "¿Qué falta?")
    assert [m["autor"] for m in cliente.get(f"/api/v1/fiscal/vencimientos/{vid}/mensajes", headers=h).get_json()["data"]] == ["cliente"]
    assert cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/mensajes", json={"texto": " "}, headers=h).get_json()["codigo"] == "mensaje_vacio"
    r = cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/mensajes", json={"texto": "Falta el extracto"}, headers=h)
    assert r.status_code == 201 and r.get_json()["data"]["cliente_avisado_por_correo"] is True and enviados == [("cliente@acme.com", "Falta el extracto")]
    assert [m["autor"] for m in r.get_json()["data"]["mensajes"]] == ["cliente", "empleado"]
    otro, _, _ = _despacho(cliente, "m2@ejemplo.com")
    assert cliente.get(f"/api/v1/fiscal/vencimientos/{vid}/mensajes", headers=otro).status_code == 404
    assert cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/mensajes", json={"texto": "x"}, headers=otro).status_code == 404


def test_pedir_un_documento_avisa_al_cliente_como_la_web(cliente, monkeypatch):
    h, _, _ = _despacho(cliente, "d@ejemplo.com")
    avisos = []
    monkeypatch.setattr("app.notificaciones_email.enviar_solicitud_documento", lambda email, desc, url: avisos.append((email, desc)))
    cid = _cliente_fiscal(cliente, h, email="c@acme.com")
    vid = _venc(cliente, h, cid).get_json()["data"]["id"]
    cliente.put(f"/api/v1/fiscal/vencimientos/{vid}", json={"documento_solicitado": "extractos de junio"}, headers=h)
    cliente.put(f"/api/v1/fiscal/vencimientos/{vid}", json={"documento_solicitado": "extractos de junio", "notas": "otra cosa"}, headers=h)    # sin cambio: no repite
    assert avisos == [("c@acme.com", "extractos de junio")]


def test_recordatorios_del_portal(cliente):
    h, _, _ = _despacho(cliente, "r@ejemplo.com")
    c = cliente.get("/api/v1/fiscal/recordatorios", headers=h).get_json()["data"]
    assert c["dias_antes"] and "cliente" in c["marcas"] and c["max_avisos_antes"]
    r = cliente.put("/api/v1/fiscal/recordatorios", json={"dias_antes": [10, 3, 1], "dias_despues": [2], "avisar_equipo": True}, headers=h).get_json()["data"]
    assert r["dias_antes"] == [10, 3, 1] and r["dias_despues"] == [2] and r["avisar_equipo"] is True
    assert cliente.put("/api/v1/fiscal/recordatorios", json={"asunto": "solo asunto"}, headers=h).get_json()["codigo"] == "recordatorios_invalidos"
    assert cliente.put("/api/v1/fiscal/recordatorios", json={"dias_antes": [999]}, headers=h).status_code == 400
    assert cliente.put("/api/v1/fiscal/recordatorios", json={"asunto": "Hola {cliente}", "cuerpo": "Vence {modelo} el {fecha_limite}"}, headers=h).get_json()["data"]["asunto"] == "Hola {cliente}"
    assert cliente.get("/api/v1/fiscal/recordatorios", headers=h).get_json()["data"]["dias_antes"] == [10, 3, 1]                # lo no enviado se conserva


def test_resumen_papelera_y_aislamiento(cliente):
    h, _, _ = _despacho(cliente, "z@ejemplo.com")
    otro, _, _ = _despacho(cliente, "z2@ejemplo.com")
    cid = _cliente_fiscal(cliente, h)
    vid = _venc(cliente, h, cid).get_json()["data"]["id"]
    res = cliente.get(f"/api/v1/fiscal/clientes/{cid}/resumen", headers=h).get_json()["data"]
    assert res["vencimientos_pendientes"] == 1 and res["modelos"] == ["303", "130"] and res["proximos"][0]["id"] == vid
    assert cliente.get(f"/api/v1/fiscal/clientes/{cid}/resumen", headers=otro).status_code == 404
    assert cliente.get(f"/api/v1/fiscal/vencimientos/{vid}", headers=otro).status_code == 404
    assert cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/presentado", headers=otro).status_code == 404
    assert cliente.post("/api/v1/fiscal/vencimientos", json={"cliente_id": cid, "modelo": "x", "periodo": "y", "fecha_limite": "2030-01-01"}, headers=otro).status_code == 404
    cliente.delete(f"/api/v1/fiscal/vencimientos/{vid}", headers=h)
    cliente.delete(f"/api/v1/fiscal/clientes/{cid}", headers=h)
    items = cliente.get("/api/v1/fiscal/papelera", headers=h).get_json()["data"]
    assert {i["tipo"] if "tipo" in i else i.get("origen") for i in items} and len(items) == 2
    assert cliente.get("/api/v1/fiscal/papelera", headers=otro).get_json()["data"] == []
    assert cliente.post("/api/v1/fiscal/papelera/otra_cosa/1/restaurar", headers=h).status_code == 404
    assert cliente.post(f"/api/v1/fiscal/papelera/cliente_fiscal/{cid}/restaurar", headers=h).status_code == 200
    assert cliente.post(f"/api/v1/fiscal/papelera/vencimiento_fiscal/{vid}/restaurar", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/fiscal/clientes/{cid}/resumen", headers=h).status_code == 200


def test_sin_despacho_y_areas_de_token(cliente):
    datos = _registrar(cliente, email="sd@ejemplo.com")
    sin = _auth(datos["token"])
    for ruta in ("/fiscal/recordatorios", "/fiscal/papelera", "/fiscal/vencimientos/propuestas?cliente_id=1"):
        assert cliente.get("/api/v1" + ruta, headers=sin).status_code == 403
    h, _, _ = _despacho(cliente, "ar@ejemplo.com")
    solo_fiscal_ro = _auth(cliente.post("/api/v1/tokens", json={"areas": ["fiscal"], "permisos": "solo_lectura"}, headers=h).get_json()["data"]["token"])
    assert cliente.get("/api/v1/fiscal/recordatorios", headers=solo_fiscal_ro).status_code == 200
    assert cliente.put("/api/v1/fiscal/recordatorios", json={"avisar_equipo": True}, headers=solo_fiscal_ro).get_json()["codigo"] == "token_solo_lectura"
    assert cliente.get("/api/v1/notas", headers=solo_fiscal_ro).get_json()["codigo"] == "token_area_no_permitida"


def test_openapi_incluye_las_rutas_fiscales(cliente):
    paths = cliente.get("/api/v1/openapi.json").get_json()["paths"]
    for ruta in ("/api/v1/fiscal/vencimientos/generar-masivo", "/api/v1/fiscal/clientes/{cliente_id}/documentos", "/api/v1/fiscal/recordatorios",
                 "/api/v1/fiscal/vencimientos/{vencimiento_id}/mensajes", "/api/v1/fiscal/papelera"):
        assert ruta in paths, ruta


def test_cliente_fiscal_acepta_email_pais_idioma_y_recordatorios(cliente):
    h, _, _ = _despacho(cliente, "cf@ejemplo.com")
    r = cliente.post("/api/v1/fiscal/clientes", json={"nombre": "Acme", "email": "info@acme.com", "pais": "fr", "idioma": "fr", "recordatorios_portal": False}, headers=h)
    assert r.status_code == 201
    d = r.get_json()["data"]
    assert (d["email"], d["pais"], d["idioma"], d["recordatorios_portal"]) == ("info@acme.com", "FR", "fr", 0)
    for malo, campo in (({"email": "no-es-email"}, "email"), ({"pais": "ESP"}, "pais"), ({"idioma": "klingon"}, "idioma")):
        r = cliente.put(f"/api/v1/fiscal/clientes/{d['id']}", json=malo, headers=h)
        assert r.status_code == 400 and r.get_json()["campo"] == campo
        assert cliente.post("/api/v1/fiscal/clientes", json={"nombre": "X", **malo}, headers=h).status_code == 400
    ok = cliente.put(f"/api/v1/fiscal/clientes/{d['id']}", json={"email": None, "pais": "es", "recordatorios_portal": True}, headers=h).get_json()["data"]
    assert ok["email"] is None and ok["pais"] == "ES" and ok["recordatorios_portal"] == 1 and ok["idioma"] == "fr"            # lo no enviado se conserva
