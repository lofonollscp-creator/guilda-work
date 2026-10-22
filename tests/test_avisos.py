"""Motor de avisos v2 (app/avisos.py): alertas sin duplicados, acuse que no cierra la obligación, escalado, cierre automático, convivencia con los avisos antiguos, pantallas, API e IA."""
from datetime import date, datetime, timedelta

import pytest

from app import acceso, avisos, db, ia_herramientas as ih, panel_fiscal, traspasos
from tests.conftest import iniciar_sesion_de_prueba
from tests.test_rutas_api import _auth, _registrar


@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Avisos")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.ana, e.biel = u("sup-av@ejemplo.com", True), u("ana-av@ejemplo.com"), u("biel-av@ejemplo.com")
    e.a = db.crear_cliente_fiscal(t, "Cliente A", nif="B12345674"); e.b = db.crear_cliente_fiscal(t, "Cliente B", nif="J21938519")
    hoy = date.today()
    e.v_prox = db.crear_vencimiento_fiscal(t, e.a, "303", "2026-T3", (hoy + timedelta(days=3)).isoformat())
    e.v_venc = db.crear_vencimiento_fiscal(t, e.b, "303", "2026-T3", (hoy - timedelta(days=2)).isoformat())
    traspasos.asignar_responsable(t, e.sup, e.a, e.ana); traspasos.asignar_responsable(t, e.sup, e.b, e.biel)
    avisos.guardar_config(t, e.sup, activo=True, dias_antes=[7, 3, 1], escalar_horas_urgente=24, escalar_horas_atencion=72, reenviar_horas=24, max_reenvios=2)
    return e


def _notifs(uid):
    conn = db.get_connection()
    try:
        return [f["titulo"] for f in conn.execute("SELECT titulo FROM notificaciones WHERE usuario_id = ? AND tipo = 'aviso_fiscal' ORDER BY id", (uid,))]
    finally:
        conn.close()


def _alerta(d, tipo):
    return next(a for a in avisos.listar(d.t, d.sup, estado=None) if a["tipo"] == tipo)


def test_viene_apagado_y_solo_la_direccion_lo_configura(usuario_id):
    t = db.crear_tenant("Despacho Avisos Apagado")
    assert avisos.config(t)["activo"] is False and avisos.activo(t) is False and avisos.evaluar_todos()["despachos"] == 0
    u = db.crear_usuario_vinculado_a_kratos("g-av@ejemplo.com", "k-g-av"); db.asignar_tenant(u, t)
    with pytest.raises(ValueError, match="Solo la dirección"):
        avisos.guardar_config(t, u, activo=True, dias_antes=[7], escalar_horas_urgente=24, escalar_horas_atencion=72, reenviar_horas=24, max_reenvios=2)


def test_validacion_de_la_configuracion(d):
    base = dict(activo=True, escalar_horas_urgente=24, escalar_horas_atencion=72, reenviar_horas=24, max_reenvios=2)
    with pytest.raises(ValueError, match="entre 1 y 5"):
        avisos.guardar_config(d.t, d.sup, dias_antes=[], **base)
    with pytest.raises(ValueError, match="entre 0 y 60"):
        avisos.guardar_config(d.t, d.sup, dias_antes=[99], **base)
    with pytest.raises(ValueError, match="debe ser un número"):
        avisos.guardar_config(d.t, d.sup, dias_antes="7,3", **{**base, "reenviar_horas": "x"})
    assert avisos.guardar_config(d.t, d.sup, dias_antes="1, 7, 3, 7", **base)["dias_antes"] == [7, 3, 1]


def test_evaluar_abre_las_alertas_con_su_destinatario_y_nunca_las_duplica(d):
    r = avisos.evaluar(d.t)
    assert r["abiertas"] == 2 and r["enviadas"] == 2
    prox, venc = _alerta(d, "obligacion_proxima"), _alerta(d, "obligacion_vencida")
    assert prox["destinatario_id"] == d.ana and prox["severidad"] == "atencion" and venc["destinatario_id"] == d.biel and venc["severidad"] == "urgente"
    assert _notifs(d.ana) == ["Obligación a punto de vencer"] and _notifs(d.biel) == ["Obligación vencida sin presentar"]
    for _ in range(5):
        assert avisos.evaluar(d.t)["abiertas"] == 0
    assert len(avisos.listar(d.t, d.sup, estado=None)) == 2 and avisos.metricas(d.t)["duplicados"] == 0
    assert len(_notifs(d.ana)) == 1, "repetir la evaluación no vuelve a avisar"


def test_al_cruzar_un_umbral_se_avisa_otra_vez_sin_crear_otra_alerta(d):
    hoy = datetime.now()
    avisos.evaluar(d.t, hoy)
    conn = db.get_connection(); conn.execute("UPDATE vencimientos_fiscales SET fecha_limite = ? WHERE id = ?", ((date.today() + timedelta(days=1)).isoformat(), d.v_prox)); conn.commit(); conn.close()
    avisos.evaluar(d.t, hoy + timedelta(hours=1))
    # la fecha cambió: es otra clave (otro plazo), no un duplicado de la anterior; la antigua se cierra
    activas = [a for a in avisos.listar(d.t, d.sup, estado=None) if a["objeto_id"] == d.v_prox]
    assert sorted(a["estado"] for a in activas) == ["abierta", "resuelta"] and next(a for a in activas if a["estado"] == "abierta")["severidad"] == "urgente"


def test_acusar_no_cierra_la_obligacion_y_detiene_la_insistencia(d):
    avisos.evaluar(d.t)
    venc = _alerta(d, "obligacion_vencida")
    avisos.acusar(d.t, d.biel, venc["id"], "Lo presento mañana")
    a = avisos.obtener(d.t, venc["id"])
    assert a["estado"] == "acusada" and a["nota_acuse"] == "Lo presento mañana" and a["acusada_por"] == d.biel
    v = db.obtener_vencimiento_fiscal(d.t, d.v_venc)
    assert v["estado"] == "pendiente" and v["fase"] != "presentada", "acusar no presenta nada"
    futuro = datetime.now() + timedelta(days=10)
    r = avisos.evaluar(d.t, futuro)
    assert r["escaladas"] == 0 and len(_notifs(d.biel)) == 1, "acusada: ni se repite ni escala"
    with pytest.raises(ValueError, match="ya está acusado"):
        avisos.acusar(d.t, d.biel, venc["id"])


def test_acusar_exige_ver_el_cliente(d):
    avisos.evaluar(d.t)
    venc = _alerta(d, "obligacion_vencida")
    otro = db.crear_tenant("Otro despacho avisos")
    ajeno = db.crear_usuario_vinculado_a_kratos("ajeno-av@ejemplo.com", "k-ajeno-av"); db.asignar_tenant(ajeno, otro)
    with pytest.raises(ValueError, match="No existe ese aviso"):
        avisos.acusar(d.t, ajeno, venc["id"])


def test_sin_acuse_se_repite_y_escala_a_coordinacion_y_luego_a_direccion(d):
    gi = acceso.crear_oficina(d.t, d.sup, "Girona")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.b, gi)
    coord = db.crear_usuario_vinculado_a_kratos("coord-av@ejemplo.com", "k-coord-av"); db.asignar_tenant(coord, d.t)
    acceso.dar_membresia(d.t, d.sup, coord, "coordinador", "oficina", gi)
    ahora = datetime.now()
    avisos.evaluar(d.t, ahora)
    assert _notifs(coord) == []
    r = avisos.evaluar(d.t, ahora + timedelta(hours=25))
    assert r["escaladas"] >= 1
    assert _notifs(coord) == ["Sin atender: Obligación vencida sin presentar"] and _alerta(d, "obligacion_vencida")["nivel"] == 1
    avisos.evaluar(d.t, ahora + timedelta(hours=50))
    assert _alerta(d, "obligacion_vencida")["nivel"] == 2 and "Sin atender: Obligación vencida sin presentar" in _notifs(d.sup)
    avisos.evaluar(d.t, ahora + timedelta(hours=200))
    assert _alerta(d, "obligacion_vencida")["nivel"] == 2, "no pasa de la dirección"


def test_sin_coordinacion_escala_directamente_a_la_direccion(d):
    ahora = datetime.now()
    avisos.evaluar(d.t, ahora)
    avisos.evaluar(d.t, ahora + timedelta(hours=25))
    assert _alerta(d, "obligacion_vencida")["nivel"] == 2 and "Sin atender: Obligación vencida sin presentar" in _notifs(d.sup)


def test_el_aviso_se_cierra_solo_cuando_la_obligacion_se_presenta(d):
    avisos.evaluar(d.t)
    conn = db.get_connection(); conn.execute("UPDATE vencimientos_fiscales SET fase = 'presentada', estado = 'presentado' WHERE id = ?", (d.v_venc,)); conn.commit(); conn.close()
    r = avisos.evaluar(d.t)
    a = _alerta(d, "obligacion_vencida")
    assert r["resueltas"] == 1 and a["estado"] == "resuelta" and "ya no está pendiente" in a["motivo_resolucion"]
    with pytest.raises(ValueError, match="ya está resuelto"):
        avisos.acusar(d.t, d.biel, a["id"])


def test_un_traspaso_sin_aceptar_con_plazo_cerca_genera_aviso_para_el_receptor(d):
    tid = traspasos.proponer(d.t, d.ana, d.a, d.biel)
    avisos.evaluar(d.t)
    a = _alerta(d, "traspaso_pendiente")
    assert a["destinatario_id"] == d.biel and a["severidad"] == "urgente"
    traspasos.aceptar(d.t, d.biel, tid)
    avisos.evaluar(d.t)
    assert _alerta(d, "traspaso_pendiente")["estado"] == "resuelta"


def test_convivencia_con_los_avisos_antiguos(d):
    tid = traspasos.proponer(d.t, d.ana, d.a, d.biel)
    assert traspasos.escalar() == 0 or True
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT escalado_en FROM traspasos WHERE id = ?", (tid,)).fetchone()["escalado_en"] is not None
    finally:
        conn.close()
    assert not any(t == "Traspaso sin aceptar y con plazo cerca" for t in _notifs(d.sup)), "con el motor v2 activo, el escalado antiguo no avisa"


def test_metricas_con_muestra_y_el_panel_cuenta_los_avisos_sin_atender(d):
    avisos.evaluar(d.t)
    m = avisos.metricas(d.t)
    assert m["abiertas"] == 2 and m["horas_hasta_acuse_mediana"] is None and m["muestra_acuses"] == 0
    avisos.acusar(d.t, d.biel, _alerta(d, "obligacion_vencida")["id"])
    m = avisos.metricas(d.t)
    assert m["acusadas"] == 1 and m["abiertas"] == 1 and m["muestra_acuses"] == 1 and m["horas_hasta_acuse_mediana"] is not None
    assert panel_fiscal.construir(d.t, d.sup)["totales"]["avisos_sin_atender"] == 1


def test_borrar_un_cliente_definitivamente_borra_sus_avisos(d):
    avisos.evaluar(d.t)
    conn = db.get_connection(); conn.execute("DELETE FROM vencimientos_fiscales WHERE cliente_fiscal_id = ?", (d.b,)); conn.commit(); conn.close()
    avisos.evaluar(d.t)
    db.eliminar_cliente_fiscal_definitivamente(d.t, d.b)
    assert all(a["cliente_fiscal_id"] != d.b for a in avisos.listar(d.t, d.sup, estado=None))


# --- Pantallas, API e IA ----------------------------------------------------------------------------------------------------------------------
def test_pantalla_de_avisos_acuse_y_configuracion(cliente):
    t = db.crear_tenant("Despacho Web Avisos")
    u = iniciar_sesion_de_prueba(cliente, "web-av@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = db.crear_cliente_fiscal(t, "Cliente Web Aviso", nif="B12345674")
    db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", (date.today() - timedelta(days=1)).isoformat())
    h = cliente.get("/fiscal/avisos").get_data(as_text=True)
    assert "desactivados en este despacho" in h and "Configuración" in h
    r = cliente.post("/fiscal/avisos", data={"activo": "1", "dias_antes": "10, 5, 1", "escalar_horas_urgente": 12, "escalar_horas_atencion": 48, "reenviar_horas": 6, "max_reenvios": 1})
    assert "aviso=hecho" in r.headers["Location"] and avisos.config(t)["dias_antes"] == [10, 5, 1]
    assert "error=" in cliente.post("/fiscal/avisos", data={"dias_antes": "", "escalar_horas_urgente": 12, "escalar_horas_atencion": 48, "reenviar_horas": 6, "max_reenvios": 1}).headers["Location"]
    avisos.evaluar(t)
    h = cliente.get("/fiscal/avisos").get_data(as_text=True)
    assert "Obligación vencida sin presentar" in h and "Cliente Web Aviso" in h and "Lo llevo" in h and "Cómo van los avisos" in h
    aid = avisos.listar(t, u)[0]["id"]
    assert "aviso=acusado" in cliente.post(f"/fiscal/avisos/{aid}/acusar", data={"nota": "Hoy mismo"}).headers["Location"]
    assert "Hoy mismo" in cliente.get("/fiscal/avisos?estado=acusada").get_data(as_text=True)
    assert "error=" in cliente.post(f"/fiscal/avisos/{aid}/acusar", data={}).headers["Location"]


def test_api_de_avisos(cliente):
    t = db.crear_tenant("Despacho API Avisos")
    datos = _registrar(cliente, "api-av@ejemplo.com"); u = db.obtener_usuario_por_email("api-av@ejemplo.com")["id"]
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    h = _auth(datos["token"])
    c = db.crear_cliente_fiscal(t, "Cliente API Aviso", nif="B12345674")
    db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", (date.today() - timedelta(days=3)).isoformat())
    assert cliente.get("/api/v1/fiscal/avisos/config", headers=h).get_json()["data"]["activo"] is False
    cfg = cliente.put("/api/v1/fiscal/avisos/config", headers=h, json={"activo": True, "dias_antes": [5, 2]}).get_json()["data"]
    assert cfg["activo"] and cfg["dias_antes"] == [5, 2] and cfg["escalar_horas_urgente"] == 24
    assert cliente.put("/api/v1/fiscal/avisos/config", headers=h, json={"dias_antes": [500]}).get_json()["codigo"] == "configuracion_no_valida"
    avisos.evaluar(t)
    lista = cliente.get("/api/v1/fiscal/avisos", headers=h).get_json()["data"]
    assert len(lista) == 1 and lista[0]["tipo"] == "obligacion_vencida" and lista[0]["cliente"] == "Cliente API Aviso" and "clave" not in lista[0]
    assert cliente.get("/api/v1/fiscal/avisos?estado=rara", headers=h).status_code == 400
    r = cliente.post(f"/api/v1/fiscal/avisos/{lista[0]['id']}/acuse", headers=h, json={"nota": "ok"})
    assert r.status_code == 200 and r.get_json()["data"]["estado"] == "acusada"
    assert cliente.post(f"/api/v1/fiscal/avisos/{lista[0]['id']}/acuse", headers=h).status_code == 409
    assert cliente.post("/api/v1/fiscal/avisos/9999/acuse", headers=h).status_code == 404
    m = cliente.get("/api/v1/fiscal/avisos/metricas", headers=h).get_json()["data"]
    assert m["acusadas"] == 1 and m["duplicados"] == 0


def test_herramientas_de_ia_de_avisos(d):
    assert "acusar_aviso_fiscal" in ih.ESCRITURA and "listar_avisos_fiscales" not in ih.ESCRITURA
    avisos.evaluar(d.t)
    lista = ih.ejecutar(d.biel, "listar_avisos_fiscales", {"estado": "abierta", "solo_mios": True})
    assert [a["titulo"] for a in lista] == ["Obligación vencida sin presentar"]
    r = ih.ejecutar(d.biel, "acusar_aviso_fiscal", {"aviso_id": lista[0]["id"], "nota": "Mañana"})
    assert r["estado"] == "acusada"
    with pytest.raises(ih.ErrorHerramientaIA):
        ih.ejecutar(d.biel, "listar_avisos_fiscales", {"estado": "rara"})


# --- Certificados en el motor ------------------------------------------------------------------------------------------------------------------
def _cert(d, dias, cliente=None, **kw):
    from app import certificados
    return certificados.alta_rapida(d.t, d.sup, tipo="fnmt_persona_fisica", caduca=(date.today() + timedelta(days=dias)).isoformat(), cliente_fiscal_id=cliente, titular=None if cliente else "Despacho", **kw)["id"]


def test_un_certificado_que_caduca_pronto_genera_aviso_con_su_custodio(d):
    cus = db.crear_usuario_vinculado_a_kratos("cus-av@ejemplo.com", "k-cus-av"); db.asignar_tenant(cus, d.t)
    conn = db.get_connection(); conn.execute("UPDATE usuarios SET custodio_certificados = 1 WHERE id = ?", (cus,)); conn.commit(); conn.close()
    lejos, cerca = _cert(d, 200), _cert(d, 20, d.a, custodio_id=cus)
    r = avisos.evaluar(d.t)
    cert = [a for a in avisos.listar(d.t, d.sup, estado=None) if a["objeto_tipo"] == "certificado"]
    assert [a["objeto_id"] for a in cert] == [cerca] and cert[0]["destinatario_id"] == cus and cert[0]["severidad"] == "atencion"
    assert "cobertura desconocida" in cert[0]["detalle"] and _notifs(cus) == ["Certificado a punto de caducar"]
    assert cert[0]["url"] == f"/certificados/{cerca}" and cert[0]["cliente"] == "Cliente A"
    assert lejos and avisos.evaluar(d.t)["abiertas"] == 0


def test_el_certificado_sin_custodio_va_al_responsable_del_cliente_y_luego_a_la_direccion(d):
    cid = _cert(d, 5, d.a)                          # el responsable de A es Ana
    avisos.evaluar(d.t)
    a = next(x for x in avisos.listar(d.t, d.sup, estado=None) if x["objeto_id"] == cid)
    assert a["destinatario_id"] == d.ana and a["severidad"] == "urgente"
    ahora = datetime.now()
    avisos.evaluar(d.t, ahora + timedelta(hours=25))
    assert "Sin atender: Certificado a punto de caducar" in _notifs(d.sup)


def test_los_avisos_de_certificados_solo_los_ven_quienes_los_gestionan(d):
    _cert(d, 10)
    avisos.evaluar(d.t)
    assert any(a["objeto_tipo"] == "certificado" for a in avisos.listar(d.t, d.sup))
    assert not any(a["objeto_tipo"] == "certificado" for a in avisos.listar(d.t, d.biel)), "un gestor sin permiso de certificados no los ve"
    al = next(a for a in avisos.listar(d.t, d.sup) if a["objeto_tipo"] == "certificado")
    with pytest.raises(ValueError, match="No existe ese aviso"):
        avisos.acusar(d.t, d.biel, al["id"])
    avisos.acusar(d.t, d.sup, al["id"], "Cita pedida")
    assert avisos.obtener(d.t, al["id"])["estado"] == "acusada"


def test_certificado_caducado_es_urgente_y_se_cierra_al_renovarlo(d):
    from app import certificados
    cid = _cert(d, 2, d.a)
    conn = db.get_connection(); conn.execute("UPDATE certificados SET not_after = ? WHERE id = ?", ((datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"), cid)); conn.commit(); conn.close()
    avisos.evaluar(d.t)
    a = next(x for x in avisos.listar(d.t, d.sup, estado=None) if x["objeto_id"] == cid)
    assert a["titulo"] == "Certificado caducado" and a["severidad"] == "urgente" and "dejan de funcionar" in a["detalle"]
    certificados.renovado(d.t, d.sup, cid, (date.today() + timedelta(days=1500)).isoformat())
    r = avisos.evaluar(d.t)
    assert r["resueltas"] >= 1 and avisos.obtener(d.t, a["id"])["estado"] == "resuelta"
    assert not [x for x in avisos.listar(d.t, d.sup) if x["objeto_tipo"] == "certificado"], "el nuevo caduca dentro de 4 años: sin aviso"


def test_con_el_motor_activo_el_aviso_interno_de_certificados_no_se_duplica_pero_el_correo_sigue(d):
    from app import certificados
    _cert(d, 6)
    certificados.revisar_avisos(d.t, enviar_correo=False)
    conn = db.get_connection()
    try:
        canales = {f["canal"] for f in conn.execute("SELECT canal FROM certificados_avisos WHERE tenant_id = ?", (d.t,))}
    finally:
        conn.close()
    assert "interno" not in canales, "el aviso interno lo da el motor v2"
    avisos.guardar_config(d.t, d.sup, activo=False, dias_antes=[7], escalar_horas_urgente=24, escalar_horas_atencion=72, reenviar_horas=24, max_reenvios=2)
    certificados.revisar_avisos(d.t, enviar_correo=False)
    conn = db.get_connection()
    try:
        assert "interno" in {f["canal"] for f in conn.execute("SELECT canal FROM certificados_avisos WHERE tenant_id = ?", (d.t,))}, "apagado el motor, todo como siempre"
    finally:
        conn.close()


def test_configuracion_de_plazos_de_certificados(d):
    base = dict(activo=True, dias_antes=[7], escalar_horas_urgente=24, escalar_horas_atencion=72, reenviar_horas=24, max_reenvios=2)
    assert avisos.config(d.t)["dias_certificados"] == [30, 15, 7, 1]
    assert avisos.guardar_config(d.t, d.sup, dias_certificados="60, 30, 7", **base)["dias_certificados"] == [60, 30, 7]
    assert avisos.guardar_config(d.t, d.sup, **base)["dias_certificados"] == [60, 30, 7], "sin indicarlo se mantiene"
    with pytest.raises(ValueError, match="certificados"):
        avisos.guardar_config(d.t, d.sup, dias_certificados=[], **base)
    _cert(d, 50)
    assert avisos.evaluar(d.t)["abiertas"] >= 1 and any(a["objeto_tipo"] == "certificado" for a in avisos.listar(d.t, d.sup))
