"""«Hoy»: la bandeja única de lo que necesita a la persona (app/bandeja_hoy.py, /hoy y el panel del inicio)."""
from datetime import date, datetime, timedelta

from app import abogados as ab
from app import bandeja_hoy, db, mensajes_enlace, nucleo, verticales
from app.db_fiscal import crear_cliente_fiscal, crear_vencimiento_fiscal
from tests.conftest import iniciar_sesion_de_prueba

HOY = date.today()


def _despacho(nombre="Despacho hoy", n=2):
    t = db.crear_tenant(nombre)
    us = []
    for i in range(n):
        u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}-{i}@ejemplo.com", f"kratos-{nombre}-{i}")
        db.asignar_tenant(u, t)
        us.append(u)
    verticales.fijar_activo(t, "abogados", True)
    return t, us


def _claves(b):
    return [s["clave"] for s in b["secciones"]]


def _web(cliente, email="hoyweb@ejemplo.com"):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    t = db.crear_tenant("Despacho " + email)
    db.asignar_tenant(uid, t)
    verticales.fijar_activo(t, "abogados", True)
    return uid, t


def test_sin_nada_pendiente_no_hay_secciones(usuario_id):
    t, (u1, _) = _despacho()
    b = bandeja_hoy.reunir(u1)
    assert b["secciones"] == [] and b["total"] == 0 and b["urgentes"] == 0 and b["destacados"] == []


def test_reune_tareas_plazos_vencimientos_y_los_ordena_por_urgencia(usuario_id, cliente):
    uid, t = _web(cliente)
    db.crear_tarea_outlook(uid, "Tarea vencida", fecha_vencimiento=(HOY - timedelta(days=2)).isoformat())
    db.crear_tarea_outlook(uid, "Tarea de hoy", fecha_vencimiento=HOY.isoformat())
    c = nucleo.crear_cliente(t, "Cliente Uno")
    x = nucleo.crear_expediente(t, uid, c, "Asunto uno", tipo="procedimiento_judicial")
    nucleo.crear_plazo(t, uid, "Plazo próximo", (HOY + timedelta(days=3)).isoformat(), expediente_id=x, responsable_id=uid)
    nucleo.crear_plazo(t, uid, "Plazo vencido", (HOY - timedelta(days=1)).isoformat(), expediente_id=x, responsable_id=uid)
    nucleo.crear_plazo(t, uid, "Plazo lejano", (HOY + timedelta(days=60)).isoformat(), expediente_id=x, responsable_id=uid)
    f = crear_cliente_fiscal(t, "Cliente fiscal", nif="12345678Z")
    crear_vencimiento_fiscal(t, f, "303", "2026-T3", (HOY + timedelta(days=2)).isoformat(), usuario_id=uid)
    crear_vencimiento_fiscal(t, f, "111", "2026-T3", (HOY + timedelta(days=2)).isoformat(), usuario_id=None)      # de nadie: no es mío
    with cliente.application.test_request_context():
        b = bandeja_hoy.reunir(uid, False, HOY)
    assert set(_claves(b)) == {"tareas", "plazos", "vencimientos"}
    tareas = next(s for s in b["secciones"] if s["clave"] == "tareas")["elementos"]
    assert [(i["titulo"], i["urgencia"]) for i in tareas] == [("Tarea vencida", "vencido"), ("Tarea de hoy", "hoy")]
    plazos = next(s for s in b["secciones"] if s["clave"] == "plazos")["elementos"]
    assert [(i["titulo"], i["urgencia"]) for i in plazos] == [("Plazo vencido", "vencido"), ("Plazo próximo", "proximo")], "el lejano no aparece"
    assert plazos[0]["url"] == f"/expedientes/{x}"
    venc = next(s for s in b["secciones"] if s["clave"] == "vencimientos")["elementos"]
    assert [i["titulo"] for i in venc] == ["303 · Cliente fiscal"]
    assert b["urgentes"] == 3 and b["total"] == 5
    assert [i["urgencia"] for i in b["destacados"]] == sorted((i["urgencia"] for i in b["destacados"]), key=lambda u: bandeja_hoy.ORDEN_URGENCIA[u])


def test_los_mensajes_de_clientes_sin_leer_aparecen_solo_para_quien_ve_el_expediente(usuario_id, cliente):
    uid, t = _web(cliente, "hoymsg@ejemplo.com")
    otro = db.crear_usuario_vinculado_a_kratos("otro-hoy@ejemplo.com", "kratos-otro-hoy"); db.asignar_tenant(otro, t)
    c = nucleo.crear_cliente(t, "Cliente Msg")
    x = nucleo.crear_expediente(t, uid, c, "Visible", tipo="procedimiento_judicial")
    reservado = nucleo.crear_expediente(t, uid, c, "Reservado", tipo="procedimiento_judicial", confidencial=True)
    for exp in (x, reservado):
        token = ab.crear_enlace(t, uid, exp, permite_mensajes=True)
        mensajes_enlace.enviar_externo("abogados", token, "Carmen", "¿Cómo va?")
        mensajes_enlace.enviar_externo("abogados", token, "Carmen", "¿Hay novedades?")
    with cliente.application.test_request_context():
        mios = next(s for s in bandeja_hoy.reunir(uid, True, HOY)["secciones"] if s["clave"] == "mensajes")["elementos"]
        assert len(mios) == 2 and all("2 mensajes sin leer de Carmen" == i["titulo"] for i in mios)
        suyos = [s for s in bandeja_hoy.reunir(otro, False, HOY)["secciones"] if s["clave"] == "mensajes"]
        assert [i["detalle"] for s in suyos for i in s["elementos"]] == ["Visible"] or suyos == [], "no ve el confidencial al que no pertenece"
        assert all("Reservado" != i["detalle"] for s in suyos for i in s["elementos"])
    mensajes_enlace.marcar_leidos("abogados", t, x)
    with cliente.application.test_request_context():
        assert len(next(s for s in bandeja_hoy.reunir(uid, True, HOY)["secciones"] if s["clave"] == "mensajes")["elementos"]) == 1


def test_las_ausencias_por_aprobar_solo_las_ve_quien_gestiona(usuario_id, cliente):
    from app import ausencias
    uid, t = _web(cliente, "hoyaus@ejemplo.com")
    db.asignar_supervisor_tenant(uid, True)
    empleado = db.crear_usuario_vinculado_a_kratos("emp-hoy@ejemplo.com", "kratos-emp-hoy"); db.asignar_tenant(empleado, t)
    ausencias.solicitar(t, empleado, "vacaciones", (HOY + timedelta(days=10)).isoformat(), (HOY + timedelta(days=12)).isoformat())
    with cliente.application.test_request_context():
        assert "ausencias" in _claves(bandeja_hoy.reunir(uid, True, HOY))
        assert "ausencias" not in _claves(bandeja_hoy.reunir(empleado, False, HOY))


def test_un_despacho_no_ve_lo_de_otro(usuario_id, cliente):
    uid, t = _web(cliente, "hoyaislado@ejemplo.com")
    t2, (otro, _) = _despacho("Otro despacho hoy")
    db.crear_tarea_outlook(otro, "Tarea del otro", fecha_vencimiento=HOY.isoformat())
    nucleo.crear_plazo(t2, otro, "Plazo del otro", HOY.isoformat(), responsable_id=otro)
    with cliente.application.test_request_context():
        assert bandeja_hoy.reunir(uid, True, HOY)["secciones"] == []


def test_la_pantalla_hoy_vacia_y_con_cosas(cliente):
    uid, t = _web(cliente, "hoyweb2@ejemplo.com")
    html = cliente.get("/hoy/").get_data(as_text=True)
    assert "Todo al día" in html
    db.crear_tarea_outlook(uid, "Llamar a Carmen", fecha_vencimiento=(HOY - timedelta(days=1)).isoformat())
    html = cliente.get("/hoy/").get_data(as_text=True)
    assert "Llamar a Carmen" in html and "Vencido" in html and "1 cosa necesita tu atención" in html and "Todo al día" not in html


def test_hay_que_iniciar_sesion_para_ver_hoy(cliente):
    assert cliente.get("/hoy/").status_code in (302, 401)


def test_el_inicio_pide_el_panel_despues_y_este_no_repite_las_tareas(cliente):
    uid, t = _web(cliente, "hoyinicio@ejemplo.com")
    assert 'id="dash-hoy"' in cliente.get("/").get_data(as_text=True), "el inicio solo lleva el marcador: no suma consultas"
    db.crear_tarea_outlook(uid, "Tarea del inicio", fecha_vencimiento=(HOY - timedelta(days=1)).isoformat())
    assert cliente.get("/hoy/destacados").status_code == 204, "solo tareas: ya salen en «Mi día»"
    nucleo.crear_plazo(t, uid, "Plazo del inicio", HOY.isoformat(), responsable_id=uid)
    r = cliente.get("/hoy/destacados")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Necesita tu atención" in html and "Plazo del inicio" in html and "Ver todo (2)" in html and "Tarea del inicio" not in html


def test_el_panel_del_inicio_escapa_el_texto(cliente):
    uid, t = _web(cliente, "hoyxss@ejemplo.com")
    nucleo.crear_plazo(t, uid, "<img src=x onerror=alert(1)>", HOY.isoformat(), responsable_id=uid)
    html = cliente.get("/hoy/destacados").get_data(as_text=True)
    assert "<img src=x" not in html and "&lt;img" in html
    assert cliente.get("/hoy/destacados").status_code == 200


def test_el_enlace_de_hoy_esta_en_la_barra_lateral(cliente):
    _web(cliente, "hoybarra@ejemplo.com")
    assert 'href="/hoy/"' in cliente.get("/").get_data(as_text=True)


def test_marcar_como_hecho_una_a_una_y_en_conjunto(cliente):
    uid, t = _web(cliente, "hoyhecho@ejemplo.com")
    a = db.crear_tarea_outlook(uid, "Tarea A", fecha_vencimiento=(HOY - timedelta(days=1)).isoformat())
    b = db.crear_tarea_outlook(uid, "Tarea B", fecha_vencimiento=HOY.isoformat())
    c = db.crear_tarea_outlook(uid, "Tarea C", fecha_vencimiento=HOY.isoformat())
    cl = nucleo.crear_cliente(t, "Cliente Hecho")
    x = nucleo.crear_expediente(t, uid, cl, "Asunto hecho", tipo="procedimiento_judicial")
    z = nucleo.crear_plazo(t, uid, "Plazo hecho", (HOY + timedelta(days=2)).isoformat(), expediente_id=x, responsable_id=uid)
    html = cliente.get("/hoy/").get_data(as_text=True)
    assert "Marcar todo como hecho" in html and "Marcar la sección como hecha" in html and html.count('class="hoy-v2-hecho"') == 4
    # una por una
    r = cliente.post("/hoy/hecho", data={"elemento": f"tarea:{a}"})
    assert r.status_code == 302 and "hechos=1" in r.headers["Location"] and "fallos=0" in r.headers["Location"]
    assert db.obtener_tarea_outlook(uid, a)["estado"] == "completada"
    assert "Tarea A" not in cliente.get("/hoy/").get_data(as_text=True)
    # en conjunto, repitiendo una ya hecha y con una clave inventada (no cuenta como hecha)
    r = cliente.post("/hoy/hecho", data={"elemento": [f"tarea:{b}", f"tarea:{c}", f"plazo:{z}", "correo:7"]})
    assert "hechos=3" in r.headers["Location"] and "fallos=1" in r.headers["Location"]
    assert db.obtener_tarea_outlook(uid, b)["estado"] == "completada" and db.obtener_tarea_outlook(uid, c)["estado"] == "completada"
    assert "Todo al día" in cliente.get("/hoy/").get_data(as_text=True)


def test_hecho_respeta_permisos_y_tareas_bloqueadas(cliente):
    uid, t = _web(cliente, "hoyhecho2@ejemplo.com")
    ajeno = db.crear_usuario_vinculado_a_kratos("ajeno-hecho@ejemplo.com", "kratos-ajeno-hecho")
    de_otro = db.crear_tarea_outlook(ajeno, "Tarea de otra persona", fecha_vencimiento=HOY.isoformat())
    r = cliente.post("/hoy/hecho", data={"elemento": f"tarea:{de_otro}"})
    assert "hechos=0" in r.headers["Location"] and "fallos=1" in r.headers["Location"]
    assert db.obtener_tarea_outlook(ajeno, de_otro)["estado"] != "completada"
    assert cliente.get("/hoy/?hechos=0&fallos=1").status_code == 200


def test_los_certificados_que_caducan_salen_con_dias_servicios_y_riesgo_de_presentacion(cliente):
    from app import certificados as ce
    uid, t = _web(cliente, "hoycert@ejemplo.com")
    db.asignar_supervisor_tenant(uid, True)
    cf = crear_cliente_fiscal(t, "Panadería Marta")
    pronto = ce.alta_rapida(t, uid, tipo="fnmt_persona_fisica", caduca=(HOY + timedelta(days=5)).isoformat(), cliente_fiscal_id=cf, titular="Marta Puig")["id"]
    ce.vincular(t, uid, pronto, cliente_fiscal_id=cf, servicio="presentacion", autorizacion="Mandato firmado")
    ce.alta_rapida(t, uid, tipo="fnmt_persona_fisica", caduca=(HOY - timedelta(days=3)).isoformat(), titular="Antiguo Pérez")
    ce.alta_rapida(t, uid, tipo="fnmt_persona_fisica", caduca=(HOY + timedelta(days=200)).isoformat(), titular="Lejano Gómez")
    crear_vencimiento_fiscal(t, cf, "303", "4T", (HOY + timedelta(days=20)).isoformat())
    with cliente.application.test_request_context():
        b = bandeja_hoy.reunir(uid, True, HOY)
    seccion = {s["clave"]: s for s in b["secciones"]}["certificados"]
    por_titulo = {i["titulo"]: i for i in seccion["elementos"]}
    assert any("Marta Puig" in t for t in por_titulo) and not any("Lejano" in t for t in por_titulo)
    marta = next(i for t_, i in por_titulo.items() if "Marta Puig" in t_)
    assert "Caduca en 5 días" in marta["detalle"] and "Panadería Marta" in marta["detalle"] and "presentación de impuestos" in marta["detalle"] and marta["urgencia"] == "hoy"
    antiguo = next(i for t_, i in por_titulo.items() if "Antiguo" in t_)
    assert "Caducó hace 3 días" in antiguo["detalle"] and antiguo["urgencia"] == "vencido"
    assert any(i["titulo"].startswith("303") and "caduca" in i["detalle"].lower() for i in {s["clave"]: s for s in b["secciones"]}["certificados_riesgo"]["elementos"])


# --- J25: ficheros para a3 que piden que alguien haga algo -------------------------------------------------------------------------------------------------

def _con_fichero(nombre):
    from app import facturas_contables as fc
    from tests.test_facturas_contables import LINEA, _datos
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos(f"{nombre.lower().replace(' ', '')}@ejemplo.com", f"kratos-{nombre}")
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Cliente Fichero SL", nif="B12345678")
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8"})
    fid = fc.crear(t, u, c, _datos(numero="H-1", tercero_nif="A58818501"), [LINEA])
    fc.cambiar_estado(t, u, fid, "revisada")
    lote = fc.exportar(t, u, c)["lote"]
    return fc, t, u, c, lote


def test_un_fichero_sin_marcar_pasados_unos_dias_y_uno_rechazado_aparecen_en_hoy(cliente):
    fc, t, u, c, lote = _con_fichero("Despacho hoy ficheros")
    assert fc.ficheros_por_atender(t, u) == []                                                      # recién exportado: aún es pronto
    futuro = HOY + timedelta(days=4)
    r = fc.ficheros_por_atender(t, u, futuro)
    assert [(x["id"], x["motivo"]) for x in r] == [(lote, "sin_estado")]
    fc.fijar_estado_a3_del_lote(t, u, lote, "rechazado", "falta la cuenta 4720")
    r = fc.ficheros_por_atender(t, u)                                                               # un rechazado no espera días
    assert [(x["motivo"], x["motivo_a3"]) for x in r] == [("rechazado", "falta la cuenta 4720")]
    with cliente.application.test_request_context():
        b = bandeja_hoy.reunir(u)
    textos = [str(i) for s in b["secciones"] if s["clave"] == "contabilizacion" for i in s["elementos"]]
    assert any("Rechazado por a3: falta la cuenta 4720" in x for x in textos)


def test_un_fichero_importado_o_ya_cruzado_con_el_retorno_no_pide_nada():
    fc, t, u, c, lote = _con_fichero("Despacho hoy ficheros dos")
    fc.fijar_estado_a3_del_lote(t, u, lote, "importado")
    assert fc.ficheros_por_atender(t, u, HOY + timedelta(days=30)) == []
    fc.fijar_estado_a3_del_lote(t, u, lote, "")
    conn = fc.db.get_connection()
    try:
        conn.execute("UPDATE contabilidad_lotes SET comprobado_en = ? WHERE id = ?", (fc.db.now_iso(), lote)); conn.commit()
    finally:
        conn.close()
    assert fc.ficheros_por_atender(t, u, HOY + timedelta(days=30)) == []                           # cruzado con lo que devolvió a3: se importó
