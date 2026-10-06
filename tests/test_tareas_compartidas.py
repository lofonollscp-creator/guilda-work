"""Tareas compartidas entre usuarios del mismo despacho: el colaborador puede
editar y completar; el observador solo ve; nada cruza de un tenant a otro."""
from app import db
from tests.conftest import iniciar_sesion_de_prueba


def _despacho(*emails):
    tenant = db.crear_tenant(f"Despacho {emails[0]}")
    ids = []
    for email in emails:
        uid = db.crear_usuario(email, "contrasena123")
        db.asignar_tenant(uid, tenant)
        ids.append(uid)
    return tenant, ids


def test_compartir_solo_dentro_del_despacho_y_solo_el_dueno():
    _, (ana, luis) = _despacho("ana@comp.com", "luis@comp.com")
    _, (ajeno,) = _despacho("ajeno@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Cierre trimestral")

    assert db.compartir_tarea_outlook(ana, tarea, ajeno) is False       # otro despacho
    assert db.compartir_tarea_outlook(ana, tarea, ana) is False          # a uno mismo
    assert db.compartir_tarea_outlook(ana, tarea, luis, "admin") is False  # rol inválido
    assert db.compartir_tarea_outlook(luis, tarea, ana) is False          # no es suya
    assert db.compartir_tarea_outlook(ana, tarea, luis, "colabora") is True
    assert [p["usuario_id"] for p in db.participantes_de_tarea(tarea)] == [luis]
    assert db.rol_en_tarea(ajeno, tarea) is None


def test_colaborador_ve_edita_completa_y_trabaja_el_checklist_pero_no_borra():
    _, (ana, luis) = _despacho("ana2@comp.com", "luis2@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Revisar nóminas")
    db.compartir_tarea_outlook(ana, tarea, luis, "colabora")

    assert [t["id"] for t in db.listar_tareas_outlook(luis, solo_compartidas=True)] == [tarea]
    assert [t["id"] for t in db.listar_tareas_outlook(luis, incluir_asignadas=True)] == [tarea]
    assert db.obtener_tarea_outlook_visible(luis, tarea) is not None

    db.editar_tarea_outlook(luis, tarea, asunto="Nóminas de octubre", prioridad="alta")
    assert db.obtener_tarea_outlook(ana, tarea)["asunto"] == "Nóminas de octubre"
    item = db.agregar_item_checklist(luis, tarea, "paso 1")
    assert item is not None and db.alternar_item_checklist(luis, item) is True
    assert db.cambiar_estado_tarea_outlook(luis, tarea, "en_progreso") is True
    db.completar_tarea_outlook(luis, tarea)
    assert db.obtener_tarea_outlook(ana, tarea)["estado"] == "completada"

    db.eliminar_tarea_outlook(luis, tarea)
    assert db.obtener_tarea_outlook(ana, tarea) is not None  # borrar sigue siendo del dueño
    assert db.asignar_tarea_outlook(luis, tarea, ana) is False


def test_observador_solo_ve():
    _, (ana, luis) = _despacho("ana3@comp.com", "luis3@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Informe")
    item = db.agregar_item_checklist(ana, tarea, "uno")
    db.compartir_tarea_outlook(ana, tarea, luis, "observa")

    assert db.obtener_tarea_outlook_visible(luis, tarea) is not None
    db.editar_tarea_outlook(luis, tarea, asunto="Hackeada")
    assert db.obtener_tarea_outlook(ana, tarea)["asunto"] == "Informe"
    assert db.cambiar_estado_tarea_outlook(luis, tarea, "en_progreso") is False
    db.completar_tarea_outlook(luis, tarea)
    assert db.obtener_tarea_outlook(ana, tarea)["estado"] != "completada"
    assert db.alternar_item_checklist(luis, item) is False
    assert db.agregar_item_checklist(luis, tarea, "dos") is None
    assert db.puede_editar_tarea(luis, tarea) is False


def test_dejar_de_compartir_por_el_dueno_o_por_el_propio_participante():
    _, (ana, luis, eva) = _despacho("ana4@comp.com", "luis4@comp.com", "eva4@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Tarea")
    db.compartir_tarea_outlook(ana, tarea, luis)
    db.compartir_tarea_outlook(ana, tarea, eva)

    assert db.dejar_de_compartir_tarea_outlook(luis, tarea, eva) is False  # un tercero no quita a otro
    assert db.dejar_de_compartir_tarea_outlook(luis, tarea, luis) is True   # salirse
    assert db.dejar_de_compartir_tarea_outlook(ana, tarea, eva) is True     # el dueño quita
    assert db.participantes_de_tarea(tarea) == []
    assert db.obtener_tarea_outlook_visible(luis, tarea) is None


def test_rutas_compartir_y_edicion_por_colaborador(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "dueno@comp.com", "contrasena123")
    tenant = db.crear_tenant("Despacho rutas")
    db.asignar_tenant(uid, tenant)
    compi = db.crear_usuario("compi@comp.com", "contrasena123")
    db.asignar_tenant(compi, tenant)
    tarea = db.crear_tarea_outlook(uid, "Compartible")

    r = cliente.post(f"/tareas/{tarea}/compartir", data={"usuario_id": compi, "rol": "colabora"})
    assert r.status_code == 302
    html = cliente.get(f"/tareas/{tarea}/editar").get_data(as_text=True)
    assert "Compartida con" in html and "compi@comp.com" in html
    assert "compi@comp.com" in cliente.get("/tareas/").get_data(as_text=True) or "Con 1 persona" in cliente.get("/tareas/").get_data(as_text=True)

    ajeno = db.crear_usuario("ajeno2@otro.com", "contrasena123")
    db.asignar_tenant(ajeno, db.crear_tenant("Otro"))
    assert cliente.post(f"/tareas/{tarea}/compartir", data={"usuario_id": ajeno}).status_code == 404


# --- Comentarios con menciones ---------------------------------------------------------

def test_comentar_detecta_menciones_solo_entre_quienes_ven_la_tarea():
    _, (ana, luis, eva) = _despacho("ana5@comp.com", "luis5@comp.com", "eva5@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Con hilo")
    db.compartir_tarea_outlook(ana, tarea, luis, "observa")  # eva no la ve

    r = db.comentar_tarea_outlook(ana, tarea, "Mirad esto @luis5@comp.com y @eva5@comp.com")
    assert r["menciones"] == [luis]          # eva no ve la tarea: no se le menciona
    assert r["otros"] == []                  # luis ya está mencionado, nadie más implicado
    assert db.comentar_tarea_outlook(eva, tarea, "intruso") is None
    assert db.comentar_tarea_outlook(ana, tarea, "   ") is None

    # un observador también puede comentar
    r2 = db.comentar_tarea_outlook(luis, tarea, "visto, gracias")
    assert r2["menciones"] == [] and r2["otros"] == [ana]
    hilo = db.listar_comentarios_tarea(luis, tarea)
    assert [c["texto"] for c in hilo][-1] == "visto, gracias"
    assert hilo[0]["mencionados"] == ["luis5@comp.com"]
    assert db.listar_comentarios_tarea(eva, tarea) == []


def test_menciones_prefieren_el_nombre_mas_largo():
    personas = [{"id": 1, "nombre": "Ana"}, {"id": 2, "nombre": "Ana Ruiz"}]
    assert db.detectar_menciones("hola @Ana Ruiz", personas) == [2]
    assert sorted(db.detectar_menciones("@ana y @Ana Ruiz", personas)) == [1, 2]
    assert db.detectar_menciones("hola @Ana", personas, excluir_id=1) == []


def test_borrar_comentario_solo_autor_o_dueno():
    _, (ana, luis, eva) = _despacho("ana6@comp.com", "luis6@comp.com", "eva6@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Hilo")
    db.compartir_tarea_outlook(ana, tarea, luis)
    db.compartir_tarea_outlook(ana, tarea, eva)
    c_luis = db.comentar_tarea_outlook(luis, tarea, "mío")["id"]
    assert db.eliminar_comentario_tarea(eva, tarea, c_luis) is False
    assert db.eliminar_comentario_tarea(ana, tarea, c_luis) is True      # el dueño modera
    c2 = db.comentar_tarea_outlook(luis, tarea, "otro")["id"]
    assert db.eliminar_comentario_tarea(luis, tarea, c2) is True         # el autor
    assert db.contar_comentarios_tareas([tarea]) == {}


def test_rutas_comentar_con_mencion_y_ver(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "dueno2@comp.com", "contrasena123")
    tenant = db.crear_tenant("Despacho comentarios")
    db.asignar_tenant(uid, tenant)
    compi = db.crear_usuario("compi2@comp.com", "contrasena123")
    db.asignar_tenant(compi, tenant)
    tarea = db.crear_tarea_outlook(uid, "Hablemos")
    db.compartir_tarea_outlook(uid, tarea, compi, "colabora")

    r = cliente.post(f"/tareas/{tarea}/comentarios", data={"texto": "Hola @compi2@comp.com <b>x</b>"})
    assert r.status_code == 302
    html = cliente.get(f"/tareas/{tarea}").get_data(as_text=True)
    assert 'class="mencion"' in html and "&lt;b&gt;x&lt;/b&gt;" in html  # menciones resaltadas y HTML escapado
    assert "Comentarios" in html
    assert cliente.get(f"/tareas/{tarea}/editar").status_code == 200
    assert "tarea-comentarios-pill" in cliente.get("/tareas/").get_data(as_text=True)
    assert cliente.get("/tareas/99999").status_code == 404


# --- Historial de actividad y tiempo del equipo ----------------------------------------

def test_historial_registra_quien_hizo_que_y_solo_lo_ve_quien_ve_la_tarea():
    _, (ana, luis, eva) = _despacho("ana7@comp.com", "luis7@comp.com", "eva7@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Con historial")
    db.compartir_tarea_outlook(ana, tarea, luis, "colabora")
    db.editar_tarea_outlook(luis, tarea, asunto="Con historial v2", prioridad="alta")
    item = db.agregar_item_checklist(luis, tarea, "paso 1")
    db.alternar_item_checklist(ana, item)
    db.cambiar_estado_tarea_outlook(luis, tarea, "en_progreso")
    db.comentar_tarea_outlook(ana, tarea, "ok")
    db.completar_tarea_outlook(luis, tarea)
    db.dejar_de_compartir_tarea_outlook(ana, tarea, luis)

    tipos = [a["tipo"] for a in db.actividad_de_tarea(ana, tarea)]
    assert tipos[0] == "dejo_compartir" and tipos[-1] == "creada"  # lo más reciente primero
    assert {"compartida", "editada", "subtarea_nueva", "subtarea_hecha", "estado", "comentario", "completada"} <= set(tipos)
    editada = next(a for a in db.actividad_de_tarea(ana, tarea) if a["tipo"] == "editada")
    assert editada["autor"] == "luis7@comp.com" and "asunto" in editada["detalle"] and "prioridad" in editada["detalle"]
    assert db.actividad_de_tarea(eva, tarea) == []      # eva no la ve
    assert db.actividad_de_tarea(luis, tarea) == []     # ya no participa


def test_edicion_sin_cambios_no_ensucia_el_historial():
    _, (ana,) = _despacho("ana8@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Igual", prioridad="normal")
    db.editar_tarea_outlook(ana, tarea, asunto="Igual", prioridad="normal")
    assert [a["tipo"] for a in db.actividad_de_tarea(ana, tarea)] == ["creada"]


def test_tiempo_del_equipo_suma_por_persona():
    _, (ana, luis, eva) = _despacho("ana9@comp.com", "luis9@comp.com", "eva9@comp.com")
    proyecto_a = db.crear_categoria(ana, "A")
    proyecto_l = db.crear_categoria(luis, "L")
    tarea = db.crear_tarea_outlook(ana, "Tiempo", categoria_id=proyecto_a)
    db.compartir_tarea_outlook(ana, tarea, luis, "colabora")
    for uid, proyecto, segundos in ((ana, proyecto_a, 600), (luis, proyecto_l, 1800)):
        t = db.crear_tarea(uid, "Tiempo", proyecto, "duracion", tarea_outlook_id=tarea)
        conn = db.get_connection()
        conn.execute("UPDATE tareas SET estado = 'finalizada', duracion_segundos = ? WHERE id = ?", (segundos, t))
        conn.commit(); conn.close()

    r = db.tiempo_equipo_tarea(ana, tarea)
    assert r["total"] == 2400
    assert [(p["nombre"], p["segundos"]) for p in r["personas"]] == [("luis9@comp.com", 1800), ("ana9@comp.com", 600)]
    assert db.tiempo_equipo_tarea(eva, tarea) == {"total": 0, "personas": []}


def test_ficha_muestra_actividad_y_tiempo(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "dueno3@comp.com", "contrasena123")
    tenant = db.crear_tenant("Despacho historial")
    db.asignar_tenant(uid, tenant)
    tarea = db.crear_tarea_outlook(uid, "Ficha")
    db.editar_tarea_outlook(uid, tarea, prioridad="alta")
    for url in (f"/tareas/{tarea}", f"/tareas/{tarea}/editar"):
        html = cliente.get(url).get_data(as_text=True)
        assert "Actividad" in html and "creó la tarea" in html and "editó" in html


def test_carga_equipo_solo_cuenta_lo_que_el_usuario_ve():
    _, (ana, luis, eva) = _despacho("ana10@comp.com", "luis10@comp.com", "eva10@comp.com")
    t1 = db.crear_tarea_outlook(ana, "Propia de Ana", fecha_vencimiento="2000-01-01T10:00")
    t2 = db.crear_tarea_outlook(ana, "Para Luis", asignada_a=luis)
    t3 = db.crear_tarea_outlook(eva, "Privada de Eva")  # Ana no la ve
    db.completar_tarea_outlook(ana, db.crear_tarea_outlook(ana, "Hecha"))
    carga = {p["responsable_id"]: p for p in db.carga_equipo(ana)}
    assert set(carga) == {ana, luis}                      # Eva no aparece
    assert carga[ana]["abiertas"] == 1 and carga[ana]["atrasadas"] == 1
    assert carga[luis]["abiertas"] == 1 and carga[luis]["atrasadas"] == 0
    assert [p["responsable_id"] for p in db.carga_equipo(ana)][0] == ana  # las atrasadas primero
    assert {p["responsable_id"] for p in db.carga_equipo(eva)} == {eva}


# --- Notas compartidas -----------------------------------------------------------------

def test_compartir_nota_colabora_edita_texto_pero_no_lo_del_dueno():
    _, (ana, luis, eva) = _despacho("ana11@comp.com", "luis11@comp.com", "eva11@comp.com")
    _, (ajeno,) = _despacho("ajeno11@otro.com")
    nota = db.crear_nota(ana, "Texto original", titulo="Acta")
    assert db.compartir_nota(ana, nota, ajeno) is False
    assert db.compartir_nota(luis, nota, eva) is False        # no es suya
    assert db.compartir_nota(ana, nota, luis, "colabora") is True
    assert db.compartir_nota(ana, nota, eva, "observa") is True

    assert [n["id"] for n in db.listar_notas(luis)] == []                        # por defecto, solo las propias
    assert [n["id"] for n in db.listar_notas(luis, incluir_compartidas=True)] == [nota]
    assert [n["id"] for n in db.listar_notas(luis, solo_compartidas=True)] == [nota]
    assert db.obtener_nota_visible(luis, nota)["dueno_nombre"] == "ana11@comp.com"

    db.editar_nota(luis, nota, "Texto de Luis", titulo="Acta v2", fijada=True)
    n = db.obtener_nota(ana, nota)
    assert n["texto"] == "Texto de Luis" and n["titulo"] == "Acta v2" and not n["fijada"]  # fijar es del dueño

    db.editar_nota(eva, nota, "Hackeada")                                       # solo lectura
    assert db.obtener_nota(ana, nota)["texto"] == "Texto de Luis"
    assert db.obtener_nota_visible(eva, nota) is not None
    db.eliminar_nota(luis, nota)
    assert db.obtener_nota(ana, nota) is not None                                # borrar es del dueño


def test_dejar_de_compartir_nota_y_adjuntos_visibles_solo_para_participantes():
    _, (ana, luis, eva) = _despacho("ana12@comp.com", "luis12@comp.com", "eva12@comp.com")
    nota = db.crear_nota(ana, "Con adjunto")
    adj = db.agregar_adjunto_nota(ana, nota, "a.txt", "text/plain", b"hola")
    db.compartir_nota(ana, nota, luis)
    assert db.obtener_adjunto_nota(luis, adj) is not None
    assert db.obtener_adjunto_nota(eva, adj) is None
    assert db.dejar_de_compartir_nota(eva, nota, luis) is False
    assert db.dejar_de_compartir_nota(luis, nota, luis) is True                  # salirse
    assert db.obtener_adjunto_nota(luis, adj) is None
    assert db.rol_en_nota(luis, nota) is None


def test_rutas_notas_compartidas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "dueno4@comp.com", "contrasena123")
    tenant = db.crear_tenant("Despacho notas")
    db.asignar_tenant(uid, tenant)
    compi = db.crear_usuario("compi4@comp.com", "contrasena123")
    db.asignar_tenant(compi, tenant)
    nota = db.crear_nota(uid, "Nota para compartir", titulo="Compartible")
    assert cliente.post(f"/nota/{nota}/compartir", data={"usuario_id": compi, "rol": "colabora"}).status_code == 302
    html = cliente.get(f"/notas?nota={nota}").get_data(as_text=True)
    assert "Compartida con" in html and "compi4@comp.com" in html
    otro = db.crear_usuario("ajeno4@otro.com", "contrasena123")
    db.asignar_tenant(otro, db.crear_tenant("Otro despacho"))
    assert cliente.post(f"/nota/{nota}/compartir", data={"usuario_id": otro}).status_code == 404
    assert cliente.get("/notas?compartidas=1").status_code == 200
