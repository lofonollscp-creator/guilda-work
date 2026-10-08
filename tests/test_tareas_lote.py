"""Acciones en lote sobre tareas (lista general y proyecto): permisos por tarea y resultado fiable."""
from datetime import date, timedelta

from app import db
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_proyectos_paginas import _otro_cliente


def _equipo(*emails):
    tenant = db.crear_tenant(f"Despacho lote {emails[0]}")
    ids = []
    for e in emails:
        u = db.crear_usuario(e, "contrasena123")
        db.asignar_tenant(u, tenant)
        ids.append(u)
    return tenant, ids


def test_acciones_basicas_sobre_tareas_propias():
    _, (ana, luis) = _equipo("lt-1@x.com", "lt-2@x.com")
    p1, p2 = db.crear_categoria(ana, "P1"), db.crear_categoria(ana, "P2")
    a, b, c = (db.crear_tarea_outlook(ana, n, categoria_id=p1) for n in "abc")
    assert db.accion_en_lote(ana, [a, b, c], "prioridad", "alta") == {"ok": 3, "fallos": 0}
    assert {db.obtener_tarea_outlook(ana, t)["prioridad"] for t in (a, b, c)} == {"alta"}
    assert db.accion_en_lote(ana, [a, b], "proyecto", str(p2)) == {"ok": 2, "fallos": 0}
    assert [db.obtener_tarea_outlook(ana, t)["categoria_id"] for t in (a, b, c)] == [p2, p2, p1]
    assert db.accion_en_lote(ana, [a, b], "proyecto", "") == {"ok": 2, "fallos": 0} and db.obtener_tarea_outlook(ana, a)["categoria_id"] is None
    manana = (date.today() + timedelta(days=1)).isoformat()
    assert db.accion_en_lote(ana, [a, b, c], "fecha", manana)["ok"] == 3 and db.obtener_tarea_outlook(ana, c)["fecha_vencimiento"] == manana
    assert db.accion_en_lote(ana, [a, b, c], "fecha", "")["ok"] == 3 and db.obtener_tarea_outlook(ana, c)["fecha_vencimiento"] is None
    assert db.accion_en_lote(ana, [a, b], "asignar", str(luis)) == {"ok": 2, "fallos": 0} and db.obtener_tarea_outlook(ana, a)["asignada_a"] == luis
    assert db.accion_en_lote(ana, [a, b], "asignar", "")["ok"] == 2 and db.obtener_tarea_outlook(ana, a)["asignada_a"] is None
    assert db.accion_en_lote(ana, [a, b], "estado", "en_progreso")["ok"] == 2 and db.obtener_tarea_outlook(ana, a)["estado"] == "en_progreso"
    assert db.accion_en_lote(ana, [a, b, c], "completar") == {"ok": 3, "fallos": 0} and db.obtener_tarea_outlook(ana, c)["estado"] == "completada"


def test_lo_que_no_se_puede_cuenta_como_fallo():
    _, (ana, luis, eva) = _equipo("lt-3@x.com", "lt-4@x.com", "lt-5@x.com")
    ajena_tenant = db.crear_usuario("lt-6@x.com", "contrasena123")
    suya = db.crear_tarea_outlook(ana, "Mía")
    privada_de_luis = db.crear_tarea_outlook(luis, "Privada de Luis")
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, eva, "observa")
    db.compartir_proyecto(ana, p, luis, "colabora")
    del_proyecto = db.crear_tarea_en_proyecto(ana, p, "Del proyecto")
    r = db.accion_en_lote(ana, [suya, privada_de_luis, 99999, "x", None, suya], "prioridad", "alta")
    assert r == {"ok": 1, "fallos": 2}                                                       # la privada y la inexistente fallan; «x», None y el duplicado se descartan
    assert db.obtener_tarea_outlook(luis, privada_de_luis)["prioridad"] == "normal"
    assert db.accion_en_lote(eva, [del_proyecto], "prioridad", "alta") == {"ok": 0, "fallos": 1}      # observador
    assert db.accion_en_lote(ajena_tenant, [suya], "completar") == {"ok": 0, "fallos": 1}
    assert db.accion_en_lote(ana, [suya], "prioridad", "urgentísima") == {"ok": 0, "fallos": 1}
    assert db.accion_en_lote(ana, [suya], "estado", "inventado") == {"ok": 0, "fallos": 1}
    assert db.accion_en_lote(ana, [suya], "fecha", "mañana") == {"ok": 0, "fallos": 1}
    assert db.accion_en_lote(ana, [suya], "asignar", str(ajena_tenant)) == {"ok": 0, "fallos": 1}      # de otro despacho
    ajeno_p = db.crear_categoria(luis, "De Luis")
    assert db.accion_en_lote(ana, [suya], "proyecto", str(ajeno_p)) == {"ok": 0, "fallos": 1}          # proyecto que no es suyo: no se mueve
    assert db.obtener_tarea_outlook(ana, suya)["categoria_id"] is None
    # un colaborador no cambia el proyecto de una tarea que no es suya, pero sí su prioridad
    assert db.accion_en_lote(luis, [del_proyecto], "proyecto", str(ajeno_p)) == {"ok": 0, "fallos": 1}
    assert db.accion_en_lote(luis, [del_proyecto], "prioridad", "baja") == {"ok": 1, "fallos": 0}
    try:
        db.accion_en_lote(ana, [suya], "borrar_todo")
        assert False
    except ValueError:
        pass


def test_una_tarea_bloqueada_no_se_completa_en_lote():
    _, (ana,) = _equipo("lt-7@x.com")
    previa, espera = db.crear_tarea_outlook(ana, "Previa"), db.crear_tarea_outlook(ana, "Espera")
    conn = db.get_connection()
    conn.execute("INSERT INTO tareas_dependencias (tarea_id, depende_de_id) VALUES (?, ?)", (espera, previa))
    conn.commit()
    conn.close()
    assert db.accion_en_lote(ana, [espera], "completar") == {"ok": 0, "fallos": 1}
    assert db.accion_en_lote(ana, [espera, previa], "completar") == {"ok": 1, "fallos": 1}            # se procesan en orden: la que espera aún estaba bloqueada
    assert db.accion_en_lote(ana, [espera], "completar") == {"ok": 1, "fallos": 0}                    # y ahora ya no


def test_limite_de_tareas_por_lote():
    _, (ana,) = _equipo("lt-8@x.com")
    ids = [db.crear_tarea_outlook(ana, f"T{i}") for i in range(db.MAX_TAREAS_LOTE + 5)]
    assert db.accion_en_lote(ana, ids, "prioridad", "alta") == {"ok": db.MAX_TAREAS_LOTE, "fallos": 0}


def test_pantalla_lista_marcar_y_aplicar(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "lt-9@x.com", "contrasena123")
    tenant = db.crear_tenant("Despacho lote pantalla")
    db.asignar_tenant(uid, tenant)
    p = db.crear_categoria(uid, "Destino")
    a, b = db.crear_tarea_outlook(uid, "Primera"), db.crear_tarea_outlook(uid, "Segunda")
    html = cliente.get("/tareas/").get_data(as_text=True)
    assert 'id="lote-form"' in html and html.count('class="lote-casilla"') == 2 and 'form="lote-form"' in html and "Mover a un proyecto" in html
    r = cliente.post("/tareas/lote", data={"ids": [a, b], "accion": "proyecto", "valor_proyecto": str(p), "valor_estado": "x", "volver_a": "/tareas/?prioridad=normal"})
    assert r.status_code == 302 and r.headers["Location"].startswith("/tareas/?prioridad=normal&aviso=")
    assert [db.obtener_tarea_outlook(uid, t)["categoria_id"] for t in (a, b)] == [p, p]
    assert "2%20tareas%20actualizadas" in r.headers["Location"]
    html = cliente.get(r.headers["Location"]).get_data(as_text=True)
    assert "2 tareas actualizadas." in html
    # redirección abierta: solo rutas propias
    r = cliente.post("/tareas/lote", data={"ids": [a], "accion": "completar", "volver_a": "//evil.example/x"})
    assert r.headers["Location"].startswith("/tareas/?aviso=") and db.obtener_tarea_outlook(uid, a)["estado"] == "completada"
    r = cliente.post("/tareas/lote", data={"ids": [a], "accion": "inventada", "volver_a": "https://evil.example"})
    assert r.headers["Location"].startswith("/tareas/?aviso=")
    assert "No%20has%20marcado" in cliente.post("/tareas/lote", data={"accion": "completar"}).headers["Location"]


def test_proyecto_lote_solo_toca_sus_tareas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "lt-10@x.com", "contrasena123")
    tenant = db.crear_tenant("Despacho lote proyecto")
    db.asignar_tenant(uid, tenant)
    p, otro = db.crear_categoria(uid, "P"), db.crear_categoria(uid, "Otro")
    s1, s2 = db.crear_seccion(uid, p, "Uno"), db.crear_seccion(uid, p, "Dos")
    a, b = db.crear_tarea_en_proyecto(uid, p, "A", seccion_id=s1), db.crear_tarea_en_proyecto(uid, p, "B", seccion_id=s1)
    fuera = db.crear_tarea_en_proyecto(uid, otro, "Fuera", seccion_id=None)
    html = cliente.get(f"/proyecto/{p}/lista").get_data(as_text=True)
    assert f"/proyecto/{p}/lote" in html and "Mover a una sección" in html and html.count('class="lote-casilla"') == 2
    r = cliente.post(f"/proyecto/{p}/lote", data={"ids": [a, b, fuera], "accion": "seccion", "valor_seccion": str(s2)})
    assert r.status_code == 302 and "aviso=" in r.headers["Location"]
    assert [db.obtener_tarea_outlook(uid, t)["seccion_id"] for t in (a, b, fuera)] == [s2, s2, None]
    assert "2 tareas actualizadas" in cliente.get(r.headers["Location"]).get_data(as_text=True)
    cliente.post(f"/proyecto/{p}/lote", data={"ids": [a], "accion": "prioridad", "valor_prioridad": "alta"})
    assert db.obtener_tarea_outlook(uid, a)["prioridad"] == "alta"
    with _otro_cliente("lt-11@x.com") as (eva, id_eva):
        db.asignar_tenant(id_eva, tenant)
        db.compartir_proyecto(uid, p, id_eva, "observa")
        assert eva.post(f"/proyecto/{p}/lote", data={"ids": [a], "accion": "completar"}).status_code == 403
        assert 'id="lote-form"' not in eva.get(f"/proyecto/{p}/lista").get_data(as_text=True)
    with _otro_cliente("lt-12@x.com") as (ajeno, id_ajeno):
        db.asignar_tenant(id_ajeno, db.crear_tenant("Ajeno lote"))
        assert ajeno.post(f"/proyecto/{p}/lote", data={"ids": [a], "accion": "completar"}).status_code == 404
