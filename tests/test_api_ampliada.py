"""API REST ampliada (`app/rutas_api_ampliada.py`): notas/tareas, proyectos, checklist, asignación, «mi día», correo,
notificaciones, búsqueda, consumo de IA y comunicados."""
from app import comunicados, db, ia_consumo, openapi
from tests.test_rutas_api import _auth, _registrar


def _usuario(cliente, email):
    datos = _registrar(cliente, email=email)
    return _auth(datos["token"]), datos["usuario"]["id"]


def test_listados_de_notas_y_tareas_con_filtros_y_paginacion(cliente):
    h, _ = _usuario(cliente, "n@ejemplo.com")
    p = cliente.post("/api/v1/proyectos", json={"nombre": "Alfa", "color": "#112233"}, headers=h).get_json()["data"]["id"]
    for i in range(3):
        cliente.post("/api/v1/notas", json={"texto": f"nota {i} rojo" if i else "otra cosa", "categoria_id": p}, headers=h)
    r = cliente.get("/api/v1/notas", headers=h)
    assert r.status_code == 200 and len(r.get_json()["data"]) == 3 and r.headers["X-Total-Count"] == "3"
    r = cliente.get("/api/v1/notas?limit=2&offset=1", headers=h)
    assert len(r.get_json()["data"]) == 2 and r.headers["X-Total-Count"] == "3"
    assert len(cliente.get("/api/v1/notas?q=rojo", headers=h).get_json()["data"]) == 2
    assert len(cliente.get(f"/api/v1/notas?proyecto_id={p}", headers=h).get_json()["data"]) == 3
    nota_id = cliente.get("/api/v1/notas", headers=h).get_json()["data"][0]["id"]
    assert cliente.get(f"/api/v1/notas/{nota_id}", headers=h).status_code == 200
    assert cliente.get("/api/v1/notas/9999", headers=h).status_code == 404
    assert cliente.get("/api/v1/tareas", headers=h).get_json()["data"] == []
    assert cliente.get("/api/v1/notas").status_code == 401


def test_fijar_nota_y_aislamiento(cliente):
    h1, _ = _usuario(cliente, "f1@ejemplo.com")
    h2, _ = _usuario(cliente, "f2@ejemplo.com")
    nota = cliente.post("/api/v1/notas", json={"texto": "x"}, headers=h1).get_json()["data"]["id"]
    assert cliente.post(f"/api/v1/notas/{nota}/fijar", json={"fijada": True}, headers=h1).get_json()["data"]["fijada"] == 1
    assert cliente.post(f"/api/v1/notas/{nota}/fijar", json={"fijada": False}, headers=h1).get_json()["data"]["fijada"] == 0
    assert cliente.post(f"/api/v1/notas/{nota}/fijar", headers=h2).status_code == 404
    assert cliente.get(f"/api/v1/notas/{nota}", headers=h2).status_code == 404


def test_proyectos_crud(cliente):
    h, _ = _usuario(cliente, "p@ejemplo.com")
    assert cliente.post("/api/v1/proyectos", json={"nombre": "  "}, headers=h).status_code == 400
    p = cliente.post("/api/v1/proyectos", json={"nombre": "Uno"}, headers=h).get_json()["data"]["id"]
    assert cliente.put(f"/api/v1/proyectos/{p}", json={"nombre": "Dos"}, headers=h).get_json()["data"]["nombre"] == "Dos"
    assert [x["nombre"] for x in cliente.get("/api/v1/proyectos", headers=h).get_json()["data"]] == ["Dos"]
    assert cliente.delete(f"/api/v1/proyectos/{p}", headers=h).status_code == 200
    assert cliente.get("/api/v1/proyectos", headers=h).get_json()["data"] == []
    assert cliente.put("/api/v1/proyectos/999", json={"nombre": "x"}, headers=h).status_code == 404


def test_checklist_asignacion_y_mi_dia(cliente):
    h1, u1 = _usuario(cliente, "d1@ejemplo.com")
    h2, u2 = _usuario(cliente, "d2@ejemplo.com")
    h3, u3 = _usuario(cliente, "d3@ejemplo.com")
    t = db.crear_tenant("Despacho API")
    db.asignar_tenant(u1, t); db.asignar_tenant(u2, t)
    tarea = cliente.post("/api/v1/tareas-outlook", json={"asunto": "Revisar", "fecha_vencimiento": "2020-01-01"}, headers=h1).get_json()["data"]["id"]
    r = cliente.post(f"/api/v1/tareas-outlook/{tarea}/checklist", json={"texto": "Paso 1"}, headers=h1)
    assert r.status_code == 201
    item = r.get_json()["data"]["id"]
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/checklist", json={"texto": " "}, headers=h1).status_code == 400
    assert cliente.post(f"/api/v1/checklist/{item}/alternar", headers=h1).status_code == 200
    detalle = cliente.get(f"/api/v1/tareas-outlook/{tarea}", headers=h1).get_json()["data"]
    assert detalle["checklist"][0]["hecha"] == 1 and detalle["porcentaje_completado"] == 100
    assert cliente.get(f"/api/v1/tareas-outlook/{tarea}", headers=h3).status_code == 404            # otro despacho
    assert [c["id"] for c in cliente.get("/api/v1/companeros", headers=h1).get_json()["data"]] == [u2]
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/asignar", json={"companero_id": u3}, headers=h1).status_code == 403
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/asignar", json={"companero_id": u2}, headers=h1).status_code == 200
    assert cliente.get(f"/api/v1/tareas-outlook/{tarea}", headers=h2).status_code == 200            # el asignado la ve
    dia = cliente.get("/api/v1/mi-dia", headers=h2).get_json()["data"]
    assert set(dia) and any(tarea == x["id"] for filas in dia.values() for x in filas)
    assert cliente.post(f"/api/v1/tareas-outlook/{tarea}/asignar", json={}, headers=h1).status_code == 200


def test_correo_conversacion_tarea_nota_y_aislamiento(cliente):
    h1, u1 = _usuario(cliente, "c1@ejemplo.com")
    h2, _ = _usuario(cliente, "c2@ejemplo.com")
    cuenta = db.crear_cuenta_correo(u1, "T", "imap", "h", 993, "c1@ejemplo.com")
    m = db.guardar_mensaje_correo(cuenta, "1", "Factura octubre", "cli@x.com", "c1@ejemplo.com", "2026-10-01", "Adjunto la factura", None)
    assert [x["id"] for x in cliente.get(f"/api/v1/correo/mensajes/{m}/conversacion", headers=h1).get_json()["data"]] == [m]
    t = cliente.post(f"/api/v1/correo/mensajes/{m}/tarea", json={"fecha_vencimiento": "2026-11-01"}, headers=h1)
    assert t.status_code == 201 and t.get_json()["data"]["asunto"] == "Factura octubre" and t.get_json()["data"]["mensaje_correo_id"] == m
    n = cliente.post(f"/api/v1/correo/mensajes/{m}/nota", headers=h1)
    assert n.status_code == 201 and n.get_json()["data"]["titulo"] == "Factura octubre"
    for ruta in ("conversacion",):
        assert cliente.get(f"/api/v1/correo/mensajes/{m}/{ruta}", headers=h2).status_code == 404
    assert cliente.post(f"/api/v1/correo/mensajes/{m}/tarea", headers=h2).status_code == 404
    assert cliente.get("/api/v1/correo/programados", headers=h1).get_json()["data"] == []
    assert cliente.get("/api/v1/correo/seguimientos", headers=h1).get_json()["data"] == []
    assert cliente.get("/api/v1/correo/plantillas", headers=h1).status_code == 200
    assert cliente.delete("/api/v1/correo/programados/999", headers=h1).status_code == 404


def test_notificaciones_busqueda_ia_y_comunicados(cliente):
    h, u = _usuario(cliente, "o@ejemplo.com")
    t = db.crear_tenant("Despacho O")
    db.asignar_tenant(u, t)
    db.crear_notificacion(u, "aviso", "Hola", "cuerpo", None)
    r = cliente.get("/api/v1/notificaciones", headers=h).get_json()["data"]
    assert r["no_leidas"] == 1 and r["notificaciones"][0]["titulo"] == "Hola"
    cliente.post("/api/v1/notificaciones/leidas", headers=h)
    assert cliente.get("/api/v1/notificaciones", headers=h).get_json()["data"]["no_leidas"] == 0
    assert cliente.get("/api/v1/buscar", headers=h).status_code == 400
    assert cliente.get("/api/v1/buscar?q=zzz", headers=h).status_code == 200
    ia_consumo.fijar_limite(t, 5)
    ia_consumo.reservar(u)
    c = cliente.get("/api/v1/ia/consumo", headers=h).get_json()["data"]
    assert (c["usadas"], c["limite"], c["ilimitado"]) == (1, 5, False)
    info = comunicados.crear("Novedad"); crit = comunicados.crear("Caída", nivel="critico")
    lista = cliente.get("/api/v1/comunicados", headers=h).get_json()["data"]
    assert [x["titulo"] for x in lista] == ["Caída", "Novedad"]
    assert cliente.post(f"/api/v1/comunicados/{crit}/cerrar", headers=h).status_code == 403
    assert cliente.post(f"/api/v1/comunicados/{info}/cerrar", headers=h).status_code == 200
    assert [x["titulo"] for x in cliente.get("/api/v1/comunicados", headers=h).get_json()["data"]] == ["Caída"]


def test_token_de_solo_lectura_solo_puede_leer_lo_nuevo(cliente):
    h, u = _usuario(cliente, "ro@ejemplo.com")
    tok = cliente.post("/api/v1/tokens", json={"nombre": "ro", "permisos": "solo_lectura"}, headers=h).get_json()["data"]["token"]
    ro = _auth(tok)
    assert cliente.get("/api/v1/notas", headers=ro).status_code == 200
    assert cliente.post("/api/v1/proyectos", json={"nombre": "x"}, headers=ro).status_code == 403
    assert cliente.post("/api/v1/notificaciones/leidas", headers=ro).status_code == 403


def test_openapi_incluye_las_rutas_nuevas(cliente):
    spec = cliente.get("/api/v1/openapi.json").get_json()
    for ruta in ("/api/v1/proyectos", "/api/v1/mi-dia", "/api/v1/buscar", "/api/v1/tareas-outlook/{tarea_id}/asignar", "/api/v1/comunicados"):
        assert ruta in spec["paths"], ruta
    assert "get" in spec["paths"]["/api/v1/notas"] and "post" in spec["paths"]["/api/v1/notas"]
