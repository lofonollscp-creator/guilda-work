"""Revisión (aprobación) de tareas: otra persona del despacho, bloquea el cierre mientras esté pendiente, aprobar o pedir cambios."""
import pytest

from app import auditoria, db, tareas_trabajo as tt
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_api_tareas import _tarea, _usuario


def _equipo(cliente, prefijo):
    t = db.crear_tenant(f"Despacho {prefijo}")
    h1, u1 = _usuario(cliente, f"{prefijo}1@ejemplo.com", t)
    h2, u2 = _usuario(cliente, f"{prefijo}2@ejemplo.com", t)
    h3, u3 = _usuario(cliente, f"{prefijo}3@ejemplo.com", t)
    return t, (h1, u1), (h2, u2), (h3, u3)


def _pedir(cliente, h, tid, revisor, nota=None):
    return cliente.post(f"/api/v1/tareas-outlook/{tid}/revision", json={"revisor_id": revisor, "nota": nota}, headers=h)


def _resolver(cliente, h, tid, decision, nota=None):
    return cliente.post(f"/api/v1/tareas-outlook/{tid}/revision/resolver", json={"decision": decision, "nota": nota}, headers=h)


def _notis(uid):
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM notificaciones WHERE usuario_id = ? AND tipo = 'revision_tarea' ORDER BY id", (uid,))]
    finally:
        conn.close()


def test_pedir_revision_reglas_y_visibilidad_del_revisor(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "rv1")
    ajeno = _usuario(cliente, "rv1x@ejemplo.com", db.crear_tenant("Otro despacho rv"))
    tid = _tarea(cliente, h1, "Declaración")
    assert _pedir(cliente, h1, tid, u1).get_json()["codigo"] == "revisor_invalido"                       # no vale uno mismo
    assert _pedir(cliente, h1, tid, ajeno[1]).get_json()["codigo"] == "revisor_invalido"                 # ni de otro despacho
    assert _pedir(cliente, h1, tid, "x").get_json()["codigo"] == "revisor_invalido" and _pedir(cliente, h1, tid, None).status_code == 400
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}", headers=h2).status_code == 404                  # el revisor aún no ve la tarea
    r = _pedir(cliente, h1, tid, u2, "Mira el IVA")
    assert r.status_code == 201 and r.get_json()["data"]["pendiente"]["revisor_id"] == u2
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}", headers=h2).status_code == 200                  # ahora sí: se le comparte para poder revisar
    n = _notis(u2)
    assert len(n) == 1 and "Declaración" in n[0]["titulo"] and n[0]["cuerpo"] == "Mira el IVA"
    dup = _pedir(cliente, h1, tid, u3)
    assert dup.status_code == 409 and dup.get_json()["codigo"] == "revision_pendiente"
    assert _pedir(cliente, h3, tid, u2).status_code == 404                                                # u3 ni ve la tarea
    assert _pedir(cliente, ajeno[0], tid, u2).status_code == 404
    assert any(a["tipo"] == "revision_solicitada" for a in cliente.get(f"/api/v1/tareas-outlook/{tid}/actividad", headers=h1).get_json()["data"])
    assert "tarea.revision.solicitar" in {e["accion"] for e in auditoria.listar(t, entidad="tarea")}


def test_un_observador_no_puede_pedir_revision_ni_sobre_una_completada(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "rv2")
    tid = _tarea(cliente, h1, "Solo mirar")
    cliente.post(f"/api/v1/tareas-outlook/{tid}/compartir", json={"usuario_id": u2, "rol": "observa"}, headers=h1)
    assert _pedir(cliente, h2, tid, u3).get_json()["codigo"] == "sin_permiso"
    cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "completada"}, headers=h1)
    r = _pedir(cliente, h1, tid, u2)
    assert r.status_code == 409 and r.get_json()["codigo"] == "tarea_completada"


def test_mientras_esta_pendiente_no_se_puede_completar_por_ningun_camino(cliente):
    t, (h1, u1), (h2, u2), _ = _equipo(cliente, "rv3")
    tid = _tarea(cliente, h1, "En revisión")
    _pedir(cliente, h1, tid, u2)
    for r in (cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "completada"}, headers=h1),
              cliente.post(f"/api/v1/tareas-outlook/{tid}/completar", headers=h1),
              cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "completada"}, headers=h1)):
        assert r.status_code == 409 and r.get_json()["codigo"] == "revision_pendiente"
    assert db.cambiar_estado_tarea_outlook(u1, tid, "completada") is False
    db.completar_tarea_outlook(u1, tid)
    assert db.obtener_tarea_outlook(u1, tid)["estado"] == "no_iniciada"
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "en_progreso"}, headers=h1).status_code == 200      # trabajar sigue permitido


def test_aprobar_no_completa_sola_pero_deja_completarla(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "rv4")
    tid = _tarea(cliente, h1, "Para aprobar")
    _pedir(cliente, h1, tid, u2)
    r = _resolver(cliente, h1, tid, "aprobar")                                                           # quien la pidió no la resuelve
    assert r.status_code == 403 and r.get_json()["codigo"] == "sin_permiso"
    assert _resolver(cliente, h3, tid, "aprobar").status_code == 404                                      # un tercero ni la ve
    assert _resolver(cliente, h2, tid, "quizas").get_json()["codigo"] == "decision_invalida"
    r = _resolver(cliente, h2, tid, "aprobar", "Todo bien")
    assert r.status_code == 200 and r.get_json()["data"]["pendiente"] is None and r.get_json()["data"]["historial"][0]["estado"] == "aprobada"
    assert db.obtener_tarea_outlook(u1, tid)["estado"] == "no_iniciada"                                    # aprobar no completa
    assert [n["titulo"] for n in _notis(u1)] == ["Revisión aprobada: Para aprobar"] and _notis(u1)[0]["cuerpo"] == "Todo bien"
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "completada"}, headers=h1).status_code == 200
    assert _resolver(cliente, h2, tid, "aprobar").status_code == 404                                      # ya no hay nada pendiente


def test_pedir_cambios_exige_nota_y_devuelve_la_tarea_a_en_progreso(cliente):
    t, (h1, u1), (h2, u2), _ = _equipo(cliente, "rv5")
    tid = _tarea(cliente, h1, "Con cambios")
    _pedir(cliente, h1, tid, u2)
    assert _resolver(cliente, h2, tid, "cambios", "  ").get_json()["codigo"] == "nota_obligatoria"
    assert tt.revision_pendiente(tid) is not None                                                         # no se resolvió a medias
    assert _resolver(cliente, h2, tid, "cambios", "Falta la base imponible").status_code == 200
    assert db.obtener_tarea_outlook(u1, tid)["estado"] == "en_progreso"
    assert _notis(u1)[0]["titulo"] == "Piden cambios: Con cambios" and "base imponible" in _notis(u1)[0]["cuerpo"]
    assert _pedir(cliente, h1, tid, u2).status_code == 201                                                # se puede pedir otra
    assert {e["accion"] for e in auditoria.listar(t, entidad="tarea")} >= {"tarea.revision.cambios", "tarea.revision.solicitar"}


def test_cancelar_la_revision(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "rv6")
    tid = _tarea(cliente, h1, "Cancelable")
    _pedir(cliente, h1, tid, u2)
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/revision/cancelar", headers=h2).status_code == 404       # el revisor no la cancela
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/revision/cancelar", headers=h1).status_code == 200
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}/revision", headers=h1).get_json()["data"]["historial"][0]["estado"] == "cancelada"
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "completada"}, headers=h1).status_code == 200


def test_pantalla_de_revision_flujo_completo(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "rvw1@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho revisión web")
    db.asignar_tenant(uid, t)
    revisor = db.crear_usuario_vinculado_a_kratos("rvw2@ejemplo.com", "k-rvw2"); db.asignar_tenant(revisor, t)
    tid = db.crear_tarea_outlook(uid, asunto="Revisión web")
    html = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert 'id="revision"' in html and "Pedir revisión" in html and "No hay ninguna revisión pendiente" not in html
    assert cliente.post(f"/tareas/{tid}/revision", data={"revisor_id": str(uid)}).status_code == 302
    assert tt.revision_pendiente(tid) is None                                                              # a sí mismo no
    assert cliente.post(f"/tareas/{tid}/revision", data={"revisor_id": str(revisor), "nota": "Gracias"}).status_code == 302
    assert tt.revision_pendiente(tid)["revisor_id"] == revisor
    html = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert "Mientras esté pendiente" in html and "Retirar la petición" in html and "Aprobar" not in html.split('id="revision"')[1]      # el solicitante no ve los botones del revisor
    cliente.post(f"/tareas/{tid}/estado", data={"estado": "completada"})
    assert db.obtener_tarea_outlook(uid, tid)["estado"] == "no_iniciada"
    assert cliente.post(f"/tareas/{tid}/revision/cancelar").status_code == 302 and tt.revision_pendiente(tid) is None
    assert cliente.post(f"/tareas/{tid}/revision/cancelar").status_code == 404


def test_borrar_el_despacho_y_la_tarea_no_se_atascan_con_revisiones(cliente):
    t, (h1, u1), (h2, u2), _ = _equipo(cliente, "rv7")
    tid = _tarea(cliente, h1, "Con revisión")
    _pedir(cliente, h1, tid, u2)
    db.eliminar_tarea_outlook(u1, tid)
    db.eliminar_tarea_outlook_definitivamente(u1, tid)                                                     # cae en cascada con la tarea
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tarea_revisiones WHERE tarea_id = ?", (tid,)).fetchone()[0] == 0
    finally:
        conn.close()
    t2, (h4, u4), (h5, u5), _ = _equipo(cliente, "rv8")
    tid2 = _tarea(cliente, h4, "Otra")
    _pedir(cliente, h4, tid2, u5)
    db.borrar_tenant(t2)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT tenant_id FROM tarea_revisiones WHERE tarea_id = ?", (tid2,)).fetchone()[0] is None       # la tarea es de la persona y se conserva sin despacho
    finally:
        conn.close()


# --- Varios revisores -----------------------------------------------------------------------------------------------------------

def _pedir_varios(cliente, h, tid, revisores, modo=None, nota=None):
    cuerpo = {"revisor_ids": revisores, "nota": nota}
    if modo:
        cuerpo["modo"] = modo
    return cliente.post(f"/api/v1/tareas-outlook/{tid}/revision", json=cuerpo, headers=h)


def test_validacion_de_varios_revisores(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "mv1")
    ajeno = _usuario(cliente, "mv1x@ejemplo.com", db.crear_tenant("Otro despacho mv"))
    tid = _tarea(cliente, h1, "Varios")
    for malos, codigo in (([], "revisor_invalido"), ([u1, u2], "revisor_invalido"), ([u2, ajeno[1]], "revisor_invalido"), ([u2, "x"], "revisor_invalido")):
        assert _pedir_varios(cliente, h1, tid, malos).get_json()["codigo"] == codigo, malos
    assert _pedir_varios(cliente, h1, tid, [u2, u3], modo="mitad").get_json()["codigo"] == "modo_invalido"
    muchos = [db.crear_usuario_vinculado_a_kratos(f"mv1-{i}@ejemplo.com", f"k-mv1-{i}") for i in range(tt.MAX_REVISORES)]
    for u in muchos:
        db.asignar_tenant(u, t)
    r = _pedir_varios(cliente, h1, tid, [u2, u3, *muchos])
    assert r.status_code == 400 and r.get_json()["codigo"] == "demasiados_revisores"
    assert tt.revision_pendiente(tid) is None                                                          # ninguna petición a medias
    r = _pedir_varios(cliente, h1, tid, [u2, u3, u2], nota="Mirad el IVA")                              # repetidos se unifican
    assert r.status_code == 201
    p = r.get_json()["data"]["pendiente"]
    assert p["revisores"] == [u2, u3] and p["modo"] == "todos" and [v["estado"] for v in p["votos"]] == ["pendiente", "pendiente"]
    assert len(_notis(u2)) == 1 and len(_notis(u3)) == 1 and _notis(u2)[0]["cuerpo"] == "Mirad el IVA"
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}", headers=h3).status_code == 200               # los dos pueden ver la tarea


def test_modo_todos_hace_falta_que_aprueben_todos(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "mv2")
    tid = _tarea(cliente, h1, "Todos")
    _pedir_varios(cliente, h1, tid, [u2, u3])
    assert _resolver(cliente, h1, tid, "aprobar").status_code == 403                                   # quien la pidió no vota
    r = _resolver(cliente, h2, tid, "aprobar", "Por mi parte bien")
    assert r.status_code == 200
    p = r.get_json()["data"]["pendiente"]
    assert p is not None and p["aprobados"] == 1 and p["pendientes"] == [u3]                            # sigue pendiente: falta una persona
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "completada"}, headers=h1).get_json()["codigo"] == "revision_pendiente"
    assert _notis(u1) == []                                                                            # un voto parcial no molesta a quien la pidió
    dup = _resolver(cliente, h2, tid, "aprobar")
    assert dup.status_code == 409 and dup.get_json()["codigo"] == "ya_has_votado"                       # nadie vota dos veces
    r = _resolver(cliente, h3, tid, "aprobar", "Y por la mía")
    assert r.get_json()["data"]["pendiente"] is None and r.get_json()["data"]["historial"][0]["estado"] == "aprobada"
    assert [n["titulo"] for n in _notis(u1)] == ["Revisión aprobada: Todos"] and "Y por la mía" in _notis(u1)[0]["cuerpo"]
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "completada"}, headers=h1).status_code == 200
    h = cliente.get(f"/api/v1/tareas-outlook/{tid}/revision", headers=h1).get_json()["data"]["historial"][0]
    assert [v["estado"] for v in h["votos"]] == ["aprobado", "aprobado"] and h["aprobados"] == 2
    acciones = {e["accion"] for e in auditoria.listar(t, entidad="tarea")}
    assert {"tarea.revision.voto", "tarea.revision.aprobar", "tarea.revision.solicitar"} <= acciones


def test_modo_cualquiera_basta_con_uno_y_el_resto_ya_no_vota(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "mv3")
    tid = _tarea(cliente, h1, "Cualquiera")
    _pedir_varios(cliente, h1, tid, [u2, u3], modo="cualquiera")
    assert _resolver(cliente, h3, tid, "aprobar").get_json()["data"]["historial"][0]["estado"] == "aprobada"
    r = _resolver(cliente, h2, tid, "aprobar")
    assert r.status_code == 404                                                                        # ya está resuelta: no queda nada pendiente
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "completada"}, headers=h1).status_code == 200


def test_una_peticion_de_cambios_detiene_la_revision_en_cualquier_modo(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "mv4")
    for modo in ("todos", "cualquiera"):
        tid = _tarea(cliente, h1, f"Cambios {modo}")
        _pedir_varios(cliente, h1, tid, [u2, u3], modo=modo)
        assert _resolver(cliente, h2, tid, "cambios", "  ").get_json()["codigo"] == "nota_obligatoria"
        if modo == "todos":
            _resolver(cliente, h2, tid, "aprobar")                                                     # uno aprueba…
            r = _resolver(cliente, h3, tid, "cambios", "Falta la base")                                 # …y el otro pide cambios: gana la petición de cambios
        else:
            r = _resolver(cliente, h3, tid, "cambios", "Falta la base")
        h = r.get_json()["data"]["historial"][0]
        assert h["estado"] == "cambios" and r.get_json()["data"]["pendiente"] is None
        assert db.obtener_tarea_outlook(u1, tid)["estado"] == "en_progreso"
        assert _notis(u1)[-1]["titulo"] == f"Piden cambios: Cambios {modo}" and "Falta la base" in _notis(u1)[-1]["cuerpo"]
        assert _resolver(cliente, h2, tid, "aprobar").status_code == 404                                # los demás ya no votan
        assert cliente.post(f"/api/v1/tareas-outlook/{tid}/estado", json={"estado": "completada"}, headers=h1).status_code == 200      # y se puede volver a empezar o cerrar


def test_solo_vota_quien_esta_designado_y_se_puede_retirar(cliente):
    t, (h1, u1), (h2, u2), (h3, u3) = _equipo(cliente, "mv5")
    h4, u4 = _usuario(cliente, "mv5d@ejemplo.com", t)
    tid = _tarea(cliente, h1, "Designados")
    _pedir_varios(cliente, h1, tid, [u2, u3])
    cliente.post(f"/api/v1/tareas-outlook/{tid}/compartir", json={"usuario_id": u4, "rol": "colabora"}, headers=h1)
    r = _resolver(cliente, h4, tid, "aprobar")
    assert r.status_code == 403 and r.get_json()["codigo"] == "sin_permiso"                            # ve la tarea y colabora, pero no es revisor
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/revision/cancelar", headers=h2).status_code == 404       # un revisor no la retira
    _resolver(cliente, h2, tid, "aprobar")
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/revision/cancelar", headers=h1).status_code == 200
    assert _resolver(cliente, h3, tid, "aprobar").status_code == 404
    hist = cliente.get(f"/api/v1/tareas-outlook/{tid}/revision", headers=h1).get_json()["data"]["historial"][0]
    assert hist["estado"] == "cancelada" and [v["estado"] for v in hist["votos"]] == ["aprobado", "pendiente"]       # lo votado queda como historial
    assert _pedir_varios(cliente, h1, tid, [u2, u3]).status_code == 201                                    # y se puede pedir otra


def test_las_revisiones_de_antes_pasan_a_tener_su_voto(cliente):
    t, (h1, u1), (h2, u2), _ = _equipo(cliente, "mv6")
    pendiente = _tarea(cliente, h1, "Antigua pendiente")
    hecha = _tarea(cliente, h1, "Antigua aprobada")
    conn = db.get_connection()
    try:
        # como quedaron antes de existir los votos: la revisión con su único revisor y sin filas de voto
        for tid, estado in ((pendiente, "pendiente"), (hecha, "aprobada")):
            conn.execute("INSERT INTO tarea_revisiones (tenant_id, tarea_id, solicitada_por, revisor_id, estado, nota_resolucion, solicitada_en, resuelta_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (t, tid, u1, u2, estado, "Bien" if estado == "aprobada" else None, db.now_iso(), db.now_iso() if estado == "aprobada" else None))
        conn.commit()
        conn.execute("INSERT OR IGNORE INTO tareas_participantes (tarea_id, usuario_id, rol, compartida_en) VALUES (?, ?, 'observa', ?)", (pendiente, u2, db.now_iso()))     # como ya estaba compartida
        tt.crear_esquema(conn); tt.crear_esquema(conn)                                                   # y repetirlo no duplica
        conn.commit()
    finally:
        conn.close()
    p = tt.revision_pendiente(pendiente)
    assert p["revisores"] == [u2] and p["pendientes"] == [u2] and p["modo"] == "todos"
    assert tt.historial_de_revisiones(hecha)[0]["votos"][0]["estado"] == "aprobado"
    assert _resolver(cliente, h2, pendiente, "aprobar").get_json()["data"]["historial"][0]["estado"] == "aprobada"       # y se puede resolver con el código nuevo


def test_pantalla_de_varios_revisores(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "mvw1@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho varios revisores web")
    db.asignar_tenant(uid, t)
    r2 = db.crear_usuario_vinculado_a_kratos("mvw2@ejemplo.com", "k-mvw2"); db.asignar_tenant(r2, t)
    r3 = db.crear_usuario_vinculado_a_kratos("mvw3@ejemplo.com", "k-mvw3"); db.asignar_tenant(r3, t)
    tid = db.crear_tarea_outlook(uid, asunto="Revisión web varios")
    html = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert 'name="revisor_ids"' in html and 'name="modo"' in html and "Basta con que la apruebe uno" in html
    assert cliente.post(f"/tareas/{tid}/revision", data={"revisor_ids": [str(r2), str(r3)], "modo": "cualquiera", "nota": "Mirad"}).status_code == 302
    p = tt.revision_pendiente(tid)
    assert p["revisores"] == [r2, r3] and p["modo"] == "cualquiera"
    html = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert "La revisan 2 personas" in html and "Sin votar" in html and "Retirar la petición" in html
    assert cliente.post(f"/tareas/{tid}/revision/cancelar").status_code == 302
    assert cliente.post(f"/tareas/{tid}/revision", data={"revisor_id": str(r2)}).status_code == 302          # el campo único de siempre sigue valiendo
    assert tt.revision_pendiente(tid)["revisores"] == [r2]
    cliente.post(f"/tareas/{tid}/revision/cancelar")
    assert "tiene que hacerla otra persona" in cliente.post(f"/tareas/{tid}/revision", data={"revisor_ids": [str(uid)]}, follow_redirects=True).get_data(as_text=True)


def test_herramienta_con_varios_revisores_y_el_voto_de_cada_uno():
    import mcp_tools  # noqa: F401
    from app import ia_herramientas as ih
    t = db.crear_tenant("Despacho herramientas varios")
    a, b, c = (db.crear_usuario_vinculado_a_kratos(f"{n}-mvh@ejemplo.com", f"k-{n}-mvh") for n in ("a", "b", "c"))
    for u in (a, b, c):
        db.asignar_tenant(u, t)
    tid = db.crear_tarea_outlook(a, asunto="Por herramienta")
    r = ih.ejecutar(a, "pedir_revision_tarea", {"tarea_id": tid, "revisor_ids": [b, c], "modo": "todos"})
    assert r["pendiente"]["revisores"] == [b, c]
    assert ih.ejecutar(b, "resolver_revision_tarea", {"tarea_id": tid, "decision": "aprobar"})["revision"]["estado"] == "pendiente"
    with pytest.raises(ih.ErrorHerramientaIA, match="Ya has votado"):
        ih.ejecutar(b, "resolver_revision_tarea", {"tarea_id": tid, "decision": "aprobar"})
    assert ih.ejecutar(c, "resolver_revision_tarea", {"tarea_id": tid, "decision": "aprobar"})["revision"]["estado"] == "aprobada"
    with pytest.raises(ih.ErrorHerramientaIA, match="hasta 5"):
        ih.ejecutar(a, "pedir_revision_tarea", {"tarea_id": tid, "revisor_ids": [b, c, 901, 902, 903, 904]})
