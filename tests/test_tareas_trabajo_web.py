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
