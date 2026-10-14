"""Flujo de trabajo de las obligaciones fiscales (app/obligaciones.py): fases, flujo flexible y estricto, evidencias, indicadores, roles, concurrencia y auditoría."""
from datetime import date, timedelta

import pytest

from app import acceso, auditoria, db, obligaciones as ob


@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Obligaciones")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.gestor, e.rev, e.aud = u("sup-ob@ejemplo.com", True), u("gestor-ob@ejemplo.com"), u("rev-ob@ejemplo.com"), u("aud-ob@ejemplo.com")
    acceso.dar_membresia(t, e.sup, e.rev, "revisor_fiscal", "organizacion"); acceso.dar_membresia(t, e.sup, e.aud, "auditor", "organizacion")
    e.c = db.crear_cliente_fiscal(t, "Cliente Obligaciones SL", nif="B12345674")
    e.v = db.crear_vencimiento_fiscal(t, e.c, "303", "2026-T3", (date.today() + timedelta(days=30)).isoformat(), usuario_id=e.gestor)
    return e


def _fase(d, v=None):
    return db.obtener_vencimiento_fiscal(d.t, v or d.v)["fase"]


def test_el_flujo_flexible_deja_presentar_desde_cualquier_fase_y_cerrar(d):
    r = ob.transicionar(d.t, d.gestor, d.v, "en_preparacion")
    assert r == {"fase": "en_preparacion", "estado": "pendiente", "version": 2}
    r = ob.transicionar(d.t, d.gestor, d.v, "presentada", presentacion={"referencia": "CSV-123", "organismo": "AEAT"})
    x = db.obtener_vencimiento_fiscal(d.t, d.v)
    assert (x["fase"], x["estado"], x["presentada_tarde"]) == ("presentada", "presentado", 0)
    ev = ob.evidencias(d.t, d.v)
    assert len(ev) == 1 and ev[0]["referencia"] == "CSV-123" and ev[0]["procedencia"] == "declarada_por_gestor" and ev[0]["actor"] == "gestor-ob@ejemplo.com"
    ob.transicionar(d.t, d.gestor, d.v, "cerrada")
    assert _fase(d) == "cerrada" and db.obtener_vencimiento_fiscal(d.t, d.v)["estado"] == "presentado"
    with pytest.raises(ValueError, match="No se puede pasar"):
        ob.transicionar(d.t, d.gestor, d.v, "pendiente")


def test_el_flujo_estricto_exige_revision_y_aprobacion_y_el_boton_de_siempre_lo_respeta(d):
    ob.guardar_config(d.t, d.sup, flujo_estricto=True, exigir_justificante=False)
    with pytest.raises(ValueError, match="flujo estricto"):
        ob.transicionar(d.t, d.gestor, d.v, "presentada")
    v = db.obtener_vencimiento_fiscal(d.t, d.v)
    with pytest.raises(ValueError, match="flujo estricto"):
        ob.exigir_para_marcar_presentado(d.t, d.gestor, v)
    ob.transicionar(d.t, d.gestor, d.v, "en_preparacion"); ob.transicionar(d.t, d.gestor, d.v, "en_revision")
    with pytest.raises(ValueError, match="Solo la dirección o el revisor"):
        ob.transicionar(d.t, d.gestor, d.v, "aprobada")
    assert "Obligación para revisar" in [n["titulo"] for n in db.listar_notificaciones(d.rev, 5)], "al entrar en revisión se avisa a quien revisa"
    ob.transicionar(d.t, d.rev, d.v, "aprobada")
    ob.exigir_para_marcar_presentado(d.t, d.gestor, db.obtener_vencimiento_fiscal(d.t, d.v))        # ya aprobada: el botón de siempre vale
    ob.transicionar(d.t, d.gestor, d.v, "presentada", presentacion={"presentado_en": date.today().isoformat()})
    assert _fase(d) == "presentada"
    with pytest.raises(ValueError, match="Solo la dirección"):
        ob.guardar_config(d.t, d.gestor, flujo_estricto=False, exigir_justificante=False)


def test_un_rechazo_devuelve_a_preparacion_con_motivo_y_queda_registrado_y_avisado(d):
    ob.guardar_config(d.t, d.sup, flujo_estricto=True, exigir_justificante=False)
    ob.transicionar(d.t, d.gestor, d.v, "en_preparacion"); ob.transicionar(d.t, d.gestor, d.v, "en_revision")
    with pytest.raises(ValueError, match="Solo quien revisa"):
        ob.transicionar(d.t, d.gestor, d.v, "en_preparacion", motivo="me equivoqué")
    with pytest.raises(ValueError, match="por qué se devuelve"):
        ob.transicionar(d.t, d.rev, d.v, "en_preparacion")
    ob.transicionar(d.t, d.rev, d.v, "en_preparacion", motivo="Falta el modelo 390 del año anterior")
    assert _fase(d) == "en_preparacion" and db.obtener_vencimiento_fiscal(d.t, d.v)["fase_motivo"] == "Falta el modelo 390 del año anterior"
    assert "Obligación devuelta a preparación" in [n["titulo"] for n in db.listar_notificaciones(d.gestor, 5)]
    assert auditoria.listar(d.t, entidad="obligacion", entidad_id=d.v, accion="obligacion.rechazo")[0]["detalle"]["motivo"].startswith("Falta el modelo 390")


def test_no_aplica_y_anulada_piden_justificacion_y_autorizacion_y_salen_de_las_listas(d):
    with pytest.raises(ValueError, match="Solo la dirección o el revisor"):
        ob.transicionar(d.t, d.gestor, d.v, "no_aplica", motivo="Cliente en régimen simplificado")
    with pytest.raises(ValueError, match="justificación"):
        ob.transicionar(d.t, d.rev, d.v, "no_aplica")
    ob.transicionar(d.t, d.rev, d.v, "no_aplica", motivo="Cliente en régimen simplificado")
    assert db.obtener_vencimiento_fiscal(d.t, d.v) is None and d.v not in [v["id"] for v in db.listar_vencimientos_fiscales(d.t)], "deja de contar como pendiente"
    papelera = [x for x in db.papelera_fiscal(d.t) if x["origen"] == "vencimiento_fiscal"]
    assert len(papelera) == 1
    db.restaurar_vencimiento_fiscal(d.t, d.v)               # reactivarla la devuelve al principio
    assert _fase(d) == "pendiente"
    assert "obligacion.reactivada" in [e["accion"] for e in auditoria.listar(d.t, entidad="obligacion", entidad_id=d.v)]


def test_la_presentacion_pide_fecha_valida_y_marca_la_tardia(d):
    with pytest.raises(ValueError, match="futuro"):
        ob.transicionar(d.t, d.gestor, d.v, "presentada", presentacion={"presentado_en": (date.today() + timedelta(days=3)).isoformat()})
    with pytest.raises(ValueError, match="no es válida"):
        ob.transicionar(d.t, d.gestor, d.v, "presentada", presentacion={"presentado_en": "ayer"})
    assert _fase(d) == "pendiente" and ob.evidencias(d.t, d.v) == [], "los fallos no dejan rastro a medias"
    atrasado = db.crear_vencimiento_fiscal(d.t, d.c, "303", "2020-T1", "2020-04-20")
    ob.transicionar(d.t, d.gestor, atrasado, "presentada", presentacion={"presentado_en": "2020-05-02"})
    assert db.obtener_vencimiento_fiscal(d.t, atrasado)["presentada_tarde"] == 1


def test_exigir_justificante_bloquea_presentar_y_cerrar_sin_el(d):
    ob.guardar_config(d.t, d.sup, flujo_estricto=False, exigir_justificante=True)
    with pytest.raises(ValueError, match="exige un justificante"):
        ob.transicionar(d.t, d.gestor, d.v, "presentada")
    with pytest.raises(ValueError, match="exige el justificante"):
        ob.exigir_para_marcar_presentado(d.t, d.gestor, db.obtener_vencimiento_fiscal(d.t, d.v))
    doc = db.subir_documento_vencimiento(d.v, "justificante.pdf", "application/pdf", b"%PDF-1.4 justificante", origen="justificante")
    ob.transicionar(d.t, d.gestor, d.v, "presentada", presentacion={"documento_id": doc})
    ob.transicionar(d.t, d.gestor, d.v, "cerrada")
    otro = db.crear_vencimiento_fiscal(d.t, d.c, "111", "2026-T3", "2026-10-20")
    with pytest.raises(ValueError, match="no pertenece"):
        ob.transicionar(d.t, d.gestor, otro, "presentada", presentacion={"documento_id": doc})


def test_cerrar_exige_la_evidencia(d):
    conn = db.get_connection()
    try:
        conn.execute("UPDATE vencimientos_fiscales SET fase = 'presentada', estado = 'presentado' WHERE id = ?", (d.v,)); conn.commit()
    finally:
        conn.close()
    with pytest.raises(ValueError, match="sin la evidencia"):
        ob.transicionar(d.t, d.gestor, d.v, "cerrada")


def test_el_boton_de_siempre_deja_su_evidencia_y_su_auditoria(d):
    db.marcar_presentado_vencimiento_fiscal(d.t, d.v, d.gestor)
    assert _fase(d) == "presentada" and len(ob.evidencias(d.t, d.v)) == 1
    db.marcar_presentado_vencimiento_fiscal(d.t, d.v, d.gestor)
    assert len(ob.evidencias(d.t, d.v)) == 1, "repetirlo no duplica la evidencia"
    assert [e["accion"] for e in auditoria.listar(d.t, entidad="obligacion", entidad_id=d.v)] == ["obligacion.transicion"]


def test_los_indicadores_son_independientes_de_la_fase(d):
    hoy = date(2026, 10, 13)
    mk = lambda fase, lim, bloq=0, tarde=0: {"fase": fase, "fecha_limite": lim, "bloqueada": bloq, "presentada_tarde": tarde}
    assert ob.indicadores(mk("en_preparacion", "2026-10-10"), hoy)["vencida"] is True
    assert ob.indicadores(mk("en_preparacion", "2026-10-18"), hoy)["en_riesgo"] is True and ob.indicadores(mk("en_revision", "2026-10-18"), hoy)["en_riesgo"] is False
    assert ob.indicadores(mk("en_revision", "2026-10-15"), hoy)["en_riesgo"] is True
    assert ob.indicadores(mk("pendiente", "2026-10-25", bloq=1), hoy)["en_riesgo"] is True and ob.indicadores(mk("pendiente", "2026-10-25"), hoy)["en_riesgo"] is False
    assert ob.indicadores(mk("presentada", "2026-10-10", tarde=1), hoy) == {"vencida": False, "en_riesgo": False, "bloqueada": False, "presentada_tarde": True, "dias_restantes": -3}


def test_bloquear_es_un_indicador_que_no_detiene_el_reloj(d):
    ob.bloquear(d.t, d.gestor, d.v, "Esperando los extractos del banco")
    x = db.obtener_vencimiento_fiscal(d.t, d.v)
    assert (x["bloqueada"], x["bloqueo_motivo"], x["fase"]) == (1, "Esperando los extractos del banco", "pendiente")
    ob.transicionar(d.t, d.gestor, d.v, "en_preparacion")
    assert db.obtener_vencimiento_fiscal(d.t, d.v)["bloqueada"] == 1, "cambiar de fase no desbloquea sola"
    with pytest.raises(ValueError, match="qué se está esperando"):
        ob.bloquear(d.t, d.gestor, d.v, "")
    ob.bloquear(d.t, d.gestor, d.v, None, bloqueada=False)
    assert db.obtener_vencimiento_fiscal(d.t, d.v)["bloqueada"] == 0
    assert [e["accion"] for e in auditoria.listar(d.t, entidad="obligacion", entidad_id=d.v)][:3] == ["obligacion.desbloqueo", "obligacion.transicion", "obligacion.bloqueo"]


def test_el_segundo_que_cambia_el_estado_ve_el_conflicto(d):
    v0 = db.obtener_vencimiento_fiscal(d.t, d.v)["version"]
    ob.transicionar(d.t, d.gestor, d.v, "en_preparacion", version=v0)
    with pytest.raises(ob.ConflictoDeVersion, match="Recárgala"):
        ob.transicionar(d.t, d.gestor, d.v, "en_revision", version=v0)
    assert _fase(d) == "en_preparacion"
    ob.transicionar(d.t, d.gestor, d.v, "en_revision", version=v0 + 1)


def test_el_auditor_y_quien_no_ve_el_cliente_no_pueden_cambiar_nada(d):
    with pytest.raises(ValueError, match="solo puedes consultar"):
        ob.transicionar(d.t, d.aud, d.v, "en_preparacion")
    oficina = acceso.crear_oficina(d.t, d.sup, "Girona"); otra = acceso.crear_oficina(d.t, d.sup, "Barcelona")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.c, otra)
    acceso.dar_membresia(d.t, d.sup, d.gestor, "gestor", "oficina", oficina)
    with pytest.raises(ValueError, match="No existe esa obligación"):
        ob.transicionar(d.t, d.gestor, d.v, "en_preparacion")
    assert ob.transicionar(d.t, d.rev, d.v, "en_preparacion")["fase"] == "en_preparacion"


def test_los_botones_de_la_ficha_dependen_del_rol_y_del_flujo(d):
    v = db.obtener_vencimiento_fiscal(d.t, d.v)
    assert ob.destinos_permitidos(d.t, d.gestor, v) == ["en_preparacion", "presentada"]
    assert ob.destinos_permitidos(d.t, d.rev, v) == ["en_preparacion", "presentada", "no_aplica", "anulada"]
    assert ob.destinos_permitidos(d.t, d.aud, v) == []
    ob.guardar_config(d.t, d.sup, flujo_estricto=True, exigir_justificante=False)
    assert ob.destinos_permitidos(d.t, d.gestor, v) == ["en_preparacion"]
    assert ob.destinos_permitidos(d.t, d.rev, v) == ["en_preparacion", "no_aplica", "anulada"]


def test_solo_la_direccion_cambia_el_flujo(d):
    with pytest.raises(ValueError, match="Solo la dirección"):
        ob.guardar_config(d.t, d.gestor, flujo_estricto=True, exigir_justificante=False)
    ob.guardar_config(d.t, d.sup, flujo_estricto=True, exigir_justificante=True)
    assert ob.config(d.t) == {"flujo_estricto": True, "exigir_justificante": True}
    assert ob.config(db.crear_tenant("Otro despacho")) == {"flujo_estricto": False, "exigir_justificante": False}


# --- Pantallas y API ---------------------------------------------------------------------------------------------------------------------------
from tests.conftest import iniciar_sesion_de_prueba  # noqa: E402
from tests.test_rutas_api import _auth, _registrar  # noqa: E402


def _web(cliente, email, supervisor=True):
    t = db.crear_tenant("Despacho Web Flujo " + email)
    u = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.asignar_tenant(u, t)
    if supervisor:
        db.asignar_supervisor_tenant(u, True)
    c = db.crear_cliente_fiscal(t, "Cliente Web SL", nif="B12345674")
    v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", (date.today() + timedelta(days=30)).isoformat(), usuario_id=u)
    return t, u, c, v


def test_la_ficha_muestra_el_flujo_y_permite_cambiar_de_fase(cliente):
    t, u, c, v = _web(cliente, "flujo-web@ejemplo.com")
    ficha = cliente.get(f"/fiscal/vencimientos/{v}/editar").get_data(as_text=True)
    assert "Flujo de trabajo" in ficha and "Flujo flexible" in ficha and 'name="version"' in ficha
    r = cliente.post(f"/fiscal/vencimientos/{v}/transicion", data={"destino": "en_preparacion", "version": 1})
    assert "aviso=fase" in r.headers["Location"] and _fase_de(t, v) == "en_preparacion"
    r = cliente.post(f"/fiscal/vencimientos/{v}/transicion", data={"destino": "en_revision", "version": 1})
    assert "error=" in r.headers["Location"] and _fase_de(t, v) == "en_preparacion", "versión vieja: conflicto"
    r = cliente.post(f"/fiscal/vencimientos/{v}/transicion", data={"destino": "presentada", "version": 2, "referencia": "CSV9", "presentado_en": (date.today() - timedelta(days=1)).isoformat() + "T09:30"})
    assert _fase_de(t, v) == "presentada" and ob.evidencias(t, v)[0]["referencia"] == "CSV9"
    assert "Presentación declarada por" in cliente.get(f"/fiscal/vencimientos/{v}/editar").get_data(as_text=True) or "presentación declarada por" in cliente.get(f"/fiscal/vencimientos/{v}/editar").get_data(as_text=True)
    assert cliente.post(f"/fiscal/vencimientos/{v}/bloqueo", data={"motivo": "x"}).headers["Location"].find("error=") != -1, "una presentada no se bloquea"


def _fase_de(t, v):
    return db.obtener_vencimiento_fiscal(t, v)["fase"]


def test_el_boton_de_presentar_respeta_el_flujo_estricto_en_la_web(cliente):
    t, u, c, v = _web(cliente, "flujo-web-estricto@ejemplo.com")
    ob.guardar_config(t, u, flujo_estricto=True, exigir_justificante=False)
    r = cliente.post(f"/fiscal/vencimientos/{v}/presentado")
    assert "error=" in r.headers["Location"] and _fase_de(t, v) == "pendiente"
    r = cliente.post(f"/fiscal/vencimientos/{v}/editar", data={"modelo": "303", "periodo": "2026-T3", "fecha_limite": (date.today() + timedelta(days=30)).isoformat(), "estado": "presentado"})
    assert "error=" in r.headers["Location"] and _fase_de(t, v) == "pendiente", "tampoco por el formulario de edición"
    r = cliente.post(f"/fiscal/vencimientos/{v}/editar", data={"modelo": "303", "periodo": "2026-T3", "fecha_limite": (date.today() + timedelta(days=30)).isoformat(), "estado": "pendiente", "version": 99})
    assert "error=" in r.headers["Location"], "una versión vieja del formulario se rechaza"


def test_pantalla_de_flujo_solo_para_la_direccion_y_guarda(cliente):
    t, u, c, v = _web(cliente, "flujo-web-cfg@ejemplo.com")
    assert cliente.get("/fiscal/flujo").status_code == 200
    cliente.post("/fiscal/flujo", data={"flujo_estricto": "on"})
    assert ob.config(t) == {"flujo_estricto": True, "exigir_justificante": False}


def test_la_direccion_gestiona_oficinas_y_ve_la_auditoria_por_la_web(cliente):
    t, u, c, v = _web(cliente, "flujo-web-of@ejemplo.com")
    assert cliente.get("/fiscal/oficinas").status_code == 200
    cliente.post("/fiscal/oficinas", data={"nombre": "Girona"})
    of = acceso.listar_oficinas(t)[0]["id"]
    cliente.post("/fiscal/oficinas/cliente", data={"cliente_id": c, "oficina_id": of})
    assert db.obtener_cliente_fiscal(t, c)["oficina_id"] == of
    pagina = cliente.get("/fiscal/oficinas").get_data(as_text=True)
    assert "Girona" in pagina and "Cliente Web SL" in pagina
    r = cliente.get("/fiscal/auditoria?entidad=oficina").get_data(as_text=True)
    assert "oficina.crear" in r and "flujo-web-of@ejemplo.com" in r
    assert "error=" in cliente.post(f"/fiscal/oficinas/{of}/archivar").headers["Location"], "con clientes no se archiva"


def test_quien_no_es_direccion_no_entra_a_oficinas_ni_flujo_ni_auditoria(cliente):
    t, u, c, v = _web(cliente, "flujo-web-nadie@ejemplo.com", supervisor=False)
    for ruta in ("/fiscal/oficinas", "/fiscal/flujo", "/fiscal/auditoria"):
        assert cliente.get(ruta).status_code == 403, ruta
    assert cliente.post("/fiscal/oficinas", data={"nombre": "Colada"}).status_code in (302, 403) and acceso.listar_oficinas(t) == []


def test_api_flujo_transiciones_bloqueo_y_version(cliente):
    t = db.crear_tenant("Despacho API Flujo")
    datos = _registrar(cliente, "api-flujo@ejemplo.com"); u = db.obtener_usuario_por_email("api-flujo@ejemplo.com")["id"]
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True); h = _auth(datos["token"])
    c = db.crear_cliente_fiscal(t, "Cliente API SL"); v = db.crear_vencimiento_fiscal(t, c, "303", "2026-T3", (date.today() + timedelta(days=30)).isoformat())
    f = cliente.get(f"/api/v1/fiscal/vencimientos/{v}/flujo", headers=h).get_json()["data"]
    assert f["fase"] == "pendiente" and f["version"] == 1 and "en_preparacion" in f["destinos"] and f["indicadores"]["vencida"] is False
    r = cliente.post(f"/api/v1/fiscal/vencimientos/{v}/transiciones", headers=h, json={"destino": "en_preparacion", "version": 1})
    assert r.status_code == 200 and r.get_json()["data"]["version"] == 2
    r = cliente.post(f"/api/v1/fiscal/vencimientos/{v}/transiciones", headers={**h, "If-Match": '"1"'}, json={"destino": "en_revision"})
    assert r.status_code == 412 and r.get_json()["codigo"] == "version_obsoleta"
    assert cliente.post(f"/api/v1/fiscal/vencimientos/{v}/transiciones", headers={**h, "If-Match": '"2"'}, json={"destino": "en_revision"}).status_code == 200
    assert cliente.post(f"/api/v1/fiscal/vencimientos/{v}/transiciones", headers=h, json={"destino": "no_aplica"}).get_json()["codigo"] == "transicion_invalida"
    r = cliente.put(f"/api/v1/fiscal/vencimientos/{v}/bloqueo", headers=h, json={"bloqueada": True, "motivo": "Esperando al banco"})
    assert r.get_json()["data"]["indicadores"]["bloqueada"] is True
    assert cliente.put(f"/api/v1/fiscal/flujo", headers=h, json={"flujo_estricto": True}).get_json()["data"]["flujo_estricto"] is True
    r = cliente.post(f"/api/v1/fiscal/vencimientos/{v}/presentado", headers=h)
    assert r.status_code == 409 and r.get_json()["codigo"] == "flujo_fiscal"
    r = cliente.put(f"/api/v1/fiscal/vencimientos/{v}", headers={**h, "If-Match": '"1"'}, json={"notas": "x"})
    assert r.status_code == 412
    r = cliente.put(f"/api/v1/fiscal/vencimientos/{v}", headers=h, json={"estado": "presentado"})
    assert r.status_code == 409, "tampoco editando el estado a mano"
    eventos = cliente.get("/api/v1/fiscal/auditoria?entidad=obligacion", headers=h).get_json()["data"]
    assert [e["accion"] for e in eventos][:2] == ["obligacion.bloqueo", "obligacion.transicion"]


def test_api_oficinas_roles_y_concesiones(cliente):
    t = db.crear_tenant("Despacho API Oficinas")
    datos = _registrar(cliente, "api-of@ejemplo.com"); u = db.obtener_usuario_por_email("api-of@ejemplo.com")["id"]
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True); h = _auth(datos["token"])
    otro = db.crear_usuario_vinculado_a_kratos("api-of-otro@ejemplo.com", "k-api-of-otro"); db.asignar_tenant(otro, t)
    c = db.crear_cliente_fiscal(t, "Cliente API SL", nif="B12345674")
    oid = cliente.post("/api/v1/fiscal/oficinas", headers=h, json={"nombre": "Girona"}).get_json()["data"]["id"]
    assert [o["nombre"] for o in cliente.get("/api/v1/fiscal/oficinas", headers=h).get_json()["data"]] == ["Girona"]
    assert cliente.put(f"/api/v1/fiscal/clientes/{c}/oficina", headers=h, json={"oficina_id": oid}).get_json()["data"]["oficina_id"] == oid
    mid = cliente.post("/api/v1/fiscal/membresias", headers=h, json={"usuario_id": otro, "rol": "gestor", "alcance": "oficina", "alcance_id": oid}).get_json()["data"]["id"]
    assert [m["rol"] for m in cliente.get("/api/v1/fiscal/membresias", headers=h).get_json()["data"]] == ["gestor"]
    k = cliente.post(f"/api/v1/fiscal/clientes/{c}/concesiones", headers=h, json={"usuario_id": u, "nivel": "lectura"}).get_json()
    assert k["data"]["id"] and cliente.get(f"/api/v1/fiscal/clientes/{c}/concesiones", headers=h).get_json()["data"][0]["nivel"] == "lectura"
    assert cliente.delete(f"/api/v1/fiscal/concesiones/{k['data']['id']}", headers=h).get_json()["data"]["revocada"] is True
    assert cliente.delete(f"/api/v1/fiscal/membresias/{mid}", headers=h).status_code == 200
    assert cliente.post("/api/v1/fiscal/membresias", headers=h, json={"usuario_id": otro, "rol": "dios", "alcance": "oficina", "alcance_id": oid}).get_json()["codigo"] == "membresia_invalida"
    assert cliente.post("/api/v1/fiscal/oficinas", headers=h, json={"nombre": "Girona"}).get_json()["codigo"] == "oficina_invalida"
    # una persona sin rol no administra ni audita
    d2 = _registrar(cliente, "api-of-nadie@ejemplo.com"); n = db.obtener_usuario_por_email("api-of-nadie@ejemplo.com")["id"]; db.asignar_tenant(n, t); h2 = _auth(d2["token"])
    assert cliente.post("/api/v1/fiscal/oficinas", headers=h2, json={"nombre": "Colada"}).status_code == 403
    assert cliente.get("/api/v1/fiscal/membresias", headers=h2).status_code == 403 and cliente.get("/api/v1/fiscal/auditoria", headers=h2).status_code == 403
    assert cliente.put("/api/v1/fiscal/flujo", headers=h2, json={"flujo_estricto": True}).status_code == 403
