"""Proyectos compartidos (fase 1): quién ve y qué puede hacer cada rol, que nada cruce de
despacho, que las listas generales no se llenen con el trabajo del equipo y las secciones."""
from datetime import datetime, timedelta

from app import db


def _hoy(dias=0):
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")


def _equipo(*emails, nombre="Despacho Proy"):
    tenant = db.crear_tenant(f"{nombre} {emails[0]}")
    ids = []
    for email in emails:
        uid = db.crear_usuario(email, "contrasena123")
        db.asignar_tenant(uid, tenant)
        ids.append(uid)
    return tenant, ids


def _proyecto(dueno, miembros=(), nombre=None):
    pid = db.crear_categoria(dueno, nombre or f"Proyecto de {dueno}")
    for uid, rol in miembros:
        assert db.compartir_proyecto(dueno, pid, uid, rol)
    return pid


# --- roles -----------------------------------------------------------------------------------

def test_roles_en_proyecto_y_aislamiento():
    _, (ana, luis, eva, sup) = _equipo("p-r1@x.com", "p-r2@x.com", "p-r3@x.com", "p-r4@x.com")
    _, (ajeno,) = _equipo("p-r5@x.com", nombre="Otro despacho")
    db.asignar_supervisor_tenant(sup, True)
    p = _proyecto(ana, [(luis, "colabora"), (eva, "observa")])
    privado = db.crear_categoria(ana, "Privado")
    assert [db.rol_en_proyecto(u, p) for u in (ana, luis, eva, sup, ajeno)] == ["dueno", "colabora", "observa", "observa", None]
    assert [db.rol_en_proyecto(u, privado) for u in (ana, luis, sup, ajeno)] == ["dueno", None, None, None]   # ni el supervisor ve lo privado
    assert db.compartir_proyecto(ana, p, ajeno, "colabora") is False                                          # otro despacho: no
    db.eliminar_categoria(ana, p)
    assert db.rol_en_proyecto(luis, p) is None                                                                # en la papelera: nadie lo ve


def test_quien_sale_del_despacho_pierde_el_proyecto():
    _, (ana, luis) = _equipo("p-s1@x.com", "p-s2@x.com")
    p = _proyecto(ana, [(luis, "colabora")])
    t = db.crear_tarea_en_proyecto(ana, p, "Algo")
    assert db.rol_en_tarea(luis, t) == "colabora" and db.obtener_proyecto(luis, p)
    db.asignar_tenant(luis, db.crear_tenant("Otro despacho 2"))
    assert db.rol_en_proyecto(luis, p) is None and db.obtener_proyecto(luis, p) is None
    assert db.rol_en_tarea(luis, t) is None and db.tareas_de_proyecto(luis, p) == []
    assert p not in [x["id"] for x in db.listar_proyectos_compartidos_conmigo(luis)]


def test_compartir_solo_el_dueno_cambiar_rol_y_salirse():
    _, (ana, luis, eva) = _equipo("p-c1@x.com", "p-c2@x.com", "p-c3@x.com")
    p = _proyecto(ana)
    assert db.obtener_proyecto(ana, p)["compartido"] == 0
    assert db.compartir_proyecto(luis, p, eva) is False and db.compartir_proyecto(ana, p, ana) is False
    assert db.compartir_proyecto(ana, p, luis, "admin") is False
    assert db.compartir_proyecto(ana, p, luis, "observa") and db.rol_en_proyecto(luis, p) == "observa"
    assert db.compartir_proyecto(ana, p, luis, "colabora") and db.rol_en_proyecto(luis, p) == "colabora"   # cambia el rol, no duplica
    assert len(db.miembros_de_proyecto(p)) == 1 and db.obtener_proyecto(ana, p)["compartido"] == 1
    db.compartir_proyecto(ana, p, eva)
    assert db.quitar_miembro_proyecto(luis, p, eva) is False             # un miembro no echa a otro
    assert db.quitar_miembro_proyecto(luis, p, luis) is True             # pero sí se sale
    assert db.quitar_miembro_proyecto(ana, p, eva) is True
    assert db.obtener_proyecto(ana, p)["compartido"] == 0 and db.rol_en_proyecto(eva, p) is None   # vuelve a ser personal


def test_limite_de_miembros(monkeypatch):
    _, ids = _equipo("p-l1@x.com", "p-l2@x.com", "p-l3@x.com", "p-l4@x.com")
    monkeypatch.setattr(db, "MAX_MIEMBROS_PROYECTO", 2)
    p = _proyecto(ids[0])
    assert db.compartir_proyecto(ids[0], p, ids[1]) and db.compartir_proyecto(ids[0], p, ids[2])
    assert db.compartir_proyecto(ids[0], p, ids[3]) is False
    assert db.compartir_proyecto(ids[0], p, ids[2], "observa") is True    # cambiar un rol existente no cuenta


# --- permisos sobre las tareas del proyecto ------------------------------------------------------

def test_los_miembros_ven_y_trabajan_las_tareas_segun_su_rol():
    _, (ana, luis, eva, ruth) = _equipo("p-t1@x.com", "p-t2@x.com", "p-t3@x.com", "p-t4@x.com")
    p = _proyecto(ana, [(luis, "colabora"), (eva, "observa")])
    t = db.crear_tarea_en_proyecto(luis, p, "Tarea de Luis")      # la crea un colaborador
    assert [db.rol_en_tarea(u, t) for u in (luis, ana, eva, ruth)] == ["dueno", "colabora", "observa", None]
    assert db.obtener_tarea_outlook_visible(ana, t) and db.obtener_tarea_outlook_visible(eva, t) and not db.obtener_tarea_outlook_visible(ruth, t)
    assert db.cambiar_estado_tarea_outlook(ana, t, "en_progreso") is True        # el dueño del proyecto trabaja la tarea de otro
    assert db.cambiar_estado_tarea_outlook(eva, t, "completada") is False        # el observador solo mira
    assert db.cambiar_estado_tarea_outlook(ruth, t, "completada") is False
    db.completar_tarea_outlook(ana, t)
    assert db.obtener_tarea_outlook_visible(ana, t)["estado"] == "completada"
    assert db.puede_editar_tarea(ana, t) and not db.puede_editar_tarea(eva, t)


def test_checklist_y_edicion_de_una_tarea_ajena_del_proyecto():
    _, (ana, luis) = _equipo("p-k1@x.com", "p-k2@x.com")
    p = _proyecto(ana, [(luis, "colabora")])
    t = db.crear_tarea_en_proyecto(ana, p, "Con pasos")
    item = db.agregar_item_checklist(ana, t, "paso 1")
    assert db.alternar_item_checklist(luis, item) is True        # un colaborador marca el paso de otro
    db.editar_tarea_outlook(luis, t, asunto="Editada por Luis")
    assert db.obtener_tarea_outlook_visible(ana, t)["asunto"] == "Editada por Luis"


def test_las_listas_generales_no_se_llenan_con_el_trabajo_del_equipo():
    _, (ana, luis) = _equipo("p-g1@x.com", "p-g2@x.com")
    p = _proyecto(ana, [(luis, "colabora")])
    db.crear_tarea_en_proyecto(ana, p, "Vence hoy", fecha_vencimiento=_hoy())
    db.crear_tarea_en_proyecto(ana, p, "Sin fecha")
    asignada = db.crear_tarea_en_proyecto(ana, p, "Para Luis", asignada_a=luis)
    mias = {t["asunto"] for t in db.listar_tareas_outlook(luis, incluir_asignadas=True)}
    assert mias == {"Para Luis"}                                    # solo lo asignado, como siempre
    dia = db.tareas_para_hoy(luis)
    assert [t["asunto"] for lista in dia.values() for t in lista] == ["Para Luis"]   # lo de hoy y lo suelto de Ana no entra en el día de Luis
    assert db.contar_mi_dia(luis) == (0, 0)
    assert {t["asunto"] for t in db.tareas_de_proyecto(luis, p)} == {"Vence hoy", "Sin fecha", "Para Luis"}   # pero en el proyecto sí
    assert asignada


def test_poner_tareas_en_un_proyecto_ajeno_solo_si_colabora():
    _, (ana, luis, eva) = _equipo("p-u1@x.com", "p-u2@x.com", "p-u3@x.com")
    p = _proyecto(ana, [(luis, "colabora"), (eva, "observa")])
    ok = db.crear_tarea_outlook(luis, "Libre con proyecto", categoria_id=p)
    no = db.crear_tarea_outlook(eva, "Observador", categoria_id=p)
    assert db.obtener_tarea_outlook(luis, ok)["categoria_id"] == p
    assert db.obtener_tarea_outlook(eva, no)["categoria_id"] is None               # se degrada en silencio, como siempre
    assert db.crear_tarea_en_proyecto(eva, p, "x") is None and db.crear_tarea_en_proyecto(db.crear_usuario("p-u4@x.com", "contrasena123"), p, "x") is None
    assert {x["id"] for x in db.listar_proyectos_usables(luis)} >= {p} and p not in {x["id"] for x in db.listar_proyectos_usables(eva)}
    assert [x["id"] for x in db.listar_proyectos_compartidos_conmigo(eva)] == [p]


def test_el_proyecto_hereda_el_cliente_fiscal_y_valida_que_sea_del_despacho():
    tenant, (ana, luis) = _equipo("p-h1@x.com", "p-h2@x.com")
    cliente = db.crear_cliente_fiscal(tenant, "Panadería Sol")
    ajeno = db.crear_cliente_fiscal(db.crear_tenant("Otro despacho 3"), "Ajena SL")
    p = _proyecto(ana, [(luis, "colabora")])
    assert db.actualizar_proyecto(ana, p, cliente_fiscal_id=ajeno, cambiar_cliente=True) is True
    assert db.obtener_proyecto(ana, p)["cliente_fiscal_id"] is None                    # el de otro despacho se descarta
    assert db.actualizar_proyecto(ana, p, cliente_fiscal_id=cliente, cambiar_cliente=True)
    t = db.crear_tarea_en_proyecto(luis, p, "Hereda")
    assert db.obtener_tarea_outlook(luis, t)["cliente_fiscal_id"] == cliente
    assert db.obtener_proyecto(luis, p)["cliente_nombre"] == "Panadería Sol"


# --- datos del proyecto ----------------------------------------------------------------------------------

def test_actualizar_proyecto_solo_el_dueno_y_con_validaciones():
    _, (ana, luis, eva) = _equipo("p-a1@x.com", "p-a2@x.com", "p-a3@x.com")
    p = _proyecto(ana, [(luis, "colabora")])
    assert db.actualizar_proyecto(luis, p, estado="completado") is False
    assert db.actualizar_proyecto(ana, p, estado="inventado") is False
    assert db.actualizar_proyecto(ana, p, fecha_objetivo="no-es-fecha") is False
    assert db.actualizar_proyecto(ana, p, responsable_id=eva, cambiar_responsable=True) is False      # no es miembro
    assert db.actualizar_proyecto(ana, p, estado="en_pausa", descripcion="  Cierre del 2T ", fecha_objetivo="2026-07-20", responsable_id=luis, cambiar_responsable=True)
    d = db.obtener_proyecto(luis, p)
    assert (d["estado"], d["descripcion"], d["fecha_objetivo"], d["responsable_id"]) == ("en_pausa", "Cierre del 2T", "2026-07-20", luis)
    assert d["responsable_nombre"] and d["dueno_nombre"] and d["rol"] == "colabora"
    assert db.actualizar_proyecto(ana, p, responsable_id=None, cambiar_responsable=True) and db.obtener_proyecto(ana, p)["responsable_id"] is None
    db.actualizar_proyecto(ana, p, estado="archivado")
    assert p not in [x["id"] for x in db.listar_proyectos_compartidos_conmigo(luis)]                  # archivado: fuera de la lista


# --- secciones ---------------------------------------------------------------------------------------------

def test_secciones_crear_ordenar_mover_tareas_y_borrar():
    _, (ana, luis, eva) = _equipo("p-e1@x.com", "p-e2@x.com", "p-e3@x.com")
    p = _proyecto(ana, [(luis, "colabora"), (eva, "observa")])
    otro = _proyecto(ana, nombre="Otro proyecto distinto")
    s1, s2 = db.crear_seccion(ana, p, "1. Recoger documentación"), db.crear_seccion(luis, p, "2. Contabilizar")
    assert db.crear_seccion(eva, p, "No puede") is None and db.crear_seccion(ana, p, "   ") is None
    assert [s["nombre"] for s in db.listar_secciones(p)] == ["1. Recoger documentación", "2. Contabilizar"]
    assert db.mover_seccion(luis, s2, "arriba") and [s["id"] for s in db.listar_secciones(p)] == [s2, s1]
    assert db.mover_seccion(luis, s2, "arriba") is False                                          # ya es la primera
    t = db.crear_tarea_en_proyecto(luis, p, "Pedir extractos", seccion_id=s1)
    assert db.obtener_tarea_outlook(luis, t)["seccion_id"] == s1
    ajena = db.crear_seccion(ana, otro, "De otro proyecto")
    assert db.crear_tarea_en_proyecto(ana, p, "x", seccion_id=ajena) and db.asignar_seccion_tarea(ana, t, ajena) is False
    assert db.asignar_seccion_tarea(eva, t, s2) is False and db.asignar_seccion_tarea(ana, t, s2) is True
    assert db.renombrar_seccion(luis, s2, "2. Contabilizar y revisar") and db.renombrar_seccion(eva, s2, "no") is False
    assert db.eliminar_seccion(eva, s2) is False and db.eliminar_seccion(luis, s2) is True
    assert db.obtener_tarea_outlook(luis, t)["seccion_id"] is None and len(db.listar_secciones(p)) == 1   # la tarea no se pierde
    assert db.asignar_seccion_tarea(ana, t, None) is True


# --- resumen -----------------------------------------------------------------------------------------------------

def test_resumen_del_proyecto():
    tenant, (ana, luis, eva) = _equipo("p-m1@x.com", "p-m2@x.com", "p-m3@x.com")
    cliente = db.crear_cliente_fiscal(tenant, "Cliente R")
    db.crear_vencimiento_fiscal(tenant, cliente, "303", "2026-T2", _hoy(10))
    p = _proyecto(ana, [(luis, "colabora"), (eva, "observa")])
    db.actualizar_proyecto(ana, p, cliente_fiscal_id=cliente, cambiar_cliente=True)
    a = db.crear_tarea_en_proyecto(ana, p, "Vencida", fecha_vencimiento=_hoy(-3))
    b = db.crear_tarea_en_proyecto(luis, p, "Próxima", fecha_vencimiento=_hoy(5), asignada_a=luis)
    c = db.crear_tarea_en_proyecto(ana, p, "Hecha")
    d = db.crear_tarea_en_proyecto(ana, p, "Hecha 2")
    db.completar_tarea_outlook(ana, c)
    db.completar_tarea_outlook(ana, d)
    conn = db.get_connection()
    ahora = datetime.now().isoformat(timespec="seconds")
    for uid, seg in ((ana, 3600), (luis, 1800)):
        conn.execute("INSERT INTO tareas (usuario_id,nombre,categoria_id,tipo,estado,inicio_en,fin_en,duracion_segundos) VALUES (?,?,?,?,?,?,?,?)",
                     (uid, "Trabajo", p, "duracion", "finalizada", ahora, ahora, seg))
    conn.commit()
    conn.close()
    r = db.resumen_proyecto(ana, p)
    assert (r["total"], r["hechas"], r["abiertas"], r["vencidas"], r["porcentaje"]) == (4, 2, 2, 1, 50)
    assert r["segundos_total"] == 5400 and r["segundos_semana"] == 5400
    assert r["proximo_hito"]["asunto"] == "Próxima" and r["vencimiento_cliente"]["modelo"] == "303"
    assert {x["nombre"] for x in r["carga"]} and sum(x["abiertas"] for x in r["carga"]) == 2
    assert {x["usuario_id"] for x in r["horas_por_persona"]} == {ana, luis}          # el dueño ve el desglose
    assert db.resumen_proyecto(luis, p)["horas_por_persona"] == []                  # un colaborador solo ve los totales
    assert db.resumen_proyecto(luis, p)["segundos_total"] == 5400
    assert db.resumen_proyecto(db.crear_usuario("p-m9@x.com", "contrasena123"), p) is None
    assert a and b


def test_resumen_de_proyecto_vacio():
    _, (ana,) = _equipo("p-v1@x.com")
    r = db.resumen_proyecto(ana, _proyecto(ana))
    assert (r["total"], r["porcentaje"], r["proximo_hito"], r["vencimiento_cliente"]) == (0, 0, None, None)


# --- migración ------------------------------------------------------------------------------------------------------

def test_la_migracion_es_idempotente_y_conserva_los_proyectos_existentes():
    _, (ana,) = _equipo("p-i1@x.com")
    p = db.crear_categoria(ana, "Antiguo")
    db.init_db()
    db.init_db()
    d = db.obtener_proyecto(ana, p)
    assert (d["estado"], d["compartido"], d["rol"]) == ("activo", 0, "dueno")
    conn = db.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name='tareas_participantes_todos'").fetchone()[0] == 1
    conn.close()
