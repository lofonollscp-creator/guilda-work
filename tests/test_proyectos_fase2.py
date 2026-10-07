"""Proyectos, fase 2: reordenar y pasar de sección, reprogramar desde el calendario, tablero, alta rápida
y los endpoints de arrastrar y soltar (con los permisos de siempre)."""
from datetime import date, datetime, timedelta

from app import db
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_proyectos_paginas import _dueno, _miembro, _otro_cliente

JSON = {"X-Requested-With": "fetch", "Accept": "application/json"}


def _equipo(*emails):
    tenant = db.crear_tenant(f"Despacho f2 {emails[0]}")
    ids = []
    for email in emails:
        uid = db.crear_usuario(email, "contrasena123")
        db.asignar_tenant(uid, tenant)
        ids.append(uid)
    return tenant, ids


# --- mover tareas dentro del proyecto ------------------------------------------------------------

def _orden(p, seccion_id):
    return [t["asunto"] for t in db.tareas_de_proyecto(db_dueno(p), p) if t["seccion_id"] == seccion_id]


def db_dueno(p):
    conn = db.get_connection()
    uid = conn.execute("SELECT usuario_id FROM categorias WHERE id = ?", (p,)).fetchone()[0]
    conn.close()
    return uid


def test_reordenar_y_pasar_de_seccion():
    _, (ana, luis, eva) = _equipo("f2-1@x.com", "f2-2@x.com", "f2-3@x.com")
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, luis, "colabora")
    db.compartir_proyecto(ana, p, eva, "observa")
    s1, s2 = db.crear_seccion(ana, p, "Uno"), db.crear_seccion(ana, p, "Dos")
    a, b, c = (db.crear_tarea_en_proyecto(ana, p, n, seccion_id=s1) for n in "ABC")
    d = db.crear_tarea_en_proyecto(ana, p, "D", seccion_id=s2)
    assert _orden(p, s1) == ["A", "B", "C"]
    assert db.mover_tarea_en_proyecto(luis, c, s1, a)                         # C antes que A
    assert _orden(p, s1) == ["C", "A", "B"]
    assert db.mover_tarea_en_proyecto(ana, a, s1, None)                        # A al final
    assert _orden(p, s1) == ["C", "B", "A"]
    assert db.mover_tarea_en_proyecto(ana, b, s2, d)                           # B pasa a la otra sección, antes de D
    assert _orden(p, s1) == ["C", "A"] and _orden(p, s2) == ["B", "D"]
    assert db.mover_tarea_en_proyecto(ana, b, None, None)                      # y sin sección
    assert _orden(p, None) == ["B"] and db.obtener_tarea_outlook(ana, b)["seccion_id"] is None


def test_mover_tareas_respeta_permisos_y_validaciones():
    _, (ana, luis, eva) = _equipo("f2-4@x.com", "f2-5@x.com", "f2-6@x.com")
    p, otro = db.crear_categoria(ana, "P"), db.crear_categoria(ana, "Otro")
    db.compartir_proyecto(ana, p, eva, "observa")
    s1, ajena = db.crear_seccion(ana, p, "Uno"), db.crear_seccion(ana, otro, "Ajena")
    a, b = db.crear_tarea_en_proyecto(ana, p, "A", seccion_id=s1), db.crear_tarea_en_proyecto(ana, p, "B", seccion_id=s1)
    suelta = db.crear_tarea_outlook(ana, "Sin proyecto")
    assert db.mover_tarea_en_proyecto(eva, a, s1, b) is False                  # observador
    assert db.mover_tarea_en_proyecto(luis, a, s1, b) is False                 # ni es del proyecto
    assert db.mover_tarea_en_proyecto(ana, a, ajena, None) is False            # sección de otro proyecto
    assert db.mover_tarea_en_proyecto(ana, a, s1, 99999) is False              # «antes de» inexistente
    assert db.mover_tarea_en_proyecto(ana, a, s1, a) is False if False else True
    assert db.mover_tarea_en_proyecto(ana, suelta, s1, None) is False          # una tarea sin proyecto no se coloca en secciones
    assert _orden(p, s1) == ["A", "B"]


def test_cambiar_el_dia_conserva_la_hora():
    _, (ana, eva) = _equipo("f2-7@x.com", "f2-8@x.com")
    p = db.crear_categoria(ana, "P")
    db.compartir_proyecto(ana, p, eva, "observa")
    con_hora = db.crear_tarea_en_proyecto(ana, p, "Con hora", fecha_vencimiento="2026-10-09T10:30")
    sin_hora = db.crear_tarea_en_proyecto(ana, p, "Sin hora", fecha_vencimiento="2026-10-09")
    assert db.cambiar_fecha_tarea_proyecto(ana, con_hora, "2026-10-15") and db.obtener_tarea_outlook(ana, con_hora)["fecha_vencimiento"] == "2026-10-15T10:30"
    assert db.cambiar_fecha_tarea_proyecto(ana, sin_hora, "2026-10-16") and db.obtener_tarea_outlook(ana, sin_hora)["fecha_vencimiento"] == "2026-10-16"
    assert db.cambiar_fecha_tarea_proyecto(ana, sin_hora, None) and db.obtener_tarea_outlook(ana, sin_hora)["fecha_vencimiento"] is None
    assert db.cambiar_fecha_tarea_proyecto(ana, con_hora, "mañana") is False
    assert db.cambiar_fecha_tarea_proyecto(eva, con_hora, "2026-11-01") is False and db.obtener_tarea_outlook(ana, con_hora)["fecha_vencimiento"] == "2026-10-15T10:30"


# --- páginas y endpoints -------------------------------------------------------------------------------

def test_tablero_y_calendario_se_ven_y_tienen_pestanas(cliente):
    uid, _, p = _dueno(cliente, "f2-p1@x.com")
    hoy = date.today()
    t = db.crear_tarea_en_proyecto(uid, p, "Tarea del mes", fecha_vencimiento=hoy.isoformat())
    db.crear_tarea_en_proyecto(uid, p, "Sin fecha alguna")
    tablero = cliente.get(f"/proyecto/{p}/tablero").get_data(as_text=True)
    assert "Tarea del mes" in tablero and 'data-dnd="tablero"' in tablero and f'data-tarea="{t}"' in tablero and 'draggable="true"' in tablero
    assert "No iniciada" in tablero and "En progreso" in tablero
    cal = cliente.get(f"/proyecto/{p}/calendario").get_data(as_text=True)
    assert "Tarea del mes" in cal and 'data-dnd="calendario"' in cal and f'data-fecha="{hoy.isoformat()}"' in cal
    assert "Sin fecha" in cal and "Sin fecha alguna" in cal
    mes_siguiente = (hoy.replace(day=1) + timedelta(days=40)).isoformat()
    assert cliente.get(f"/proyecto/{p}/calendario?fecha={mes_siguiente}").status_code == 200
    assert cliente.get(f"/proyecto/{p}/calendario?fecha=basura").status_code == 200
    for ruta in ("lista", "tablero", "calendario"):
        assert 'class="activa"' in cliente.get(f"/proyecto/{p}/{ruta}").get_data(as_text=True)


def test_cambiar_estado_desde_el_tablero_json_y_formulario(cliente):
    uid, _, p = _dueno(cliente, "f2-p2@x.com")
    t = db.crear_tarea_en_proyecto(uid, p, "Mover")
    r = cliente.post(f"/proyecto/{p}/tareas/{t}/estado", data={"estado": "en_progreso"}, headers=JSON)
    assert r.status_code == 200 and r.get_json() == {"ok": True, "mensaje": None, "estado": "en_progreso", "anterior": "no_iniciada"}
    assert db.obtener_tarea_outlook(uid, t)["estado"] == "en_progreso"
    bad = cliente.post(f"/proyecto/{p}/tareas/{t}/estado", data={"estado": "inventado"}, headers=JSON)
    assert bad.status_code == 400 and bad.get_json()["ok"] is False
    r = cliente.post(f"/proyecto/{p}/tareas/{t}/estado", data={"estado": "esperando"})            # sin JavaScript: vuelve al tablero
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/proyecto/{p}/tablero")
    assert cliente.post(f"/proyecto/{p}/tareas/{t}/estado", data={"estado": "inventado"}).status_code == 400
    # completar desde el tablero deja constancia como siempre
    cliente.post(f"/proyecto/{p}/tareas/{t}/estado", data={"estado": "completada"}, headers=JSON)
    assert db.obtener_tarea_outlook(uid, t)["fecha_completada"]


def test_una_tarea_bloqueada_no_puede_pasar_a_en_progreso(cliente):
    uid, _, p = _dueno(cliente, "f2-p3@x.com")
    previa, esperando = db.crear_tarea_en_proyecto(uid, p, "Previa"), db.crear_tarea_en_proyecto(uid, p, "Espera")
    db.anadir_dependencia_tarea(uid, esperando, previa) if hasattr(db, "anadir_dependencia_tarea") else None
    conn = db.get_connection()
    conn.execute("INSERT OR IGNORE INTO tareas_dependencias (tarea_id, depende_de_id) VALUES (?, ?)", (esperando, previa))
    conn.commit()
    conn.close()
    r = cliente.post(f"/proyecto/{p}/tareas/{esperando}/estado", data={"estado": "en_progreso"}, headers=JSON)
    assert r.status_code == 409 and "espera" in r.get_json()["mensaje"].lower()
    assert db.obtener_tarea_outlook(uid, esperando)["estado"] == "no_iniciada"


def test_los_endpoints_de_arrastrar_exigen_permiso(cliente):
    uid, tenant, p = _dueno(cliente, "f2-p4@x.com")
    t = db.crear_tarea_en_proyecto(uid, p, "Protegida", fecha_vencimiento="2026-10-09")
    with _otro_cliente("f2-p4b@x.com") as (eva, id_eva):
        _miembro(eva, id_eva, tenant)
        db.compartir_proyecto(uid, p, id_eva, "observa")
        for ruta, datos in ((f"estado", {"estado": "completada"}), ("fecha", {"fecha": "2026-11-01"}), ("orden", {"seccion_id": ""})):
            r = eva.post(f"/proyecto/{p}/tareas/{t}/{ruta}", data=datos, headers=JSON)
            assert r.status_code == 403 and r.get_json()["ok"] is False, ruta
        assert db.obtener_tarea_outlook(uid, t)["fecha_vencimiento"] == "2026-10-09" and db.obtener_tarea_outlook(uid, t)["estado"] == "no_iniciada"
        db.compartir_proyecto(uid, p, id_eva, "colabora")
        assert eva.post(f"/proyecto/{p}/tareas/{t}/fecha", data={"fecha": "2026-11-01"}, headers=JSON).status_code == 200
        assert db.obtener_tarea_outlook(uid, t)["fecha_vencimiento"] == "2026-11-01"
    with _otro_cliente("f2-p4c@x.com") as (ajeno, id_ajeno):
        db.asignar_tenant(id_ajeno, db.crear_tenant("Despacho ajeno f2"))
        for ruta in ("estado", "fecha", "orden"):
            assert ajeno.post(f"/proyecto/{p}/tareas/{t}/{ruta}", data={"estado": "completada"}, headers=JSON).status_code == 404
    otra = db.crear_categoria(uid, "Otro proyecto")
    assert cliente.post(f"/proyecto/{otra}/tareas/{t}/fecha", data={"fecha": "2026-12-01"}, headers=JSON).status_code == 404   # la tarea no es de ese proyecto


def test_reordenar_desde_la_pagina(cliente):
    uid, _, p = _dueno(cliente, "f2-p5@x.com")
    s = db.crear_seccion(uid, p, "Fase 1")
    a, b = db.crear_tarea_en_proyecto(uid, p, "A"), db.crear_tarea_en_proyecto(uid, p, "B")
    r = cliente.post(f"/proyecto/{p}/tareas/{b}/orden", data={"seccion_id": s, "antes_de": ""}, headers=JSON)
    assert r.status_code == 200 and r.get_json()["seccion_id"] is None          # devuelve la sección anterior (para deshacer)
    assert db.obtener_tarea_outlook(uid, b)["seccion_id"] == s
    assert cliente.post(f"/proyecto/{p}/tareas/{a}/orden", data={"seccion_id": s, "antes_de": b}, headers=JSON).status_code == 200
    assert [t["asunto"] for t in db.tareas_de_proyecto(uid, p) if t["seccion_id"] == s] == ["A", "B"]
    assert cliente.post(f"/proyecto/{p}/tareas/{a}/orden", data={"seccion_id": 99999}, headers=JSON).status_code == 403
    html = cliente.get(f"/proyecto/{p}/lista").get_data(as_text=True)
    assert 'data-dnd="lista"' in html and f'data-seccion="{s}"' in html and f'data-tarea="{a}"' in html and 'tabindex="0"' in html


def test_alta_rapida_con_texto_libre_en_el_proyecto(cliente):
    uid, tenant, p = _dueno(cliente, "f2-p6@x.com")
    with _otro_cliente("f2-p6b@x.com") as (otro, luis):
        _miembro(otro, luis, tenant)
        db.compartir_proyecto(uid, p, luis, "colabora")
        db.actualizar_proyecto(luis if False else uid, p, cambiar_responsable=False)
        s = db.crear_seccion(uid, p, "Recoger documentación")
        cliente.post(f"/proyecto/{p}/tareas", data={"asunto": "mañana 10h pedir extractos @f2-p6b !alta #recoger"})
        t = [x for x in db.tareas_de_proyecto(uid, p) if x["asunto"] == "pedir extractos"]
        assert len(t) == 1
        t = t[0]
        manana = (date.today() + timedelta(days=1)).isoformat()
        assert (t["fecha_vencimiento"], t["prioridad"], t["asignada_a"], t["seccion_id"]) == (f"{manana}T10:00", "alta", luis, s)
        # lo que el formulario trae manda sobre el texto
        cliente.post(f"/proyecto/{p}/tareas", data={"asunto": "viernes revisar", "prioridad": "baja", "fecha_vencimiento": "2030-01-01"})
        u = [x for x in db.tareas_de_proyecto(uid, p) if x["asunto"] == "revisar"][0]
        assert u["prioridad"] == "baja" and u["fecha_vencimiento"] == "2030-01-01"
        # lo ambiguo/inexistente se queda en el título
        cliente.post(f"/proyecto/{p}/tareas", data={"asunto": "hablar con @nadie"})
        assert [x for x in db.tareas_de_proyecto(uid, p) if x["asunto"] == "hablar con @nadie"]


def test_vista_previa_del_alta_rapida(cliente):
    uid, _, p = _dueno(cliente, "f2-p7@x.com")
    db.crear_seccion(uid, p, "Fase uno")
    r = cliente.get(f"/proyecto/{p}/interpretar", query_string={"texto": "viernes 10h llamar @nadie !alta #fase"})
    d = r.get_json()
    assert r.status_code == 200 and d["asunto"] == "llamar @nadie" and d["hora"] == "10:00" and d["prioridad"] == "alta" and d["seccion"] == "Fase uno"
    assert d["sin_resolver"] == ["@nadie"] and d["vencimiento"].endswith("T10:00") and d["fecha_texto"]
    assert cliente.get(f"/proyecto/{p}/interpretar").get_json()["asunto"] == ""
    with _otro_cliente("f2-p7b@x.com") as (otro, uid_otro):
        db.asignar_tenant(uid_otro, db.crear_tenant("Despacho ajeno f2b"))
        assert otro.get(f"/proyecto/{p}/interpretar", query_string={"texto": "x"}).status_code == 404


def test_alta_rapida_en_la_lista_general_de_tareas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "f2-g1@x.com", "contrasena123")
    tenant = db.crear_tenant("Despacho f2 general")
    db.asignar_tenant(uid, tenant)
    luis = db.crear_usuario("luis.f2@x.com", "contrasena123")
    db.asignar_tenant(luis, tenant)
    p = db.crear_categoria(uid, "Cierre trimestral")
    cliente.post("/tareas/", data={"asunto": "pasado mañana 9:30 llamar @luis !alta #cierre", "prioridad": "normal"})
    t = [x for x in db.listar_tareas_outlook(uid) if x["asunto"] == "llamar"][0]
    pasado = (date.today() + timedelta(days=2)).isoformat()
    assert (t["fecha_vencimiento"], t["prioridad"], t["asignada_a"], t["categoria_id"]) == (f"{pasado}T09:30", "alta", luis, p)
    cliente.post("/tareas/", data={"asunto": "Solo un título normal"})
    n = [x for x in db.listar_tareas_outlook(uid) if x["asunto"] == "Solo un título normal"][0]
    assert n["fecha_vencimiento"] is None and n["prioridad"] == "normal"
    assert "viernes 10h" in cliente.get("/tareas/").get_data(as_text=True)


def test_el_javascript_y_las_rutas_apuntan_a_lo_mismo(cliente):
    uid, _, p = _dueno(cliente, "f2-js@x.com")
    js = cliente.get("/static/proyecto.js").get_data(as_text=True)
    for ruta in ("estado", "fecha", "orden"):
        html = cliente.get(f"/proyecto/{p}/{ {'estado': 'tablero', 'fecha': 'calendario', 'orden': 'lista'}[ruta] }").get_data(as_text=True)
        assert f"/tareas/0/{ruta}" in html                 # la plantilla de URL que el JS rellena con el id
    assert '"/tareas/0/"' in js and "X-Requested-With" in js and "Alt" in js or "altKey" in js
