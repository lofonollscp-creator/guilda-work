"""Tareas visibles para el cliente en su portal: opt-in por tarea, solo lectura, solo asunto, estado y fecha, aislado por cliente y despacho."""
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
