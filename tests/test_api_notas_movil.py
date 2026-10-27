"""Notas en la app móvil (API 1.9): título y fijada al crear y editar, notas compartidas (listar, leer, editar como colaborador, compartir y dejar de compartir)."""
from app import db
from tests.test_rutas_api import _auth, _registrar


def _dos_companeros(cliente):
    a, b = _registrar(cliente, email="dueno-n@ejemplo.com"), _registrar(cliente, email="otra-n@ejemplo.com")
    t = db.crear_tenant("Despacho Notas")
    db.asignar_tenant(a["usuario"]["id"], t)
    db.asignar_tenant(b["usuario"]["id"], t)
    return (_auth(a["token"]), a["usuario"]["id"]), (_auth(b["token"]), b["usuario"]["id"])


def test_crear_y_editar_con_titulo_y_fijada(cliente):
    (h, _), _ = _dos_companeros(cliente)
    n = cliente.post("/api/v1/notas", json={"texto": "cuerpo", "titulo": "Reunión", "fijada": True}, headers=h).get_json()["data"]
    assert (n["titulo"], n["fijada"]) == ("Reunión", 1)
    # solo título, sin texto
    s = cliente.post("/api/v1/notas", json={"titulo": "Solo título"}, headers=h)
    assert s.status_code == 201
    assert cliente.post("/api/v1/notas", json={"texto": " ", "titulo": " "}, headers=h).status_code == 400
    # editar solo el título y fijada: el texto se queda
    e = cliente.put(f"/api/v1/notas/{n['id']}", json={"titulo": "Reunión lunes", "fijada": False}, headers=h).get_json()["data"]
    assert (e["texto"], e["titulo"], e["fijada"]) == ("cuerpo", "Reunión lunes", 0)
    # quitar el título
    assert cliente.put(f"/api/v1/notas/{n['id']}", json={"titulo": ""}, headers=h).get_json()["data"]["titulo"] is None
    # vaciarla del todo no se puede; mandar nada tampoco
    assert cliente.put(f"/api/v1/notas/{n['id']}", json={"texto": ""}, headers=h).status_code == 400
    assert cliente.put(f"/api/v1/notas/{n['id']}", json={}, headers=h).status_code == 400


def test_notas_compartidas_listar_leer_editar_y_salir(cliente):
    (h1, _), (h2, u2) = _dos_companeros(cliente)
    nota = cliente.post("/api/v1/notas", json={"texto": "para dos", "titulo": "Plan"}, headers=h1).get_json()["data"]["id"]
    propia = cliente.post("/api/v1/notas", json={"texto": "mía"}, headers=h2).get_json()["data"]["id"]
    # sin compartir, la otra persona ni la ve ni la lee
    assert cliente.get(f"/api/v1/notas/{nota}", headers=h2).status_code == 404
    assert [x["id"] for x in cliente.get("/api/v1/notas?compartidas=incluir", headers=h2).get_json()["data"]] == [propia]
    # compartir (solo el dueño; rol válido; compañero del despacho)
    assert cliente.post(f"/api/v1/notas/{nota}/compartir", json={"usuario_id": u2, "rol": "jefe"}, headers=h1).status_code == 400
    assert cliente.post(f"/api/v1/notas/{nota}/compartir", json={}, headers=h1).status_code == 400
    assert cliente.post(f"/api/v1/notas/{nota}/compartir", json={"usuario_id": u2, "rol": "observa"}, headers=h2).status_code == 404
    r = cliente.post(f"/api/v1/notas/{nota}/compartir", json={"usuario_id": u2, "rol": "observa"}, headers=h1)
    assert r.status_code == 200 and [(p["usuario_id"], p["rol"]) for p in r.get_json()["data"]] == [(u2, "observa")]
    # listas: incluir / solo, con rol y contadores; el total acompaña
    inc = cliente.get("/api/v1/notas?compartidas=incluir", headers=h2)
    assert {x["id"]: x["rol"] for x in inc.get_json()["data"]} == {nota: "observa", propia: "dueno"} and inc.headers["X-Total-Count"] == "2"
    solo = cliente.get("/api/v1/notas?compartidas=solo", headers=h2)
    assert [x["id"] for x in solo.get_json()["data"]] == [nota] and solo.headers["X-Total-Count"] == "1"
    assert [x["n_participantes"] for x in cliente.get("/api/v1/notas", headers=h1).get_json()["data"] if x["id"] == nota] == [1]
    # detalle: rol, participantes; quien observa no edita
    d = cliente.get(f"/api/v1/notas/{nota}", headers=h2).get_json()["data"]
    assert d["rol"] == "observa" and d["participantes"][0]["usuario_id"] == u2 and d["titulo"] == "Plan"
    assert cliente.put(f"/api/v1/notas/{nota}", json={"texto": "cambio"}, headers=h2).status_code == 404
    # colaborador: edita texto y título, pero no fija
    cliente.post(f"/api/v1/notas/{nota}/compartir", json={"usuario_id": u2, "rol": "colabora"}, headers=h1)
    e = cliente.put(f"/api/v1/notas/{nota}", json={"texto": "cambio", "titulo": "Plan B", "fijada": True}, headers=h2).get_json()["data"]
    assert (e["texto"], e["titulo"], e["fijada"]) == ("cambio", "Plan B", 0)
    assert cliente.get(f"/api/v1/notas/{nota}/participantes", headers=h2).status_code == 200
    # no la puede borrar, pero sí salirse
    assert cliente.delete(f"/api/v1/notas/{nota}", headers=h2).status_code == 404
    assert cliente.delete(f"/api/v1/notas/{nota}/compartir/{u2}", headers=h2).status_code == 200
    assert cliente.get(f"/api/v1/notas/{nota}", headers=h2).status_code == 404
    assert cliente.delete(f"/api/v1/notas/{nota}/compartir/{u2}", headers=h1).status_code == 404  # ya no estaba


def test_borrar_nota_y_restaurar_de_la_papelera(cliente):
    (h, _), _ = _dos_companeros(cliente)
    n = cliente.post("/api/v1/notas", json={"texto": "adiós"}, headers=h).get_json()["data"]["id"]
    assert cliente.delete(f"/api/v1/notas/{n}", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/notas/{n}", headers=h).status_code == 404
    assert cliente.post(f"/api/v1/papelera/nota/{n}/restaurar", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/notas/{n}", headers=h).status_code == 200


def test_papelera_con_tareas_de_la_lista_y_solo_lo_que_esta_en_ella(cliente):
    (h, _), (h2, _) = _dos_companeros(cliente)
    t = cliente.post("/api/v1/tareas-outlook", json={"asunto": "Para borrar"}, headers=h).get_json()["data"]["id"]
    viva = cliente.post("/api/v1/tareas-outlook", json={"asunto": "Sigue viva"}, headers=h).get_json()["data"]["id"]
    n = cliente.post("/api/v1/notas", json={"texto": "cuerpo", "titulo": "Con título"}, headers=h).get_json()["data"]["id"]
    cliente.delete(f"/api/v1/tareas-outlook/{t}", headers=h)
    cliente.delete(f"/api/v1/notas/{n}", headers=h)
    items = {(x["origen"], x["id"]): x for x in cliente.get("/api/v1/papelera", headers=h).get_json()["data"]}
    assert ("tarea_outlook", t) in items and items[("nota", n)]["texto"] == "Con título"
    # lo vivo y lo ajeno no se tocan: 404, no se borra nada
    assert cliente.post(f"/api/v1/papelera/tarea_outlook/{viva}/eliminar-definitivamente", headers=h).status_code == 404
    assert cliente.post(f"/api/v1/papelera/tarea_outlook/{t}/eliminar-definitivamente", headers=h2).status_code == 404
    assert cliente.get(f"/api/v1/tareas-outlook/{viva}", headers=h).status_code == 200
    # restaurar una y eliminar la otra para siempre
    assert cliente.post(f"/api/v1/papelera/tarea_outlook/{t}/restaurar", headers=h).status_code == 200
    assert cliente.get(f"/api/v1/tareas-outlook/{t}", headers=h).status_code == 200
    assert cliente.post(f"/api/v1/papelera/nota/{n}/eliminar-definitivamente", headers=h).status_code == 200
    assert [x for x in cliente.get("/api/v1/papelera", headers=h).get_json()["data"] if x["origen"] == "nota"] == []
