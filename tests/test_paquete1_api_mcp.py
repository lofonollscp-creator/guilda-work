"""Primer paquete: X-Request-Id, webhooks con firma temporal y SSRF, webhooks por API y referencia_externa con upsert."""
import hashlib
import hmac
import json
import socket
import time
import urllib.error

import pytest

from app import db, eventos as ev
from tests.test_rutas_api import _auth, _registrar


def _usuario(cliente, email, supervisor=True, tenant=True):
    datos = _registrar(cliente, email=email)
    uid = datos["usuario"]["id"]
    if tenant:
        db.asignar_tenant(uid, db.crear_tenant("Despacho " + email))
    if supervisor:
        conn = db.get_connection(); conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (uid,)); conn.commit(); conn.close()
    return _auth(datos["token"]), uid


@pytest.fixture
def dns_publico(monkeypatch):
    """Resuelve `*.publico.example` a una IP pública y `*.interno.example` a una privada, sin red real (solo parchea el
    resolutor de eventos.py, no el DNS de todo el proceso)."""
    def falso(host, puerto):
        if host.endswith("publico.example"):
            return {"93.184.216.34"}
        if host.endswith("interno.example"):
            return {"10.0.0.5"}
        if host.endswith("mixto.example"):
            return {"93.184.216.34", "169.254.169.254"}
        if host in ("127.0.0.1", "localhost"):
            return {"127.0.0.1"}
        if host == "::1":
            return {"::1"}
        raise socket.gaierror("no resuelve")
    monkeypatch.setattr(ev, "_resolver", falso)


# --- X-Request-Id ---------------------------------------------------------------------------------------------------

def test_request_id_en_cabecera_errores_y_se_respeta_el_del_cliente(cliente):
    r = cliente.get("/api/v1/notas")
    rid = r.headers["X-Request-Id"]
    assert len(rid) == 32 and r.get_json()["request_id"] == rid and r.get_json()["codigo"] == "token_invalido"
    r = cliente.get("/api/v1/notas", headers={"X-Request-Id": "mi-peticion-0001"})
    assert r.headers["X-Request-Id"] == "mi-peticion-0001" and r.get_json()["request_id"] == "mi-peticion-0001"
    r = cliente.get("/api/v1/notas", headers={"X-Request-Id": "<script>alert(1)</script>"})
    assert "<" not in r.headers["X-Request-Id"] and len(r.headers["X-Request-Id"]) == 32     # basura: se sustituye
    assert cliente.get("/api/v1/no-existe").get_json()["request_id"]
    assert cliente.get("/login").headers["X-Request-Id"]                                      # también en la web
    h, _ = _usuario(cliente, "rid@ejemplo.com")
    ok = cliente.get("/api/v1/notas", headers={**h, "X-Request-Id": "abcdefgh12"})
    assert ok.headers["X-Request-Id"] == "abcdefgh12" and "request_id" not in ok.get_json()  # en éxito, solo cabecera


# --- Webhooks: firma con marca de tiempo y SSRF -----------------------------------------------------------------------

def test_firma_v2_con_marca_de_tiempo(usuario_id, monkeypatch):
    w = db.crear_webhook(usuario_id, None, "https://x.example/h", ["nota.creada"])
    ev.emitir("nota.creada", None, {"a": 1})
    visto = {}

    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda req, timeout=None: visto.update(req=req) or R())
    ev.procesar_pendientes()
    cab = {k.lower(): v for k, v in visto["req"].header_items()}
    marca = cab["x-guilda-timestamp"]
    assert abs(int(marca) - time.time()) < 10
    esperada = hmac.new(w["secreto"].encode(), f"{marca}.".encode() + visto["req"].data, hashlib.sha256).hexdigest()
    assert cab["x-guilda-signature-v2"] == f"t={marca},v1={esperada}"
    assert cab["x-guilda-signature"].startswith("sha256=")                                     # la antigua sigue ahí


def test_validar_url_publica(dns_publico):
    v = ev.validar_url_publica
    assert v("https://hooks.publico.example/x")[0]
    for malo in ("http://hooks.publico.example/x", "https://127.0.0.1/x", "https://localhost:8080/x", "https://a.interno.example/x",
                 "https://a.mixto.example/x", "https://usuario:clave@hooks.publico.example/x", "https://no-resuelve.example/x",
                 "ftp://hooks.publico.example", "https:///sinhost", "https://[::1]/x"):
        assert not v(malo)[0], malo
    assert not v("https://hooks.publico.example/" + "a" * 600)[0]


def test_entrega_api_se_bloquea_si_el_dns_cambia_a_interno_y_no_sigue_redirecciones(usuario_id, dns_publico, monkeypatch):
    externo = db.crear_webhook(usuario_id, None, "https://a.interno.example/h", ["nota.creada"], origen="api")
    interno_confiable = db.crear_webhook(usuario_id, None, "http://127.0.0.1:5678/h", ["nota.creada"])      # backoffice: n8n local
    ev.emitir("nota.creada", None, {})
    llamadas = []

    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda req, timeout=None: llamadas.append(req.full_url) or R())
    ev.procesar_pendientes()
    assert llamadas == ["http://127.0.0.1:5678/h"]                                             # el de confianza sí; el externo no se toca
    assert "URL bloqueada" in db.entregas_de_webhook(externo["id"])[0]["error"]
    # redirecciones: un webhook de origen api no las sigue
    opener = ev.urllib.request.build_opener(ev._SinRedirecciones)
    assert ev._SinRedirecciones().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/") is None


# --- API de webhooks ----------------------------------------------------------------------------------------------------

def test_api_webhooks_crud_secreto_rotacion_y_prueba(cliente, dns_publico):
    h, _ = _usuario(cliente, "w@ejemplo.com")
    assert cliente.get("/api/v1/webhooks/catalogo-eventos", headers=h).get_json()["data"].count("cliente.creado") == 1
    for malo in ({"url": "http://hooks.publico.example/x", "eventos": ["nota.creada"]}, {"url": "https://a.interno.example/x", "eventos": ["nota.creada"]},
                 {"url": "https://hooks.publico.example/x", "eventos": []}, {"url": "https://hooks.publico.example/x", "eventos": ["inventado"]},
                 {"url": "https://hooks.publico.example/x", "eventos": ["ping"]}):
        r = cliente.post("/api/v1/webhooks", json=malo, headers=h)
        assert r.status_code == 400 and r.get_json()["codigo"] in ("url_invalida", "eventos_invalidos"), malo
    r = cliente.post("/api/v1/webhooks", json={"url": "https://hooks.publico.example/x", "eventos": ["nota.creada", "nota.creada", "tarea.creada"]}, headers=h)
    assert r.status_code == 201
    w = r.get_json()["data"]
    assert w["secreto"] and w["origen"] == "api" and w["eventos"] == ["nota.creada", "tarea.creada"]
    leido = cliente.get(f"/api/v1/webhooks/{w['id']}", headers=h).get_json()["data"]
    assert "secreto" not in leido and "secreto" not in cliente.get("/api/v1/webhooks", headers=h).get_json()["data"][0]
    nuevo = cliente.post(f"/api/v1/webhooks/{w['id']}/rotar-secreto", headers=h).get_json()["data"]["secreto"]
    assert nuevo and nuevo != w["secreto"] and db.obtener_webhook(w["id"])["secreto"] == nuevo
    r = cliente.put(f"/api/v1/webhooks/{w['id']}", json={"activo": False, "eventos": ["nota.editada"]}, headers=h).get_json()["data"]
    assert r["activo"] == 0 and r["eventos"] == ["nota.editada"] and r["url"] == "https://hooks.publico.example/x"
    assert cliente.put(f"/api/v1/webhooks/{w['id']}", json={"url": "https://a.interno.example/x"}, headers=h).status_code == 400
    assert cliente.post(f"/api/v1/webhooks/{w['id']}/probar", headers=h).status_code == 202
    ent = cliente.get(f"/api/v1/webhooks/{w['id']}/entregas", headers=h).get_json()["data"]
    assert ent["cola"][0]["evento"] == "ping"
    assert cliente.delete(f"/api/v1/webhooks/{w['id']}", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/webhooks/{w['id']}", headers=h).status_code == 404


def test_api_webhooks_permisos_aislamiento_y_limite(cliente, dns_publico, monkeypatch):
    normal, _ = _usuario(cliente, "n@ejemplo.com", supervisor=False)
    assert cliente.get("/api/v1/webhooks", headers=normal).status_code == 403
    sin_despacho, _ = _usuario(cliente, "sd@ejemplo.com", tenant=False)
    assert cliente.post("/api/v1/webhooks", json={"url": "https://h.publico.example/x", "eventos": ["nota.creada"]}, headers=sin_despacho).status_code == 403
    a, _ = _usuario(cliente, "a@ejemplo.com")
    b, _ = _usuario(cliente, "b@ejemplo.com")
    wa = cliente.post("/api/v1/webhooks", json={"url": "https://h.publico.example/a", "eventos": ["nota.creada"]}, headers=a).get_json()["data"]
    for peticion in (lambda: cliente.get(f"/api/v1/webhooks/{wa['id']}", headers=b), lambda: cliente.delete(f"/api/v1/webhooks/{wa['id']}", headers=b),
                     lambda: cliente.post(f"/api/v1/webhooks/{wa['id']}/rotar-secreto", headers=b), lambda: cliente.get(f"/api/v1/webhooks/{wa['id']}/entregas", headers=b)):
        assert peticion().status_code == 404
    assert cliente.get("/api/v1/webhooks", headers=b).get_json()["data"] == []
    # un webhook del backoffice se ve pero no se toca desde la API
    tenant_a = db.tenant_de_usuario(_ids(cliente, a))["id"]
    wb = db.crear_webhook(1, tenant_a, "http://127.0.0.1:5678/h", ["nota.creada"])
    assert cliente.get(f"/api/v1/webhooks/{wb['id']}", headers=a).status_code == 200
    r = cliente.delete(f"/api/v1/webhooks/{wb['id']}", headers=a)
    assert r.status_code == 403 and db.obtener_webhook(wb["id"]) is not None
    monkeypatch.setattr("app.rutas_api_ampliada.MAX_WEBHOOKS_POR_DESPACHO", 2)
    r = cliente.post("/api/v1/webhooks", json={"url": "https://h.publico.example/c", "eventos": ["nota.creada"]}, headers=a)
    assert r.status_code == 409 and r.get_json()["codigo"] == "limite_de_webhooks"


def _ids(cliente, h):
    return cliente.get("/api/v1/auth/me", headers=h).get_json()["data"]["id"]


def test_api_webhooks_reintentar_y_area_de_token(cliente, dns_publico):
    h, _ = _usuario(cliente, "r@ejemplo.com")
    w = cliente.post("/api/v1/webhooks", json={"url": "https://h.publico.example/a", "eventos": ["nota.creada"]}, headers=h).get_json()["data"]
    cola_id = db.cola_webhook_encolar(w["id"], "nota.creada", {})
    assert cliente.post(f"/api/v1/webhooks/entregas/{cola_id}/reintentar", headers=h).get_json()["codigo"] == "entrega_no_fallida"
    db.cola_webhook_cerrar(cola_id, "fallido", "x")
    assert cliente.post(f"/api/v1/webhooks/entregas/{cola_id}/reintentar", headers=h).status_code == 200
    assert cliente.post("/api/v1/webhooks/entregas/9999/reintentar", headers=h).status_code == 404
    solo_notas = _auth(cliente.post("/api/v1/tokens", json={"areas": ["notas"]}, headers=h).get_json()["data"]["token"])
    assert cliente.get("/api/v1/webhooks", headers=solo_notas).get_json()["codigo"] == "token_area_no_permitida"
    solo_hooks = _auth(cliente.post("/api/v1/tokens", json={"areas": ["webhooks"]}, headers=h).get_json()["data"]["token"])
    assert cliente.get("/api/v1/webhooks", headers=solo_hooks).status_code == 200


# --- referencia_externa y upsert -------------------------------------------------------------------------------------------

def test_referencia_externa_en_notas_tareas_y_clientes(cliente):
    h, uid = _usuario(cliente, "ref@ejemplo.com")
    n = cliente.post("/api/v1/notas", json={"texto": "desde el ERP", "referencia_externa": "ERP-1"}, headers=h)
    assert n.status_code == 201 and n.get_json()["data"]["referencia_externa"] == "ERP-1"
    dup = cliente.post("/api/v1/notas", json={"texto": "otra", "referencia_externa": "ERP-1"}, headers=h)
    assert dup.status_code == 409 and dup.get_json()["codigo"] == "referencia_duplicada" and len(cliente.get("/api/v1/notas", headers=h).get_json()["data"]) == 1
    assert [x["id"] for x in cliente.get("/api/v1/notas?referencia_externa=ERP-1", headers=h).get_json()["data"]] == [n.get_json()["data"]["id"]]
    assert cliente.get("/api/v1/notas?referencia_externa=NOPE", headers=h).get_json()["data"] == []
    otra = cliente.post("/api/v1/notas", json={"texto": "x"}, headers=h).get_json()["data"]["id"]
    assert cliente.put(f"/api/v1/notas/{otra}", json={"texto": "x", "referencia_externa": "ERP-1"}, headers=h).status_code == 409
    assert cliente.put(f"/api/v1/notas/{otra}", json={"texto": "x", "referencia_externa": "ERP-2"}, headers=h).get_json()["data"]["referencia_externa"] == "ERP-2"
    assert cliente.put(f"/api/v1/notas/{otra}", json={"texto": "x", "referencia_externa": None}, headers=h).get_json()["data"]["referencia_externa"] is None
    for malo in ("a" * 200, "con\nsalto", ["lista"], True):
        assert cliente.post("/api/v1/notas", json={"texto": "x", "referencia_externa": malo}, headers=h).get_json()["codigo"] == "referencia_invalida"
    t = cliente.post("/api/v1/tareas-outlook", json={"asunto": "T", "referencia_externa": "TK-9"}, headers=h).get_json()["data"]
    assert t["referencia_externa"] == "TK-9" and cliente.post("/api/v1/tareas-outlook", json={"asunto": "T2", "referencia_externa": "TK-9"}, headers=h).status_code == 409
    assert [x["id"] for x in cliente.get("/api/v1/tareas-outlook?referencia_externa=TK-9", headers=h).get_json()["data"]] == [t["id"]]
    # la misma referencia en OTRO usuario no choca
    h2, _ = _usuario(cliente, "ref2@ejemplo.com")
    assert cliente.post("/api/v1/notas", json={"texto": "mía", "referencia_externa": "ERP-1"}, headers=h2).status_code == 201


def test_upsert_por_referencia_crea_y_actualiza_sin_duplicar(cliente):
    h, _ = _usuario(cliente, "up@ejemplo.com")
    r1 = cliente.put("/api/v1/tareas-outlook/por-referencia/SAP-77", json={"asunto": "Conciliar", "prioridad": "alta"}, headers=h)
    assert r1.status_code == 201 and r1.headers["X-Guilda-Upsert"] == "creado" and r1.get_json()["data"]["referencia_externa"] == "SAP-77"
    r2 = cliente.put("/api/v1/tareas-outlook/por-referencia/SAP-77", json={"asunto": "Conciliar (rev)", "estado": "en_progreso"}, headers=h)
    assert r2.status_code == 200 and r2.headers["X-Guilda-Upsert"] == "actualizado"
    assert r2.get_json()["data"]["id"] == r1.get_json()["data"]["id"] and r2.get_json()["data"]["asunto"] == "Conciliar (rev)"
    assert len(cliente.get("/api/v1/tareas-outlook", headers=h).get_json()["data"]) == 1
    assert cliente.get("/api/v1/tareas-outlook/por-referencia/SAP-77", headers=h).get_json()["data"]["asunto"] == "Conciliar (rev)"
    assert cliente.get("/api/v1/tareas-outlook/por-referencia/NO", headers=h).status_code == 404
    n = cliente.put("/api/v1/notas/por-referencia/CRM/nota/5", json={"texto": "con barras en la referencia"}, headers=h)
    assert n.status_code == 201 and n.get_json()["data"]["referencia_externa"] == "CRM/nota/5"
    assert cliente.put("/api/v1/notas/por-referencia/CRM/nota/5", json={"texto": "otra versión"}, headers=h).status_code == 200
    assert cliente.put("/api/v1/notas/por-referencia/x", json={}, headers=h).status_code == 400            # validaciones de siempre
    malo = cliente.put("/api/v1/tareas-outlook/por-referencia/SAP-77", json={"estado": "inventado"}, headers=h)
    assert malo.status_code == 400 and malo.get_json()["codigo"] == "valor_invalido"                       # antes: 500
    ro = _auth(cliente.post("/api/v1/tokens", json={"permisos": "solo_lectura"}, headers=h).get_json()["data"]["token"])
    assert cliente.put("/api/v1/notas/por-referencia/y", json={"texto": "x"}, headers=ro).status_code == 403
    assert cliente.get("/api/v1/notas/por-referencia/CRM/nota/5", headers=ro).status_code == 200


def test_upsert_de_clientes_fiscales_por_despacho(cliente):
    a, ua = _usuario(cliente, "fa@ejemplo.com")
    b, ub = _usuario(cliente, "fb@ejemplo.com")
    c1 = cliente.put("/api/v1/fiscal/clientes/por-referencia/ERP-C-1", json={"nombre": "Acme SL", "nif": "B111"}, headers=a)
    assert c1.status_code == 201 and c1.get_json()["data"]["referencia_externa"] == "ERP-C-1"
    c2 = cliente.put("/api/v1/fiscal/clientes/por-referencia/ERP-C-1", json={"nombre": "Acme S.L.", "nif": "B111"}, headers=a)
    assert c2.status_code == 200 and c2.get_json()["data"]["id"] == c1.get_json()["data"]["id"] and c2.get_json()["data"]["nombre"] == "Acme S.L."
    assert len(cliente.get("/api/v1/fiscal/clientes", headers=a).get_json()["data"]) == 1
    otro = cliente.put("/api/v1/fiscal/clientes/por-referencia/ERP-C-1", json={"nombre": "De otro despacho"}, headers=b)
    assert otro.status_code == 201 and otro.get_json()["data"]["id"] != c1.get_json()["data"]["id"]          # el índice es por despacho
    assert cliente.get("/api/v1/fiscal/clientes/por-referencia/ERP-C-1", headers=b).get_json()["data"]["nombre"] == "De otro despacho"
    assert [x["nombre"] for x in cliente.get("/api/v1/fiscal/clientes?referencia_externa=ERP-C-1", headers=a).get_json()["data"]] == ["Acme S.L."]
    sin_despacho, _ = _usuario(cliente, "fz@ejemplo.com", tenant=False)
    assert cliente.put("/api/v1/fiscal/clientes/por-referencia/Z", json={"nombre": "x"}, headers=sin_despacho).status_code == 403
