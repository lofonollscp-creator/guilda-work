"""Fase 1 del plan (app/tareas_trabajo.py): versión con 409, motivo de bloqueo, varios clientes por tarea con un solo principal, vencida derivada y tareas de un cliente."""
from datetime import date, timedelta

from app import db, tareas_trabajo as tt
from tests.test_api_tareas import _tarea, _usuario


def _despacho(cliente, correo, nombre):
    t = db.crear_tenant(nombre)
    h, uid = _usuario(cliente, correo, t)
    return t, h, uid


def _version(cliente, h, tid):
    return cliente.get(f"/api/v1/tareas-outlook/{tid}", headers=h).get_json()["data"]["version"]


def test_vencida_es_derivada_y_se_compara_el_dia():
    hoy = date(2026, 10, 20)
    assert tt.esta_vencida("2026-10-19", "no_iniciada", hoy)
    assert tt.esta_vencida("2026-10-19T23:59:00", "en_progreso", hoy)
    assert not tt.esta_vencida("2026-10-20", "no_iniciada", hoy)          # vence hoy: todavía no
    assert not tt.esta_vencida("2026-10-19", "completada", hoy)
    assert not tt.esta_vencida(None, "no_iniciada", hoy)
    assert tt.esta_vencida("2026-10-01", "esperando", hoy) and tt.esta_vencida("2026-10-01", "aplazada", hoy)


def test_la_version_sube_con_cualquier_escritura_y_el_conflicto_da_409(cliente):
    _, h, _ = _despacho(cliente, "v1@ejemplo.com", "Despacho versión")
    tid = _tarea(cliente, h, "Con versión")
    v0 = _version(cliente, h, tid)
    assert v0 >= 1
    cliente.put(f"/api/v1/tareas-outlook/{tid}", json={"asunto": "Otro título"}, headers=h)      # escritor antiguo, sin saber de versiones
    v1 = _version(cliente, h, tid)
    assert v1 > v0
    r = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "en_progreso", "version": v0}, headers=h)
    assert r.status_code == 409
    cuerpo = r.get_json()
    assert cuerpo["codigo"] == "version_obsoleta" and cuerpo["version_actual"] == v1
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}", headers=h).get_json()["data"]["estado"] == "no_iniciada"     # el conflicto no cambió nada
    r = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "en_progreso", "version": v1}, headers=h)
    assert r.status_code == 200 and r.get_json()["data"]["estado"] == "en_progreso"
    assert r.get_json()["data"]["version"] > v1


def test_dos_escrituras_con_la_misma_version_solo_deja_pasar_una(cliente):
    _, h, _ = _despacho(cliente, "v2@ejemplo.com", "Despacho carrera")
    tid = _tarea(cliente, h, "Carrera")
    v = _version(cliente, h, tid)
    tt.reclamar_version(tid, v)                       # la primera gana
    try:
        tt.reclamar_version(tid, v)                   # la segunda llega con la versión vieja
        assert False, "debía haber conflicto"
    except tt.ConflictoDeVersion as e:
        assert e.actual > v
    tt.reclamar_version(tid, None)                    # sin versión, comportamiento de siempre


def test_version_invalida_y_cabecera_if_match(cliente):
    _, h, _ = _despacho(cliente, "v3@ejemplo.com", "Despacho cabecera")
    tid = _tarea(cliente, h, "Cabecera")
    r = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "en_progreso", "version": "abc"}, headers=h)
    assert r.status_code == 400 and r.get_json()["codigo"] == "version_invalida"
    v = _version(cliente, h, tid)
    r = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "en_progreso"}, headers={**h, "If-Match": f'"{v}"'})
    assert r.status_code == 200


def test_bloqueo_exige_motivo_y_se_limpia_al_salir(cliente):
    _, h, _ = _despacho(cliente, "b1@ejemplo.com", "Despacho bloqueo")
    tid = _tarea(cliente, h, "Bloqueable")
    r = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "esperando"}, headers=h)
    assert r.status_code == 400 and r.get_json()["codigo"] == "motivo_obligatorio"
    r = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "esperando", "motivo": "  Falta el certificado  "}, headers=h)
    assert r.status_code == 200
    assert r.get_json()["data"]["estado"] == "esperando" and r.get_json()["data"]["motivo_bloqueo"] == "Falta el certificado"
    r = cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "en_progreso", "motivo": "ignorado"}, headers=h)
    assert r.get_json()["data"]["motivo_bloqueo"] is None
    assert cliente.post(f"/api/v1/tareas-outlook/{tid}/transiciones", json={"estado": "inventado"}, headers=h).get_json()["codigo"] == "estado_invalido"
    actividad = cliente.get(f"/api/v1/tareas-outlook/{tid}/actividad", headers=h).get_json()["data"]
    assert any(a["tipo"] == "bloqueada" and "certificado" in a["detalle"] for a in actividad)


def test_transicion_respeta_dependencias_y_permisos(cliente):
    t, h, _ = _despacho(cliente, "p1@ejemplo.com", "Despacho permisos")
    h2, u2 = _usuario(cliente, "p2@ejemplo.com", t)
    a, b = _tarea(cliente, h, "A"), _tarea(cliente, h, "B")
    cliente.post(f"/api/v1/tareas-outlook/{b}/dependencias", json={"depende_de_id": a}, headers=h)
    r = cliente.post(f"/api/v1/tareas-outlook/{b}/transiciones", json={"estado": "completada"}, headers=h)
    assert r.status_code == 409 and r.get_json()["codigo"] == "tarea_bloqueada"
    assert cliente.post(f"/api/v1/tareas-outlook/{a}/compartir", json={"usuario_id": u2, "rol": "observa"}, headers=h).status_code == 201
    r = cliente.post(f"/api/v1/tareas-outlook/{a}/transiciones", json={"estado": "en_progreso"}, headers=h2)
    assert r.status_code == 403 and r.get_json()["codigo"] == "sin_permiso"         # un observador solo mira
    assert cliente.post(f"/api/v1/tareas-outlook/{a}/transiciones", json={"estado": "en_progreso"}, headers=_otro_despacho(cliente)).status_code == 404


def _otro_despacho(cliente):
    return _despacho(cliente, "ajeno@ejemplo.com", "Despacho ajeno")[1]


def test_varios_clientes_un_solo_principal_y_sincronizado(cliente):
    t, h, uid = _despacho(cliente, "c1@ejemplo.com", "Despacho clientes")
    c1, c2, c3 = (db.crear_cliente_fiscal(t, n) for n in ("Alfa SL", "Beta SL", "Gamma SL"))
    tid = _tarea(cliente, h, "Para varios clientes")
    r = cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": [c1, c2, c3, c2], "principal_id": c2}, headers=h)
    assert r.status_code == 200
    clientes = r.get_json()["data"]["clientes"]
    assert {c["id"] for c in clientes} == {c1, c2, c3} and [c["id"] for c in clientes if c["principal"]] == [c2]
    assert clientes[0]["id"] == c2                                                      # el principal va primero
    assert db.obtener_tarea_outlook(uid, tid)["cliente_fiscal_id"] == c2               # lo antiguo sigue funcionando
    r = cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": [c1, c3]}, headers=h)
    assert [c["id"] for c in r.get_json()["data"]["clientes"] if c["principal"]] == [c1]    # sin indicar, el primero
    assert db.obtener_tarea_outlook(uid, tid)["cliente_fiscal_id"] == c1
    r = cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": [c1], "principal_id": c3}, headers=h)
    assert r.status_code == 400 and r.get_json()["codigo"] == "principal_invalido"
    r = cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": []}, headers=h)
    assert r.status_code == 200 and r.get_json()["data"]["clientes"] == []
    assert db.obtener_tarea_outlook(uid, tid)["cliente_fiscal_id"] is None            # tarea interna, sin cliente
    assert cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": "1"}, headers=h).get_json()["codigo"] == "cliente_ids_invalido"


def test_no_se_vincula_un_cliente_de_otro_despacho(cliente):
    t, h, uid = _despacho(cliente, "a1@ejemplo.com", "Despacho A")
    t2 = db.crear_tenant("Despacho B")
    ajeno = db.crear_cliente_fiscal(t2, "Cliente de B")
    propio = db.crear_cliente_fiscal(t, "Cliente de A")
    tid = _tarea(cliente, h, "Aislada")
    assert cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": [propio]}, headers=h).status_code == 200
    r = cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": [propio, ajeno]}, headers=h)
    assert r.status_code == 422 and r.get_json()["codigo"] == "cliente_invalido"
    assert [c["id"] for c in tt.clientes_de_tarea(tid)] == [propio]                    # nada cambió: se rechaza entero, no se ignora a medias
    assert cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": [999999]}, headers=h).status_code == 422


def test_solo_quien_edita_la_tarea_cambia_sus_clientes(cliente):
    t, h, _ = _despacho(cliente, "e1@ejemplo.com", "Despacho edición")
    h2, u2 = _usuario(cliente, "e2@ejemplo.com", t)
    c1 = db.crear_cliente_fiscal(t, "Delta SL")
    tid = _tarea(cliente, h, "Ajena")
    cliente.post(f"/api/v1/tareas-outlook/{tid}/compartir", json={"usuario_id": u2, "rol": "observa"}, headers=h)
    assert cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": [c1]}, headers=h2).status_code == 403
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}/clientes", headers=h2).status_code == 200


def test_los_escritores_antiguos_mantienen_el_vinculo_principal(cliente):
    t, h, uid = _despacho(cliente, "s1@ejemplo.com", "Despacho sincronía")
    c1, c2 = db.crear_cliente_fiscal(t, "Épsilon SL"), db.crear_cliente_fiscal(t, "Zeta SL")
    tid = db.crear_tarea_outlook(uid, asunto="Creada a la antigua", cliente_fiscal_id=c1)
    assert [(c["id"], c["principal"]) for c in tt.clientes_de_tarea(tid)] == [(c1, True)]
    db.editar_tarea_outlook(uid, tid, cliente_fiscal_id=c2)
    assert [(c["id"], c["principal"]) for c in tt.clientes_de_tarea(tid)] == [(c2, True)]      # el escritor antiguo reemplaza al cliente
    db.editar_tarea_outlook(uid, tid, cliente_fiscal_id=None)
    assert tt.clientes_de_tarea(tid) == []
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tarea_clientes WHERE tarea_id = ? AND principal = 1", (tid,)).fetchone()[0] == 0
        assert conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ? AND cliente_fiscal_id IS NULL", (tid,)).fetchone() is not None
    finally:
        conn.close()


def test_el_filtro_de_cliente_incluye_los_vinculados_y_tareas_del_cliente(cliente):
    t, h, uid = _despacho(cliente, "f1@ejemplo.com", "Despacho filtro")
    c1, c2 = db.crear_cliente_fiscal(t, "Eta SL"), db.crear_cliente_fiscal(t, "Theta SL")
    ayer, manana = (date.today() - timedelta(days=1)).isoformat(), (date.today() + timedelta(days=1)).isoformat()
    a = _tarea(cliente, h, "Vencida de ambos", fecha_vencimiento=ayer)
    b = _tarea(cliente, h, "Futura solo de c1", fecha_vencimiento=manana)
    c = _tarea(cliente, h, "Hecha de c1")
    d = _tarea(cliente, h, "De c2")
    cliente.put(f"/api/v1/tareas-outlook/{a}/clientes", json={"cliente_ids": [c1, c2]}, headers=h)
    cliente.put(f"/api/v1/tareas-outlook/{b}/clientes", json={"cliente_ids": [c1]}, headers=h)
    cliente.put(f"/api/v1/tareas-outlook/{c}/clientes", json={"cliente_ids": [c1]}, headers=h)
    cliente.put(f"/api/v1/tareas-outlook/{d}/clientes", json={"cliente_ids": [c2]}, headers=h)
    cliente.post(f"/api/v1/tareas-outlook/{c}/estado", json={"estado": "completada"}, headers=h)
    r = cliente.get(f"/api/v1/fiscal/clientes/{c1}/tareas", headers=h).get_json()
    assert {x["id"] for x in r["data"]} == {a, b, c}                                    # vinculadas, no solo la principal
    assert r["contadores"] == {"abiertas": 2, "vencidas": 1, "completadas": 1, "total": 3}
    assert [x["id"] for x in r["data"]][-1] == c                                        # las completadas al final
    vencidas = cliente.get(f"/api/v1/fiscal/clientes/{c1}/tareas?vencidas=1", headers=h).get_json()
    assert [x["id"] for x in vencidas["data"]] == [a] and vencidas["data"][0]["vencida"] is True
    assert vencidas["contadores"]["total"] == 3                                         # los contadores no dependen del filtro
    assert {x["id"] for x in cliente.get(f"/api/v1/fiscal/clientes/{c2}/tareas?estado=no_iniciada", headers=h).get_json()["data"]} == {a, d}


def test_tareas_de_un_cliente_no_cruzan_despachos(cliente):
    t, h, _ = _despacho(cliente, "x1@ejemplo.com", "Despacho X")
    _, h2, _ = _despacho(cliente, "x2@ejemplo.com", "Despacho Y")
    c1 = db.crear_cliente_fiscal(t, "Iota SL")
    _tarea(cliente, h, "Privada")
    assert cliente.get(f"/api/v1/fiscal/clientes/{c1}/tareas", headers=h2).status_code == 404


def test_ficha_del_cliente_muestra_los_contadores(cliente):
    from app import ficha_cliente
    t, h, uid = _despacho(cliente, "fi@ejemplo.com", "Despacho ficha")
    c1 = db.crear_cliente_fiscal(t, "Kappa SL")
    ayer = (date.today() - timedelta(days=1)).isoformat()
    a = _tarea(cliente, h, "Vencida", fecha_vencimiento=ayer)
    b = _tarea(cliente, h, "Al día")
    for tid in (a, b):
        cliente.put(f"/api/v1/tareas-outlook/{tid}/clientes", json={"cliente_ids": [c1]}, headers=h)
    ctx = ficha_cliente.contexto_tareas(uid, db.obtener_cliente_fiscal(t, c1))
    assert (ctx["tareas_abiertas"], ctx["tareas_vencidas"], ctx["tareas_completadas"]) == (2, 1, 0)
    assert [x["vencida"] for x in ctx["tareas"]] == [True, False]


def test_migracion_idempotente_y_rellena_lo_existente(cliente):
    t, h, uid = _despacho(cliente, "m1@ejemplo.com", "Despacho migración")
    c1 = db.crear_cliente_fiscal(t, "Lambda SL")
    tid = db.crear_tarea_outlook(uid, asunto="Antigua", cliente_fiscal_id=c1)
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM tarea_clientes WHERE tarea_id = ?", (tid,))          # como estaba antes de existir la tabla
        conn.commit()
        tt.crear_esquema(conn)
        tt.crear_esquema(conn)                                                         # repetirla no duplica ni falla
        conn.commit()
        filas = conn.execute("SELECT principal FROM tarea_clientes WHERE tarea_id = ?", (tid,)).fetchall()
    finally:
        conn.close()
    assert [f["principal"] for f in filas] == [1]


def test_borrar_un_cliente_o_un_despacho_no_se_atasca_con_tareas_vinculadas(cliente):
    t, h, uid = _despacho(cliente, "bd1@ejemplo.com", "Despacho borrado")
    c1, c2 = db.crear_cliente_fiscal(t, "Borrable SL"), db.crear_cliente_fiscal(t, "Quedará SL")
    tid = db.crear_tarea_outlook(uid, asunto="Vinculada", cliente_fiscal_id=c1)
    tt.fijar_clientes(uid, tid, [c1, c2], c1)
    db.eliminar_cliente_fiscal_definitivamente(t, c1)                      # antes lanzaba IntegrityError por la clave foránea de tarea_clientes
    assert [c["id"] for c in tt.clientes_de_tarea(tid)] == [c2]
    db.borrar_tenant(t)                                                    # y el despacho entero, igual
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tarea_clientes WHERE tarea_id = ?", (tid,)).fetchone()[0] == 0
        assert conn.execute("SELECT 1 FROM tareas_outlook WHERE id = ?", (tid,)).fetchone() is not None       # la tarea es de la persona y se conserva
    finally:
        conn.close()
