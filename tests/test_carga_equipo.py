"""Plan de carga semanal: estimaciones por persona y día frente a la capacidad, visibilidad y reasignar/mover."""
from datetime import date, timedelta

from app import db
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_proyectos_paginas import _otro_cliente

LUNES = date(2026, 10, 5)


def _dia(n):
    return (LUNES + timedelta(days=n)).isoformat()


def _equipo(*emails):
    tenant = db.crear_tenant(f"Despacho carga {emails[0]}")
    ids = []
    for e in emails:
        u = db.crear_usuario(e, "contrasena123")
        db.asignar_tenant(u, tenant)
        ids.append(u)
    return tenant, ids


def _persona(datos, uid):
    return next(p for p in datos["personas"] if p["id"] == uid)


def test_suma_estimaciones_por_persona_y_dia_y_separa_atrasadas_y_sin_fecha():
    _, (ana, luis) = _equipo("cg-1@x.com", "cg-2@x.com")
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, luis, "colabora")
    db.crear_tarea_en_proyecto(ana, p, "Lunes 1", fecha_vencimiento=_dia(0), estimacion_min=120)
    db.crear_tarea_en_proyecto(ana, p, "Lunes 2", fecha_vencimiento=_dia(0) + "T10:00", estimacion_min=90)
    db.crear_tarea_en_proyecto(ana, p, "Lunes sin estimar", fecha_vencimiento=_dia(0))
    db.crear_tarea_en_proyecto(ana, p, "De Luis", fecha_vencimiento=_dia(2), asignada_a=luis, estimacion_min=60)
    db.crear_tarea_en_proyecto(ana, p, "Atrasada", fecha_vencimiento=_dia(-3), estimacion_min=30)
    db.crear_tarea_en_proyecto(ana, p, "Sin fecha", estimacion_min=45)
    db.crear_tarea_en_proyecto(ana, p, "Otra semana", fecha_vencimiento=_dia(9), estimacion_min=600)
    hecha = db.crear_tarea_en_proyecto(ana, p, "Hecha", fecha_vencimiento=_dia(1), estimacion_min=600)
    db.completar_tarea_outlook(ana, hecha)
    d = db.carga_semanal(ana, LUNES)
    a, l = _persona(d, ana), _persona(d, luis)
    lun = a["dias"][_dia(0)]
    assert (lun["min"], lun["n"], lun["sin_estimar"]) == (210, 3, 1)
    assert a["atrasadas"]["min"] == 30 and a["sin_fecha"]["min"] == 45
    assert l["dias"][_dia(2)]["min"] == 60 and a["dias"][_dia(2)]["n"] == 0        # cuenta para quien la tiene asignada
    assert a["semana_min"] == 210 and l["semana_min"] == 60
    assert sum(c["n"] for c in a["dias"].values()) == 3                             # ni la de otra semana ni la completada
    assert [x.isoformat() for x in d["dias"]] == [_dia(i) for i in range(7)]


def test_capacidad_por_defecto_y_segun_la_jornada_del_fichaje():
    _, (ana, luis) = _equipo("cg-3@x.com", "cg-4@x.com")
    conn = db.get_connection()
    conn.execute("INSERT INTO fichaje_datos (usuario_id, jornada_semanal_horas) VALUES (?, 20)", (luis,))
    conn.commit()
    conn.close()
    d = db.carga_semanal(ana, LUNES)
    assert _persona(d, ana)["capacidad_dia_min"] == 480 and _persona(d, luis)["capacidad_dia_min"] == 240
    assert _persona(d, luis)["capacidad_semana_min"] == 1200


def test_solo_se_ve_lo_que_se_puede_ver():
    _, (ana, luis) = _equipo("cg-5@x.com", "cg-6@x.com")
    db.crear_tarea_outlook(luis, "Privada de Luis", fecha_vencimiento=_dia(1), estimacion_min=300)
    db.crear_tarea_outlook(luis, "Para Ana", fecha_vencimiento=_dia(1), asignada_a=ana, estimacion_min=60)
    d = db.carga_semanal(ana, LUNES)
    assert _persona(d, luis)["dias"][_dia(1)]["n"] == 0 and _persona(d, ana)["dias"][_dia(1)]["min"] == 60
    ajeno = db.crear_usuario("cg-7@x.com", "contrasena123")
    assert [p["id"] for p in db.carga_semanal(ajeno, LUNES)["personas"]] == [ajeno]        # otro despacho: ni aparece


def test_los_proyectos_compartidos_se_ven_enteros_y_el_supervisor_los_ve():
    _, (ana, luis, sup) = _equipo("cg-8@x.com", "cg-9@x.com", "cg-10@x.com")
    conn = db.get_connection()
    conn.execute("UPDATE usuarios SET supervisor_tenant = 1 WHERE id = ?", (sup,))
    conn.commit()
    conn.close()
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, luis, "colabora")
    db.crear_tarea_en_proyecto(ana, p, "En el proyecto", fecha_vencimiento=_dia(3), estimacion_min=120)
    for quien in (luis, sup):
        assert _persona(db.carga_semanal(quien, LUNES), ana)["dias"][_dia(3)]["min"] == 120


def test_limita_las_tareas_que_lista_una_celda():
    _, (ana,) = _equipo("cg-11@x.com")
    for i in range(db.TAREAS_POR_CELDA + 3):
        db.crear_tarea_outlook(ana, f"T{i}", fecha_vencimiento=_dia(1), estimacion_min=10)
    c = _persona(db.carga_semanal(ana, LUNES), ana)["dias"][_dia(1)]
    assert c["n"] == db.TAREAS_POR_CELDA + 3 and len(c["tareas"]) == db.TAREAS_POR_CELDA and c["mas"] == 3 and c["min"] == 10 * c["n"]


def test_reasignar_permisos():
    _, (ana, luis, eva, ajeno) = _equipo("cg-12@x.com", "cg-13@x.com", "cg-14@x.com", "cg-15@x.com")
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, luis, "colabora")
    db.compartir_proyecto(ana, p, eva, "observa")
    t = db.crear_tarea_en_proyecto(ana, p, "En proyecto")
    assert db.reasignar_tarea_outlook(ana, t, luis) and db.obtener_tarea_outlook(ana, t)["asignada_a"] == luis
    assert db.reasignar_tarea_outlook(luis, t, ana) and db.obtener_tarea_outlook(ana, t)["asignada_a"] is None           # colaborador: se la devuelve al dueño
    assert db.reasignar_tarea_outlook(luis, t, luis) and db.obtener_tarea_outlook(ana, t)["asignada_a"] == luis
    assert db.reasignar_tarea_outlook(luis, t, eva) is False                      # un observador no puede recibir trabajo
    assert db.reasignar_tarea_outlook(luis, t, ajeno) is False
    assert db.reasignar_tarea_outlook(eva, t, luis) is False and db.reasignar_tarea_outlook(ajeno, t, luis) is False
    suelta = db.crear_tarea_outlook(ana, "Suelta")
    assert db.reasignar_tarea_outlook(ana, suelta, eva) and db.reasignar_tarea_outlook(luis, suelta, ana) is False


def test_pagina_y_mover_por_http(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "cg-p1@x.com", "contrasena123")
    tenant = db.crear_tenant("Despacho carga http")
    db.asignar_tenant(uid, tenant)
    luis = db.crear_usuario("cg-p2@x.com", "contrasena123")
    db.asignar_tenant(luis, tenant)
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday())
    t = db.crear_tarea_outlook(uid, "Preparar renta", fecha_vencimiento=lunes.isoformat() + "T09:00", estimacion_min=150)
    html = cliente.get("/tareas/carga").get_data(as_text=True)
    assert "Preparar renta" in html and "2h 30" in html and 'data-tarea="%d"' % t in html and 'class="active"' in html
    assert cliente.get("/tareas/carga?semana=basura").status_code == 200
    assert "Preparar renta" not in cliente.get("/tareas/carga?semana=" + (lunes - timedelta(days=14)).isoformat()).get_data(as_text=True)      # aún no toca
    assert "Preparar renta" in cliente.get("/tareas/carga?semana=" + (lunes + timedelta(days=14)).isoformat()).get_data(as_text=True)         # ya está atrasada
    r = cliente.post("/tareas/carga/mover", data={"tarea_id": t, "persona_id": luis, "fecha": (lunes + timedelta(days=2)).isoformat()})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    fila = db.obtener_tarea_outlook(uid, t)
    assert fila["asignada_a"] == luis and fila["fecha_vencimiento"] == (lunes + timedelta(days=2)).isoformat() + "T09:00"       # conserva la hora
    r = cliente.post("/tareas/carga/mover", data={"tarea_id": t, "fecha": ""})
    assert r.status_code == 200 and db.obtener_tarea_outlook(uid, t)["fecha_vencimiento"] is None
    assert cliente.post("/tareas/carga/mover", data={"tarea_id": t, "fecha": "no"}).status_code == 403
    assert cliente.post("/tareas/carga/mover", data={"tarea_id": 99999, "persona_id": luis}).status_code == 404
    assert cliente.post("/tareas/carga/mover", data={}).status_code == 404
    privada = db.crear_tarea_outlook(luis, "De Luis")
    assert cliente.post("/tareas/carga/mover", data={"tarea_id": privada, "persona_id": uid}).status_code == 404            # ni la ve
    with _otro_cliente("cg-p3@x.com") as (ajeno, id_ajeno):
        assert ajeno.post("/tareas/carga/mover", data={"tarea_id": t, "persona_id": id_ajeno}).status_code == 404
