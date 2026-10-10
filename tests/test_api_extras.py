"""API: adjuntos de notas, envío de correo (multipart, programado, límites), plantillas de correo y administración del fichaje."""
import base64
import io
import json
from datetime import datetime, timedelta

import pytest

from app import correo, db
from tests.test_rutas_api import _auth, _registrar


def _usuario(cliente, email, tenant_id=None, gestor=False, admin=False):
    datos = _registrar(cliente, email=email)
    uid = datos["usuario"]["id"]
    if tenant_id is not None:
        db.asignar_tenant(uid, tenant_id)
    conn = db.get_connection()
    if gestor:
        conn.execute("UPDATE usuarios SET gestor_fichajes = 1 WHERE id = ?", (uid,))
    if admin:
        conn.execute("UPDATE usuarios SET rol = 'admin' WHERE id = ?", (uid,))
    conn.commit(); conn.close()
    return _auth(datos["token"]), uid


# --- Adjuntos de notas ---------------------------------------------------------------------------------------------------

def test_adjuntos_de_nota_subir_listar_descargar_y_borrar(cliente):
    h, _ = _usuario(cliente, "n@ejemplo.com")
    otro, _ = _usuario(cliente, "n2@ejemplo.com")
    nota = cliente.post("/api/v1/notas", json={"texto": "con adjuntos"}, headers=h).get_json()["data"]["id"]
    assert cliente.post(f"/api/v1/notas/{nota}/adjuntos", headers=h, data={}, content_type="multipart/form-data").get_json()["codigo"] == "sin_archivos"
    r = cliente.post(f"/api/v1/notas/{nota}/adjuntos", headers=h, content_type="multipart/form-data", data={"adjunto": [
        (io.BytesIO(b"\x89PNG....."), "foto.png", "image/png"), (io.BytesIO(b"<html>"), "malo.html", "text/html"), (io.BytesIO(b""), "vacio.txt", "text/plain")]})
    res = r.get_json()["data"]
    assert r.status_code == 201 and [x["ok"] for x in res] == [True, False, False] and "no permitido" in res[1]["error"] and "vacío" in res[2]["error"]
    lista = cliente.get(f"/api/v1/notas/{nota}/adjuntos", headers=h).get_json()["data"]
    assert [a["nombre"] for a in lista] == ["foto.png"] and "contenido" not in lista[0]
    d = cliente.get(f"/api/v1/notas/adjuntos/{lista[0]['id']}", headers=h)
    assert d.data == b"\x89PNG....." and d.headers["Content-Disposition"].startswith("attachment") and d.headers["X-Content-Type-Options"] == "nosniff"
    assert cliente.get(f"/api/v1/notas/adjuntos/{lista[0]['id']}?ver=1", headers=h).headers["Content-Disposition"].startswith("inline")
    assert cliente.get(f"/api/v1/notas/adjuntos/{lista[0]['id']}", headers=otro).status_code == 404                       # ajeno
    assert cliente.get(f"/api/v1/notas/{nota}/adjuntos", headers=otro).status_code == 404
    assert cliente.post(f"/api/v1/notas/{nota}/adjuntos", headers=otro, content_type="multipart/form-data", data={"adjunto": (io.BytesIO(b"x"), "a.txt", "text/plain")}).status_code == 404
    assert cliente.delete(f"/api/v1/notas/adjuntos/{lista[0]['id']}", headers=otro).status_code == 404
    assert cliente.delete(f"/api/v1/notas/adjuntos/{lista[0]['id']}", headers=h).status_code == 200


def test_adjuntos_de_nota_respetan_limites(cliente):
    h, _ = _usuario(cliente, "nl@ejemplo.com")
    nota = cliente.post("/api/v1/notas", json={"texto": "x"}, headers=h).get_json()["data"]["id"]
    grande = cliente.post(f"/api/v1/notas/{nota}/adjuntos", headers=h, content_type="multipart/form-data",
                          data={"adjunto": (io.BytesIO(b"a" * (5 * 1024 * 1024 + 10)), "grande.txt", "text/plain")})
    assert grande.status_code == 400 and "5 MB" in grande.get_json()["data"][0]["error"]
    for i in range(5):
        assert cliente.post(f"/api/v1/notas/{nota}/adjuntos", headers=h, content_type="multipart/form-data", data={"adjunto": (io.BytesIO(b"x%d" % i), f"{i}.txt", "text/plain")}).status_code == 201
    sexto = cliente.post(f"/api/v1/notas/{nota}/adjuntos", headers=h, content_type="multipart/form-data", data={"adjunto": (io.BytesIO(b"y"), "6.txt", "text/plain")})
    assert sexto.status_code == 400 and "máximo 5" in sexto.get_json()["data"][0]["error"]
    ro = _auth(cliente.post("/api/v1/tokens", json={"permisos": "solo_lectura"}, headers=h).get_json()["data"]["token"])
    assert cliente.get(f"/api/v1/notas/{nota}/adjuntos", headers=ro).status_code == 200
    assert cliente.post(f"/api/v1/notas/{nota}/adjuntos", headers=ro, content_type="multipart/form-data", data={"adjunto": (io.BytesIO(b"y"), "7.txt", "text/plain")}).get_json()["codigo"] == "token_solo_lectura"


# --- Envío de correo ---------------------------------------------------------------------------------------------------------

def _cuenta(uid):
    return db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com", smtp_host="smtp.ejemplo.com", smtp_puerto=587)


CUERPO = {"destinatarios": "ana@ejemplo.com", "asunto": "Hola", "cuerpo_html": "<p>Buenas</p>"}


def test_envio_json_y_multipart_con_adjuntos(cliente, monkeypatch):
    h, uid = _usuario(cliente, "e@ejemplo.com")
    cuenta = _cuenta(uid)
    capturado = []
    monkeypatch.setattr(correo, "construir_y_enviar", lambda *a, **k: capturado.append((a, k)) or "<id-1@ejemplo.com>")
    contenido = base64.b64encode(b"hola mundo").decode()
    r = cliente.post("/api/v1/correo/enviar", json={**CUERPO, "cuenta_id": cuenta, "adjuntos": [{"nombre": "nota.txt", "tipo": "text/plain", "contenido_base64": contenido}], "seguimiento_dias": 3}, headers=h)
    assert r.status_code == 200 and r.get_json()["data"] == {"enviado": True, "message_id": "<id-1@ejemplo.com>"}
    args, kw = capturado[-1]
    assert args[1] == cuenta and kw["adjuntos"] == [{"nombre": "nota.txt", "tipo": "text/plain", "bytes": b"hola mundo"}] and kw["seguimiento_dias"] == 3
    r = cliente.post("/api/v1/correo/enviar", headers=h, content_type="multipart/form-data",
                     data={**CUERPO, "cuenta_id": str(cuenta), "adjuntos": [(io.BytesIO(b"AAA"), "a.pdf", "application/pdf"), (io.BytesIO(b"BBB"), "b.png", "image/png")]})
    assert r.status_code == 200
    assert [x["nombre"] for x in capturado[-1][1]["adjuntos"]] == ["a.pdf", "b.png"] and capturado[-1][1]["adjuntos"][0]["bytes"] == b"AAA"
    cliente.post("/api/v1/correo/enviar", json={**CUERPO, "cuenta_id": cuenta}, headers=h)
    assert capturado[-1][1]["adjuntos"] is None                                                                             # sin adjuntos: igual que siempre


def test_envio_valida_adjuntos_cuenta_y_tamano(cliente):
    h, uid = _usuario(cliente, "ev@ejemplo.com")
    cuenta = _cuenta(uid)
    r = cliente.post("/api/v1/correo/enviar", json={**CUERPO, "cuenta_id": cuenta, "adjuntos": [{"nombre": "x", "contenido_base64": "esto no es base64!!"}]}, headers=h)
    assert r.status_code == 400 and r.get_json()["codigo"] == "adjunto_invalido"                                           # antes: 500
    r = cliente.post("/api/v1/correo/enviar", json={**CUERPO, "cuenta_id": cuenta, "adjuntos": [{"nombre": f"{i}", "contenido_base64": "QQ=="} for i in range(21)]}, headers=h)
    assert r.get_json()["codigo"] == "demasiados_adjuntos"
    assert cliente.post("/api/v1/correo/enviar", json={**CUERPO, "cuenta_id": 9999}, headers=h).get_json()["error"] == "Esa cuenta no existe."
    assert cliente.post("/api/v1/correo/enviar", json={**CUERPO}, headers=h).status_code == 400                           # sin cuenta
    grande = [{"nombre": "g.bin", "bytes": b"a" * (26 * 1024 * 1024)}]
    with pytest.raises(correo.ErrorCorreo, match="25 MB"):
        correo.construir_y_enviar(uid, cuenta, "a@b.com", "x", "<p>x</p>", adjuntos=grande)                               # el límite vale también sin cola


def test_envio_programado_estado_y_cancelacion(cliente):
    h, uid = _usuario(cliente, "p@ejemplo.com")
    otro, _ = _usuario(cliente, "p2@ejemplo.com")
    cuenta = _cuenta(uid)
    futuro = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    for malo in ("ayer", (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), (datetime.now() + timedelta(days=500)).strftime("%Y-%m-%dT%H:%M")):
        r = cliente.post("/api/v1/correo/enviar", json={**CUERPO, "cuenta_id": cuenta, "programar_para": malo}, headers=h)
        assert r.status_code == 400 and r.get_json()["campo"] == "programar_para", malo
    r = cliente.post("/api/v1/correo/enviar", json={**CUERPO, "cuenta_id": cuenta, "programar_para": futuro, "adjuntos": [{"nombre": "a.txt", "contenido_base64": "QQ=="}]}, headers=h)
    assert r.status_code == 202 and r.get_json()["data"]["programado"] is True
    eid = r.get_json()["data"]["envio_id"]
    assert cliente.get(f"/api/v1/correo/envios/{eid}", headers=h).get_json()["data"]["estado"] == "pendiente"
    assert [e["id"] for e in cliente.get("/api/v1/correo/programados", headers=h).get_json()["data"]] == [eid]
    assert cliente.get(f"/api/v1/correo/envios/{eid}", headers=otro).status_code == 404
    assert cliente.post(f"/api/v1/correo/envios/{eid}/cancelar", headers=otro).status_code == 404
    c = cliente.post(f"/api/v1/correo/envios/{eid}/cancelar", json={"como_borrador": True}, headers=h).get_json()["data"]
    assert c["cancelado"] is True and c["borrador_id"] and db.obtener_borrador_correo(uid, c["borrador_id"])["asunto"] == "Hola"
    assert cliente.get(f"/api/v1/correo/envios/{eid}", headers=h).get_json()["data"]["estado"] == "cancelado"
    assert cliente.post(f"/api/v1/correo/envios/{eid}/cancelar", headers=h).get_json()["codigo"] == "envio_no_cancelable"
    r2 = cliente.post("/api/v1/correo/enviar", json={**CUERPO, "cuenta_id": cuenta, "programar_para": futuro}, headers=h).get_json()["data"]["envio_id"]
    assert cliente.delete(f"/api/v1/correo/programados/{r2}", headers=h).status_code == 200
    assert db.adjuntos_envio_correo(r2) == [] and cliente.get(f"/api/v1/correo/programados", headers=h).get_json()["data"] == []


# --- Plantillas de correo ------------------------------------------------------------------------------------------------------

def test_plantillas_crud_variables_y_renderizado(cliente):
    t = db.crear_tenant("Despacho plantillas")
    h, uid = _usuario(cliente, "pl@ejemplo.com", t)
    otro, _ = _usuario(cliente, "pl2@ejemplo.com", db.crear_tenant("Otro"))
    assert "cliente" in [v["nombre"] for v in cliente.get("/api/v1/correo/plantillas/variables", headers=h).get_json()["data"]]
    assert cliente.post("/api/v1/correo/plantillas", json={"nombre": "", "cuerpo": "x"}, headers=h).get_json()["codigo"] == "plantilla_invalida"
    assert cliente.post("/api/v1/correo/plantillas", json={"nombre": "x", "cuerpo": " "}, headers=h).status_code == 400
    p = cliente.post("/api/v1/correo/plantillas", json={"nombre": "Pedir extractos", "asunto": "Modelo {{modelo}} de {{cliente}}", "cuerpo": "<p>Hola {{cliente}}, falta {{documento}} y {{inventada}}</p>", "modelo": "303"}, headers=h)
    assert p.status_code == 201
    pid = p.get_json()["data"]["id"]
    assert pid in [x["id"] for x in cliente.get("/api/v1/correo/plantillas", headers=h).get_json()["data"]]
    cli = db.crear_cliente_fiscal(t, "Acme <SL>")
    r = cliente.get(f"/api/v1/correo/plantillas/{pid}?cliente_fiscal_id={cli}", headers=h).get_json()["data"]["renderizada"]
    assert "Acme <SL>" in r["asunto"] and "&lt;SL&gt;" in r["cuerpo"] and "documento" in r["sin_resolver"]                        # el valor se escapa solo en el HTML
    assert "{{inventada}}" in r["cuerpo"] and "{{documento}}" in r["cuerpo"]                                                    # lo que no se resuelve se deja a la vista
    assert "renderizada" not in cliente.get(f"/api/v1/correo/plantillas/{pid}", headers=h).get_json()["data"]
    e = cliente.put(f"/api/v1/correo/plantillas/{pid}", json={"nombre": "Pedir extractos v2"}, headers=h).get_json()["data"]
    assert e["nombre"] == "Pedir extractos v2" and e["asunto"].startswith("Modelo") and e["modelo"] == "303"                     # lo no enviado se conserva
    assert cliente.put(f"/api/v1/correo/plantillas/{pid}", json={"cuerpo": ""}, headers=h).status_code == 400
    for ruta in (lambda: cliente.get(f"/api/v1/correo/plantillas/{pid}", headers=otro), lambda: cliente.put(f"/api/v1/correo/plantillas/{pid}", json={"nombre": "x"}, headers=otro),
                 lambda: cliente.delete(f"/api/v1/correo/plantillas/{pid}", headers=otro)):
        assert ruta().status_code == 404
    assert cliente.delete(f"/api/v1/correo/plantillas/{pid}", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/correo/plantillas/{pid}", headers=h).status_code == 404


# --- Fichaje: administración -----------------------------------------------------------------------------------------------------

def _fichar(uid, tenant, tipo, marca):
    return db.fichar(uid, tenant, tipo, marca_tiempo=marca)


def test_fichaje_admin_resumen_detalle_y_permisos(cliente):
    t1, t2 = db.crear_tenant("Despacho F1"), db.crear_tenant("Despacho F2")
    gestor, g_id = _usuario(cliente, "g@ejemplo.com", t1, gestor=True)
    normal, n_id = _usuario(cliente, "w@ejemplo.com", t1)
    ajeno, a_id = _usuario(cliente, "x@ejemplo.com", t2)
    _fichar(n_id, t1, "entrada", "2026-10-05T08:00:00"); _fichar(n_id, t1, "salida", "2026-10-05T16:00:00")
    _fichar(a_id, t2, "entrada", "2026-10-05T09:00:00")
    assert cliente.get("/api/v1/fichaje/admin/resumen", headers=normal).status_code == 403                                  # un trabajador no administra
    res = cliente.get("/api/v1/fichaje/admin/resumen?desde=2026-10-01&hasta=2026-10-31", headers=gestor).get_json()["data"]
    assert res["tenant_id"] == t1 and {f["usuario_id"] for f in res["trabajadores"]} >= {n_id}
    assert a_id not in {f["usuario_id"] for f in res["trabajadores"]}                                                          # solo su despacho
    assert cliente.get(f"/api/v1/fichaje/admin/resumen?tenant_id={t2}", headers=gestor).get_json()["data"]["tenant_id"] == t1  # el tenant_id de un gestor se ignora
    d = cliente.get(f"/api/v1/fichaje/admin/usuarios/{n_id}", headers=gestor).get_json()["data"]
    assert [f["tipo"] for f in d["fichajes"]] == ["salida", "entrada"] and d["email"] == "w@ejemplo.com"                          # el más reciente primero
    assert cliente.get(f"/api/v1/fichaje/admin/usuarios/{a_id}", headers=gestor).status_code == 404                          # de otro despacho: ni existe
    assert cliente.get("/api/v1/fichaje/admin/usuarios/99999", headers=gestor).status_code == 404


def test_fichaje_admin_corrige_sin_sobrescribir_y_audita(cliente):
    t = db.crear_tenant("Despacho FC")
    gestor, g_id = _usuario(cliente, "gc@ejemplo.com", t, gestor=True)
    _, n_id = _usuario(cliente, "wc@ejemplo.com", t)
    entrada = _fichar(n_id, t, "entrada", "2026-10-05T08:00:00")
    for malo, codigo in (({"tipo": "vacaciones", "marca_tiempo": "2026-10-05T16:00"}, "tipo_invalido"), ({"tipo": "salida", "marca_tiempo": "ayer"}, "marca_invalida"), ({"tipo": "entrada", "marca_tiempo": "2026-10-05T17:00"}, "fichaje_invalido")):
        r = cliente.post(f"/api/v1/fichaje/admin/usuarios/{n_id}/corregir", json=malo, headers=gestor)
        assert r.status_code == 400 and r.get_json()["codigo"] == codigo, malo                                                   # entrada tras entrada: transición no válida
    r = cliente.post(f"/api/v1/fichaje/admin/usuarios/{n_id}/corregir", json={"tipo": "salida", "marca_tiempo": "2026-10-05T16:30", "nota": "Olvidó fichar la salida"}, headers=gestor)
    assert r.status_code == 201
    fichajes = cliente.get(f"/api/v1/fichaje/admin/usuarios/{n_id}", headers=gestor).get_json()["data"]["fichajes"]
    assert [f["tipo"] for f in fichajes] == ["salida", "entrada"] and fichajes[1]["id"] == entrada and fichajes[1]["marca_tiempo"] == "2026-10-05T08:00:00"
    c = fichajes[0]
    assert (c["origen"], c["creado_por"], c["nota"]) == ("correccion_admin", g_id, "Olvidó fichar la salida") and c["marca_tiempo"] == "2026-10-05T16:30:00"
    ro = _auth(cliente.post("/api/v1/tokens", json={"permisos": "solo_lectura"}, headers=gestor).get_json()["data"]["token"])
    assert cliente.post(f"/api/v1/fichaje/admin/usuarios/{n_id}/corregir", json={"tipo": "salida", "marca_tiempo": "2026-10-06T10:00"}, headers=ro).get_json()["codigo"] == "token_solo_lectura"
    assert cliente.get("/api/v1/fichaje/admin/verificar-integridad", headers=gestor).get_json()["data"]


def test_fichaje_admin_exportaciones_y_admin_global(cliente):
    t1, t2 = db.crear_tenant("Despacho FE1"), db.crear_tenant("Despacho FE2")
    gestor, _ = _usuario(cliente, "ge@ejemplo.com", t1, gestor=True)
    admin, _ = _usuario(cliente, "ad@ejemplo.com", admin=True)
    _, n1 = _usuario(cliente, "n1@ejemplo.com", t1)
    _, n2 = _usuario(cliente, "n2@ejemplo.com", t2)
    for uid, t in ((n1, t1), (n2, t2)):
        _fichar(uid, t, "entrada", "2026-10-05T08:00:00"); _fichar(uid, t, "salida", "2026-10-05T14:00:00")
    for formato, mime in (("csv", "text/csv"), ("json", "application/json"), ("pdf", "application/pdf")):
        r = cliente.get(f"/api/v1/fichaje/admin/exportar.{formato}?desde=2026-10-01&hasta=2026-10-31", headers=gestor)
        assert r.status_code == 200 and r.mimetype == mime and f"fichajes.{formato}" in r.headers["Content-Disposition"], formato
    exportado = json.loads(cliente.get("/api/v1/fichaje/admin/exportar.json", headers=gestor).data)
    assert "n2@ejemplo.com" not in json.dumps(exportado) and "n1@ejemplo.com" in json.dumps(exportado)
    assert cliente.get(f"/api/v1/fichaje/admin/exportar.csv?usuario_id={n2}", headers=gestor).status_code == 404               # trabajador de otro despacho
    assert cliente.get("/api/v1/fichaje/admin/resumen", headers=admin).get_json()["codigo"] == "peticion_invalida"            # el admin global debe elegir despacho
    assert cliente.get(f"/api/v1/fichaje/admin/resumen?tenant_id={t2}", headers=admin).get_json()["data"]["trabajadores"][0]["usuario_id"] == n2
    assert cliente.get("/api/v1/fichaje/admin/resumen?tenant_id=99999", headers=admin).status_code == 404
    area = _auth(cliente.post("/api/v1/tokens", json={"areas": ["notas"]}, headers=gestor).get_json()["data"]["token"])
    assert cliente.get("/api/v1/fichaje/admin/resumen", headers=area).get_json()["codigo"] == "token_area_no_permitida"


def test_openapi_incluye_lo_nuevo(cliente):
    paths = cliente.get("/api/v1/openapi.json").get_json()["paths"]
    for ruta in ("/api/v1/notas/{nota_id}/adjuntos", "/api/v1/notas/adjuntos/{adjunto_id}", "/api/v1/correo/envios/{envio_id}/cancelar",
                 "/api/v1/correo/plantillas/{plantilla_id}", "/api/v1/fichaje/admin/resumen", "/api/v1/fichaje/admin/usuarios/{usuario_id}/corregir"):
        assert ruta in paths, ruta
