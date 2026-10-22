"""Reglas de automatización (app/automatizaciones.py): idempotencia, reintentos, sin bucles, permisos y aislamiento entre despachos."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import automatizaciones as au, certificados as ce, db, tareas_trabajo as tt

AHORA = datetime(2026, 10, 20, 8, 0, 0, tzinfo=timezone.utc)
HOY = AHORA.date()


@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Automatizaciones")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.cus, e.otro = u("sup-au@ejemplo.com", True), u("cus-au@ejemplo.com"), u("otro-au@ejemplo.com")
    ce.fijar_custodio_flag(t, e.sup, e.cus, True)
    e.cliente = db.crear_cliente_fiscal(t, "Marta Puig", nif="12345678Z")
    return e


def _cert(d, dias, **kw):
    return ce.alta_rapida(d.t, d.sup, tipo="otro", caduca=(HOY + timedelta(days=dias)).isoformat(), titular=kw.pop("titular", "Marta Puig"), custodio_id=d.cus, cliente_fiscal_id=d.cliente, **kw)["id"]


def _regla_cert(d, dias_antes=30, **kw):
    return au.crear_regla(d.t, d.sup, "Renovar", "certificado.caduca", {"dias_antes": dias_antes}, kw.get("acciones") or [
        {"tipo": "crear_tarea", "asunto": "Renovar el certificado de {titular} ({fecha})", "prioridad": "alta", "dias_plazo": 10, "asignar_a": "responsable"},
        {"tipo": "notificar", "titulo": "Caduca {titular}", "cuerpo": "En {dias} días", "a": "responsable"}])


def _tareas(uid):
    return [dict(t) for t in db.listar_tareas_outlook(uid, incluir_asignadas=True)]


def _notificaciones(uid):
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM notificaciones WHERE usuario_id = ? ORDER BY id", (uid,))]
    finally:
        conn.close()


# --- Validación y permisos ---------------------------------------------------------------------------------------------

def test_validacion_de_condiciones_y_acciones(d):
    assert au.validar_condiciones("certificado.caduca", {}) == {"dias_antes": 30}
    assert au.validar_condiciones("tarea.vencida", {"dias_vencida": "5", "prioridades": ["alta", "rara"]}) == {"dias_vencida": 5, "prioridades": ["alta"]}
    for malo in ({"dias_antes": -1}, {"dias_antes": 9999}, {"dias_antes": "x"}):
        with pytest.raises(ValueError):
            au.validar_condiciones("certificado.caduca", malo)
    with pytest.raises(ValueError):
        au.validar_condiciones("inventado", {})
    for malas in ([], [{"tipo": "borrar_todo"}], [{"tipo": "crear_tarea", "asunto": " "}], [{"tipo": "notificar"}], [{"tipo": "comentar", "texto": "x"}],
                  [{"tipo": "notificar", "titulo": "a", "a": "nadie_raro"}], [{"tipo": "notificar", "titulo": "a"}] * (au.MAX_ACCIONES + 1)):
        with pytest.raises(ValueError):
            au.validar_acciones("certificado.caduca", malas)
    assert au.validar_acciones("tarea.vencida", [{"tipo": "comentar", "texto": "hola"}])[0]["texto"] == "hola"


def test_solo_la_direccion_gestiona_reglas_y_queda_auditado(d):
    with pytest.raises(PermissionError):
        _regla_cert_con(d, d.otro)
    rid = _regla_cert(d)
    with pytest.raises(PermissionError):
        au.cambiar_regla(d.t, d.cus, rid, activa=False)
    with pytest.raises(PermissionError):
        au.borrar_regla(d.t, d.otro, rid)
    r = au.cambiar_regla(d.t, d.sup, rid, activa=False)
    assert r["activa"] is False and r["version"] == 1
    r = au.cambiar_regla(d.t, d.sup, rid, condiciones={"dias_antes": 45})
    assert r["version"] == 2 and r["condiciones"] == {"dias_antes": 45}
    from app import auditoria
    assert {e["accion"] for e in auditoria.listar(d.t, entidad="regla")} >= {"automatizacion.crear", "automatizacion.cambiar"}
    assert au.obtener_regla(db.crear_tenant("Otro"), rid) is None                                  # no se ve desde otro despacho


def _regla_cert_con(d, quien):
    return au.crear_regla(d.t, quien, "X", "certificado.caduca", {}, [{"tipo": "notificar", "titulo": "a"}])


def test_limite_de_reglas_por_despacho(d, monkeypatch):
    monkeypatch.setattr(au, "MAX_REGLAS", 2)
    _regla_cert(d); _regla_cert(d)
    with pytest.raises(ValueError):
        _regla_cert(d)


# --- Certificados -------------------------------------------------------------------------------------------------------

def test_certificado_cerca_de_caducar_crea_una_sola_tarea_aunque_se_repita(d):
    _regla_cert(d)
    c = _cert(d, 20)
    _cert(d, 90, titular="Lejano")                                         # fuera de la ventana
    r1 = au.ejecutar(d.t, AHORA)
    assert (r1["nuevas"], r1["ok"]) == (1, 1)
    for _ in range(3):
        assert au.ejecutar(d.t, AHORA + timedelta(hours=2))["nuevas"] == 0
    tareas = _tareas(d.cus)
    assert len(tareas) == 1
    t = tareas[0]
    assert t["asunto"] == f"Renovar el certificado de Marta Puig ({(HOY + timedelta(days=20)).isoformat()})"
    assert t["prioridad"] == "alta" and t["fecha_vencimiento"][:10] == (HOY + timedelta(days=10)).isoformat() and t["cliente_fiscal_id"] == d.cliente
    assert t["referencia_externa"].startswith("auto:")
    avisos = [n for n in _notificaciones(d.cus) if n["tipo"] == "automatizacion"]
    assert len(avisos) == 1 and "En 20 días" in avisos[0]["cuerpo"]
    assert [e["estado"] for e in au.ejecuciones(d.t)] == ["ok"] and c


def test_un_certificado_renovado_deja_de_avisar_y_el_nuevo_ciclo_avisa_otra_vez(d):
    _regla_cert(d)
    c = _cert(d, 20)
    au.ejecutar(d.t, AHORA)
    r = ce.renovado(d.t, d.sup, c, (HOY + timedelta(days=365)).isoformat())              # misma entrada con nueva caducidad: la clave cambia
    assert au.ejecutar(d.t, AHORA + timedelta(days=1))["nuevas"] == 0      # a 365 días no entra en la ventana
    assert len(_tareas(d.cus)) == 1
    assert au.ejecutar(d.t, AHORA + timedelta(days=340))["nuevas"] == 1    # un año después, caducidad nueva ⇒ aviso nuevo
    assert len(_tareas(d.cus)) == 2 and r


def test_un_certificado_con_sucesor_no_dispara(d):
    _regla_cert(d)
    c = _cert(d, 10)
    n = _cert(d, 300, titular="Sucesor")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE certificados SET sustituye_a = ? WHERE id = ?", (c, n))
        conn.commit()
    finally:
        conn.close()
    assert au.ejecutar(d.t, AHORA)["nuevas"] == 0


def test_simular_no_escribe_nada(d):
    rid = _regla_cert(d)
    _cert(d, 5); _cert(d, 15, titular="Otro titular")
    s = au.simular(d.t, rid, AHORA)
    assert (s["cumplen"], s["nuevas"], s["ya_atendidas"]) == (2, 2, 0) and {e["datos"]["titular"] for e in s["ejemplos"]} == {"Marta Puig", "Otro titular"}
    assert _tareas(d.cus) == [] and au.ejecuciones(d.t) == []
    au.ejecutar(d.t, AHORA)
    assert au.simular(d.t, rid, AHORA)["ya_atendidas"] == 2


def test_una_regla_apagada_no_hace_nada(d):
    rid = _regla_cert(d)
    _cert(d, 5)
    au.cambiar_regla(d.t, d.sup, rid, activa=False)
    assert au.ejecutar(d.t, AHORA)["reglas"] == 0 and _tareas(d.cus) == []


# --- Tareas vencidas y vencimientos -------------------------------------------------------------------------------------------

def test_tarea_vencida_avisa_deja_nota_y_no_se_dispara_a_si_misma(d):
    au.crear_regla(d.t, d.sup, "Vencidas", "tarea.vencida", {"dias_vencida": 3}, [
        {"tipo": "notificar", "titulo": "Vencida: {asunto}", "cuerpo": "Desde el {fecha}", "a": "responsable"}, {"tipo": "comentar", "texto": "Aviso: {dias} días vencida"}])
    vieja = db.crear_tarea_outlook(d.otro, asunto="Presentar IVA", fecha_vencimiento=(HOY - timedelta(days=5)).isoformat())
    db.crear_tarea_outlook(d.otro, asunto="Reciente", fecha_vencimiento=(HOY - timedelta(days=1)).isoformat())
    hecha = db.crear_tarea_outlook(d.otro, asunto="Hecha", fecha_vencimiento=(HOY - timedelta(days=9)).isoformat())
    db.completar_tarea_outlook(d.otro, hecha)
    r = au.ejecutar(d.t, AHORA)
    assert r["nuevas"] == 1 and au.ejecutar(d.t, AHORA)["nuevas"] == 0
    assert [n["titulo"] for n in _notificaciones(d.otro) if n["tipo"] == "automatizacion"] == ["Vencida: Presentar IVA"]
    assert any(a["tipo"] == "automatizacion" and "5 días" in a["detalle"] for a in db.actividad_de_tarea(d.otro, vieja))


def test_las_tareas_creadas_por_una_regla_no_activan_reglas_de_tareas_vencidas(d):
    _regla_cert(d, acciones=[{"tipo": "crear_tarea", "asunto": "Renovar {titular}", "dias_plazo": 0, "asignar_a": "responsable"}])
    au.crear_regla(d.t, d.sup, "Vencidas", "tarea.vencida", {"dias_vencida": 1}, [{"tipo": "notificar", "titulo": "Vencida {asunto}", "a": "responsable"}])
    _cert(d, 10)
    au.ejecutar(d.t, AHORA)
    mas_tarde = AHORA + timedelta(days=10)
    r = au.ejecutar(d.t, mas_tarde)
    assert r["nuevas"] == 0                       # la tarea automática ya está vencida, pero no vuelve a disparar nada (sin bucle)
    assert [n for n in _notificaciones(d.cus) if n["tipo"] == "automatizacion" and n["titulo"].startswith("Vencida")] == []


def test_filtros_de_tarea_vencida(d):
    au.crear_regla(d.t, d.sup, "Solo altas", "tarea.vencida", {"dias_vencida": 1, "prioridades": ["alta"], "cliente_fiscal_id": d.cliente}, [{"tipo": "notificar", "titulo": "x {asunto}", "a": "responsable"}])
    ayer = (HOY - timedelta(days=3)).isoformat()
    db.crear_tarea_outlook(d.otro, asunto="Alta con cliente", prioridad="alta", fecha_vencimiento=ayer, cliente_fiscal_id=d.cliente)
    db.crear_tarea_outlook(d.otro, asunto="Normal", prioridad="normal", fecha_vencimiento=ayer, cliente_fiscal_id=d.cliente)
    db.crear_tarea_outlook(d.otro, asunto="Alta sin cliente", prioridad="alta", fecha_vencimiento=ayer)
    assert au.ejecutar(d.t, AHORA)["nuevas"] == 1


def test_vencimiento_proximo_crea_la_tarea_solo_si_esta_pendiente(d):
    au.crear_regla(d.t, d.sup, "Modelos", "vencimiento.proximo", {"dias_antes": 7, "modelo": "303"}, [
        {"tipo": "crear_tarea", "asunto": "Preparar {modelo} de {cliente} ({periodo})", "dias_plazo": 3, "asignar_a": d.otro}])
    db.crear_vencimiento_fiscal(d.t, d.cliente, "303", "2026-T3", (HOY + timedelta(days=5)).isoformat())
    db.crear_vencimiento_fiscal(d.t, d.cliente, "111", "2026-T3", (HOY + timedelta(days=5)).isoformat())           # otro modelo
    db.crear_vencimiento_fiscal(d.t, d.cliente, "303", "2026-T4", (HOY + timedelta(days=60)).isoformat())          # lejos
    v = db.crear_vencimiento_fiscal(d.t, d.cliente, "303", "2026-T2", (HOY + timedelta(days=2)).isoformat())
    conn = db.get_connection()
    try:
        conn.execute("UPDATE vencimientos_fiscales SET estado = 'presentado' WHERE id = ?", (v,))
        conn.commit()
    finally:
        conn.close()
    assert au.ejecutar(d.t, AHORA)["nuevas"] == 1
    assert [t["asunto"] for t in _tareas(d.otro)] == ["Preparar 303 de Marta Puig (2026-T3)"]


# --- Reintentos y fallos -----------------------------------------------------------------------------------------------------------

def test_reintentos_con_espera_y_aviso_unico_a_la_direccion_al_fallar_del_todo(d, monkeypatch):
    _regla_cert(d)
    _cert(d, 5)
    original = au._aplicar
    monkeypatch.setattr(au, "_aplicar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("servicio caído")))
    r = au.ejecutar(d.t, AHORA)
    assert (r["nuevas"], r["errores"]) == (1, 1)
    e = au.ejecuciones(d.t)[0]
    assert (e["estado"], e["intentos"], e["error"]) == ("error", 1, "RuntimeError: servicio caído")
    assert au.ejecutar(d.t, AHORA + timedelta(minutes=5))["reintentos"] == 0                 # aún no toca
    assert au.ejecutar(d.t, AHORA + timedelta(minutes=16))["errores"] == 1                    # segundo intento
    r = au.ejecutar(d.t, AHORA + timedelta(minutes=16 + 61))
    assert r["fallidas"] == 1
    e = au.ejecuciones(d.t)[0]
    assert (e["estado"], e["intentos"]) == ("fallida", 3)
    fallos = [n for n in _notificaciones(d.sup) if n["tipo"] == "automatizacion_fallo"]
    assert len(fallos) == 1 and "servicio caído" in fallos[0]["cuerpo"]
    assert au.ejecutar(d.t, AHORA + timedelta(days=2))["reintentos"] == 0                     # una fallida no insiste sola
    assert len([n for n in _notificaciones(d.sup) if n["tipo"] == "automatizacion_fallo"]) == 1
    monkeypatch.setattr(au, "_aplicar", original)
    with pytest.raises(PermissionError):
        au.reintentar(d.t, d.otro, e["id"])
    assert au.reintentar(d.t, d.sup, e["id"]) is True and au.reintentar(d.t, d.sup, e["id"]) is False
    assert au.ejecutar(d.t, datetime.now(timezone.utc) + timedelta(minutes=1))["ok"] == 1          # «reintentar» usa el reloj real: se avanza desde ahora, no desde la fecha simulada
    assert len(_tareas(d.cus)) == 1


def test_al_reintentar_no_se_repiten_las_acciones_ya_hechas(d, monkeypatch):
    _regla_cert(d)
    _cert(d, 5)
    original = au._aplicar
    llamadas = {"n": 0}

    def inestable(tenant_id, regla, oc, accion, clave, hoy):
        if accion["tipo"] == "notificar" and llamadas["n"] == 0:
            llamadas["n"] += 1
            raise RuntimeError("push caído")
        return original(tenant_id, regla, oc, accion, clave, hoy)
    monkeypatch.setattr(au, "_aplicar", inestable)
    au.ejecutar(d.t, AHORA)
    assert len(_tareas(d.cus)) == 1 and au.ejecuciones(d.t)[0]["progreso"] and au.ejecuciones(d.t)[0]["estado"] == "error"
    au.ejecutar(d.t, AHORA + timedelta(minutes=20))
    assert len(_tareas(d.cus)) == 1                                           # la tarea no se duplicó
    e = au.ejecuciones(d.t)[0]
    assert e["estado"] == "ok" and len(e["progreso"]) == 2


def test_un_reintento_cuyo_objeto_ya_no_cumple_se_cierra_sin_actuar(d, monkeypatch):
    _regla_cert(d)
    c = _cert(d, 5)
    original = au._aplicar
    monkeypatch.setattr(au, "_aplicar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falla")))
    au.ejecutar(d.t, AHORA)
    monkeypatch.setattr(au, "_aplicar", original)
    ce.renovado(d.t, d.sup, c, (HOY + timedelta(days=700)).isoformat())                      # entre tanto se renueva
    au.ejecutar(d.t, AHORA + timedelta(minutes=20))
    e = au.ejecuciones(d.t)[0]
    assert e["estado"] == "ok" and "Ya no se cumple" in e["error"] and _tareas(d.cus) == []


def test_una_ejecucion_encallada_se_recupera(d):
    rid = _regla_cert(d)
    _cert(d, 5)
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO automatizaciones_ejecuciones (tenant_id, regla_id, regla_version, clave, objeto, estado, creada_en, actualizada_en) VALUES (?, ?, 1, ?, 'x', 'pendiente', '2026-10-20T07:00:00', '2026-10-20T07:00:00')",
                     (d.t, rid, f"cert:{[f['id'] for f in _certs(d.t)][0]}:{(HOY + timedelta(days=5)).isoformat()}"))
        conn.commit()
    finally:
        conn.close()
    assert au.ejecutar(d.t, AHORA)["reintentos"] == 1 and len(_tareas(d.cus)) == 1


def _certs(t):
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id FROM certificados WHERE tenant_id = ?", (t,))]
    finally:
        conn.close()


# --- Topes, despachos y tiempo -----------------------------------------------------------------------------------------------------

def test_tope_por_pasada_y_continuacion(d, monkeypatch):
    _regla_cert(d, acciones=[{"tipo": "crear_tarea", "asunto": "Renovar {titular}", "asignar_a": "responsable"}])
    for i in range(5):
        _cert(d, 5 + i, titular=f"Titular {i}")
    monkeypatch.setattr(au, "MAX_POR_PASADA", 2)
    r = au.ejecutar(d.t, AHORA)
    assert r["nuevas"] == 2 and r["topes"] >= 1
    assert au.ejecutar(d.t, AHORA)["nuevas"] == 2 and au.ejecutar(d.t, AHORA)["nuevas"] == 1
    assert len(_tareas(d.cus)) == 5


def test_las_reglas_de_un_despacho_no_tocan_datos_de_otro(d):
    otro = db.crear_tenant("Despacho vecino")
    v = db.crear_usuario_vinculado_a_kratos("sup-vecino@ejemplo.com", "k-sv"); db.asignar_tenant(v, otro); db.asignar_supervisor_tenant(v, True)
    au.crear_regla(otro, v, "Vecino", "certificado.caduca", {"dias_antes": 365}, [{"tipo": "crear_tarea", "asunto": "Renovar {titular}", "asignar_a": "responsable"}])
    _cert(d, 5)
    r = au.ejecutar(None, AHORA)                                     # pasada global
    assert r["nuevas"] == 0 and _tareas(v) == [] and _tareas(d.cus) == []
    assert au.ejecuciones(d.t) == [] and au.ejecuciones(otro) == []
    assert au.ejecutar(d.t, AHORA)["reglas"] == 0


def test_hoy_depende_de_la_zona_del_despacho(d):
    justo = datetime(2026, 10, 20, 23, 30, tzinfo=timezone.utc)
    assert au.hoy_del_despacho(d.t, justo).isoformat() == "2026-10-21"          # Madrid ya es el 21 (UTC+2)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tenants SET zona_horaria = 'America/Los_Angeles' WHERE id = ?", (d.t,))
        conn.commit()
    finally:
        conn.close()
    assert au.hoy_del_despacho(d.t, justo).isoformat() == "2026-10-20"


def test_las_plantillas_son_validas_y_rellenar_no_ejecuta_nada(d):
    for p in au.PLANTILLAS.values():
        au.crear_regla(d.t, d.sup, p["nombre"], p["disparador"], p["condiciones"], p["acciones"])
    assert len(au.listar_reglas(d.t)) == len(au.PLANTILLAS)
    assert au.rellenar("Hola {nombre} {__class__} {x.y} {desconocida}", {"nombre": "Ana"}) == "Hola Ana  {x.y} "


def test_borrar_el_despacho_borra_sus_reglas_y_ejecuciones(d):
    _regla_cert(d)
    _cert(d, 5)
    au.ejecutar(d.t, AHORA)
    db.borrar_tenant(d.t)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM automatizaciones_reglas WHERE tenant_id = ?", (d.t,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM automatizaciones_ejecuciones WHERE tenant_id = ?", (d.t,)).fetchone()[0] == 0
    finally:
        conn.close()


# --- Pantalla ------------------------------------------------------------------------------------------------------------------

def test_pantalla_de_automatizaciones_solo_para_la_direccion(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "dir-au@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho pantalla")
    db.asignar_tenant(uid, t)
    assert cliente.get("/tareas/automatizaciones").status_code == 404                  # sin ser dirección ni lo ve
    assert "Automatizaciones" not in cliente.get("/tareas/recurrentes").get_data(as_text=True)
    db.asignar_supervisor_tenant(uid, True)
    assert "Automatizaciones" in cliente.get("/tareas/recurrentes").get_data(as_text=True)
    assert cliente.post("/tareas/automatizaciones/nueva", data={"plantilla": "inventada"}).status_code == 400
    assert cliente.post("/tareas/automatizaciones/nueva", data={"plantilla": "renovar_certificado"}).status_code == 302
    regla = au.listar_reglas(t)[0]
    html = cliente.get("/tareas/automatizaciones").get_data(as_text=True)
    assert regla["nombre"] in html and "Activa" in html
    r = cliente.post(f"/tareas/automatizaciones/{regla['id']}/cambiar", data={"dias": "45"})
    assert au.obtener_regla(t, regla["id"])["condiciones"] == {"dias_antes": 45} and r.status_code == 302
    html = cliente.post(f"/tareas/automatizaciones/{regla['id']}/cambiar", data={"dias": "9999"}, follow_redirects=True).get_data(as_text=True)
    assert "entre 0 y 365" in html and au.obtener_regla(t, regla["id"])["condiciones"] == {"dias_antes": 45}
    cliente.post(f"/tareas/automatizaciones/{regla['id']}/cambiar", data={"accion": "apagar"})
    assert au.obtener_regla(t, regla["id"])["activa"] is False
    assert "no se ha creado ni enviado nada" in cliente.post(f"/tareas/automatizaciones/{regla['id']}/simular").get_data(as_text=True)
    assert cliente.post("/tareas/automatizaciones/999/borrar").status_code == 404
    assert cliente.post(f"/tareas/automatizaciones/{regla['id']}/borrar").status_code == 302 and au.listar_reglas(t) == []


def test_la_pantalla_enseña_los_fallos_y_permite_reintentar(cliente, monkeypatch):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "dir2-au@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho fallos")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    ce.fijar_custodio_flag(t, uid, uid, True)
    rid = au.crear_regla(t, uid, "Renovar", "certificado.caduca", {"dias_antes": 30}, [{"tipo": "crear_tarea", "asunto": "Renovar {titular}", "asignar_a": "responsable"}])
    ce.alta_rapida(t, uid, tipo="otro", caduca=(HOY + timedelta(days=5)).isoformat(), titular="Fallo SL", custodio_id=uid)
    original = au._aplicar
    monkeypatch.setattr(au, "_aplicar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("caída de prueba")))
    for minutos in (0, 16, 16 + 61):
        au.ejecutar(t, AHORA + timedelta(minutes=minutos))
    html = cliente.get("/tareas/automatizaciones").get_data(as_text=True)
    assert "ha fallado del todo" in html and "caída de prueba" in html and "Reintentar" in html and rid
    monkeypatch.setattr(au, "_aplicar", original)
    ejecucion = au.ejecuciones(t)[0]
    assert cliente.post(f"/tareas/automatizaciones/ejecuciones/{ejecucion['id']}/reintentar").status_code == 302
    au.ejecutar(t, datetime.now(timezone.utc) + timedelta(minutes=1))                     # «reintentar» usa el reloj real
    assert au.ejecuciones(t)[0]["estado"] == "ok" and "ha fallado del todo" not in cliente.get("/tareas/automatizaciones").get_data(as_text=True)


# --- Constructor de reglas ---------------------------------------------------------------------------------------------------------

def test_las_variables_de_los_textos_tienen_que_existir_para_ese_disparador(d):
    for disparador, ok, mala in (("certificado.caduca", "{titular} {fecha} {dias}", "{asunto}"), ("tarea.vencida", "{asunto} {fecha} {dias}", "{titular}"),
                                 ("vencimiento.proximo", "{modelo} {periodo} {cliente} {fecha} {dias}", "{titular}")):
        assert au.validar_acciones(disparador, [{"tipo": "notificar", "titulo": ok}])[0]["titulo"] == ok
        for accion in ({"tipo": "notificar", "titulo": mala}, {"tipo": "crear_tarea", "asunto": "x", "cuerpo": mala}):
            with pytest.raises(ValueError, match="no existe para este disparador"):
                au.validar_acciones(disparador, [accion])
    with pytest.raises(ValueError, match="Puedes usar: {titular}, {fecha}, {dias}"):
        au.validar_acciones("certificado.caduca", [{"tipo": "crear_tarea", "asunto": "Renovar {cliente}"}])


def test_las_personas_y_el_cliente_de_una_regla_tienen_que_ser_del_despacho(d):
    otro = db.crear_tenant("Despacho de otra gente")
    ajena = db.crear_usuario_vinculado_a_kratos("ajena-au@ejemplo.com", "k-ajena-au"); db.asignar_tenant(ajena, otro)
    cliente_ajeno = db.crear_cliente_fiscal(otro, "Cliente ajeno SL")
    with pytest.raises(ValueError, match="no es de tu despacho"):
        au.crear_regla(d.t, d.sup, "x", "certificado.caduca", {}, [{"tipo": "crear_tarea", "asunto": "Renovar", "asignar_a": ajena}])
    with pytest.raises(ValueError, match="no es de tu despacho"):
        au.crear_regla(d.t, d.sup, "x", "certificado.caduca", {}, [{"tipo": "notificar", "titulo": "Aviso", "a": ajena}])
    with pytest.raises(ValueError, match="cliente elegido no es de tu despacho"):
        au.crear_regla(d.t, d.sup, "x", "tarea.vencida", {"cliente_fiscal_id": cliente_ajeno}, [{"tipo": "notificar", "titulo": "Aviso"}])
    rid = au.crear_regla(d.t, d.sup, "bien", "tarea.vencida", {"cliente_fiscal_id": d.cliente}, [{"tipo": "notificar", "titulo": "Aviso", "a": d.otro}])
    with pytest.raises(ValueError, match="no es de tu despacho"):
        au.cambiar_regla(d.t, d.sup, rid, acciones=[{"tipo": "notificar", "titulo": "Aviso", "a": ajena}])


def test_el_formulario_se_traduce_a_condiciones_y_acciones():
    from werkzeug.datastructures import MultiDict
    f = MultiDict([("c_dias_tarea", "4"), ("c_prioridades", "alta"), ("c_prioridades", "normal"), ("c_cliente", "7"),
                   ("a0_tipo", "crear_tarea"), ("a0_asunto", "Llamar por {asunto}"), ("a0_cuerpo", "Hoy"), ("a0_prioridad", "alta"), ("a0_dias_plazo", "2"), ("a0_dest", "u:9"),
                   ("a1_tipo", ""), ("a1_asunto", "se ignora"),
                   ("a2_tipo", "notificar"), ("a2_titulo", "Vencida"), ("a2_cuerpo_aviso", "Desde {fecha}"), ("a2_dest_aviso", "direccion"),
                   ("a3_tipo", "comentar"), ("a3_texto", "Aviso automático")])
    cond, acc = au.formulario_a_regla(f, "tarea.vencida")
    assert cond == {"dias_vencida": "4", "prioridades": ["alta", "normal"], "cliente_fiscal_id": "7"}
    assert [a["tipo"] for a in acc] == ["crear_tarea", "notificar", "comentar"]
    assert acc[0]["asignar_a"] == "9" and acc[1]["a"] == "direccion" and acc[1]["cuerpo"] == "Desde {fecha}"
    assert au.formulario_a_regla(MultiDict([("c_dias_cert", "10")]), "certificado.caduca") == ({"dias_antes": "10"}, [])
    assert au.formulario_a_regla(MultiDict([("c_dias_venc", "3"), ("c_modelo", "303")]), "vencimiento.proximo")[0] == {"dias_antes": "3", "modelo": "303"}
    with pytest.raises(ValueError):
        au.formulario_a_regla(MultiDict(), "inventado")


def test_cambiar_las_acciones_deja_a_la_vista_lo_que_estaba_a_medias(d, monkeypatch):
    rid = _regla_cert(d)
    _cert(d, 5); _cert(d, 6, titular="Segundo")
    original = au._aplicar

    def inestable(tenant_id, regla, oc, accion, clave, hoy):
        if accion["tipo"] == "notificar" and oc["datos"]["titular"] == "Marta Puig":
            raise RuntimeError("push caído")                # a medias: la tarea ya se creó
        if oc["datos"]["titular"] == "Segundo":
            raise RuntimeError("falla antes de hacer nada") if accion["tipo"] == "crear_tarea" else RuntimeError("no llega")
        return original(tenant_id, regla, oc, accion, clave, hoy)
    monkeypatch.setattr(au, "_aplicar", inestable)
    au.ejecutar(d.t, AHORA)
    por_titular = {e["objeto"]: e for e in au.ejecuciones(d.t)}
    assert sorted(e["estado"] for e in por_titular.values()) == ["error", "error"]
    au.cambiar_regla(d.t, d.sup, rid, acciones=[{"tipo": "notificar", "titulo": "Otra cosa {titular}", "a": "responsable"}])
    estados = {e["objeto"]: (e["estado"], e["error"]) for e in au.ejecuciones(d.t)}
    a_medias = [v for v in estados.values() if v[0] == "fallida"]
    intactas = [v for v in estados.values() if v[0] == "error"]
    assert len(a_medias) == 1 and "La regla cambió" in a_medias[0][1] and len(intactas) == 1          # la que no había hecho nada sigue reintentándose
    assert au.cambiar_regla(d.t, d.sup, rid, nombre="Solo el nombre")["version"] == 2                  # y cambiar solo el nombre no toca nada de esto


def test_pantalla_del_constructor_crear_editar_y_errores(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "con1-au@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho constructor")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    otro = db.crear_usuario_vinculado_a_kratos("con1b-au@ejemplo.com", "k-con1b"); db.asignar_tenant(otro, t)
    cl = db.crear_cliente_fiscal(t, "Cliente Constructor SL")
    html = cliente.get("/tareas/automatizaciones/regla").get_data(as_text=True)
    assert 'id="constructor-regla"' in html and "1. Cuándo" in html and "2. Condición" in html and "3. Qué hace" in html and "Acción 5" in html and "{titular}" in html
    datos = {"nombre": "Vencidas a medida", "disparador": "tarea.vencida", "c_dias_tarea": "3", "c_prioridades": ["alta"], "c_cliente": str(cl), "activa": "1",
             "a0_tipo": "crear_tarea", "a0_asunto": "Reclamar: {asunto}", "a0_prioridad": "alta", "a0_dias_plazo": "1", "a0_dest": f"u:{otro}",
             "a1_tipo": "notificar", "a1_titulo": "Vencida hace {dias} días", "a1_dest_aviso": "direccion"}
    assert cliente.post("/tareas/automatizaciones/regla", data=datos).status_code == 302
    r = au.listar_reglas(t)[0]
    assert r["nombre"] == "Vencidas a medida" and r["condiciones"] == {"dias_vencida": 3, "prioridades": ["alta"], "cliente_fiscal_id": cl} and r["activa"] is True
    assert r["acciones"][0]["asignar_a"] == otro and r["acciones"][1]["a"] == "direccion"
    lista = cliente.get("/tareas/automatizaciones").get_data(as_text=True)
    assert "Crea la tarea «Reclamar: {asunto}»" in lista and "Avisa: «Vencida hace {dias} días»" in lista and "/automatizaciones/regla/" in lista
    # errores: se vuelve a enseñar lo escrito con el motivo
    malo = {**datos, "nombre": "Mala", "a0_asunto": "Hola {titular}"}
    resp = cliente.post("/tareas/automatizaciones/regla", data=malo)
    assert resp.status_code == 422 and "no existe para este disparador" in resp.get_data(as_text=True) and 'value="Mala"' in resp.get_data(as_text=True)
    assert len(au.listar_reglas(t)) == 1
    sin_acciones = {"nombre": "Vacía", "disparador": "certificado.caduca", "c_dias_cert": "20"}
    assert "al menos una acción" in cliente.post("/tareas/automatizaciones/regla", data=sin_acciones).get_data(as_text=True)
    assert cliente.post("/tareas/automatizaciones/regla", data={**datos, "disparador": "inventado"}).status_code == 400
    # editar: el disparador manda lo guardado
    html = cliente.get(f"/tareas/automatizaciones/regla/{r['id']}").get_data(as_text=True)
    assert "Vencidas a medida" in html and "no se puede cambiar" in html and f'value="{3}"' in html
    editado = {**datos, "nombre": "Editada", "disparador": "certificado.caduca", "c_dias_tarea": "5", "a1_tipo": "", "activa": ""}
    assert cliente.post(f"/tareas/automatizaciones/regla/{r['id']}", data=editado).status_code == 302
    r2 = au.obtener_regla(t, r["id"])
    assert r2["disparador"] == "tarea.vencida" and r2["nombre"] == "Editada" and r2["condiciones"]["dias_vencida"] == 5 and len(r2["acciones"]) == 1 and r2["activa"] is False and r2["version"] == 2
    assert cliente.get("/tareas/automatizaciones/regla/99999").status_code == 404


def test_el_constructor_no_deja_usar_personas_de_otro_despacho_ni_a_quien_no_es_direccion(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "con2-au@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho constructor dos")
    db.asignar_tenant(uid, t)
    assert cliente.get("/tareas/automatizaciones/regla").status_code == 404                           # no es dirección
    assert cliente.post("/tareas/automatizaciones/regla", data={"nombre": "x", "disparador": "certificado.caduca"}).status_code == 404
    db.asignar_supervisor_tenant(uid, True)
    ajena = db.crear_usuario_vinculado_a_kratos("ajena2-au@ejemplo.com", "k-ajena2"); db.asignar_tenant(ajena, db.crear_tenant("Otro despacho constructor"))
    r = cliente.post("/tareas/automatizaciones/regla", data={"nombre": "Con ajena", "disparador": "certificado.caduca", "c_dias_cert": "30", "a0_tipo": "crear_tarea", "a0_asunto": "Renovar {titular}",
                                                            "a0_dest": f"u:{ajena}"})
    assert r.status_code == 422 and "no es de tu despacho" in r.get_data(as_text=True) and au.listar_reglas(t) == []


# --- Disparadores por evento ------------------------------------------------------------------------------------------------------

def _regla_estado(d, estado="esperando", **extra):
    return au.crear_regla(d.t, d.sup, "Al cambiar", "tarea.estado", {"estado": estado, **extra},
                          [{"tipo": "notificar", "titulo": "{asunto}: de {anterior} a {estado}", "cuerpo": "Cliente {cliente}", "a": "direccion"}])


def _avisos_de_automatizacion(uid):
    return [n for n in _notificaciones(uid) if n["tipo"] == "automatizacion"]


def test_validacion_de_los_disparadores_de_evento(d):
    assert au.validar_condiciones("tarea.creada", {"prioridades": ["alta", "rara"], "cliente_fiscal_id": "3"}) == {"prioridades": ["alta"], "cliente_fiscal_id": 3}
    assert au.validar_condiciones("tarea.estado", {"estado": "esperando"}) == {"estado": "esperando"}
    with pytest.raises(ValueError, match="a qué estado"):
        au.validar_condiciones("tarea.estado", {})
    with pytest.raises(ValueError, match="a qué estado"):
        au.validar_condiciones("tarea.estado", {"estado": "inventado"})
    assert au.validar_acciones("tarea.estado", [{"tipo": "comentar", "texto": "{estado}"}])[0]["tipo"] == "comentar"
    with pytest.raises(ValueError, match="no existe para este disparador"):
        au.validar_acciones("tarea.creada", [{"tipo": "notificar", "titulo": "{estado}"}])         # «estado» solo existe al cambiar de estado
    with pytest.raises(ValueError, match="no existe para este disparador"):
        au.validar_acciones("tarea.estado", [{"tipo": "notificar", "titulo": "{titular}"}])


def test_el_cambio_de_estado_dispara_la_regla_una_vez_por_cada_cambio(d):
    _regla_estado(d)
    t = db.crear_tarea_outlook(d.cus, asunto="Declaración", cliente_fiscal_id=d.cliente)
    db.cambiar_estado_tarea_outlook(d.cus, t, "en_progreso")                       # otro estado: no interesa
    db.cambiar_estado_tarea_outlook(d.cus, t, "esperando")
    r = au.procesar_eventos(AHORA)
    assert (r["eventos"], r["ejecuciones"], r["ok"]) == (2, 1, 1)                  # se anotan los dos cambios (la regla escucha cambios de estado), pero solo uno cumple su condición
    avisos = _avisos_de_automatizacion(d.sup)
    assert [a["titulo"] for a in avisos] == ["Declaración: de En progreso a Esperando a otros"] and avisos[0]["cuerpo"] == "Cliente Marta Puig"
    assert au.procesar_eventos(AHORA)["eventos"] == 0                              # repetir no hace nada
    db.cambiar_estado_tarea_outlook(d.cus, t, "en_progreso")
    db.cambiar_estado_tarea_outlook(d.cus, t, "esperando")                         # otro cambio, otro aviso
    au.procesar_eventos(AHORA)
    assert len(_avisos_de_automatizacion(d.sup)) == 2
    assert au.eventos_pendientes() == 0


def test_se_dispara_venga_el_cambio_de_donde_venga(d):
    _regla_estado(d, "completada")
    ana = d.cus
    t1 = db.crear_tarea_outlook(ana, asunto="Por completar")
    t2 = db.crear_tarea_outlook(ana, asunto="Por la edición")
    t3 = db.crear_tarea_outlook(ana, asunto="Por transición")
    db.completar_tarea_outlook(ana, t1)                                             # el camino de «completar»
    db.editar_tarea_outlook(ana, t2, estado="completada")                           # el de editar (API PUT)
    tt.transicionar(ana, t3, "completada")                                          # el de la API de transiciones
    au.procesar_eventos(AHORA)
    assert sorted(a["titulo"] for a in _avisos_de_automatizacion(d.sup)) == ["Por completar: de Sin empezar a Completada", "Por la edición: de Sin empezar a Completada",
                                                                              "Por transición: de Sin empezar a Completada"]


def test_pedir_cambios_en_una_revision_y_reabrir_el_padre_tambien_son_cambios_de_estado(d):
    _regla_estado(d, "en_progreso")
    t = db.crear_tarea_outlook(d.cus, asunto="Con revisión")
    tt.solicitar_revision(d.cus, t, d.otro)
    tt.resolver_revision(d.otro, t, "cambios", "Falta algo")
    padre = db.crear_tarea_outlook(d.cus, asunto="Padre")
    hija = tt.crear_subtarea(d.cus, padre, "Hija")
    db.cambiar_estado_tarea_outlook(d.cus, hija, "completada")
    db.cambiar_estado_tarea_outlook(d.cus, padre, "completada")
    au.procesar_eventos(AHORA)
    n0 = len(_avisos_de_automatizacion(d.sup))
    db.cambiar_estado_tarea_outlook(d.cus, hija, "no_iniciada")                    # reabrir la hija devuelve el padre a «en progreso»
    au.procesar_eventos(AHORA)
    titulos = [a["titulo"] for a in _avisos_de_automatizacion(d.sup)]
    assert n0 == 1 and "Con revisión: de En revisión a En progreso" in titulos and "Padre: de Completada a En progreso" in titulos


def test_la_creacion_de_tareas_dispara_con_filtros_y_nunca_las_creadas_por_una_automatizacion(d):
    au.crear_regla(d.t, d.sup, "Urgentes", "tarea.creada", {"prioridades": ["alta"], "cliente_fiscal_id": d.cliente}, [{"tipo": "notificar", "titulo": "Nueva: {asunto} ({prioridad})", "a": "direccion"}])
    db.crear_tarea_outlook(d.cus, asunto="Urgente del cliente", prioridad="alta", cliente_fiscal_id=d.cliente)
    db.crear_tarea_outlook(d.cus, asunto="Normal del cliente", prioridad="normal", cliente_fiscal_id=d.cliente)
    db.crear_tarea_outlook(d.cus, asunto="Urgente sin cliente", prioridad="alta")
    r = au.procesar_eventos(AHORA)
    assert r["eventos"] == 3 and r["ejecuciones"] == 1
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Nueva: Urgente del cliente (alta)"]


def test_una_regla_de_evento_no_se_dispara_a_si_misma_ni_en_cadena(d):
    # Esta regla crea una tarea urgente cada vez que se crea una tarea urgente: sin protección sería un bucle infinito.
    au.crear_regla(d.t, d.sup, "Bucle", "tarea.creada", {"prioridades": ["alta"]}, [{"tipo": "crear_tarea", "asunto": "Seguimiento de {asunto}", "prioridad": "alta", "dias_plazo": 1, "asignar_a": d.cus}])
    au.crear_regla(d.t, d.sup, "Cadena", "tarea.creada", {}, [{"tipo": "notificar", "titulo": "Creada {asunto}", "a": "direccion"}])
    db.crear_tarea_outlook(d.cus, asunto="Original", prioridad="alta")
    for _ in range(5):
        au.procesar_eventos(AHORA)
    asuntos = sorted(t["asunto"] for t in _tareas(d.cus))
    assert asuntos == ["Original", "Seguimiento de Original"]                       # una sola tarea nueva, nada de bucle
    assert [a["titulo"] for a in _avisos_de_automatizacion(d.sup)] == ["Creada Original"]       # y la segunda regla no se activa por la tarea que creó la primera
    assert au.eventos_pendientes() == 0


def test_solo_se_encolan_eventos_si_hay_una_regla_activa_que_los_escuche(d):
    db.crear_tarea_outlook(d.cus, asunto="Sin reglas")
    assert au.eventos_pendientes() == 0
    rid = _regla_estado(d)
    db.crear_tarea_outlook(d.cus, asunto="Con regla de estado")                   # crear no interesa a una regla de estado
    assert au.eventos_pendientes() == 0
    t = db.crear_tarea_outlook(d.cus, asunto="Cambiará")
    db.cambiar_estado_tarea_outlook(d.cus, t, "esperando")
    assert au.eventos_pendientes() == 1
    au.cambiar_regla(d.t, d.sup, rid, activa=False)
    db.cambiar_estado_tarea_outlook(d.cus, t, "en_progreso")
    assert au.eventos_pendientes() == 1                                           # apagada: ya no se anota nada nuevo


def test_las_reglas_y_eventos_de_un_despacho_no_tocan_a_otro(d):
    otro = db.crear_tenant("Despacho vecino eventos")
    v = db.crear_usuario_vinculado_a_kratos("sup-vecino-ev@ejemplo.com", "k-sve"); db.asignar_tenant(v, otro); db.asignar_supervisor_tenant(v, True)
    a = db.crear_usuario_vinculado_a_kratos("ana-vecino-ev@ejemplo.com", "k-ave"); db.asignar_tenant(a, otro)
    au.crear_regla(otro, v, "Vecino", "tarea.estado", {"estado": "esperando"}, [{"tipo": "notificar", "titulo": "Vecino: {asunto}", "a": "direccion"}])
    _regla_estado(d)
    t_nuestra = db.crear_tarea_outlook(d.cus, asunto="Nuestra")
    t_vecina = db.crear_tarea_outlook(a, asunto="Del vecino")
    db.cambiar_estado_tarea_outlook(d.cus, t_nuestra, "esperando")
    db.cambiar_estado_tarea_outlook(a, t_vecina, "esperando")
    au.procesar_eventos(AHORA)
    assert [x["titulo"] for x in _avisos_de_automatizacion(d.sup)] == ["Nuestra: de Sin empezar a Esperando a otros"]
    assert [x["titulo"] for x in _avisos_de_automatizacion(v)] == ["Vecino: Del vecino"]


def test_un_fallo_en_una_regla_de_evento_se_reintenta_con_su_contexto_y_no_duplica(d, monkeypatch):
    au.crear_regla(d.t, d.sup, "Dos pasos", "tarea.estado", {"estado": "esperando"},
                   [{"tipo": "crear_tarea", "asunto": "Reclamar {asunto}", "dias_plazo": 1, "asignar_a": d.cus}, {"tipo": "notificar", "titulo": "Reclamar {asunto}", "a": "direccion"}])
    original = au._aplicar_accion

    def inestable(tenant_id, regla, oc, accion, clave, hoy):
        if accion["tipo"] == "notificar" and not getattr(inestable, "ya", False):
            inestable.ya = True
            raise RuntimeError("push caído")
        return original(tenant_id, regla, oc, accion, clave, hoy)
    monkeypatch.setattr(au, "_aplicar_accion", inestable)
    t = db.crear_tarea_outlook(d.cus, asunto="Pago")
    db.cambiar_estado_tarea_outlook(d.cus, t, "esperando")
    r = au.procesar_eventos(AHORA)
    assert (r["ejecuciones"], r["errores"]) == (1, 1) and len([x for x in _tareas(d.cus) if x["asunto"] == "Reclamar Pago"]) == 1
    e = au.ejecuciones(d.t)[0]
    assert e["estado"] == "error" and len(e["progreso"]) == 1
    au.ejecutar(d.t, AHORA + timedelta(minutes=20))                                # el reintento usa el contexto guardado (no hay nada que buscar)
    assert au.ejecuciones(d.t)[0]["estado"] == "ok"
    assert len([x for x in _tareas(d.cus) if x["asunto"] == "Reclamar Pago"]) == 1 and len(_avisos_de_automatizacion(d.sup)) == 1


def test_comentar_deja_la_nota_en_la_tarea_del_evento(d):
    au.crear_regla(d.t, d.sup, "Nota", "tarea.estado", {"estado": "aplazada"}, [{"tipo": "comentar", "texto": "Aplazada: avisar al cliente"}])
    t = db.crear_tarea_outlook(d.cus, asunto="Aplazable")
    db.cambiar_estado_tarea_outlook(d.cus, t, "aplazada")
    au.procesar_eventos(AHORA)
    assert any(a["tipo"] == "automatizacion" and "avisar al cliente" in a["detalle"] for a in db.actividad_de_tarea(d.cus, t))


def test_una_tarea_borrada_antes_de_procesar_se_ignora_sin_romper(d):
    _regla_estado(d)
    t = db.crear_tarea_outlook(d.cus, asunto="Efímera")
    db.cambiar_estado_tarea_outlook(d.cus, t, "esperando")
    db.eliminar_tarea_outlook(d.cus, t)
    r = au.procesar_eventos(AHORA)
    assert r["eventos"] == 1 and r["ejecuciones"] == 0 and au.eventos_pendientes() == 0


def test_la_vista_previa_de_una_regla_de_evento_enseña_los_casos_recientes_sin_escribir(d):
    rid = _regla_estado(d)
    t = db.crear_tarea_outlook(d.cus, asunto="En espera ahora")
    db.cambiar_estado_tarea_outlook(d.cus, t, "esperando")
    db.crear_tarea_outlook(d.cus, asunto="Otra cosa")
    au.procesar_eventos(AHORA)
    antes = len(au.ejecuciones(d.t))
    s = au.simular(d.t, rid)
    assert s["reciente"] is True and s["cumplen"] == 1 and s["ejemplos"][0]["datos"]["asunto"] == "En espera ahora" and len(au.ejecuciones(d.t)) == antes
    # y el análisis diario no se inventa casos para las reglas de evento
    assert au.ejecutar(d.t, AHORA)["nuevas"] == 0


def test_las_plantillas_nuevas_y_el_borrado_del_despacho(d):
    for clave in ("tarea_bloqueada", "tarea_urgente"):
        p = au.PLANTILLAS[clave]
        au.crear_regla(d.t, d.sup, p["nombre"], p["disparador"], p["condiciones"], p["acciones"])
    t = db.crear_tarea_outlook(d.cus, asunto="Nueva", prioridad="alta")
    db.cambiar_estado_tarea_outlook(d.cus, t, "esperando")
    assert au.eventos_pendientes() == 2
    db.borrar_tenant(d.t)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM automatizaciones_eventos WHERE tenant_id = ?", (d.t,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_constructor_y_lista_con_disparadores_de_evento(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "ev1-au@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho eventos pantalla")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    html = cliente.get("/tareas/automatizaciones/regla").get_data(as_text=True)
    assert 'value="tarea.creada"' in html and 'value="tarea.estado"' in html and 'name="c_estado_e"' in html and "{estado}" in html
    datos = {"nombre": "Al esperar", "disparador": "tarea.estado", "c_estado_e": "esperando", "c_prioridades_e": ["alta"], "activa": "1",
             "a0_tipo": "notificar", "a0_titulo": "En espera: {asunto}", "a0_dest_aviso": "direccion", "a1_tipo": "comentar", "a1_texto": "Pasó a {estado}"}
    assert cliente.post("/tareas/automatizaciones/regla", data=datos).status_code == 302
    r = au.listar_reglas(t)[0]
    assert r["condiciones"] == {"estado": "esperando", "prioridades": ["alta"]} and [a["tipo"] for a in r["acciones"]] == ["notificar", "comentar"]
    lista = cliente.get("/tareas/automatizaciones").get_data(as_text=True)
    assert "Una tarea cambia de estado" in lista and 'name="dias"' not in lista                     # una regla de evento no tiene «días»
    assert cliente.post(f"/tareas/automatizaciones/{r['id']}/cambiar", data={"dias": "9"}).status_code == 302
    assert au.obtener_regla(t, r["id"])["condiciones"] == {"estado": "esperando", "prioridades": ["alta"]}   # y mandar días no estropea nada
    assert "reacciona cuando ocurre" in cliente.post(f"/tareas/automatizaciones/{r['id']}/simular").get_data(as_text=True)
    sin_estado = {**datos, "nombre": "Mala", "c_estado_e": "inventado"}
    resp = cliente.post("/tareas/automatizaciones/regla", data=sin_estado)
    assert resp.status_code == 422 and "a qué estado" in resp.get_data(as_text=True) and len(au.listar_reglas(t)) == 1
    creada = {"nombre": "Nueva", "disparador": "tarea.creada", "c_prioridades_c": ["alta"], "a0_tipo": "notificar", "a0_titulo": "Nueva {asunto}"}
    assert cliente.post("/tareas/automatizaciones/regla", data=creada).status_code == 302


# --- Acciones sobre la tarea: fijar fecha, asignar, pedir revisión -----------------------------------------------------------------

def test_validacion_de_las_acciones_sobre_la_tarea(d):
    ok = au.validar_acciones("tarea.creada", [{"tipo": "fijar_fecha", "dias_plazo": "5"}, {"tipo": "asignar", "a": str(d.otro)}, {"tipo": "pedir_revision", "revisor": d.otro, "nota": "Mira {asunto}"}])
    assert ok[0] == {"tipo": "fijar_fecha", "dias_plazo": 5, "solo_si_vacia": True} and ok[1] == {"tipo": "asignar", "a": d.otro} and ok[2]["revisor"] == d.otro
    for disparador in ("certificado.caduca", "vencimiento.proximo"):
        for accion in ({"tipo": "fijar_fecha"}, {"tipo": "asignar", "a": 1}, {"tipo": "pedir_revision", "revisor": 1}):
            with pytest.raises(ValueError, match="actúa sobre la tarea"):
                au.validar_acciones(disparador, [accion])
    for malo in ({"tipo": "asignar"}, {"tipo": "asignar", "a": "responsable"}, {"tipo": "pedir_revision", "revisor": "direccion"}, {"tipo": "pedir_revision", "revisor": 0}):
        with pytest.raises(ValueError, match="elige una persona"):
            au.validar_acciones("tarea.creada", [malo])
    with pytest.raises(ValueError, match="no existe para este disparador"):
        au.validar_acciones("tarea.creada", [{"tipo": "pedir_revision", "revisor": 1, "nota": "{titular}"}])
    ajena = db.crear_usuario_vinculado_a_kratos("ajena-acc@ejemplo.com", "k-ajena-acc"); db.asignar_tenant(ajena, db.crear_tenant("Otro despacho acciones"))
    for accion in ({"tipo": "asignar", "a": ajena}, {"tipo": "pedir_revision", "revisor": ajena}):
        with pytest.raises(ValueError, match="no es de tu despacho"):
            au.crear_regla(d.t, d.sup, "x", "tarea.creada", {}, [accion])


def test_fijar_fecha_solo_si_esta_vacia_y_sin_repetirse(d):
    au.crear_regla(d.t, d.sup, "Fecha", "tarea.creada", {}, [{"tipo": "fijar_fecha", "dias_plazo": 3}])
    sin = db.crear_tarea_outlook(d.cus, asunto="Sin fecha")
    con = db.crear_tarea_outlook(d.cus, asunto="Con fecha", fecha_vencimiento="2030-01-01")
    au.procesar_eventos(AHORA)
    assert db.obtener_tarea_outlook(d.cus, sin)["fecha_vencimiento"][:10] == (HOY + timedelta(days=3)).isoformat()
    assert db.obtener_tarea_outlook(d.cus, con)["fecha_vencimiento"][:10] == "2030-01-01"                 # no pisa la que ya tenía
    assert any(a["tipo"] == "automatizacion" and "fecha límite en 3 días" in a["detalle"] for a in db.actividad_de_tarea(d.cus, sin))
    assert au.procesar_eventos(AHORA)["eventos"] == 0
    # con «solo si está vacía» desmarcado sí la sustituye
    au.crear_regla(d.t, d.sup, "Fecha forzada", "tarea.creada", {}, [{"tipo": "fijar_fecha", "dias_plazo": 1, "solo_si_vacia": False}])
    otra = db.crear_tarea_outlook(d.cus, asunto="Otra", fecha_vencimiento="2030-01-01")
    au.procesar_eventos(AHORA)
    assert db.obtener_tarea_outlook(d.cus, otra)["fecha_vencimiento"][:10] == (HOY + timedelta(days=1)).isoformat()


def test_asignar_una_tarea_nueva_a_una_persona_del_despacho(d):
    au.crear_regla(d.t, d.sup, "Reparto", "tarea.creada", {"prioridades": ["alta"]}, [{"tipo": "asignar", "a": d.otro}])
    urgente = db.crear_tarea_outlook(d.cus, asunto="Urgente", prioridad="alta")
    normal = db.crear_tarea_outlook(d.cus, asunto="Normal")
    au.procesar_eventos(AHORA)
    assert db.obtener_tarea_outlook(d.cus, urgente)["asignada_a"] == d.otro and db.obtener_tarea_outlook(d.cus, normal)["asignada_a"] is None
    assert [t["asunto"] for t in _tareas(d.otro)] == ["Urgente"]                                      # y ahora la ve quien la lleva
    assert au.ejecuciones(d.t)[0]["progreso"] == ["asignada"]


def test_pedir_revision_automatica_y_sus_casos_limite(d):
    with pytest.raises(ValueError, match="ya completada"):                                # una combinación imposible se rechaza al guardar, no se ve fallar cada vez
        au.crear_regla(d.t, d.sup, "Imposible", "tarea.estado", {"estado": "completada"}, [{"tipo": "pedir_revision", "revisor": d.otro}])
    au.crear_regla(d.t, d.sup, "Revisión", "tarea.estado", {"estado": "en_progreso"}, [{"tipo": "pedir_revision", "revisor": d.otro, "nota": "Revisa {asunto}"}])
    t = db.crear_tarea_outlook(d.cus, asunto="Modelo 303")
    db.cambiar_estado_tarea_outlook(d.cus, t, "en_progreso")
    r = au.procesar_eventos(AHORA)
    assert r["ok"] == 1 and tt.revision_pendiente(t)["revisor_id"] == d.otro, (r, [e["error"] for e in au.ejecuciones(d.t)])
    assert [n for n in _notificaciones(d.otro) if n["tipo"] == "revision_tarea"][0]["cuerpo"] == "Revisa Modelo 303"
    # el revisor es el propio dueño: la acción falla y se ve, sin tumbar nada
    au.crear_regla(d.t, d.sup, "Autorevisión", "tarea.creada", {}, [{"tipo": "pedir_revision", "revisor": d.cus}])
    db.crear_tarea_outlook(d.cus, asunto="Propia")
    r = au.procesar_eventos(AHORA)
    assert r["errores"] == 1
    e = [x for x in au.ejecuciones(d.t) if x["regla"] == "Autorevisión"][0]
    assert e["estado"] == "error" and "otra persona" in e["error"]
    rid = au.crear_regla(d.t, d.sup, "Cambiable", "tarea.estado", {"estado": "esperando"}, [{"tipo": "notificar", "titulo": "x", "a": "direccion"}])
    with pytest.raises(ValueError, match="ya completada"):                                # y lo mismo al editarla
        au.cambiar_regla(d.t, d.sup, rid, condiciones={"estado": "completada"}, acciones=[{"tipo": "pedir_revision", "revisor": d.otro}])


def test_una_revision_ya_pendiente_no_hace_fallar_a_la_regla(d):
    # La tarea ya está «en revisión», así que no puede cambiar de estado: el caso se da con un disparador diario (aquí, una tarea vencida).
    au.crear_regla(d.t, d.sup, "Revisión", "tarea.vencida", {"dias_vencida": 1}, [{"tipo": "pedir_revision", "revisor": d.otro}])
    t = db.crear_tarea_outlook(d.cus, asunto="Con revisión previa", fecha_vencimiento=(HOY - timedelta(days=3)).isoformat())
    tt.solicitar_revision(d.cus, t, d.sup)
    r = au.ejecutar(d.t, AHORA)
    assert (r["ok"], r["errores"]) == (1, 0) and tt.revision_pendiente(t)["revisor_id"] == d.sup and au.ejecuciones(d.t)[0]["progreso"] == ["ya había una revisión pendiente"]


def test_las_acciones_sobre_la_tarea_valen_tambien_con_tareas_vencidas(d):
    au.crear_regla(d.t, d.sup, "Vencidas", "tarea.vencida", {"dias_vencida": 2}, [{"tipo": "asignar", "a": d.otro}, {"tipo": "fijar_fecha", "dias_plazo": 2, "solo_si_vacia": False}])
    t = db.crear_tarea_outlook(d.cus, asunto="Atrasada", fecha_vencimiento=(HOY - timedelta(days=5)).isoformat())
    assert au.ejecutar(d.t, AHORA)["ok"] == 1
    f = db.obtener_tarea_outlook(d.cus, t)
    assert f["asignada_a"] == d.otro and f["fecha_vencimiento"][:10] == (HOY + timedelta(days=2)).isoformat()
    assert au.ejecutar(d.t, AHORA)["nuevas"] == 0                                     # la clave incluye la fecha antigua; con la nueva ya no está vencida


def test_el_constructor_guarda_las_acciones_nuevas(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    uid = iniciar_sesion_de_prueba(cliente, "acc1-au@ejemplo.com", "contrasena123")
    t = db.crear_tenant("Despacho acciones pantalla")
    db.asignar_tenant(uid, t); db.asignar_supervisor_tenant(uid, True)
    otra = db.crear_usuario_vinculado_a_kratos("acc1b-au@ejemplo.com", "k-acc1b"); db.asignar_tenant(otra, t)
    html = cliente.get("/tareas/automatizaciones/regla").get_data(as_text=True)
    assert 'value="fijar_fecha"' in html and 'value="asignar"' in html and 'value="pedir_revision"' in html and 'name="a0_revisor"' in html
    datos = {"nombre": "Alta de tarea", "disparador": "tarea.creada", "activa": "1",
             "a0_tipo": "fijar_fecha", "a0_dias_fecha": "4", "a0_solo_vacia": "1",
             "a1_tipo": "asignar", "a1_persona": str(otra),
             "a2_tipo": "pedir_revision", "a2_revisor": str(otra), "a2_nota_rev": "Mira {asunto}"}
    assert cliente.post("/tareas/automatizaciones/regla", data=datos).status_code == 302
    r = au.listar_reglas(t)[0]
    assert r["acciones"][0] == {"tipo": "fijar_fecha", "dias_plazo": 4, "solo_si_vacia": True} and r["acciones"][1]["a"] == otra and r["acciones"][2]["nota"] == "Mira {asunto}"
    lista = cliente.get("/tareas/automatizaciones").get_data(as_text=True)
    assert "Fija la fecha límite a 4 días vista" in lista and "Asigna la tarea a una persona" in lista and "Pide que otra persona revise la tarea" in lista
    html = cliente.get(f"/tareas/automatizaciones/regla/{r['id']}").get_data(as_text=True)
    assert f'<option value="{otra}" selected>' in html
    mala = {**datos, "nombre": "Mala", "disparador": "certificado.caduca", "c_dias_cert": "10"}
    resp = cliente.post("/tareas/automatizaciones/regla", data=mala)
    assert resp.status_code == 422 and "actúa sobre la tarea" in resp.get_data(as_text=True) and len(au.listar_reglas(t)) == 1
