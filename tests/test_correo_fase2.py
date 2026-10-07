"""Fase 2 de correo: vínculo automático con el cliente fiscal por remitente,
adjuntos guardados en un vencimiento (internos por defecto), plantillas con
variables y endurecimiento del correo de equipo."""
from contextlib import contextmanager

from app import correo, db
from tests.conftest import iniciar_sesion_de_prueba


@contextmanager
def _otro_cliente(email):
    from app.auth import limiter
    from app.main import app as flask_app

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as otro:
        yield otro, iniciar_sesion_de_prueba(otro, email, "contrasena123")


def _montar(cliente, email, despacho=None):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    tenant = db.crear_tenant(despacho or "Gestoria " + email)
    db.asignar_tenant(uid, tenant)
    cuenta = db.crear_cuenta_correo(uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    return uid, tenant, cuenta


def _msg(cuenta, uid, remitente="a@b.com", asunto="Asunto", cuerpo="cuerpo"):
    return db.guardar_mensaje_correo(
        cuenta_id=cuenta, uid=uid, asunto=asunto, remitente=remitente, destinatarios="yo@ejemplo.com",
        fecha="2026-03-10T10:00:00", cuerpo_texto=cuerpo, cuerpo_html=None,
    )


# --- vínculo por remitente -----------------------------------------------------

def test_correo_nuevo_se_enlaza_con_el_cliente_por_email_del_remitente(cliente):
    uid, tenant, cuenta = _montar(cliente, "f2-auto@ejemplo.com")
    cid = db.crear_cliente_fiscal(tenant, "Panadería Sol", email="Sol@Panaderia.com")
    m = _msg(cuenta, "1", remitente="Ana Sol <sol@panaderia.com>")
    correo._aplicar_categoria_automatica(uid, m, "Ana Sol <sol@panaderia.com>", "Hola")
    assert db.obtener_mensaje_correo(m)["cliente_fiscal_id"] == cid
    otro = _msg(cuenta, "2", remitente="desconocido@x.com")
    correo._aplicar_categoria_automatica(uid, otro, "desconocido@x.com", "Hola")
    assert db.obtener_mensaje_correo(otro)["cliente_fiscal_id"] is None


def test_no_vincula_si_hay_dos_clientes_con_el_mismo_email_ni_de_otro_despacho(cliente):
    uid, tenant, cuenta = _montar(cliente, "f2-dup@ejemplo.com")
    db.crear_cliente_fiscal(tenant, "Uno", email="dup@x.com")
    db.crear_cliente_fiscal(tenant, "Dos", email="dup@x.com")
    ajeno = db.crear_tenant("Otro despacho")
    db.crear_cliente_fiscal(ajeno, "Ajeno", email="ajeno@x.com")
    for n, rem in enumerate(("dup@x.com", "ajeno@x.com")):
        m = _msg(cuenta, str(n), remitente=rem)
        correo._aplicar_categoria_automatica(uid, m, rem, "Hola")
        assert db.obtener_mensaje_correo(m)["cliente_fiscal_id"] is None


def test_el_vinculo_automatico_no_pisa_uno_existente_y_se_puede_rellenar_hacia_atras(cliente):
    uid, tenant, cuenta = _montar(cliente, "f2-atras@ejemplo.com")
    a = db.crear_cliente_fiscal(tenant, "A", email="a@x.com")
    b = db.crear_cliente_fiscal(tenant, "B")
    viejo = _msg(cuenta, "1", remitente="a@x.com")
    puesto_a_mano = _msg(cuenta, "2", remitente="a@x.com")
    db.asignar_cliente_fiscal_correo(tenant, puesto_a_mano, b)
    correo._aplicar_categoria_automatica(uid, puesto_a_mano, "a@x.com", "x")
    assert db.obtener_mensaje_correo(puesto_a_mano)["cliente_fiscal_id"] == b
    assert correo.vincular_correos_a_clientes(uid) == 1
    assert db.obtener_mensaje_correo(viejo)["cliente_fiscal_id"] == a
    assert correo.vincular_correos_a_clientes(uid) == 0


def test_boton_de_vincular_antiguos(cliente):
    uid, tenant, cuenta = _montar(cliente, "f2-boton@ejemplo.com")
    db.crear_cliente_fiscal(tenant, "A", email="a@x.com")
    _msg(cuenta, "1", remitente="a@x.com")
    r = cliente.post("/correo/ajustes/vincular-clientes", follow_redirects=True)
    assert r.status_code == 200 and "Correos enlazados: 1" in r.get_data(as_text=True)


# --- adjuntos -> vencimiento -----------------------------------------------------

def _con_adjunto(cliente, email, nombre="factura.pdf", tipo="application/pdf"):
    uid, tenant, cuenta = _montar(cliente, email)
    cid = db.crear_cliente_fiscal(tenant, "Cliente Doc", email="doc@x.com")
    venc = db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T1", "2026-04-20")
    m = _msg(cuenta, "1", remitente="doc@x.com")
    db.guardar_adjuntos_correo(m, [{"nombre": nombre, "tipo": tipo, "bytes": b"%PDF-1.4 contenido"}])
    adj = db.listar_adjuntos_correo(m)[0]["id"]
    return uid, tenant, cid, venc, m, adj


def test_guardar_adjunto_en_vencimiento_es_interno_por_defecto(cliente):
    uid, tenant, cid, venc, m, adj = _con_adjunto(cliente, "f2-adj@ejemplo.com")
    r = cliente.post(f"/correo/{m}/adjunto/{adj}/guardar-vencimiento", data={"vencimiento_id": venc}, follow_redirects=True)
    assert "Adjunto guardado en el vencimiento." in r.get_data(as_text=True)
    docs = db.listar_documentos_vencimiento(venc)
    assert len(docs) == 1 and docs[0]["origen"] == "correo" and docs[0]["nombre_archivo"] == "factura.pdf"
    # el cliente no lo ve
    assert db.listar_documentos_vencimiento(venc, excluir_origenes=db.ORIGENES_INTERNOS_DOCUMENTO_VENCIMIENTO) == []


def test_el_portal_no_enseña_ni_sirve_los_adjuntos_internos(cliente):
    uid, tenant, cid, venc, m, adj = _con_adjunto(cliente, "f2-portal@ejemplo.com")
    interno = correo.guardar_adjunto_en_vencimiento(uid, m, adj, venc)
    visible = correo.guardar_adjunto_en_vencimiento(uid, m, adj, venc, visible_cliente=True)
    token = db.crear_acceso_cliente_fiscal(cid, "127.0.0.1")
    with _otro_cliente("f2-portal-otro@ejemplo.com") as (http, _uid):
        http.get(f"/portal/entrar/{token}")
        html = http.get(f"/portal/vencimientos/{venc}/documentos").get_data(as_text=True)
        assert f"documento_id={visible}" in html or f"/documentos/{visible}" in html
        assert f"/documentos/{interno}" not in html
        assert http.get(f"/portal/vencimientos/{venc}/documentos/{interno}").status_code == 404
        assert http.get(f"/portal/vencimientos/{venc}/documentos/{visible}").status_code == 200


def test_adjunto_solo_visible_al_cliente_si_es_imagen_o_pdf_y_validaciones(cliente):
    uid, tenant, cid, venc, m, adj = _con_adjunto(cliente, "f2-mime@ejemplo.com", "hoja.xlsx", "application/vnd.ms-excel")
    try:
        correo.guardar_adjunto_en_vencimiento(uid, m, adj, venc, visible_cliente=True)
        assert False, "debía rechazarlo"
    except correo.ErrorCorreo as e:
        assert "imágenes o PDF" in str(e)
    assert correo.guardar_adjunto_en_vencimiento(uid, m, adj, venc)  # interno: cualquier tipo
    ajeno = db.crear_tenant("Ajeno")
    cajeno = db.crear_cliente_fiscal(ajeno, "X")
    vajeno = db.crear_vencimiento_fiscal(ajeno, cajeno, "303", "2026-T1", "2026-04-20")
    try:
        correo.guardar_adjunto_en_vencimiento(uid, m, adj, vajeno)
        assert False, "vencimiento de otro despacho"
    except correo.ErrorCorreo:
        pass
    with _otro_cliente("f2-mime-otro@ejemplo.com") as (http, otro_uid):
        db.asignar_tenant(otro_uid, tenant)
        r = http.post(f"/correo/{m}/adjunto/{adj}/guardar-vencimiento", data={"vencimiento_id": venc})
        assert r.status_code == 404  # el mensaje no es suyo


def test_la_bandeja_ofrece_guardar_adjunto_solo_con_cliente_enlazado(cliente):
    uid, tenant, cid, venc, m, adj = _con_adjunto(cliente, "f2-ui@ejemplo.com")
    cuenta = db.listar_cuentas_correo(uid)[0]["id"]
    assert "Guardar en un vencimiento" not in cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)
    db.asignar_cliente_fiscal_correo(tenant, m, cid)
    assert "Guardar en un vencimiento" in cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={m}").get_data(as_text=True)


# --- plantillas con variables -------------------------------------------------------

def test_rellenar_plantilla_con_cliente_y_proximo_vencimiento(cliente):
    uid, tenant, cuenta = _montar(cliente, "f2-pl@ejemplo.com", "Gestoría Norte")
    cid = db.crear_cliente_fiscal(tenant, "Bar <Pepe>", nif="B123")
    db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T2", "2026-07-20")
    db.crear_vencimiento_fiscal(tenant, cid, "111", "2026-T1", "2026-04-20")
    valores = correo.contexto_plantilla(uid, cid)
    assert valores["despacho"] == "Gestoría Norte" and valores["modelo"] == "111" and valores["fecha_limite"] == "20/04/2026"
    texto, faltan = correo.rellenar_plantilla("Hola {{ cliente }}, modelo {{modelo}} ({{ periodo }}) vence {{fecha_limite}}. {{inventada}}", valores, html=True)
    assert "Bar &lt;Pepe&gt;" in texto and "111" in texto and "{{inventada}}" in texto and faltan == []
    sin_cliente, faltan = correo.rellenar_plantilla("{{cliente}} {{mi_nombre}}", correo.contexto_plantilla(uid))
    assert faltan == ["cliente"] and "{{cliente}}" in sin_cliente


def test_plantilla_json_usa_el_cliente_del_correo_respondido_y_no_cruza_despachos(cliente):
    uid, tenant, cuenta = _montar(cliente, "f2-pj@ejemplo.com")
    cid = db.crear_cliente_fiscal(tenant, "Cliente Resp", email="r@x.com")
    pid = db.crear_plantilla_correo(uid, "Aviso", "Para {{cliente}}", "Hola {{cliente}} de {{despacho}}")
    m = _msg(cuenta, "1", remitente="r@x.com")
    db.asignar_cliente_fiscal_correo(tenant, m, cid)
    datos = cliente.get(f"/correo/plantillas/{pid}.json?en_respuesta_a={m}").get_json()
    assert datos["asunto"] == "Para Cliente Resp" and "Cliente Resp" in datos["cuerpo"] and datos["sin_resolver"] == []
    ajeno = db.crear_tenant("Ajeno 2")
    cajeno = db.crear_cliente_fiscal(ajeno, "Secreto SL")
    datos = cliente.get(f"/correo/plantillas/{pid}.json?cliente_fiscal_id={cajeno}").get_json()
    assert "Secreto SL" not in datos["cuerpo"] and datos["sin_resolver"] == ["cliente"]


# --- correo de equipo ------------------------------------------------------------------

def _equipo(cliente, email_otro):
    uid, tenant, cuenta = _montar(cliente, "f2-eq@ejemplo.com", "Despacho Eq")
    m = _msg(cuenta, "1", asunto="Confidencial")
    return uid, tenant, m


def test_quien_sale_del_despacho_pierde_el_acceso_a_lo_compartido(cliente):
    uid, tenant, m = _equipo(cliente, "x")
    with _otro_cliente("f2-eq-otro@ejemplo.com") as (http, otro):
        db.asignar_tenant(otro, tenant)
        assert db.compartir_correo(uid, m, otro) and db.asignar_correo(uid, m, otro)
        assert db.rol_en_correo(otro, m) == "asignado" and http.get(f"/correo/equipo/{m}").status_code == 200
        db.asignar_tenant(otro, db.crear_tenant("Otro despacho"))
        assert db.rol_en_correo(otro, m) is None and http.get(f"/correo/equipo/{m}").status_code == 404
        db.desasignar_tenant(otro)
        assert db.rol_en_correo(otro, m) is None


def test_historial_registra_acciones_y_solo_lo_ve_el_dueno(cliente):
    uid, tenant, m = _equipo(cliente, "x")
    with _otro_cliente("f2-eq-hist@ejemplo.com") as (http, otro):
        db.asignar_tenant(otro, tenant)
        db.compartir_correo(uid, m, otro)
        http.get(f"/correo/equipo/{m}")
        http.get(f"/correo/equipo/{m}")  # misma persona y día: una sola lectura
        http.post(f"/correo/equipo/{m}/notas", data={"texto": "Visto"})
        acciones = [h["accion"] for h in db.historial_correo_equipo(uid, m)]
        assert acciones.count("leer") == 1 and "compartir" in acciones and "nota" in acciones
        assert db.historial_correo_equipo(otro, m) == []
        assert "Quién ha hecho qué" not in http.get(f"/correo/equipo/{m}").get_data(as_text=True)
    assert "Quién ha hecho qué" in cliente.get(f"/correo/equipo/{m}").get_data(as_text=True)
    db.dejar_de_compartir_correo(uid, m, otro)
    assert "quitar" in [h["accion"] for h in db.historial_correo_equipo(uid, m)]


def test_limites_de_compartidos_y_de_notas(cliente, monkeypatch):
    uid, tenant, m = _equipo(cliente, "x")
    monkeypatch.setattr(db, "MAX_COMPARTIDOS_POR_MENSAJE", 2)
    monkeypatch.setattr(db, "MAX_NOTAS_INTERNAS_POR_MENSAJE", 2)
    otros = []
    for n in range(3):
        o = db.crear_usuario_vinculado_a_kratos(f"f2-lim{n}@ejemplo.com", f"k-lim{n}")
        db.asignar_tenant(o, tenant)
        otros.append(o)
    assert db.compartir_correo(uid, m, otros[0]) and db.compartir_correo(uid, m, otros[1])
    assert db.compartir_correo(uid, m, otros[1])  # repetir no cuenta
    assert not db.compartir_correo(uid, m, otros[2])
    assert cliente.post(f"/correo/{m}/equipo/compartir", data={"usuario_id": otros[2]}).status_code == 400
    assert db.anadir_nota_interna_correo(uid, m, "uno") and db.anadir_nota_interna_correo(uid, m, "dos")
    assert db.anadir_nota_interna_correo(uid, m, "tres") is None
