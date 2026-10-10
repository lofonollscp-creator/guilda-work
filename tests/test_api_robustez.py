"""Robustez de la API para uso interno y externo: errores con código, versión, ETag, `campos`, idempotencia, límite por
usuario y sincronización incremental (/sync)."""
from datetime import datetime, timedelta

from app import auth, db
from tests.test_rutas_api import _auth, _registrar


def _usuario(cliente, email):
    datos = _registrar(cliente, email=email)
    return _auth(datos["token"]), datos["usuario"]["id"]


# --- Errores y cabeceras ------------------------------------------------------------------------------------

def test_errores_llevan_codigo_estable_ademas_del_texto(cliente):
    h, _ = _usuario(cliente, "e@ejemplo.com")
    r = cliente.get("/api/v1/notas")
    cuerpo = r.get_json()
    assert r.status_code == 401 and {k: cuerpo[k] for k in ("ok", "error", "codigo")} == {"ok": False, "error": "Token inválido o ausente.", "codigo": "token_invalido"}
    assert cuerpo["request_id"] == r.headers["X-Request-Id"]
    r = cliente.get("/api/v1/notas/9999", headers=h)
    assert r.status_code == 404 and r.get_json()["codigo"] == "no_encontrado" and r.get_json()["ok"] is False and r.get_json()["error"]
    assert cliente.post("/api/v1/proyectos", json={"nombre": ""}, headers=h).get_json()["codigo"] == "peticion_invalida"
    assert cliente.delete("/api/v1/notas", headers=h).get_json()["codigo"] == "metodo_no_permitido"
    ro = _auth(cliente.post("/api/v1/tokens", json={"nombre": "ro", "permisos": "solo_lectura"}, headers=h).get_json()["data"]["token"])
    r = cliente.post("/api/v1/proyectos", json={"nombre": "x"}, headers=ro)
    assert r.status_code == 403 and r.get_json()["codigo"] == "token_solo_lectura"
    r = cliente.get("/api/v1/sync?cursor=-3", headers=h)
    assert r.status_code == 400 and r.get_json()["codigo"] == "cursor_invalido" and r.get_json()["campo"] == "cursor"


def test_un_error_interno_en_la_api_es_json_con_500(cliente, monkeypatch):
    h, _ = _usuario(cliente, "i@ejemplo.com")
    monkeypatch.setattr(db, "listar_categorias", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = cliente.get("/api/v1/proyectos", headers=h)
    assert r.status_code == 500 and r.get_json()["ok"] is False and r.get_json()["codigo"] == "error_interno"


def test_version_etag_y_304(cliente):
    h, _ = _usuario(cliente, "v@ejemplo.com")
    cliente.post("/api/v1/notas", json={"texto": "hola"}, headers=h)
    r = cliente.get("/api/v1/notas", headers=h)
    assert r.headers["X-API-Version"].startswith("1.") and r.headers["ETag"] and r.headers["Cache-Control"] == "private, no-cache"
    r2 = cliente.get("/api/v1/notas", headers={**h, "If-None-Match": r.headers["ETag"]})
    assert r2.status_code == 304 and r2.get_data() == b"" and r2.headers["ETag"] == r.headers["ETag"]
    cliente.post("/api/v1/notas", json={"texto": "otra"}, headers=h)                         # cambia el contenido: ya no hay 304
    r3 = cliente.get("/api/v1/notas", headers={**h, "If-None-Match": r.headers["ETag"]})
    assert r3.status_code == 200 and r3.headers["ETag"] != r.headers["ETag"]
    assert cliente.post("/api/v1/notas", json={"texto": "x"}, headers=h).headers.get("ETag") is None   # solo lecturas


def test_campos_limita_lo_que_se_devuelve(cliente):
    h, _ = _usuario(cliente, "c@ejemplo.com")
    cliente.post("/api/v1/notas", json={"texto": "con título"}, headers=h)
    filas = cliente.get("/api/v1/notas?campos=id,texto", headers=h).get_json()["data"]
    assert set(filas[0]) == {"id", "texto"}
    una = cliente.get(f"/api/v1/notas/{filas[0]['id']}?campos=id", headers=h).get_json()["data"]
    assert una == {"id": filas[0]["id"]}


def test_paginacion_de_notas_en_sql_con_total(cliente):
    h, _ = _usuario(cliente, "p@ejemplo.com")
    for i in range(5):
        cliente.post("/api/v1/notas", json={"texto": f"nota {i}"}, headers=h)
    r = cliente.get("/api/v1/notas?limit=2&offset=4", headers=h)
    assert len(r.get_json()["data"]) == 1 and r.headers["X-Total-Count"] == "5"
    assert cliente.get("/api/v1/notas?q=nota 3", headers=h).headers["X-Total-Count"] == "1"


# --- Límite por usuario ---------------------------------------------------------------------------------------

def test_limite_de_peticiones_por_usuario_con_cabeceras(cliente, monkeypatch):
    monkeypatch.setattr(auth, "API_LIMITE_POR_MINUTO", 3)
    h, _ = _usuario(cliente, "l@ejemplo.com")
    auth.reiniciar_limite_api()
    r = cliente.get("/api/v1/notas", headers=h)
    assert (r.headers["X-RateLimit-Limit"], r.headers["X-RateLimit-Remaining"]) == ("3", "2") and int(r.headers["X-RateLimit-Reset"]) >= 1
    cliente.get("/api/v1/notas", headers=h); cliente.get("/api/v1/notas", headers=h)
    r = cliente.get("/api/v1/notas", headers=h)
    assert r.status_code == 429 and r.get_json()["codigo"] == "limite_excedido" and int(r.headers["Retry-After"]) >= 1
    otro, _ = _usuario(cliente, "l2@ejemplo.com")
    assert cliente.get("/api/v1/notas", headers=otro).status_code == 200                   # el límite es por usuario


# --- Idempotencia -----------------------------------------------------------------------------------------------

def test_idempotency_key_evita_duplicados_en_reintentos(cliente):
    h, _ = _usuario(cliente, "d@ejemplo.com")
    k = {**h, "Idempotency-Key": "abc-123"}
    r1 = cliente.post("/api/v1/notas", json={"texto": "una sola vez"}, headers=k)
    r2 = cliente.post("/api/v1/notas", json={"texto": "una sola vez"}, headers=k)
    assert r1.status_code == r2.status_code == 201 and r1.get_json() == r2.get_json()
    assert r2.headers["Idempotent-Replay"] == "true" and "Idempotent-Replay" not in r1.headers
    assert len(cliente.get("/api/v1/notas", headers=h).get_json()["data"]) == 1
    r3 = cliente.post("/api/v1/notas", json={"texto": "distinta"}, headers=k)
    assert r3.status_code == 422 and r3.get_json()["codigo"] == "idempotencia_conflicto"
    cliente.post("/api/v1/notas", json={"texto": "sin clave"}, headers=h)
    cliente.post("/api/v1/notas", json={"texto": "sin clave"}, headers=h)
    assert len(cliente.get("/api/v1/notas", headers=h).get_json()["data"]) == 3          # sin clave, cada POST crea


def test_idempotencia_es_por_usuario_y_en_curso_da_409(cliente):
    h1, u1 = _usuario(cliente, "d1@ejemplo.com")
    h2, _ = _usuario(cliente, "d2@ejemplo.com")
    cliente.post("/api/v1/notas", json={"texto": "a"}, headers={**h1, "Idempotency-Key": "k"})
    r = cliente.post("/api/v1/notas", json={"texto": "a"}, headers={**h2, "Idempotency-Key": "k"})
    assert r.status_code == 201 and "Idempotent-Replay" not in r.headers                    # otra persona, misma clave: no choca
    assert db.idempotencia_reservar(u1, "pendiente", "h") == ("nuevo",)
    assert db.idempotencia_reservar(u1, "pendiente", "h") == ("en_curso",)
    db.idempotencia_liberar(u1, "pendiente")
    assert db.idempotencia_reservar(u1, "pendiente", "h") == ("nuevo",)


def test_un_error_de_servidor_no_se_queda_guardado_como_respuesta(cliente, monkeypatch):
    h, u = _usuario(cliente, "d5@ejemplo.com")
    k = {**h, "Idempotency-Key": "fallo"}
    original = db.crear_categoria
    monkeypatch.setattr(db, "crear_categoria", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cliente.post("/api/v1/proyectos", json={"nombre": "P"}, headers=k).status_code == 500
    monkeypatch.setattr(db, "crear_categoria", original)
    assert cliente.post("/api/v1/proyectos", json={"nombre": "P"}, headers=k).status_code == 201     # se puede reintentar


# --- Sincronización incremental -----------------------------------------------------------------------------------

def test_sync_flujo_completo_con_notas_proyectos_y_borrados(cliente):
    h, u = _usuario(cliente, "s@ejemplo.com")
    cursor0 = cliente.get("/api/v1/sync", headers=h).get_json()["data"]["cursor"]
    nota = cliente.post("/api/v1/notas", json={"texto": "primera"}, headers=h).get_json()["data"]["id"]
    proyecto = cliente.post("/api/v1/proyectos", json={"nombre": "P1"}, headers=h).get_json()["data"]["id"]
    d = cliente.get(f"/api/v1/sync?cursor={cursor0}", headers=h).get_json()["data"]
    assert [n["id"] for n in d["cambios"]["notas"]] == [nota] and [p["id"] for p in d["cambios"]["proyectos"]] == [proyecto]
    assert d["eliminados"] == {} and not d["hay_mas"] and not d["reiniciar"] and d["cursor"] > cursor0
    # sin cambios nuevos: vacío y mismo cursor
    d2 = cliente.get(f"/api/v1/sync?cursor={d['cursor']}", headers=h).get_json()["data"]
    assert d2["cambios"] == {} and d2["eliminados"] == {} and d2["cursor"] == d["cursor"]
    # editar + fijar + borrar (papelera) la misma nota -> solo cuenta el último estado: eliminada
    cliente.put(f"/api/v1/notas/{nota}", json={"texto": "editada"}, headers=h)
    cliente.post(f"/api/v1/notas/{nota}/fijar", json={"fijada": True}, headers=h)
    cliente.delete(f"/api/v1/notas/{nota}", headers=h)
    d3 = cliente.get(f"/api/v1/sync?cursor={d['cursor']}", headers=h).get_json()["data"]
    assert d3["eliminados"] == {"notas": [nota]} and "notas" not in d3["cambios"]
    # restaurar de la papelera -> vuelve como cambio
    cliente.post(f"/api/v1/papelera/nota/{nota}/restaurar", headers=h)
    d4 = cliente.get(f"/api/v1/sync?cursor={d3['cursor']}", headers=h).get_json()["data"]
    assert [n["id"] for n in d4["cambios"]["notas"]] == [nota]


def test_sync_aisla_usuarios_y_reparte_tareas_asignadas(cliente):
    h1, u1 = _usuario(cliente, "s1@ejemplo.com")
    h2, u2 = _usuario(cliente, "s2@ejemplo.com")
    t = db.crear_tenant("Despacho sync")
    db.asignar_tenant(u1, t); db.asignar_tenant(u2, t)
    c1, c2 = (cliente.get("/api/v1/sync", headers=h).get_json()["data"]["cursor"] for h in (h1, h2))
    cliente.post("/api/v1/notas", json={"texto": "privada"}, headers=h1)
    assert cliente.get(f"/api/v1/sync?cursor={c2}", headers=h2).get_json()["data"]["cambios"] == {}
    tarea = cliente.post("/api/v1/tareas-outlook", json={"asunto": "Para ti"}, headers=h1).get_json()["data"]["id"]
    cliente.post(f"/api/v1/tareas-outlook/{tarea}/asignar", json={"companero_id": u2}, headers=h1)
    d = cliente.get(f"/api/v1/sync?cursor={c2}", headers=h2).get_json()["data"]
    assert [x["id"] for x in d["cambios"]["tareas_outlook"]] == [tarea] and "notas" not in d["cambios"]
    cliente.post(f"/api/v1/tareas-outlook/{tarea}/asignar", json={}, headers=h1)                  # se la quitan
    d2 = cliente.get(f"/api/v1/sync?cursor={d['cursor']}", headers=h2).get_json()["data"]
    assert d2["eliminados"] == {"tareas_outlook": [tarea]}


def test_sync_pagina_y_pide_reiniciar_si_el_cursor_caduco(cliente):
    h, u = _usuario(cliente, "sp@ejemplo.com")
    c0 = cliente.get("/api/v1/sync", headers=h).get_json()["data"]["cursor"]
    for i in range(5):
        cliente.post("/api/v1/notas", json={"texto": f"n{i}"}, headers=h)
    d = cliente.get(f"/api/v1/sync?cursor={c0}&limit=2", headers=h).get_json()["data"]
    assert len(d["cambios"]["notas"]) == 2 and d["hay_mas"]
    vistos = len(d["cambios"]["notas"]); cur = d["cursor"]
    while d["hay_mas"]:
        d = cliente.get(f"/api/v1/sync?cursor={cur}&limit=2", headers=h).get_json()["data"]
        vistos += len(d["cambios"].get("notas", [])); cur = d["cursor"]
    assert vistos == 5
    conn = db.get_connection()
    conn.execute("UPDATE api_cambios SET creado_en = ?", ((datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S"),))
    db._purgar_cambios(conn); conn.commit(); conn.close()
    r = cliente.get(f"/api/v1/sync?cursor={c0}", headers=h).get_json()["data"]
    assert r["reiniciar"] is True and r["cursor"] >= cur
    assert cliente.get(f"/api/v1/sync?cursor={r['cursor']}", headers=h).get_json()["data"]["reiniciar"] is False


def test_openapi_y_docs_incluyen_sync(cliente):
    assert "/api/v1/sync" in cliente.get("/api/v1/openapi.json").get_json()["paths"]
