"""Vistas guardadas de la lista de tareas: filtros validados, privadas o compartidas con el despacho."""
from app import db
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_proyectos_paginas import _otro_cliente


def test_los_filtros_se_limpian():
    f = db.filtros_vista_validos({"vista": "mias", "estado": "en_progreso", "prioridad": "alta", "categoria": "IVA", "q": " 303 ", "completadas": "1",
                                  "nombre": "no", "otro": "x"})
    assert f == {"vista": "mias", "estado": "en_progreso", "prioridad": "alta", "categoria": "IVA", "q": "303", "completadas": "1"}
    assert db.filtros_vista_validos({"vista": "todas", "estado": "inventado", "prioridad": "urgente", "completadas": "0", "q": "x" * 500}) == {"q": "x" * 100}
    assert db.filtros_vista_validos({}) == {}


def test_crear_actualizar_limitar_y_eliminar():
    uid = db.crear_usuario("tv-1@x.com", "contrasena123")
    assert db.crear_vista_tareas(uid, "  ", {"estado": "en_progreso"}) is None and db.crear_vista_tareas(uid, "Sin filtros", {"nada": "1"}) is None
    v = db.crear_vista_tareas(uid, "Mis   urgentes", {"prioridad": "alta"})
    assert db.crear_vista_tareas(uid, "Mis urgentes", {"prioridad": "baja", "estado": "esperando"}) == v          # mismo nombre: actualiza
    [vista] = db.listar_vistas_tareas(uid)
    assert vista["nombre"] == "Mis urgentes" and vista["filtros"] == {"prioridad": "baja", "estado": "esperando"} and vista["mia"] and not vista["compartida"]
    for i in range(db.MAX_VISTAS_TAREAS):
        db.crear_vista_tareas(uid, f"V{i}", {"q": str(i)})
    assert db.crear_vista_tareas(uid, "Una más", {"q": "x"}) is None
    otro = db.crear_usuario("tv-1b@x.com", "contrasena123")
    assert db.eliminar_vista_tareas(otro, v) is False and db.eliminar_vista_tareas(uid, v) is True and db.eliminar_vista_tareas(uid, v) is False


def test_compartir_solo_dentro_del_despacho():
    tenant, otro_tenant = db.crear_tenant("Despacho vistas"), db.crear_tenant("Otro despacho vistas")
    ana, luis, ajeno, sin_despacho = (db.crear_usuario(f"tv-{n}@x.com", "contrasena123") for n in "abcd")
    for u, t in ((ana, tenant), (luis, tenant), (ajeno, otro_tenant)):
        db.asignar_tenant(u, t)
    db.crear_vista_tareas(ana, "Compartida", {"estado": "esperando"}, compartida=True)
    db.crear_vista_tareas(ana, "Privada", {"estado": "aplazada"})
    db.crear_vista_tareas(sin_despacho, "Sin despacho", {"estado": "esperando"}, compartida=True)         # sin despacho no se comparte con nadie
    assert [(v["nombre"], v["mia"]) for v in db.listar_vistas_tareas(luis)] == [("Compartida", False)]
    assert db.listar_vistas_tareas(ajeno) == []
    assert [v["compartida"] for v in db.listar_vistas_tareas(sin_despacho)] == [False]
    assert db.eliminar_vista_tareas(luis, db.listar_vistas_tareas(luis)[0]["id"]) is False                    # solo la borra su autora


def test_pantalla_guardar_aplicar_y_borrar(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "tv-2@x.com", "contrasena123")
    tenant = db.crear_tenant("Despacho pantalla vistas")
    db.asignar_tenant(uid, tenant)
    db.crear_tarea_outlook(uid, "Revisar el 303", prioridad="alta")
    db.crear_tarea_outlook(uid, "Llamar", prioridad="baja")
    html = cliente.get("/tareas/?prioridad=alta").get_data(as_text=True)
    assert "Guardar esta vista" in html and "Revisar el 303" in html and "Llamar" not in html
    assert "Guardar esta vista" not in cliente.get("/tareas/").get_data(as_text=True)                        # sin filtros no hay nada que guardar
    r = cliente.post("/tareas/vistas", data={"nombre": "Urgentes", "prioridad": "alta", "estado": "inventado", "compartida": "on", "nombre_x": "z"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/tareas/?prioridad=alta")
    [v] = db.listar_vistas_tareas(uid)
    assert v["filtros"] == {"prioridad": "alta"} and v["compartida"]
    html = cliente.get("/tareas/?prioridad=alta").get_data(as_text=True)
    assert 'aria-current=page' in html and "Urgentes" in html and "Guardar esta vista" not in html and "compartida" in html
    html = cliente.get("/tareas/?prioridad=baja").get_data(as_text=True)
    assert "Urgentes" in html and "Guardar esta vista" in html
    assert "error=" in cliente.post("/tareas/vistas", data={"nombre": "", "prioridad": "alta"}).headers["Location"]
    assert "error=" in cliente.post("/tareas/vistas", data={"nombre": "Vacía"}).headers["Location"]
    with _otro_cliente("tv-3@x.com") as (colega, id_colega):
        db.asignar_tenant(id_colega, tenant)
        html = colega.get("/tareas/").get_data(as_text=True)
        assert "Urgentes" in html and "tv-3@x.com" not in html.split("Urgentes")[0][-200:]
        assert colega.post(f"/tareas/vistas/{v['id']}/eliminar").status_code == 404
    assert cliente.post(f"/tareas/vistas/{v['id']}/eliminar").status_code == 302 and db.listar_vistas_tareas(uid) == []
