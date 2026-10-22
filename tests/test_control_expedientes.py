"""Expedientes unificados del control fiscal (app/control_expedientes.py, RF-13): tipos y estados, lista de comprobación, cierre con controles y excepción autorizada,
documentos versionados y conservación, comentarios sin secretos con menciones, enlace con obligaciones y certificados, alcance por oficinas, pantallas, API e IA."""
from datetime import date, timedelta

import pytest

from app import acceso, almacen_documentos, control_expedientes as ce, db, nucleo, verticales
from tests.conftest import iniciar_sesion_de_prueba


@pytest.fixture
def d(usuario_id):
    t = db.crear_tenant("Despacho Expedientes")
    class E: pass
    e = E(); e.t = t
    def u(mail, sup=False, nombre=None):
        x = db.crear_usuario_vinculado_a_kratos(mail, "k-" + mail); db.asignar_tenant(x, t)
        if sup:
            db.asignar_supervisor_tenant(x, True)
        return x
    e.sup, e.ana, e.biel, e.rev = u("sup-ex@ejemplo.com", True), u("ana-ex@ejemplo.com"), u("biel-ex@ejemplo.com"), u("rev-ex@ejemplo.com")
    e.cf = db.crear_cliente_fiscal(t, "Cliente Exp SL", nif="B12345674")
    e.cli = nucleo.vincular_cliente_fiscal(t, e.cf)
    e.v = db.crear_vencimiento_fiscal(t, e.cf, "303", "2026-T3", (date.today() + timedelta(days=9)).isoformat())
    return e


def _nuevo(d, tipo="control_obligacion", **kw):
    return ce.crear(d.t, d.sup, d.cli, tipo, "Expediente de prueba", responsable_id=d.ana, **kw)


def test_los_tipos_y_estados_de_rf13_estan_disponibles_en_la_gestoria(d):
    tipos = verticales.tipos_expediente(d.t)
    for i in ("control_campana", "control_obligacion", "control_renovacion", "control_requerimiento", "control_incidencia"):
        assert i in tipos
    assert [e.id for e in tipos["control_obligacion"].estados] == ["abierto", "en_curso", "pendiente_cliente", "pendiente_tercero", "en_revision", "resuelto", "cerrado"]
    assert tipos["control_obligacion"].estados[-1].cerrado and not tipos["control_obligacion"].estados[5].cerrado


def test_crear_trae_datos_de_control_y_lista_de_partida(d):
    x = _nuevo(d, prioridad="alta", fecha_objetivo="2026-12-01", revisor_id=d.rev)
    det = ce.detalle(d.t, d.sup, x)
    assert det["estado"] == "abierto" and det["control"]["prioridad"] == "alta" and det["control"]["revisor_id"] == d.rev and det["control"]["fecha_objetivo"] == "2026-12-01"
    assert len(det["lista"]) == 4 and all(p["obligatorio"] for p in det["lista"]) and det["faltan_obligatorios"] == 4
    with pytest.raises(ValueError, match="Prioridad"):
        _nuevo(d, prioridad="máxima")
    with pytest.raises(ValueError, match="AAAA-MM-DD"):
        _nuevo(d, fecha_objetivo="mañana")
    with pytest.raises(ValueError, match="no pertenece"):
        _nuevo(d, revisor_id=99999)
    with pytest.raises(ValueError, match="no existe"):
        ce.crear(d.t, d.sup, d.cli, "control_rara", "x")


def test_cerrar_exige_completar_los_obligatorios(d):
    x = _nuevo(d)
    with pytest.raises(ValueError, match="faltan 4 puntos obligatorios"):
        nucleo.cambiar_estado_expediente(d.t, d.sup, x, "cerrado", True)
    for p in ce.listar_lista(x):
        ce.marcar_punto(d.t, d.ana, p["id"], True, "ok")
    nucleo.cambiar_estado_expediente(d.t, d.ana, x, "cerrado", False)
    assert ce.detalle(d.t, d.sup, x)["estado"] == "cerrado" and ce.detalle(d.t, d.sup, x)["cerrado_en"]


def test_excepcion_autorizada_solo_direccion_o_revisor_fiscal(d):
    acceso.dar_membresia(d.t, d.sup, d.rev, "revisor_fiscal", "organizacion")
    x = _nuevo(d)
    with pytest.raises(ValueError, match="Solo la dirección o un revisor fiscal puede autorizar"):
        nucleo.cambiar_estado_expediente(d.t, d.biel, x, "cerrado", False, excepcion="Urgente")
    nucleo.cambiar_estado_expediente(d.t, d.rev, x, "cerrado", False, excepcion="El cliente ya no es cliente")
    c = ce.datos_de(x)
    assert c["excepcion_motivo"] == "El cliente ya no es cliente" and c["excepcion_por"] == d.rev
    with pytest.raises(ValueError, match="Solo la dirección o un revisor fiscal puede reabrir"):
        nucleo.cambiar_estado_expediente(d.t, d.biel, x, "en_curso", False)
    nucleo.cambiar_estado_expediente(d.t, d.sup, x, "en_curso", True)
    assert ce.detalle(d.t, d.sup, x)["cerrado_en"] is None


def test_pendiente_de_tercero_y_resuelto_no_exigen_controles_ni_pausan_la_fecha(d):
    x = _nuevo(d, fecha_objetivo=(date.today() - timedelta(days=1)).isoformat())
    nucleo.cambiar_estado_expediente(d.t, d.ana, x, "pendiente_tercero", False)
    nucleo.cambiar_estado_expediente(d.t, d.ana, x, "resuelto", False)
    assert ce.detalle(d.t, d.sup, x)["control"]["fecha_objetivo"] == (date.today() - timedelta(days=1)).isoformat()
    assert [a["id"] for a in ce.vencidos_abiertos(d.t)] == [], "resuelto ya no cuenta como abierto"
    y = _nuevo(d, fecha_objetivo=(date.today() - timedelta(days=1)).isoformat())
    nucleo.cambiar_estado_expediente(d.t, d.ana, y, "pendiente_cliente", False)
    assert [a["id"] for a in ce.vencidos_abiertos(d.t)] == [y], "esperar al cliente no pausa el plazo"


def test_lista_de_comprobacion_anadir_asignar_y_quitar(d):
    x = _nuevo(d)
    pid = ce.anadir_punto(d.t, d.ana, x, "Llamar al cliente", obligatorio=False, asignado_id=d.biel, fecha_limite="2026-11-01")
    p = next(p for p in ce.listar_lista(x) if p["id"] == pid)
    assert p["asignado_id"] == d.biel and not p["obligatorio"] and p["fecha_limite"] == "2026-11-01"
    with pytest.raises(ValueError, match="secreto"):
        ce.anadir_punto(d.t, d.ana, x, "Entrar con contraseña: hunter2")
    with pytest.raises(ValueError, match="Escribe el punto"):
        ce.anadir_punto(d.t, d.ana, x, "  ")
    ce.eliminar_punto(d.t, d.ana, pid)
    obligatorio = ce.listar_lista(x)[0]["id"]
    with pytest.raises(ValueError, match="Solo la dirección o un revisor fiscal puede quitar"):
        ce.eliminar_punto(d.t, d.ana, obligatorio)
    ce.eliminar_punto(d.t, d.sup, obligatorio)


def test_comentarios_sin_secretos(d):
    x = _nuevo(d)
    for malo in ("la contraseña: Abc12345 del portal", "password=hunter22", "-----BEGIN PRIVATE KEY----- MIIE", "api_key: sk_live_1234567890", "token: abcdefghijkl",
                 "tarjeta 4111 1111 1111 1111 caduca 12/28", "dato aGVsbG8gd29ybGQgdGhpcyBpcyBhIHZlcnkgbG9uZyBiYXNlNjQgc3RyaW5n"):
        with pytest.raises(ValueError, match="no pueden llevar secretos"):
            nucleo.anotar_expediente(d.t, d.ana, x, malo, False)
    nucleo.anotar_expediente(d.t, d.ana, x, "La contraseña del portal está en el gestor de contraseñas, entrada «AEAT». IBAN ES9121000418450200051332.", False)
    assert any("gestor de contraseñas" in e["texto"] for e in nucleo.linea_de_tiempo(d.t, d.sup, x, True))
    assert ce.contiene_secreto("El 303 se presenta el día 20") is None


def test_menciones_solo_avisan_a_quien_puede_ver_el_expediente(d):
    gi = acceso.crear_oficina(d.t, d.sup, "Girona")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.cf, gi)
    acceso.dar_membresia(d.t, d.sup, d.ana, "gestor", "oficina", gi)
    x = _nuevo(d)
    r = nucleo.anotar_expediente(d.t, d.sup, x, "Mirad esto @ana-ex y @biel-ex y @nadie", True)
    assert r["avisadas"] == ["ana-ex"] and r["sin_acceso"] == ["biel-ex"] and r["no_encontradas"] == ["nadie"]
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM notificaciones WHERE usuario_id = ? AND tipo = 'mencion'", (d.ana,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM notificaciones WHERE usuario_id = ? AND tipo = 'mencion'", (d.biel,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_documentos_versionados_y_conservacion(d):
    x = _nuevo(d)
    r, doc = almacen_documentos.guardar(d.ana, "modelo303.pdf", "application/pdf", b"%PDF borrador uno", expediente_id=x, categoria="modelo")
    assert r == "ok"
    v2 = ce.subir_version(d.t, d.ana, doc, "modelo303.pdf", "application/pdf", b"%PDF version dos")
    docs = ce.documentos(d.t, d.sup, x)
    assert len(docs) == 1 and docs[0]["id"] == v2 and docs[0]["version"] == 2 and docs[0]["versiones"][0]["id"] == doc and docs[0]["categoria"] == "modelo" and len(docs[0]["hash_sha256"]) == 64
    with pytest.raises(ValueError, match="Ya hay una versión más reciente"):
        ce.subir_version(d.t, d.ana, doc, "x.pdf", "application/pdf", b"otra cosa")
    with pytest.raises(ValueError, match="idéntico"):
        ce.subir_version(d.t, d.ana, v2, "modelo303.pdf", "application/pdf", b"%PDF version dos")
    with pytest.raises(ValueError, match="clave privada"):
        ce.subir_version(d.t, d.ana, v2, "k.pem", "text/plain", b"-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----")
    ce.fijar_conservacion(d.t, d.sup, v2, (date.today() + timedelta(days=365)).isoformat())
    assert almacen_documentos.eliminar(d.t, d.sup, v2) is False, "conservar hasta: no va a la papelera antes de tiempo"
    ce.fijar_conservacion(d.t, d.sup, v2, None)
    assert almacen_documentos.eliminar(d.t, d.sup, v2) is True


def test_abrir_desde_obligacion_y_certificado_sin_duplicar(d):
    from app import certificados
    a = ce.abrir_desde_obligacion(d.t, d.sup, d.v)
    assert a["nuevo"] is True
    det = ce.detalle(d.t, d.sup, a["id"])
    assert det["tipo"] == "control_obligacion" and det["control"]["vinculo_tipo"] == "obligacion" and det["control"]["fecha_objetivo"] == (date.today() + timedelta(days=9)).isoformat() and "303" in det["titulo"]
    assert ce.abrir_desde_obligacion(d.t, d.sup, d.v) == {"id": a["id"], "nuevo": False}
    for p in ce.listar_lista(a["id"]):
        ce.marcar_punto(d.t, d.sup, p["id"])
    nucleo.cambiar_estado_expediente(d.t, d.sup, a["id"], "cerrado", True)
    assert ce.abrir_desde_obligacion(d.t, d.sup, d.v)["nuevo"] is True, "cerrado el anterior, se puede abrir otro"
    with pytest.raises(ValueError, match="No existe esa obligación"):
        ce.abrir_desde_obligacion(d.t, d.sup, 99999)
    cid = certificados.alta_rapida(d.t, d.sup, tipo="fnmt_persona_fisica", caduca=(date.today() + timedelta(days=40)).isoformat(), cliente_fiscal_id=d.cf)["id"]
    r = ce.abrir_desde_certificado(d.t, d.sup, cid)
    assert r["nuevo"] and ce.detalle(d.t, d.sup, r["id"])["tipo"] == "control_renovacion" and ce.abrir_desde_certificado(d.t, d.sup, cid)["nuevo"] is False
    sin_cliente = certificados.alta_rapida(d.t, d.sup, tipo="otro", caduca="2030-01-01", titular="Despacho")["id"]
    with pytest.raises(ValueError, match="Asocia primero"):
        ce.abrir_desde_certificado(d.t, d.sup, sin_cliente)
    with pytest.raises(ValueError, match="Solo los custodios"):
        ce.abrir_desde_certificado(d.t, d.biel, cid)


def test_el_alcance_por_oficinas_y_el_auditor_solo_lectura(d):
    gi, bc = acceso.crear_oficina(d.t, d.sup, "Girona"), acceso.crear_oficina(d.t, d.sup, "Barcelona")
    acceso.asignar_cliente_a_oficina(d.t, d.sup, d.cf, gi)
    acceso.dar_membresia(d.t, d.sup, d.ana, "gestor", "oficina", gi); acceso.dar_membresia(d.t, d.sup, d.biel, "gestor", "oficina", bc)
    aud = db.crear_usuario_vinculado_a_kratos("aud-ex@ejemplo.com", "k-aud-ex"); db.asignar_tenant(aud, d.t)
    acceso.dar_membresia(d.t, d.sup, aud, "auditor", "organizacion")
    x = _nuevo(d)
    assert [e["id"] for e in ce.listar(d.t, d.ana)] == [x] and ce.listar(d.t, d.biel) == []
    with pytest.raises(ValueError, match="Expediente no encontrado"):
        ce.detalle(d.t, d.biel, x)
    assert ce.detalle(d.t, aud, x)["id"] == x
    for f in (lambda: ce.anadir_punto(d.t, aud, x, "Algo"), lambda: ce.marcar_punto(d.t, aud, ce.listar_lista(x)[0]["id"]), lambda: ce.editar_control(d.t, aud, x, prioridad="alta"),
              lambda: nucleo.cambiar_estado_expediente(d.t, aud, x, "en_curso", False), lambda: nucleo.anotar_expediente(d.t, aud, x, "hola", False)):
        with pytest.raises(ValueError, match="solo puedes consultar"):
            f()


def test_editar_control_y_validaciones(d):
    x = _nuevo(d)
    c = ce.editar_control(d.t, d.ana, x, prioridad="urgente", fecha_objetivo="2026-11-30", revisor_id=d.rev)
    assert c["prioridad"] == "urgente" and c["revisor_id"] == d.rev
    with pytest.raises(ValueError, match="distintas"):
        ce.editar_control(d.t, d.ana, x, revisor_id=d.ana)
    with pytest.raises(ValueError, match="Prioridad"):
        ce.editar_control(d.t, d.ana, x, prioridad="meh")
    assert ce.editar_control(d.t, d.ana, x, fecha_objetivo="")["fecha_objetivo"] is None


def test_un_expediente_de_otro_tipo_no_se_gestiona_con_este_modulo(d):
    general = nucleo.crear_expediente(d.t, d.sup, d.cli, "Asunto general")
    with pytest.raises(ValueError, match="Expediente no encontrado"):
        ce.anadir_punto(d.t, d.sup, general, "No debería")
    assert all(e["id"] != general for e in ce.listar(d.t, d.sup))


def test_listar_resume_el_avance_y_ordena_por_prioridad(d):
    a, b = _nuevo(d, prioridad="baja"), _nuevo(d, prioridad="urgente", fecha_objetivo="2026-11-01")
    ce.marcar_punto(d.t, d.sup, ce.listar_lista(b)[0]["id"])
    lista = ce.listar(d.t, d.sup)
    assert [x["id"] for x in lista] == [b, a] and lista[0]["puntos"] == 4 and lista[0]["puntos_hechos"] == 1 and lista[0]["obligatorios_pendientes"] == 3
    assert ce.sin_evidencia(d.t) == {"n": 0, "sin": 0}


def test_borrar_el_despacho_borra_los_expedientes_de_control(d):
    _nuevo(d)
    otro = db.crear_tenant("Despacho a borrar exp")
    cf = db.crear_cliente_fiscal(otro, "Cliente borrar", nif="J21938519")
    u = db.crear_usuario_vinculado_a_kratos("borra-ex@ejemplo.com", "k-borra-ex"); db.asignar_tenant(u, otro)
    ce.crear(otro, u, nucleo.vincular_cliente_fiscal(otro, cf), "control_incidencia", "Algo pasó")
    db.borrar_tenant(otro, confirmar_fichajes=True) if "confirmar_fichajes" in db.borrar_tenant.__code__.co_varnames else db.borrar_tenant(otro)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM expediente_control c JOIN expedientes x ON x.id = c.expediente_id WHERE x.tenant_id = ?", (otro,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_un_expediente_pasado_de_fecha_genera_aviso_y_se_cierra_al_resolverlo(d):
    from app import avisos
    avisos.guardar_config(d.t, d.sup, activo=True, dias_antes=[7], escalar_horas_urgente=24, escalar_horas_atencion=72, reenviar_horas=24, max_reenvios=2)
    x = _nuevo(d, prioridad="alta", fecha_objetivo=(date.today() - timedelta(days=4)).isoformat())
    avisos.evaluar(d.t)
    a = next(a for a in avisos.listar(d.t, d.sup, estado=None) if a["objeto_tipo"] == "expediente")
    assert a["objeto_id"] == x and a["severidad"] == "urgente" and a["destinatario_id"] == d.ana and a["url"] == f"/expedientes/{x}" and "hace 4 días" in a["detalle"]
    nucleo.cambiar_estado_expediente(d.t, d.ana, x, "resuelto", False)
    avisos.evaluar(d.t)
    assert avisos.obtener(d.t, a["id"])["estado"] == "resuelta"


def test_el_panel_cuenta_los_expedientes_sin_ningun_documento(d):
    from app import panel_fiscal
    x = _nuevo(d)
    nucleo.cambiar_estado_expediente(d.t, d.ana, x, "resuelto", False)
    assert panel_fiscal.construir(d.t, d.sup)["indicadores"]["expedientes"] == {"n": 1, "sin": 1}
    almacen_documentos.guardar(d.ana, "justificante.pdf", "application/pdf", b"%PDF justificante", expediente_id=x)
    assert panel_fiscal.construir(d.t, d.sup)["indicadores"]["expedientes"] == {"n": 1, "sin": 0}


# --- Pantallas, API e IA ----------------------------------------------------------------------------------------------------------------------
def test_pantallas_del_expediente_de_control(cliente):
    t = db.crear_tenant("Despacho Web Expedientes")
    u = iniciar_sesion_de_prueba(cliente, "web-ex@ejemplo.com", "contrasena123")
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    cf = db.crear_cliente_fiscal(t, "Cliente Web Exp", nif="B12345674")
    vid = db.crear_vencimiento_fiscal(t, cf, "303", "2026-T3", (date.today() + timedelta(days=5)).isoformat())
    r = cliente.post(f"/fiscal/expedientes/obligacion/{vid}/abrir")
    assert r.status_code == 302 and "/expedientes/" in r.headers["Location"]
    ficha = cliente.get(r.headers["Location"]).get_data(as_text=True)
    assert "Control del expediente" in ficha and "Lista de comprobación" in ficha and "Documentación recibida del cliente" in ficha and "no pausa el plazo legal" in ficha
    xid = int(r.headers["Location"].split("/expedientes/")[1].split("?")[0])
    assert cliente.post(f"/fiscal/expedientes/obligacion/{vid}/abrir").headers["Location"].endswith(f"/expedientes/{xid}")
    r = cliente.post(f"/expedientes/{xid}/estado", data={"estado": "cerrado"})
    assert "faltan+4+puntos+obligatorios" in r.headers["Location"] or "faltan%204" in r.headers["Location"] or "error=" in r.headers["Location"]
    assert "Cerrar con excepción" in cliente.get(f"/expedientes/{xid}").get_data(as_text=True)
    r = cliente.post(f"/expedientes/{xid}/nota", data={"texto": "la contraseña: Secreto99 del portal"})
    assert "error=" in r.headers["Location"] and "secretos" in cliente.get(r.headers["Location"]).get_data(as_text=True)
    p = ce.listar_lista(xid)[0]
    cliente.post(f"/fiscal/expedientes/lista/{p['id']}/hecho", data={"nota": "Recibida"})
    assert ce.listar_lista(xid)[0]["hecho_en"]
    cliente.post(f"/fiscal/expedientes/{xid}/lista", data={"texto": "Avisar al cliente", "obligatorio": "1"})
    assert any(x["texto"] == "Avisar al cliente" and x["obligatorio"] for x in ce.listar_lista(xid))
    cliente.post(f"/fiscal/expedientes/{xid}/control", data={"prioridad": "urgente", "fecha_objetivo": "2026-12-01"})
    assert ce.datos_de(xid)["prioridad"] == "urgente"
    r = cliente.post(f"/expedientes/{xid}/estado", data={"estado": "cerrado", "excepcion": "El cliente cierra la actividad"})
    assert "error" not in r.headers["Location"] and ce.detalle(t, u, xid)["estado"] == "cerrado"
    lista = cliente.get("/fiscal/expedientes?todos=1").get_data(as_text=True)
    assert "Expedientes de control" in lista and "303 2026-T3" in lista
    assert cliente.post("/fiscal/expedientes/nuevo", data={"cliente_id": nucleo.vincular_cliente_fiscal(t, cf), "tipo": "control_incidencia", "titulo": "Caída del portal"}).status_code == 302
    assert any(x["titulo"] == "Caída del portal" for x in ce.listar(t, u))


def test_api_de_expedientes_de_control(cliente):
    from tests.test_rutas_api import _auth, _registrar
    t = db.crear_tenant("Despacho API Expedientes")
    datos = _registrar(cliente, "api-ex@ejemplo.com"); u = db.obtener_usuario_por_email("api-ex@ejemplo.com")["id"]
    db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    h = _auth(datos["token"])
    cf = db.crear_cliente_fiscal(t, "Cliente API Exp", nif="B12345674")
    vid = db.crear_vencimiento_fiscal(t, cf, "303", "2026-T3", (date.today() + timedelta(days=5)).isoformat())
    r = cliente.post("/api/v1/fiscal/expedientes", headers=h, json={"cliente_fiscal_id": cf, "tipo": "control_requerimiento", "titulo": "Requerimiento IVA", "prioridad": "alta", "fecha_objetivo": "2026-12-01"})
    assert r.status_code == 201 and r.get_json()["data"]["faltan_obligatorios"] == 4
    xid = r.get_json()["data"]["id"]
    assert cliente.post("/api/v1/fiscal/expedientes", headers=h, json={"cliente_fiscal_id": cf, "tipo": "raro", "titulo": "x"}).status_code == 400
    assert cliente.post("/api/v1/fiscal/expedientes", headers=h, json={"cliente_fiscal_id": 9999, "tipo": "control_incidencia", "titulo": "x"}).status_code == 404
    ob = cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/expediente", headers=h)
    assert ob.status_code == 201 and cliente.post(f"/api/v1/fiscal/vencimientos/{vid}/expediente", headers=h).status_code == 200
    lista = cliente.get("/api/v1/fiscal/expedientes", headers=h).get_json()["data"]
    assert {x["id"] for x in lista} >= {xid} and lista[0]["prioridad"] in ("alta", "normal")
    assert cliente.get("/api/v1/fiscal/expedientes?tipo=raro", headers=h).status_code == 400
    assert cliente.put(f"/api/v1/fiscal/expedientes/{xid}", headers=h, json={"prioridad": "urgente", "fecha_objetivo": None}).get_json()["data"]["control"]["prioridad"] == "urgente"
    assert cliente.put(f"/api/v1/fiscal/expedientes/{xid}", headers=h, json={"prioridad": "meh"}).status_code == 400
    r = cliente.post(f"/api/v1/fiscal/expedientes/{xid}/estado", headers=h, json={"estado": "cerrado"})
    assert r.status_code == 400 and "puntos obligatorios" in r.get_json()["error"]
    punto = cliente.post(f"/api/v1/fiscal/expedientes/{xid}/lista", headers=h, json={"texto": "Extra", "obligatorio": False})
    assert punto.status_code == 201
    pid = ce.listar_lista(xid)[0]["id"]
    assert cliente.post(f"/api/v1/fiscal/expedientes/lista/{pid}/hecho", headers=h, json={"nota": "ok"}).get_json()["data"]["hecho"] is True
    assert cliente.post(f"/api/v1/fiscal/expedientes/{xid}/comentarios", headers=h, json={"texto": "password: Hunter2022"}).status_code == 400
    assert cliente.post(f"/api/v1/fiscal/expedientes/{xid}/comentarios", headers=h, json={"texto": "Pendiente del cliente @nadie"}).get_json()["data"]["no_encontradas"] == ["nadie"]
    r = cliente.post(f"/api/v1/fiscal/expedientes/{xid}/estado", headers=h, json={"estado": "cerrado", "excepcion": "Archivado por la dirección"})
    assert r.status_code == 200 and r.get_json()["data"]["estado"] == "cerrado"
    assert cliente.get("/api/v1/fiscal/expedientes/99999", headers=h).status_code == 404
    det = cliente.get(f"/api/v1/fiscal/expedientes/{xid}", headers=h).get_json()["data"]
    assert det["control"]["excepcion_motivo"] == "Archivado por la dirección"


def test_herramientas_de_ia_de_expedientes_de_control(d):
    from app import ia_herramientas as ih
    for n in ("abrir_expediente_control", "marcar_punto_expediente", "cambiar_estado_expediente_control", "comentar_expediente_control"):
        assert n in ih.ESCRITURA
    assert "listar_expedientes_control" not in ih.ESCRITURA and "ver_expediente_control" not in ih.ESCRITURA
    r = ih.ejecutar(d.sup, "abrir_expediente_control", {"obligacion_id": d.v})
    assert r["nuevo"] and ih.ejecutar(d.sup, "abrir_expediente_control", {"obligacion_id": d.v})["nuevo"] is False
    ficha = ih.ejecutar(d.sup, "ver_expediente_control", {"expediente_id": r["id"]})
    assert ficha["faltan_obligatorios"] == 4 and len(ficha["lista"]) == 4
    assert [x["id"] for x in ih.ejecutar(d.sup, "listar_expedientes_control", {})] == [r["id"]]
    with pytest.raises(ih.ErrorHerramientaIA, match="faltan 4"):
        ih.ejecutar(d.sup, "cambiar_estado_expediente_control", {"expediente_id": r["id"], "estado": "cerrado"})
    assert ih.ejecutar(d.sup, "marcar_punto_expediente", {"punto_id": ficha["lista"][0]["id"]})["hecho"] is True
    assert ih.ejecutar(d.sup, "cambiar_estado_expediente_control", {"expediente_id": r["id"], "estado": "cerrado", "excepcion": "Ya no aplica"})["estado"] == "cerrado"
    nuevo = ih.ejecutar(d.sup, "abrir_expediente_control", {"cliente_fiscal_id": d.cf, "tipo": "control_incidencia", "titulo": "Caída"})
    with pytest.raises(ih.ErrorHerramientaIA, match="secretos"):
        ih.ejecutar(d.sup, "comentar_expediente_control", {"expediente_id": nuevo["id"], "texto": "token: abcdef123456"})
    assert ih.ejecutar(d.sup, "comentar_expediente_control", {"expediente_id": nuevo["id"], "texto": "Avisado @ana-ex"})["avisadas"] == ["ana-ex"]
