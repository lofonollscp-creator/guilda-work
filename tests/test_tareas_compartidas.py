"""Tareas compartidas entre usuarios del mismo despacho: el colaborador puede
editar y completar; el observador solo ve; nada cruza de un tenant a otro."""
import pytest

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


# --- Plantillas de tareas --------------------------------------------------------------

def test_parsear_items_de_plantilla():
    items = db.parsear_items_plantilla(
        "Pedir documentación | 0 | alta\n- Copia del DNI\n- Escrituras\n\nDar de alta | +3\nSeguimiento | x | rara\n| 5"
    )
    assert [(i["asunto"], i["dias"], i["prioridad"]) for i in items] == [
        ("Pedir documentación", 0, "alta"), ("Dar de alta", 3, "normal"), ("Seguimiento", 0, "normal"),
    ]
    assert items[0]["checklist"] == ["Copia del DNI", "Escrituras"]
    assert db.parsear_items_plantilla("- suelta sin tarea") == []
    assert db.parsear_items_plantilla(db.items_a_texto([{**i, "checklist": "\n".join(i["checklist"])} for i in items])) == items


def test_plantilla_crea_las_tareas_con_plazos_relativos():
    _, (ana, luis) = _despacho("ana13@comp.com", "luis13@comp.com")
    assert db.crear_plantilla_tareas(ana, "", None, "algo") is None
    assert db.crear_plantilla_tareas(ana, "Vacía", None, "   ") is None
    pid = db.crear_plantilla_tareas(ana, "Alta de cliente", "Proceso estándar", "Pedir documentación | 0 | alta\n- DNI\nDar de alta | 3")
    ids = db.aplicar_plantilla_tareas(ana, pid, "2026-10-01", nuevo_proyecto="Cliente Nuevo SL", asignada_a=luis)
    assert len(ids) == 2
    t1, t2 = (db.obtener_tarea_outlook(ana, i) for i in ids)
    assert t1["fecha_vencimiento"].startswith("2026-10-01") and t2["fecha_vencimiento"].startswith("2026-10-04")
    assert t1["prioridad"] == "alta" and t1["asignada_a"] == luis and t1["categoria_nombre"] == "Cliente Nuevo SL"
    assert [c["texto"] for c in db.listar_checklist(ids[0])] == ["DNI"]


def test_plantillas_compartidas_se_ven_en_el_despacho_pero_solo_las_edita_el_autor():
    _, (ana, luis) = _despacho("ana14@comp.com", "luis14@comp.com")
    _, (ajeno,) = _despacho("ajeno14@otro.com")
    privada = db.crear_plantilla_tareas(ana, "Privada", None, "Tarea A")
    comun = db.crear_plantilla_tareas(ana, "Común", None, "Tarea B", compartida=True)
    assert [p["nombre"] for p in db.listar_plantillas_tareas(luis)] == ["Común"]
    assert db.listar_plantillas_tareas(ajeno) == []
    assert db.aplicar_plantilla_tareas(luis, privada, "2026-10-01") == []
    assert len(db.aplicar_plantilla_tareas(luis, comun, "2026-10-01")) == 1
    assert db.editar_plantilla_tareas(luis, comun, "Hackeada", None, "x", True) is False
    assert db.eliminar_plantilla_tareas(luis, comun) is False
    assert db.editar_plantilla_tareas(ana, comun, "Común v2", None, "Tarea B\nTarea C", True) is True
    assert db.obtener_plantilla_tareas(luis, comun)["n_tareas"] == 2
    assert db.eliminar_plantilla_tareas(ana, comun) is True


def test_rutas_plantillas(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "dueno5@comp.com", "contrasena123")
    tenant = db.crear_tenant("Despacho plantillas")
    db.asignar_tenant(uid, tenant)
    r = cliente.post("/tareas/plantillas", data={"nombre": "Cierre", "items": "Revisar IVA | 0\nPresentar 303 | 5 | alta"})
    assert r.status_code == 302
    assert "Cierre" in cliente.get("/tareas/plantillas").get_data(as_text=True)
    pid = db.listar_plantillas_tareas(uid)[0]["id"]
    assert cliente.get(f"/tareas/plantillas?editar={pid}").status_code == 200
    r = cliente.post(f"/tareas/plantillas/{pid}/aplicar", data={"fecha_inicio": "2026-10-01"})
    assert r.status_code == 302 and "plantilla_creadas=2" in r.headers["Location"]
    assert "Presentar 303" in cliente.get("/tareas/").get_data(as_text=True)
    assert cliente.post("/tareas/plantillas", data={"nombre": "", "items": ""}).status_code == 302
    assert cliente.post(f"/tareas/plantillas/{pid}/eliminar").status_code == 302


# --- Dependencias entre tareas ---------------------------------------------------------

def test_dependencia_bloquea_hasta_completar_la_previa_y_evita_ciclos():
    _, (ana, luis) = _despacho("ana15@comp.com", "luis15@comp.com")
    a = db.crear_tarea_outlook(ana, "Recoger datos")
    b = db.crear_tarea_outlook(ana, "Preparar informe")
    c = db.crear_tarea_outlook(ana, "Enviar", asignada_a=luis)
    assert db.anadir_dependencia_tarea(ana, b, a) is True
    assert db.anadir_dependencia_tarea(ana, c, b) is True
    assert db.anadir_dependencia_tarea(ana, a, c) is False   # ciclo a -> c -> b -> a
    assert db.anadir_dependencia_tarea(ana, a, a) is False   # consigo misma
    assert db.bloqueos_de_tareas([a, b, c]) == {b: 1, c: 1}

    db.completar_tarea_outlook(ana, b)                        # b espera a a: no se completa
    assert db.obtener_tarea_outlook(ana, b)["estado"] != "completada"
    assert db.cambiar_estado_tarea_outlook(ana, b, "en_progreso") is False
    with pytest.raises(ValueError):
        db.iniciar_cronometro_tarea_outlook(ana, b, db.crear_categoria(ana, "P"))

    db.completar_tarea_outlook(ana, a)
    assert [t["id"] for t in db.tareas_desbloqueadas_por(a)] == [b]
    assert db.bloqueos_de_tareas([b, c]) == {c: 1}
    db.completar_tarea_outlook(ana, b)
    assert [(t["id"], t["responsable_id"]) for t in db.tareas_desbloqueadas_por(b)] == [(c, luis)]
    assert "desbloqueada" in [x["tipo"] for x in db.actividad_de_tarea(ana, c)]
    assert db.bloqueos_de_tareas([c]) == {}


def test_dependencias_respetan_permisos_y_borrados():
    _, (ana, luis, eva) = _despacho("ana16@comp.com", "luis16@comp.com", "eva16@comp.com")
    a = db.crear_tarea_outlook(ana, "A")
    b = db.crear_tarea_outlook(ana, "B")
    privada = db.crear_tarea_outlook(eva, "Privada de Eva")
    db.compartir_tarea_outlook(ana, b, luis, "observa")
    assert db.anadir_dependencia_tarea(luis, b, a) is False       # solo lectura: no puede editar
    assert db.anadir_dependencia_tarea(ana, b, privada) is False  # no ve la tarea de Eva
    assert db.anadir_dependencia_tarea(ana, b, a) is True
    assert db.quitar_dependencia_tarea(luis, b, a) is False
    db.eliminar_tarea_outlook(ana, a)                              # una previa en la papelera ya no bloquea
    assert db.bloqueos_de_tareas([b]) == {}
    assert db.quitar_dependencia_tarea(ana, b, a) is True


def test_plantilla_encadenada_crea_la_cadena():
    _, (ana,) = _despacho("ana17@comp.com")
    pid = db.crear_plantilla_tareas(ana, "Cadena", None, "Uno | 0\nDos | 1\nTres | 2")
    ids = db.aplicar_plantilla_tareas(ana, pid, "2026-10-01", encadenar=True)
    assert db.bloqueos_de_tareas(ids) == {ids[1]: 1, ids[2]: 1}
    assert [d["id"] for d in db.dependencias_de_tarea(ids[2])] == [ids[1]]


def test_rutas_dependencias(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "dueno6@comp.com", "contrasena123")
    tenant = db.crear_tenant("Despacho dependencias")
    db.asignar_tenant(uid, tenant)
    a = db.crear_tarea_outlook(uid, "Primera")
    b = db.crear_tarea_outlook(uid, "Segunda")
    assert cliente.post(f"/tareas/{b}/dependencias", data={"depende_de_id": a}).status_code == 302
    assert "Espera a" in cliente.get(f"/tareas/{b}/editar").get_data(as_text=True)
    assert "Espera a 1 tarea" in cliente.get("/tareas/").get_data(as_text=True)
    r = cliente.post(f"/tareas/{b}/completar")
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    assert db.obtener_tarea_outlook(uid, b)["estado"] != "completada"
    cliente.post(f"/tareas/{a}/completar")
    cliente.post(f"/tareas/{b}/completar")
    assert db.obtener_tarea_outlook(uid, b)["estado"] == "completada"
    r = cliente.post(f"/tareas/{a}/dependencias", data={"depende_de_id": b})   # ciclo
    assert "error=" in r.headers["Location"]


# --- Recordatorios por tarea -----------------------------------------------------------

def test_recordatorios_propios_relativos_y_pospuestos(monkeypatch):
    from datetime import datetime
    _, (ana, luis, eva) = _despacho("ana18@comp.com", "luis18@comp.com", "eva18@comp.com")
    tarea = db.crear_tarea_outlook(ana, "Presentar 303", fecha_vencimiento="2026-10-20T10:00")
    db.compartir_tarea_outlook(ana, tarea, luis, "observa")

    assert db.anadir_recordatorio_tarea(eva, tarea, "2026-10-19T09:00") is None        # no la ve
    assert db.anadir_recordatorio_tarea(ana, tarea, "no es una fecha") is None
    r1 = db.recordatorio_relativo(ana, tarea, "1d_antes", ["app", "correo", "raro"])
    r2 = db.anadir_recordatorio_tarea(luis, tarea, "2026-10-18T08:00")                  # un observador también puede
    assert db.recordatorio_relativo(ana, tarea, "inventado") is None
    mios = db.listar_recordatorios_tarea(ana, tarea)
    assert [(r["avisar_en"], r["canales"]) for r in mios] == [("2026-10-19T10:00:00", "app,correo")]  # solo los propios
    assert [r["avisar_en"] for r in db.listar_recordatorios_tarea(luis, tarea)] == ["2026-10-18T08:00:00"]

    antes = datetime(2026, 10, 18, 7, 0)
    assert db.recordatorios_de_tarea_pendientes_de_aviso(antes) == []
    despues = datetime(2026, 10, 19, 12, 0)
    assert {r["id"] for r in db.recordatorios_de_tarea_pendientes_de_aviso(despues)} == {r1, r2}
    db.marcar_recordatorio_tarea_enviado(r1)
    assert [r["id"] for r in db.recordatorios_de_tarea_pendientes_de_aviso(despues)] == [r2]

    assert db.posponer_recordatorio_tarea(eva, r1, "1h") is False                       # ajeno
    assert db.posponer_recordatorio_tarea(ana, r1, "rara") is False
    assert db.posponer_recordatorio_tarea(ana, r1, "manana", ahora=datetime(2026, 10, 19, 12, 0)) is True
    assert db.listar_recordatorios_tarea(ana, tarea)[0]["avisar_en"] == "2026-10-20T09:00:00"
    assert db.listar_recordatorios_tarea(ana, tarea)[0]["enviado_en"] is None            # vuelve a estar pendiente

    db.completar_tarea_outlook(ana, tarea)                                               # tarea cerrada: no avisa
    assert db.recordatorios_de_tarea_pendientes_de_aviso(datetime(2027, 1, 1)) == []
    assert db.eliminar_recordatorio_tarea(luis, r2) is True


def test_procesar_recordatorios_envia_por_cada_canal_y_solo_una_vez(monkeypatch):
    from datetime import datetime
    from app import notificaciones, notificaciones_email, ntfy, recordatorios_tareas
    _, (ana,) = _despacho("ana19@comp.com")
    tid = db.tenant_de_usuario(ana)["id"]
    db.guardar_ntfy(tid, "tenant_x", "tk_secreto")
    tarea = db.crear_tarea_outlook(ana, "Llamar", fecha_vencimiento="2026-10-20T10:00")
    db.anadir_recordatorio_tarea(ana, tarea, "2026-10-19T09:00", ["app", "correo", "ntfy"])

    enviados = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda *a, **k: enviados.append(("app", a[0], a[2])))
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda dest, asunto, cuerpo: enviados.append(("correo", dest)))
    monkeypatch.setattr(ntfy, "enviar", lambda topic, token, titulo, msg, **k: enviados.append(("ntfy", topic)))

    assert recordatorios_tareas.procesar_recordatorios(datetime(2026, 10, 19, 8, 0)) == 0
    assert recordatorios_tareas.procesar_recordatorios(datetime(2026, 10, 19, 9, 1)) == 1
    assert sorted(e[0] for e in enviados) == ["app", "correo", "ntfy"]
    assert ("correo", "ana19@comp.com") in enviados and ("ntfy", "tenant_x") in enviados
    assert recordatorios_tareas.procesar_recordatorios(datetime(2026, 10, 19, 9, 5)) == 0   # no se repite


def test_un_canal_roto_no_impide_los_demas(monkeypatch):
    from datetime import datetime
    from app import notificaciones, notificaciones_email, recordatorios_tareas
    _, (ana,) = _despacho("ana20@comp.com")
    tarea = db.crear_tarea_outlook(ana, "X")
    db.anadir_recordatorio_tarea(ana, tarea, "2026-10-19T09:00", ["correo", "app"])
    llamadas = []
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda *a: (_ for _ in ()).throw(RuntimeError("smtp caído")))
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda *a, **k: llamadas.append(a[0]))
    assert recordatorios_tareas.procesar_recordatorios(datetime(2026, 10, 19, 10, 0)) == 1
    assert llamadas == [ana]


def test_rutas_recordatorios(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "dueno7@comp.com", "contrasena123")
    tenant = db.crear_tenant("Despacho recordatorios")
    db.asignar_tenant(uid, tenant)
    tarea = db.crear_tarea_outlook(uid, "Con aviso", fecha_vencimiento="2026-12-20T10:00")
    r = cliente.post(f"/tareas/{tarea}/recordatorios", data={"atajo": "1d_antes", "canales": ["app", "correo"]})
    assert r.status_code == 302 and "error=" not in r.headers["Location"]
    r = cliente.post(f"/tareas/{tarea}/recordatorios", data={"avisar_en": ""})
    assert "error=" in r.headers["Location"]
    html = cliente.get(f"/tareas/{tarea}").get_data(as_text=True)
    assert "2026-12-19 10:00" in html and "Recordatorios" in html
    rid = db.listar_recordatorios_tarea(uid, tarea)[0]["id"]
    assert cliente.post(f"/tareas/recordatorios/{rid}/posponer", data={"opcion": "1h"}).status_code == 302
    assert cliente.get(f"/tareas/{tarea}/editar").status_code == 200
    assert cliente.post(f"/tareas/recordatorios/{rid}/eliminar").status_code == 302
    assert db.listar_recordatorios_tarea(uid, tarea) == []
    assert cliente.post(f"/tareas/recordatorios/{rid}/eliminar").status_code == 404


# --- Calendario unificado --------------------------------------------------------------

def test_calendario_unifica_tareas_compartidas_citas_y_fichajes(cliente, monkeypatch):
    from datetime import date
    from app import calcom
    uid = iniciar_sesion_de_prueba(cliente, "dueno8@comp.com", "contrasena123")
    tenant = db.crear_tenant("Despacho calendario")
    db.asignar_tenant(uid, tenant)
    compi = db.crear_usuario("compi8@comp.com", "contrasena123")
    db.asignar_tenant(compi, tenant)
    hoy = date.today().isoformat()
    propia = db.crear_tarea_outlook(uid, "Propia del día", fecha_vencimiento=f"{hoy}T10:00")
    ajena = db.crear_tarea_outlook(compi, "Compartida conmigo", fecha_vencimiento=f"{hoy}T11:00")
    db.compartir_tarea_outlook(compi, ajena, uid, "observa")
    privada = db.crear_tarea_outlook(compi, "Privada del compañero", fecha_vencimiento=f"{hoy}T12:00")

    conn = db.get_connection()
    conn.execute("UPDATE tenants SET calcom_api_key = 'k' WHERE id = ?", (tenant,))
    conn.commit(); conn.close()
    monkeypatch.setattr(calcom, "listar_reservas", lambda *a, **k: [{"title": "Reunión con cliente", "start": f"{hoy}T09:30:00.000Z"}])

    html = cliente.get("/tareas/calendario?vista=dia").get_data(as_text=True)
    assert "Propia del día" in html and "Compartida conmigo" in html
    assert f"/tareas/{ajena}" in html and f"/tareas/{ajena}/editar" not in html   # solo lectura: a la ficha
    assert "Privada del compañero" not in html
    assert "Reunión con cliente" in html and 'data-capa="citas"' in html

    def roto(*a, **k):
        raise calcom.ErrorCalcom("caído")
    monkeypatch.setattr(calcom, "listar_reservas", roto)
    html = cliente.get("/tareas/calendario").get_data(as_text=True)
    assert "No se han podido cargar las citas" in html and "Propia del día" in html
