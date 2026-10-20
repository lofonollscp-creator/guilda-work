"""Reglas de automatización (app/automatizaciones.py): idempotencia, reintentos, sin bucles, permisos y aislamiento entre despachos."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import automatizaciones as au, certificados as ce, db

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
    assert au.ejecutar(d.t, AHORA + timedelta(days=2))["ok"] == 1
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
    assert len(au.listar_reglas(d.t)) == 3
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
    au.ejecutar(t, AHORA + timedelta(days=2))
    assert au.ejecuciones(t)[0]["estado"] == "ok" and "ha fallado del todo" not in cliente.get("/tareas/automatizaciones").get_data(as_text=True)
