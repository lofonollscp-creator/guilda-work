"""Tareas visibles para el cliente en su portal: opt-in por tarea, solo lectura, solo asunto, estado y fecha, aislado por cliente y despacho."""
import pytest

from app import auditoria, db, tareas_trabajo as tt
from tests.conftest import iniciar_sesion_de_prueba


def _entrar_como_cliente(cliente_http, cliente_fiscal_id):
    token = db.crear_acceso_cliente_fiscal(cliente_fiscal_id, "127.0.0.1")
    cliente_http.get(f"/portal/entrar/{token}")


def _mundo(cliente, correo):
    uid = iniciar_sesion_de_prueba(cliente, correo, "contrasena123")
    t = db.crear_tenant(f"Despacho {correo}")
    db.asignar_tenant(uid, t)
    c1 = db.crear_cliente_fiscal(t, "Cliente Uno", email=f"uno-{correo}")
    c2 = db.crear_cliente_fiscal(t, "Cliente Dos", email=f"dos-{correo}")
    return uid, t, c1, c2


def test_por_defecto_ninguna_tarea_sale_al_portal(cliente):
    uid, t, c1, c2 = _mundo(cliente, "pc1@ejemplo.com")
    db.crear_tarea_outlook(uid, asunto="Interna del cliente uno", cliente_fiscal_id=c1)
    assert tt.tareas_para_cliente(t, c1) == []


def test_marcar_visible_exige_cliente_y_permiso_y_queda_auditado(cliente):
    uid, t, c1, c2 = _mundo(cliente, "pc2@ejemplo.com")
    sin_cliente = db.crear_tarea_outlook(uid, asunto="Sin cliente")
    con_cliente = db.crear_tarea_outlook(uid, asunto="Con cliente", cliente_fiscal_id=c1)
    try:
        tt.fijar_visible_cliente(uid, sin_cliente, True)
        assert False
    except tt.TransicionInvalida as e:
        assert e.codigo == "sin_cliente"
    otra = db.crear_usuario_vinculado_a_kratos("pc2b@ejemplo.com", "k-pc2b"); db.asignar_tenant(otra, t)
    db.compartir_tarea_outlook(uid, con_cliente, otra, "observa")
    try:
        tt.fijar_visible_cliente(otra, con_cliente, True)                                       # un observador no decide qué ve el cliente
        assert False
    except tt.TransicionInvalida as e:
        assert e.codigo == "sin_permiso"
    tt.fijar_visible_cliente(uid, con_cliente, True)
    assert [x["asunto"] for x in tt.tareas_para_cliente(t, c1)] == ["Con cliente"]
    assert "tarea.visible_cliente" in {e["accion"] for e in auditoria.listar(t, entidad="tarea")}
    assert any(a["tipo"] == "visible_cliente" for a in db.actividad_de_tarea(uid, con_cliente))
    tt.fijar_visible_cliente(uid, con_cliente, False)
    assert tt.tareas_para_cliente(t, c1) == []


def test_el_cliente_ve_solo_asunto_estado_y_fecha_de_sus_tareas_marcadas(cliente):
    uid, t, c1, c2 = _mundo(cliente, "pc3@ejemplo.com")
    a = db.crear_tarea_outlook(uid, asunto="Reunir facturas del trimestre", cuerpo="NOTA INTERNA SECRETA", fecha_vencimiento="2026-11-10", cliente_fiscal_id=c1)
    db.comentar_tarea_outlook(uid, a, "COMENTARIO INTERNO")
    tt.subir_adjunto(uid, a, "interno.pdf", b"%PDF interno")
    tt.transicionar(uid, a, "esperando", "MOTIVO INTERNO")
    b = db.crear_tarea_outlook(uid, asunto="De otro cliente", cliente_fiscal_id=c2)
    privada = db.crear_tarea_outlook(uid, asunto="No marcada", cliente_fiscal_id=c1)
    hecha = db.crear_tarea_outlook(uid, asunto="Alta censal", cliente_fiscal_id=c1)
    sub = tt.crear_subtarea(uid, a, "Subtarea interna")
    for x in (a, b, hecha):
        tt.fijar_visible_cliente(uid, x, True)
    db.completar_tarea_outlook(uid, hecha)
    portal = cliente.application.test_client()
    _entrar_como_cliente(portal, c1)
    html = portal.get("/portal/").get_data(as_text=True)
    assert "Reunir facturas del trimestre" in html and "En espera" in html and "Alta censal" in html and "Completada" in html
    assert "Trabajo en curso con tu gestoría" in html
    for secreto in ("NOTA INTERNA SECRETA", "COMENTARIO INTERNO", "interno.pdf", "MOTIVO INTERNO", "De otro cliente", "No marcada", "Subtarea interna"):
        assert secreto not in html, secreto
    assert html.index("Reunir facturas") < html.index("Alta censal")                           # las abiertas primero
    assert privada and sub


def test_una_tarea_con_dos_clientes_sale_a_los_dos_pero_no_a_un_tercero(cliente):
    uid, t, c1, c2 = _mundo(cliente, "pc4@ejemplo.com")
    c3 = db.crear_cliente_fiscal(t, "Cliente Tres", email="tres-pc4@ejemplo.com")
    a = db.crear_tarea_outlook(uid, asunto="Compartida entre dos", cliente_fiscal_id=c1)
    tt.fijar_clientes(uid, a, [c1, c2], c1)
    tt.fijar_visible_cliente(uid, a, True)
    assert [x["asunto"] for x in tt.tareas_para_cliente(t, c1)] == ["Compartida entre dos"] and [x["asunto"] for x in tt.tareas_para_cliente(t, c2)] == ["Compartida entre dos"]
    assert tt.tareas_para_cliente(t, c3) == []


def test_aislamiento_entre_despachos_y_papelera(cliente):
    uid, t, c1, c2 = _mundo(cliente, "pc5@ejemplo.com")
    a = db.crear_tarea_outlook(uid, asunto="Visible", cliente_fiscal_id=c1)
    tt.fijar_visible_cliente(uid, a, True)
    otro = db.crear_tenant("Otro despacho portal")
    assert tt.tareas_para_cliente(otro, c1) == []                                                # un id de cliente ajeno no abre nada
    db.eliminar_tarea_outlook(uid, a)
    assert tt.tareas_para_cliente(t, c1) == []                                                   # en la papelera deja de verse
    db.restaurar_tarea_outlook(uid, a)
    assert len(tt.tareas_para_cliente(t, c1)) == 1


def test_api_y_formulario_para_marcar_la_tarea(cliente):
    from tests.test_api_tareas import _tarea, _usuario
    t = db.crear_tenant("Despacho API portal")
    h, uid = _usuario(cliente, "pc6@ejemplo.com", t)
    c1 = db.crear_cliente_fiscal(t, "Cliente API", email="api-pc6@ejemplo.com")
    tid = _tarea(cliente, h, "Para el portal")
    r = cliente.put(f"/api/v1/tareas-outlook/{tid}/visible-cliente", json={"visible": True}, headers=h)
    assert r.status_code == 409 and r.get_json()["codigo"] == "sin_cliente"
    assert cliente.put(f"/api/v1/tareas-outlook/{tid}/visible-cliente", json={"visible": "si"}, headers=h).get_json()["codigo"] == "visible_invalido"
    tt.fijar_clientes(uid, tid, [c1], c1)
    assert cliente.put(f"/api/v1/tareas-outlook/{tid}/visible-cliente", json={"visible": True}, headers=h).status_code == 200
    assert cliente.get(f"/api/v1/tareas-outlook/{tid}", headers=h).get_json()["data"]["visible_cliente"] == 1
    ajeno = _usuario(cliente, "pc6x@ejemplo.com", db.crear_tenant("Despacho ajeno portal"))[0]
    assert cliente.put(f"/api/v1/tareas-outlook/{tid}/visible-cliente", json={"visible": False}, headers=ajeno).status_code == 404


def test_formulario_web_de_edicion_marca_y_desmarca(cliente):
    uid, t, c1, c2 = _mundo(cliente, "pc7@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="Formulario", cliente_fiscal_id=c1)
    html = cliente.get(f"/tareas/{tid}/editar").get_data(as_text=True)
    assert "Enseñar esta tarea al cliente en su portal" in html and 'name="visible_cliente"' in html

    def enviar(**extra):
        t_ = db.obtener_tarea_outlook(uid, tid)
        return cliente.post(f"/tareas/{tid}/editar", data={"asunto": "Formulario", "estado": "no_iniciada", "prioridad": "normal", "porcentaje_completado": "0", "version": str(t_["version"]),
                                                          "cliente_fiscal_id": str(c1), **extra})
    assert enviar(visible_cliente_enviado="1", visible_cliente="1").status_code == 302 and len(tt.tareas_para_cliente(t, c1)) == 1
    enviar()                                                                                      # un formulario antiguo, sin el campo, no cambia nada
    assert len(tt.tareas_para_cliente(t, c1)) == 1
    enviar(visible_cliente_enviado="1")                                                           # casilla desmarcada
    assert tt.tareas_para_cliente(t, c1) == []
    sin = db.crear_tarea_outlook(uid, asunto="Sin cliente")
    assert 'name="visible_cliente"' not in cliente.get(f"/tareas/{sin}/editar").get_data(as_text=True)


# --- Comentarios del cliente ----------------------------------------------------------------------------------------------------------

def _tarea_comentable(uid, t, cliente_fiscal_id, asunto="Reunir facturas", comentarios=True, **kw):
    tid = db.crear_tarea_outlook(uid, asunto=asunto, cliente_fiscal_id=cliente_fiscal_id, **kw)
    tt.fijar_visible_cliente(uid, tid, True, comentarios)
    return tid


def _portal(cliente, cliente_fiscal_id):
    p = cliente.application.test_client()
    _entrar_como_cliente(p, cliente_fiscal_id)
    return p


def _comentar(portal, tid, texto="Os mando los tickets hoy"):
    return portal.post(f"/portal/tareas/{tid}/comentarios", data={"texto": texto})


def _guardados(tid):
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM tarea_comentarios_cliente WHERE tarea_id = ? ORDER BY id", (tid,))]
    finally:
        conn.close()


def test_comentar_exige_el_permiso_y_visible(cliente):
    uid, t, c1, c2 = _mundo(cliente, "cc1@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="X", cliente_fiscal_id=c1)
    with pytest.raises(tt.TransicionInvalida) as e:
        tt.fijar_visible_cliente(uid, tid, False, True)
    assert e.value.codigo == "comentarios_sin_visible"
    tt.fijar_visible_cliente(uid, tid, True)                                         # visible, pero sin permiso para comentar (lo de siempre)
    assert tareas_para(t, c1)[0]["puede_comentar"] is False
    tt.fijar_visible_cliente(uid, tid, True, True)
    assert tareas_para(t, c1)[0]["puede_comentar"] is True
    tt.fijar_visible_cliente(uid, tid, False)                                        # dejar de enseñarla apaga también los comentarios
    tt.fijar_visible_cliente(uid, tid, True)
    assert tareas_para(t, c1)[0]["puede_comentar"] is False
    assert "tarea.comentarios_cliente" in {e["accion"] for e in auditoria.listar(t, entidad="tarea")}


def tareas_para(t, c):
    return tt.tareas_para_cliente(t, c)


def test_el_cliente_comenta_el_equipo_recibe_aviso_y_ve_su_conversacion(cliente, monkeypatch):
    from app import notificaciones
    avisos = []
    monkeypatch.setattr(notificaciones, "crear_y_enviar", lambda usuario_id, tipo, titulo, cuerpo, url=None, datos=None, **k: avisos.append((usuario_id, tipo, titulo, cuerpo, url)))
    uid, t, c1, c2 = _mundo(cliente, "cc2@ejemplo.com")
    otra = db.crear_usuario_vinculado_a_kratos("cc2b@ejemplo.com", "k-cc2b"); db.asignar_tenant(otra, t)
    tid = _tarea_comentable(uid, t, c1)
    db.asignar_tarea_outlook(uid, tid, otra)
    portal = _portal(cliente, c1)
    html = portal.get("/portal/").get_data(as_text=True)
    assert "Escribe un comentario" in html and f'action="/portal/tareas/{tid}/comentarios"' in html
    r = _comentar(portal, tid)
    assert r.status_code == 302 and f"#tarea-{tid}" in r.headers["Location"]
    g = _guardados(tid)
    assert len(g) == 1 and g[0]["autor"] == "cliente" and g[0]["cliente_fiscal_id"] == c1 and g[0]["leido_en"] is None
    assert sorted(a[0] for a in avisos) == sorted({uid, otra}) and avisos[0][1] == "portal_comentario_tarea" and f"/tareas/{tid}#cliente" in avisos[0][4]
    assert "Os mando los tickets hoy" in portal.get("/portal/").get_data(as_text=True)
    assert "tarea.comentario_cliente" in {e["accion"] for e in auditoria.listar(t, entidad="tarea")}


def test_lo_que_no_se_puede_comentar_es_un_404_y_no_se_guarda_nada(cliente):
    uid, t, c1, c2 = _mundo(cliente, "cc3@ejemplo.com")
    sin_permiso = db.crear_tarea_outlook(uid, asunto="Sin permiso", cliente_fiscal_id=c1); tt.fijar_visible_cliente(uid, sin_permiso, True)
    oculta = db.crear_tarea_outlook(uid, asunto="Oculta", cliente_fiscal_id=c1)
    de_otro_cliente = _tarea_comentable(uid, t, c2, "De Dos")
    ajeno_t = db.crear_tenant("Otro despacho comentarios"); ajeno_u = db.crear_usuario_vinculado_a_kratos("cc3x@ejemplo.com", "k-cc3x"); db.asignar_tenant(ajeno_u, ajeno_t)
    ajena = db.crear_cliente_fiscal(ajeno_t, "Ajeno SL")
    de_otro_despacho = _tarea_comentable(ajeno_u, ajeno_t, ajena, "De otro despacho")
    papelera = _tarea_comentable(uid, t, c1, "En la papelera"); db.eliminar_tarea_outlook(uid, papelera)
    portal = _portal(cliente, c1)
    for tid in (sin_permiso, oculta, de_otro_cliente, de_otro_despacho, papelera, 99999):
        assert _comentar(portal, tid).status_code == 404, tid
        assert _guardados(tid) == []
    anonimo = cliente.application.test_client()
    assert "/portal/entrar" in _comentar(anonimo, sin_permiso).headers["Location"]                      # sin sesión del portal, a entrar


def test_validaciones_de_texto_completada_y_limites(cliente, monkeypatch):
    uid, t, c1, c2 = _mundo(cliente, "cc4@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    for texto, mensaje in (("   ", "Escribe algo antes de enviar"), ("x" * (tt.MAX_CARACTERES_COMENTARIO + 1), "como máximo 1000 caracteres")):
        r = portal.post(f"/portal/tareas/{tid}/comentarios", data={"texto": texto}, follow_redirects=True)
        assert r.status_code == 200 and mensaje in r.get_data(as_text=True), mensaje
    assert _guardados(tid) == []
    _comentar(portal, tid, "Hola\x00\x07 mundo")
    assert _guardados(tid)[0]["texto"] == "Hola mundo"                                                  # sin caracteres de control
    monkeypatch.setattr(tt, "MAX_COMENTARIOS_POR_HORA_Y_TAREA", 3)
    for i in range(5):
        _comentar(portal, tid, f"Comentario {i}")
    assert len(_guardados(tid)) == 3                                                                  # el resto se rechaza, no se guarda
    otra = _tarea_comentable(uid, t, c1, "Otra tarea")
    monkeypatch.setattr(tt, "MAX_COMENTARIOS_POR_DIA", 4)
    _comentar(portal, otra, "En otra")
    _comentar(portal, otra, "Y otra más")
    assert len(_guardados(otra)) == 1                                                                 # el tope diario cuenta todas las tareas del cliente
    db.completar_tarea_outlook(uid, tid)
    assert [x["puede_comentar"] for x in tareas_para(t, c1) if x["id"] == tid] == [False]                 # completada: ya no se puede comentar
    _comentar(portal, tid, "Tarde")
    assert len(_guardados(tid)) == 3
    with pytest.raises(tt.ComentarioInvalido) as e:
        tt.comentar_como_cliente(t, c1, tid, "Tarde")
    assert e.value.codigo == "cerrada"


def test_el_html_del_comentario_no_se_ejecuta_ni_en_el_portal_ni_en_la_ficha(cliente):
    uid, t, c1, c2 = _mundo(cliente, "cc5@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    _comentar(portal, tid, '<script>alert("x")</script><b>negrita</b>')
    for html in (portal.get("/portal/").get_data(as_text=True), cliente.get(f"/tareas/{tid}").get_data(as_text=True)):
        assert "<script>alert" not in html and "&lt;script&gt;" in html and "<b>negrita</b>" not in html


def test_cada_cliente_ve_solo_su_conversacion(cliente):
    uid, t, c1, c2 = _mundo(cliente, "cc6@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    tt.fijar_clientes(uid, tid, [c1, c2], c1)
    p1, p2 = _portal(cliente, c1), _portal(cliente, c2)
    _comentar(p1, tid, "Secreto del uno")
    _comentar(p2, tid, "Secreto del dos")
    tt.responder_al_cliente(uid, tid, c1, "Respuesta al uno")
    h1, h2 = p1.get("/portal/").get_data(as_text=True), p2.get("/portal/").get_data(as_text=True)
    assert "Secreto del uno" in h1 and "Respuesta al uno" in h1 and "Secreto del dos" not in h1
    assert "Secreto del dos" in h2 and "Secreto del uno" not in h2 and "Respuesta al uno" not in h2
    assert [c["cliente"] for c in tt.conversaciones_con_clientes(uid, tid)] == ["Cliente Uno", "Cliente Dos"]          # el equipo ve las dos, separadas


def test_el_equipo_lee_contesta_con_correo_y_oculta(cliente, monkeypatch):
    from app import notificaciones_email as ne
    enviados = []
    monkeypatch.setattr(ne, "_enviar", lambda destino, asunto, plano, html=None: enviados.append((destino, asunto, plano)))
    uid, t, c1, c2 = _mundo(cliente, "cc7@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    _comentar(portal, tid, "Primera duda")
    _comentar(portal, tid, "Comentario inadecuado")
    html = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert 'id="cliente"' in html and "Conversación con el cliente" in html and "2 nuevos" in html and "Primera duda" in html
    assert "nuevos" not in cliente.get(f"/tareas/{tid}").get_data(as_text=True).split('id="cliente"')[1][:400]       # al verlo queda leído
    r = cliente.post(f"/tareas/{tid}/cliente/responder", data={"cliente_fiscal_id": str(c1), "texto": "Gracias, ya lo vemos"})
    assert r.status_code == 302 and len(enviados) == 1 and enviados[0][0] == f"uno-cc7@ejemplo.com" and "Gracias, ya lo vemos" in enviados[0][2]
    assert "Gracias, ya lo vemos" in portal.get("/portal/").get_data(as_text=True)
    malo = [c for c in _guardados(tid) if c["texto"] == "Comentario inadecuado"][0]
    assert cliente.post(f"/tareas/cliente-comentarios/{malo['id']}/ocultar").status_code == 302
    assert "Comentario inadecuado" not in portal.get("/portal/").get_data(as_text=True) and "Primera duda" in portal.get("/portal/").get_data(as_text=True)
    ficha = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert "Comentario inadecuado" not in ficha and "Comentario oculto" in ficha
    assert cliente.post(f"/tareas/cliente-comentarios/{malo['id']}/ocultar").status_code == 404           # ya oculto
    acciones = {e["accion"] for e in auditoria.listar(t, entidad="tarea")}
    assert {"tarea.respuesta_cliente", "tarea.comentario_cliente.ocultar"} <= acciones


def test_un_fallo_del_correo_no_estropea_la_respuesta_y_sin_correo_tampoco(cliente, monkeypatch):
    from app import notificaciones_email as ne
    def roto(*a, **k):
        raise ne.ErrorNotificacionesEmail("SMTP caído")
    monkeypatch.setattr(ne, "_enviar", roto)
    uid, t, c1, c2 = _mundo(cliente, "cc8@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    assert cliente.post(f"/tareas/{tid}/cliente/responder", data={"cliente_fiscal_id": str(c1), "texto": "Respondo igual"}).status_code == 302
    assert [c["texto"] for c in _guardados(tid)] == ["Respondo igual"]


def test_responder_exige_permiso_cliente_vinculado_y_texto(cliente):
    uid, t, c1, c2 = _mundo(cliente, "cc9@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    observador = db.crear_usuario_vinculado_a_kratos("cc9b@ejemplo.com", "k-cc9b"); db.asignar_tenant(observador, t)
    db.compartir_tarea_outlook(uid, tid, observador, "observa")
    for quien, cid, texto, codigo in ((observador, c1, "Hola", "sin_permiso"), (uid, c2, "Hola", "cliente_invalido"), (uid, c1, "  ", "vacio"), (uid, c1, "x" * 1001, "largo")):
        with pytest.raises(tt.TransicionInvalida) as e:
            tt.responder_al_cliente(quien, tid, cid, texto)
        assert e.value.codigo == codigo
    ajeno = db.crear_usuario_vinculado_a_kratos("cc9x@ejemplo.com", "k-cc9x"); db.asignar_tenant(ajeno, db.crear_tenant("Otro despacho responder"))
    with pytest.raises(tt.TransicionInvalida) as e:
        tt.responder_al_cliente(ajeno, tid, c1, "Hola")
    assert e.value.codigo == "no_encontrada"
    assert tt.conversaciones_con_clientes(ajeno, tid) == [] and tt.ocultar_comentario_de_cliente(ajeno, 1) is None


def test_si_se_deja_de_enseñar_el_cliente_ya_no_ve_ni_comenta_pero_el_equipo_conserva_la_conversacion(cliente):
    uid, t, c1, c2 = _mundo(cliente, "cc10@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    portal = _portal(cliente, c1)
    _comentar(portal, tid, "Antes de ocultarla")
    tt.fijar_visible_cliente(uid, tid, False)
    assert tareas_para(t, c1) == [] and _comentar(portal, tid, "Después").status_code == 404
    assert [c["texto"] for c in _guardados(tid)] == ["Antes de ocultarla"]
    html = cliente.get(f"/tareas/{tid}").get_data(as_text=True)
    assert "ya no se enseña al cliente" in html and "Antes de ocultarla" in html


def test_formulario_y_api_del_permiso_de_comentarios(cliente):
    from tests.test_api_tareas import _tarea, _usuario
    uid, t, c1, c2 = _mundo(cliente, "cc11@ejemplo.com")
    tid = db.crear_tarea_outlook(uid, asunto="Formulario", cliente_fiscal_id=c1)

    def enviar(**extra):
        f = db.obtener_tarea_outlook(uid, tid)
        return cliente.post(f"/tareas/{tid}/editar", data={"asunto": "Formulario", "estado": "no_iniciada", "prioridad": "normal", "porcentaje_completado": "0", "version": str(f["version"]),
                                                          "cliente_fiscal_id": str(c1), "visible_cliente_enviado": "1", **extra})
    assert "Permitir que el cliente escriba comentarios" in cliente.get(f"/tareas/{tid}/editar").get_data(as_text=True)
    assert enviar(visible_cliente="1", comentarios_cliente="1").status_code == 302 and tareas_para(t, c1)[0]["puede_comentar"] is True
    assert enviar(visible_cliente="1").status_code == 302 and tareas_para(t, c1)[0]["puede_comentar"] is False
    r = enviar(comentarios_cliente="1")                                                            # comentarios sin enseñarla: se rechaza con motivo
    assert r.status_code == 422 and "primero hay que enseñarle la tarea" in r.get_data(as_text=True)
    t2 = db.crear_tenant("Despacho API comentarios")
    h, u = _usuario(cliente, "cc11b@ejemplo.com", t2)
    c = db.crear_cliente_fiscal(t2, "Cliente API SL")
    api = _tarea(cliente, h, "Por API")
    tt.fijar_clientes(u, api, [c], c)
    url = f"/api/v1/tareas-outlook/{api}/visible-cliente"
    assert cliente.put(url, json={"visible": True, "comentarios": "si"}, headers=h).get_json()["codigo"] == "comentarios_invalido"
    assert cliente.put(url, json={"visible": False, "comentarios": True}, headers=h).get_json()["codigo"] == "comentarios_sin_visible"
    assert cliente.put(url, json={"visible": True, "comentarios": True}, headers=h).status_code == 200 and tareas_para(t2, c)[0]["puede_comentar"] is True


def test_borrar_un_cliente_o_un_despacho_no_se_atasca_con_conversaciones(cliente):
    uid, t, c1, c2 = _mundo(cliente, "cc12@ejemplo.com")
    tid = _tarea_comentable(uid, t, c1)
    tt.fijar_clientes(uid, tid, [c1, c2], c1)
    tt.comentar_como_cliente(t, c1, tid, "Uno")
    tt.comentar_como_cliente(t, c2, tid, "Dos")
    db.eliminar_cliente_fiscal_definitivamente(t, c1)                                                  # antes de esto, la clave foránea lo impedía
    assert [c["cliente_fiscal_id"] for c in _guardados(tid)] == [c2]
    db.borrar_tenant(t)
    assert _guardados(tid) == []
    otra = db.crear_tarea_outlook(uid, asunto="Se borra del todo")
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO tarea_comentarios_cliente (tenant_id, tarea_id, cliente_fiscal_id, autor, texto, creado_en) SELECT 1, ?, id, 'cliente', 'x', ? FROM clientes_fiscales LIMIT 1", (otra, db.now_iso()))
        conn.commit()
    finally:
        conn.close()
    db.eliminar_tarea_outlook(uid, otra); db.eliminar_tarea_outlook_definitivamente(uid, otra)             # y las conversaciones caen con su tarea
    assert _guardados(otra) == []


def test_un_cliente_que_ya_entro_al_portal_se_puede_borrar_para_siempre(cliente):
    uid, t, c1, c2 = _mundo(cliente, "cc13@ejemplo.com")
    _portal(cliente, c1)                                                                              # entrar al portal crea un enlace de acceso que antes impedía borrar al cliente
    db.eliminar_cliente_fiscal_definitivamente(t, c1)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM clientes_fiscales WHERE id = ?", (c1,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM clientes_fiscales_accesos WHERE cliente_fiscal_id = ?", (c1,)).fetchone()[0] == 0
    finally:
        conn.close()
