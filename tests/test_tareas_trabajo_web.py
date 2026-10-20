"""Fase 2 del plan: el formulario de edición de la tarea (conflicto de versión, motivo de bloqueo, varios clientes) y los filtros de la pestaña Tareas del cliente."""
from datetime import date, timedelta

from app import db, tareas_trabajo as tt
from tests.conftest import iniciar_sesion_de_prueba


def _sesion(cliente, email):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant(f"Despacho {email}")
    db.asignar_tenant(uid, t)
    return uid, t


def _formulario(tarea, **cambios):
    datos = {"asunto": tarea["asunto"], "estado": tarea["estado"], "prioridad": tarea["prioridad"], "porcentaje_completado": "0", "version": str(tarea["version"])}
    datos.update(cambios)
    return datos


def test_el_formulario_lleva_la_version_y_guarda_con_ella(cliente):
    uid, t = _sesion(cliente, "w1@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="Editable")
    html = cliente.get(f"/tareas/{tid}/editar").get_data(as_text=True)
    version = db.obtener_tarea_outlook(uid, tid)["version"]
    assert f'name="version" value="{version}"' in html and 'name="motivo_bloqueo"' in html
    r = cliente.post(f"/tareas/{tid}/editar", data=_formulario(db.obtener_tarea_outlook(uid, tid), asunto="Cambiada"))
    assert r.status_code == 302
    assert db.obtener_tarea_outlook(uid, tid)["asunto"] == "Cambiada"


def test_conflicto_de_edicion_no_pisa_y_muestra_la_tarea_actual(cliente):
    uid, t = _sesion(cliente, "w2@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="Original")
    abierta = dict(db.obtener_tarea_outlook(uid, tid))                      # lo que vio la persona al abrir el formulario
    db.editar_tarea_outlook(uid, tid, asunto="Cambio de otra persona")       # otra persona guarda antes
    r = cliente.post(f"/tareas/{tid}/editar", data=_formulario(abierta, asunto="Mi cambio"))
    assert r.status_code == 409
    html = r.get_data(as_text=True)
    assert "Otra persona ha modificado esta tarea" in html and "Cambio de otra persona" in html
    assert db.obtener_tarea_outlook(uid, tid)["asunto"] == "Cambio de otra persona"      # no se pisó
    nueva = db.obtener_tarea_outlook(uid, tid)["version"]
    assert f'name="version" value="{nueva}"' in html                                      # el formulario devuelto ya lleva la versión vigente
    assert cliente.post(f"/tareas/{tid}/editar", data=_formulario(db.obtener_tarea_outlook(uid, tid), asunto="Mi cambio")).status_code == 302
    assert cliente.post(f"/tareas/{tid}/editar", data=_formulario(abierta, version="x")).status_code == 400


def test_sin_version_el_formulario_antiguo_sigue_funcionando(cliente):
    uid, t = _sesion(cliente, "w3@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="Antigua")
    datos = _formulario(db.obtener_tarea_outlook(uid, tid), asunto="Sin versión")
    del datos["version"]
    assert cliente.post(f"/tareas/{tid}/editar", data=datos).status_code == 302


def test_esperando_pide_motivo_y_se_borra_al_salir(cliente):
    uid, t = _sesion(cliente, "w4@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="Bloqueo web")
    r = cliente.post(f"/tareas/{tid}/editar", data=_formulario(db.obtener_tarea_outlook(uid, tid), estado="esperando"))
    assert "Indica por qué la tarea queda bloqueada" in r.get_data(as_text=True)
    assert db.obtener_tarea_outlook(uid, tid)["estado"] == "no_iniciada"
    r = cliente.post(f"/tareas/{tid}/editar", data=_formulario(db.obtener_tarea_outlook(uid, tid), estado="esperando", motivo_bloqueo="Falta el modelo firmado"))
    assert r.status_code == 302
    f = db.obtener_tarea_outlook(uid, tid)
    assert (f["estado"], f["motivo_bloqueo"]) == ("esperando", "Falta el modelo firmado")
    assert "Falta el modelo firmado" in cliente.get(f"/tareas/{tid}/editar").get_data(as_text=True)
    cliente.post(f"/tareas/{tid}/editar", data=_formulario(db.obtener_tarea_outlook(uid, tid), estado="en_progreso", motivo_bloqueo="Falta el modelo firmado"))
    assert db.obtener_tarea_outlook(uid, tid)["motivo_bloqueo"] is None
    cliente.post(f"/tareas/{tid}/estado", data={"estado": "esperando"})              # el tablero no pide motivo, pero tampoco arrastra uno viejo
    cliente.post(f"/tareas/{tid}/estado", data={"estado": "aplazada"})
    assert db.obtener_tarea_outlook(uid, tid)["motivo_bloqueo"] is None


def test_formulario_con_varios_clientes(cliente):
    uid, t = _sesion(cliente, "w5@ejemplo.com")
    c1, c2, c3 = (db.crear_cliente_fiscal(t, n) for n in ("Uno SL", "Dos SL", "Tres SL"))
    tid = db.crear_tarea_outlook(uid, asunto="Multi", cliente_fiscal_id=c1)
    html = cliente.get(f"/tareas/{tid}/editar").get_data(as_text=True)
    assert 'name="clientes_vinculados"' in html and 'name="clientes_enviados"' in html
    datos = _formulario(db.obtener_tarea_outlook(uid, tid), cliente_fiscal_id=str(c2), clientes_enviados="1")
    datos["clientes_vinculados"] = [str(c1), str(c3), str(c2)]
    assert cliente.post(f"/tareas/{tid}/editar", data=datos).status_code == 302
    clientes = tt.clientes_de_tarea(tid)
    assert {c["id"] for c in clientes} == {c1, c2, c3} and [c["id"] for c in clientes if c["principal"]] == [c2]
    assert db.obtener_tarea_outlook(uid, tid)["cliente_fiscal_id"] == c2
    datos = _formulario(db.obtener_tarea_outlook(uid, tid), cliente_fiscal_id=str(c2), clientes_enviados="1")        # ninguno marcado: solo el principal
    cliente.post(f"/tareas/{tid}/editar", data=datos)
    assert [c["id"] for c in tt.clientes_de_tarea(tid)] == [c2]


def test_sin_el_campo_de_clientes_no_se_tocan_los_vinculos(cliente):
    uid, t = _sesion(cliente, "w6@ejemplo.com")
    c1, c2 = db.crear_cliente_fiscal(t, "Uno SL"), db.crear_cliente_fiscal(t, "Dos SL")
    tid = db.crear_tarea_outlook(uid, asunto="Conservar", cliente_fiscal_id=c1)
    tt.fijar_clientes(uid, tid, [c1, c2], c1)
    cliente.post(f"/tareas/{tid}/editar", data=_formulario(db.obtener_tarea_outlook(uid, tid), asunto="Solo el título", cliente_fiscal_id=str(c1)))
    assert {c["id"] for c in tt.clientes_de_tarea(tid)} == {c1, c2}


def test_no_se_vincula_un_cliente_ajeno_desde_el_formulario(cliente):
    uid, t = _sesion(cliente, "w7@ejemplo.com")
    ajeno = db.crear_cliente_fiscal(db.crear_tenant("Otro despacho"), "Ajeno SL")
    propio, otro = db.crear_cliente_fiscal(t, "Propio SL"), db.crear_cliente_fiscal(t, "Otro propio SL")
    tid = db.crear_tarea_outlook(uid, asunto="Aislada", cliente_fiscal_id=propio)
    datos = _formulario(db.obtener_tarea_outlook(uid, tid), cliente_fiscal_id=str(propio), clientes_enviados="1")
    datos["clientes_vinculados"] = [str(ajeno)]
    assert cliente.post(f"/tareas/{tid}/editar", data=datos).status_code == 422
    assert [c["id"] for c in tt.clientes_de_tarea(tid)] == [propio]


def test_filtros_de_la_pestana_tareas_del_cliente(cliente):
    uid, t = _sesion(cliente, "w8@ejemplo.com")
    fid = db.crear_cliente_fiscal(t, "Filtros SL")
    cid = db.obtener_cliente_fiscal(t, fid)["cliente_id"]
    ayer, manana = (date.today() - timedelta(days=1)).isoformat(), (date.today() + timedelta(days=1)).isoformat()
    db.crear_tarea_outlook(uid, asunto="Tarea vencida", cliente_fiscal_id=fid, fecha_vencimiento=ayer)
    db.crear_tarea_outlook(uid, asunto="Tarea futura", cliente_fiscal_id=fid, fecha_vencimiento=manana)
    hecha = db.crear_tarea_outlook(uid, asunto="Tarea hecha", cliente_fiscal_id=fid)
    db.completar_tarea_outlook(uid, hecha)

    def pagina(filtro=None):
        return cliente.get(f"/clientes/{cid}?pestana=tareas" + (f"&tareas={filtro}" if filtro else "")).get_data(as_text=True)
    todas = pagina()
    assert all(x in todas for x in ("Tarea vencida", "Tarea futura", "Tarea hecha")) and "(2 abiertas)" in todas
    v = pagina("vencidas")
    assert "Tarea vencida" in v and "Tarea futura" not in v and "Tarea hecha" not in v and "(2 abiertas)" in v          # contadores intactos
    assert "Tarea hecha" in pagina("completadas") and "Tarea vencida" not in pagina("completadas")
    a = pagina("abiertas")
    assert "Tarea futura" in a and "Tarea hecha" not in a
    assert "Tarea vencida" in pagina("inventado") and 'aria-current="true"' in v


# --- Crear una tarea con varios clientes ----------------------------------------------------------------------------------------

def test_crear_tarea_con_varios_clientes_desde_la_lista(cliente):
    uid, t = _sesion(cliente, "cr1@ejemplo.com")
    c1, c2, c3 = (db.crear_cliente_fiscal(t, n) for n in ("Uno SL", "Dos SL", "Tres SL"))
    html = cliente.get("/tareas/").get_data(as_text=True)
    assert 'name="clientes_vinculados"' in html and "Más clientes" in html and 'id="nueva-tarea"' in html
    r = cliente.post("/tareas/", data={"asunto": "Para tres clientes", "cliente_fiscal_id": str(c2), "clientes_vinculados": [str(c1), str(c3), str(c2)]})
    assert r.status_code == 302
    tid = [x["id"] for x in db.listar_tareas_outlook(uid) if x["asunto"] == "Para tres clientes"][0]
    clientes = tt.clientes_de_tarea(tid)
    assert {c["id"] for c in clientes} == {c1, c2, c3} and [c["id"] for c in clientes if c["principal"]] == [c2]
    assert db.obtener_tarea_outlook(uid, tid)["cliente_fiscal_id"] == c2


def test_sin_cliente_principal_el_primero_marcado_pasa_a_serlo(cliente):
    uid, t = _sesion(cliente, "cr2@ejemplo.com")
    c1, c2 = db.crear_cliente_fiscal(t, "Uno SL"), db.crear_cliente_fiscal(t, "Dos SL")
    cliente.post("/tareas/", data={"asunto": "Solo extras", "clientes_vinculados": [str(c1), str(c2)]})
    tid = [x["id"] for x in db.listar_tareas_outlook(uid) if x["asunto"] == "Solo extras"][0]
    assert [c["id"] for c in tt.clientes_de_tarea(tid)] == [c1, c2] and db.obtener_tarea_outlook(uid, tid)["cliente_fiscal_id"] == c1


def test_un_cliente_ajeno_corta_la_creacion_entera(cliente):
    uid, t = _sesion(cliente, "cr3@ejemplo.com")
    propio = db.crear_cliente_fiscal(t, "Propio SL")
    ajeno = db.crear_cliente_fiscal(db.crear_tenant("Otro despacho creación"), "Ajeno SL")
    r = cliente.post("/tareas/", data={"asunto": "No debe crearse", "cliente_fiscal_id": str(propio), "clientes_vinculados": [str(ajeno)]})
    assert r.status_code == 302 and "error=" in r.headers["Location"]
    assert [x for x in db.listar_tareas_outlook(uid) if x["asunto"] == "No debe crearse"] == []          # ni siquiera una tarea a medias
    cliente.post("/tareas/", data={"asunto": "No debe crearse", "clientes_vinculados": ["abc", "99999"]})
    assert [x for x in db.listar_tareas_outlook(uid) if x["asunto"] == "No debe crearse"] == []


def test_la_creacion_de_siempre_con_un_solo_cliente_no_cambia(cliente):
    uid, t = _sesion(cliente, "cr4@ejemplo.com")
    c1 = db.crear_cliente_fiscal(t, "Uno SL")
    cliente.post("/tareas/", data={"asunto": "Clásica", "cliente_fiscal_id": str(c1)})
    tid = [x["id"] for x in db.listar_tareas_outlook(uid) if x["asunto"] == "Clásica"][0]
    assert [(c["id"], c["principal"]) for c in tt.clientes_de_tarea(tid)] == [(c1, True)]
    cliente.post("/tareas/", data={"asunto": "Sin cliente"})
    sin = [x["id"] for x in db.listar_tareas_outlook(uid) if x["asunto"] == "Sin cliente"][0]
    assert tt.clientes_de_tarea(sin) == []


def test_el_selector_solo_sale_con_mas_de_un_cliente_y_se_preselecciona_desde_la_ficha(cliente):
    uid, t = _sesion(cliente, "cr5@ejemplo.com")
    c1 = db.crear_cliente_fiscal(t, "Único SL")
    assert 'name="clientes_vinculados"' not in cliente.get("/tareas/").get_data(as_text=True)         # con un solo cliente no hace falta
    c2 = db.crear_cliente_fiscal(t, "Segundo SL")
    html = cliente.get(f"/tareas/?nuevo_cliente={c2}").get_data(as_text=True)
    assert f'<option value="{c2}" selected>' in html and f'<option value="{c1}" selected>' not in html
    cid = db.obtener_cliente_fiscal(t, c1)["cliente_id"]
    ficha = cliente.get(f"/clientes/{cid}?pestana=tareas").get_data(as_text=True)
    assert "Nueva tarea para este cliente" in ficha and f"nuevo_cliente={c1}" in ficha and "#nueva-tarea" in ficha
