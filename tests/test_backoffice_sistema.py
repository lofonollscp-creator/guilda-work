"""Backoffice independiente: funciones migradas del panel antiguo — leads,
solicitudes del portal, webhooks, herramientas, ingresos, salud, diagnóstico,
estado, copias, claves de API, exportación y borrado de tenants, y altas de
usuario con aprovisionamiento."""
import json

import pytest

from app import (baserow, chatwoot, db, espocrm, facturascripts, kratos, listmonk, metabase, nextcloud, ntfy,
                 openproject, paperless, stalwart, umami, uptime_kuma)
from backoffice import aprovisionamiento, auth
from backoffice.main import create_app
from tests.test_backoffice_app import CLAVE, entrar, post


@pytest.fixture
def bo(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "backoffice.db")
    monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "bo_secret.key")
    auth.crear_admin("jorge", CLAVE, "Jorge")
    cliente = create_app(testing=True).test_client()
    entrar(cliente)
    return cliente


# --- Comercial ----------------------------------------------------------------

def test_leads_filtra_pendientes_y_marca_atendidos(bo):
    a = db.crear_lead_contacto("Ana Lead", "ana@lead.com", "Empresa A", "600", "Hola")
    db.crear_lead_contacto("Beto Lead", "beto@lead.com")
    db.marcar_lead_atendido(a, True)
    html = bo.get("/leads").get_data(as_text=True)
    assert "Beto Lead" in html and "Ana Lead" not in html
    assert "Ana Lead" in bo.get("/leads?estado=todos").get_data(as_text=True)
    post(bo, f"/leads/{a}/atendido", atendido="0")
    assert "Ana Lead" in bo.get("/leads").get_data(as_text=True)
    assert any(r["accion"] == "lead.pendiente" for r in auth.listar_auditoria())


def _solicitud(email="cliente@portal.com", nombre="Cliente Portal"):
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO solicitudes_acceso_portal (nombre, email, nif, mensaje, creado_en) VALUES (?, ?, 'B123', 'Quiero acceso', ?)",
            (nombre, email, db.now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_solicitudes_del_portal_vincular_y_crear_cliente(bo):
    t = db.crear_tenant("Gestoría Portal")
    cliente = db.crear_cliente_fiscal(t, "Existente SL")
    s1, s2 = _solicitud("uno@portal.com", "Uno"), _solicitud("dos@portal.com", "Dos")
    html = bo.get("/solicitudes-portal").get_data(as_text=True)
    assert "Uno" in html and "Dos" in html and "Existente SL" in html
    post(bo, f"/solicitudes-portal/{s1}/vincular", cliente_fiscal_id=str(cliente))
    assert db.obtener_cliente_fiscal(t, cliente)["email"] == "uno@portal.com"
    post(bo, f"/solicitudes-portal/{s2}/crear-cliente", tenant_id=str(t))
    assert any(c["email"] == "dos@portal.com" and c["nif"] == "B123" for c in db.listar_clientes_fiscales(t))
    assert "Uno" not in bo.get("/solicitudes-portal").get_data(as_text=True)          # ya atendidas
    assert "ATENDIDA" in bo.get("/solicitudes-portal?estado=todas").get_data(as_text=True)
    post(bo, f"/solicitudes-portal/{s1}/vincular", cliente_fiscal_id="")              # sin elegir: aviso, sin romper
    post(bo, "/solicitudes-portal/99999/crear-cliente", tenant_id=str(t))


# --- Herramientas, ingresos, salud, diagnóstico, estado, copias ------------------------

def test_catalogo_e_ingresos(bo):
    from app import herramientas
    t = db.crear_tenant("Ingresos SL")
    db.ocultar_herramienta(t, herramientas.HERRAMIENTAS[0]["id"])
    html = bo.get("/herramientas").get_data(as_text=True)
    assert herramientas.HERRAMIENTAS[0]["nombre"] in html and "0 / 1" in html
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO planes_guilda (nombre, precio_mensual_centimos, activo, creado_en) VALUES ('Pro', 5000, 1, ?)", (db.now_iso(),))
        conn.execute("UPDATE tenants SET plan_id = 1, suscripcion_estado = 'activa' WHERE id = ?", (t,))
        conn.commit()
    finally:
        conn.close()
    html = bo.get("/ingresos").get_data(as_text=True)
    assert "50 €" in html and "600 €" in html and "Ingresos SL" in html


def test_salud_funciona_sin_babel_y_muestra_semaforos(bo):
    r = bo.get("/salud")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Última copia de seguridad" in html and "punto-" in html and "Espacio libre en disco" in html


def test_diagnostico_y_estado_con_uptime_kuma(bo, monkeypatch):
    assert "Stripe (plataforma)" in bo.get("/diagnostico").get_data(as_text=True)
    monkeypatch.setattr(uptime_kuma, "listar_monitores", lambda: [{"nombre": "Web", "estado": "activo", "tiempo_respuesta_ms": 42.4}])
    html = bo.get("/estado").get_data(as_text=True)
    assert "Web" in html and "42 ms" in html
    def cae():
        raise uptime_kuma.ErrorUptimeKuma("sin conexión")
    monkeypatch.setattr(uptime_kuma, "listar_monitores", cae)
    assert "sin conexión" in bo.get("/estado").get_data(as_text=True)


def test_copias_de_seguridad(bo):
    assert "Todavía no hay ninguna copia" in bo.get("/copias").get_data(as_text=True)
    post(bo, "/copias")
    html = bo.get("/copias").get_data(as_text=True)
    assert "registro_" in html and "Todavía no hay" not in html
    assert any(r["accion"] == "copia.crear" for r in auth.listar_auditoria())


# --- Webhooks -------------------------------------------------------------------------

def test_webhooks_crear_mostrar_secreto_una_vez_y_borrar(bo):
    t = db.crear_tenant("Hooks SL")
    r = post(bo, "/webhooks", url="https://ejemplo.com/hook", tenant_id=str(t), eventos=["tarea.creada", "nota.editada", "inventado"])
    html = r.get_data(as_text=True)
    wh = db.listar_todos_los_webhooks()[t][0]
    assert r.status_code == 200 and wh["secreto"] in html
    assert json.loads(wh["eventos"]) == ["tarea.creada", "nota.editada"]
    listado = bo.get("/webhooks").get_data(as_text=True)
    assert "https://ejemplo.com/hook" in listado and wh["secreto"] not in listado and "Hooks SL" in listado
    post(bo, "/webhooks", url="javascript:alert(1)", eventos=["tarea.creada"])
    post(bo, "/webhooks", url="https://x.com", eventos=[])
    post(bo, "/webhooks", url="https://x.com", tenant_id="9999", eventos=["tarea.creada"])
    assert len(db.listar_todos_los_webhooks()[t]) == 1 and len(db.listar_todos_los_webhooks()) == 1
    post(bo, f"/webhooks/{wh['id']}/borrar")
    assert db.listar_todos_los_webhooks() == {}
    assert post(bo, "/webhooks/9999/borrar").status_code == 404


# --- Operaciones sobre un tenant -------------------------------------------------------

def test_claves_de_api_se_guardan_sin_mostrarse_ni_auditarse(bo):
    t = db.crear_tenant("Claves SL")
    for servicio, campo in (("facturascripts", "facturascripts_api_key"), ("documenso", "documenso_api_key"), ("calcom", "calcom_api_key")):
        post(bo, f"/tenants/{t}/claves/{servicio}", api_key=f"clave-{servicio}-SECRETA")
        assert db.obtener_tenant(t)[campo] == f"clave-{servicio}-SECRETA"
    html = bo.get(f"/tenants/{t}?seccion=integraciones").get_data(as_text=True)
    assert html.count("GUARDADA") == 3 and "SECRETA" not in html
    assert all("SECRETA" not in (a["detalle"] or "") for a in auth.listar_auditoria())
    assert post(bo, f"/tenants/{t}/claves/otro", api_key="x").status_code == 404
    post(bo, f"/tenants/{t}/claves/calcom", api_key="  ")
    assert db.obtener_tenant(t)["calcom_api_key"] == "clave-calcom-SECRETA"


def test_integraciones_muestran_que_esta_aprovisionado(bo):
    t = db.crear_tenant("Integra SL")
    db.guardar_ntfy(t, "topic-x", "token-x")
    html = bo.get(f"/tenants/{t}?seccion=integraciones").get_data(as_text=True)
    assert "APROVISIONADO" in html and "token-x" not in html


def test_exportar_datos_del_tenant(bo):
    t = db.crear_tenant("Export SL")
    db.crear_cliente_fiscal(t, "Cliente Exportado")
    r = post(bo, f"/tenants/{t}/exportar")
    assert r.status_code == 200 and r.mimetype == "application/json" and "attachment" in r.headers["Content-Disposition"]
    assert "Cliente Exportado" in r.get_data(as_text=True)
    assert any(a["accion"] == "tenant.exportar" for a in auth.listar_auditoria())
    assert post(bo, "/tenants/9999/exportar").status_code == 404


def test_borrar_tenant_exige_confirmar_el_nombre_y_retira_integraciones(bo, monkeypatch):
    llamadas = []
    monkeypatch.setattr(aprovisionamiento, "desaprovisionar_tenant", lambda t: llamadas.append(t["nombre"]) or [{"servicio": "X", "estado": "creado", "detalle": "", "datos": {}}])
    t = db.crear_tenant("Borrable SL")
    post(bo, f"/tenants/{t}/borrar", confirmacion="otro nombre")
    assert db.obtener_tenant(t) is not None and llamadas == []
    r = post(bo, f"/tenants/{t}/borrar", confirmacion="Borrable SL")
    assert r.status_code == 200 and "Borrable SL" in r.get_data(as_text=True) and db.obtener_tenant(t) is None and llamadas == ["Borrable SL"]
    assert any(a["accion"] == "tenant.borrar" for a in auth.listar_auditoria())
    assert post(bo, "/tenants/9999/borrar", confirmacion="x").status_code == 404


def test_desaprovisionar_aisla_los_fallos_de_cada_servicio(monkeypatch):
    def cae(*a, **k):
        raise RuntimeError("servicio caído")
    for modulo in (facturascripts, paperless, baserow, listmonk, ntfy, umami, stalwart, espocrm, nextcloud):
        monkeypatch.setattr(modulo, "desaprovisionar_tenant", cae)
    t = db.crear_tenant("Cae SL")
    pasos = aprovisionamiento.desaprovisionar_tenant(db.obtener_tenant(t))
    assert len(pasos) == 9 and all(p["estado"] == "error" and "servicio caído" in p["detalle"] for p in pasos)


# --- Alta de usuario con aprovisionamiento ----------------------------------------------

def test_alta_de_usuario_aprovisiona_en_las_herramientas_y_muestra_cada_resultado(bo, monkeypatch):
    t = db.crear_tenant("Alta SL")
    db.guardar_umami(t, "team-1", "web-1")
    monkeypatch.setattr(kratos, "crear_identidad", lambda e, c: "identidad-x")
    recibido = {}
    monkeypatch.setattr(openproject, "crear_usuario", lambda e, c: recibido.setdefault("op", c))
    def chatwoot_roto(e, c, n):
        raise chatwoot.ErrorChatwoot("Chatwoot caído")
    monkeypatch.setattr(chatwoot, "crear_usuario", chatwoot_roto)
    monkeypatch.setattr(metabase, "crear_usuario", lambda e: None)
    monkeypatch.setattr(umami, "crear_usuario_tenant", lambda e, team, c: recibido.setdefault("um", (team, c)))
    r = post(bo, "/usuarios", email="alta@ejemplo.com", tenant_id=str(t))
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "OpenProject" in html and "Chatwoot caído" in html and "Umami" in html
    assert recibido["op"] == recibido["um"][1] and recibido["um"][0] == "team-1" and recibido["op"] in html
    assert db.obtener_usuario_por_email("alta@ejemplo.com")["tenant_id"] == t


def test_las_paginas_nuevas_requieren_sesion(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "b.db"); monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "k.key")
    anonimo = create_app(testing=True).test_client()
    for ruta in ("/leads", "/solicitudes-portal", "/herramientas", "/ingresos", "/salud", "/diagnostico", "/estado", "/copias", "/webhooks"):
        assert anonimo.get(ruta).status_code == 302, ruta
    for ruta in ("/copias", "/webhooks", "/tenants/1/borrar", "/tenants/1/exportar", "/leads/1/atendido"):
        assert anonimo.post(ruta, data={}).status_code == 400, ruta


# --- Avisos por correo: comprobar antes de necesitarlos ------------------------------------------------------------------------------

def test_la_pagina_salud_dice_si_los_avisos_estan_configurados_sin_enseñar_secretos(bo, monkeypatch):
    from app import notificaciones_email as ne
    monkeypatch.setattr(ne, "PORTAL_SMTP_HOST", "smtp.ejemplo.com")
    monkeypatch.setattr(ne, "PORTAL_SMTP_USUARIO", "u@ejemplo.com")
    monkeypatch.setattr(ne, "PORTAL_SMTP_CONTRASENA", "SECRETO-NO-SE-MUESTRA")
    monkeypatch.setattr(ne, "PORTAL_SMTP_REMITENTE", "no-reply@ejemplo.com")
    monkeypatch.setattr(ne, "ALERTAS_ADMIN_EMAIL", "jorge@guilda.cat")
    html = bo.get("/salud").get_data(as_text=True)
    assert "smtp.ejemplo.com:587" in html and "j****@guilda.cat" in html
    assert "SECRETO-NO-SE-MUESTRA" not in html and "jorge@guilda.cat" not in html
    monkeypatch.setattr(ne, "ALERTAS_ADMIN_EMAIL", None)
    monkeypatch.setattr(ne, "PORTAL_SMTP_HOST", None)
    sin = bo.get("/salud").get_data(as_text=True)
    assert "SIN CONFIGURAR" in sin and "ALERTAS_ADMIN_EMAIL" in sin and "PORTAL_SMTP_HOST" in sin


def test_comprobar_conexion_no_envia_nada_y_explica_el_fallo(bo, monkeypatch):
    from app import notificaciones_email as ne
    import smtplib
    for nombre, valor in (("PORTAL_SMTP_HOST", "smtp.ejemplo.com"), ("PORTAL_SMTP_USUARIO", "u"), ("PORTAL_SMTP_CONTRASENA", "p"), ("PORTAL_SMTP_REMITENTE", "r@x.com")):
        monkeypatch.setattr(ne, nombre, valor)
    acciones = []

    class SMTPFalso:
        def __init__(self, *a, **k): acciones.append("conectar")
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): acciones.append("tls")
        def login(self, u, p): acciones.append("login")
        def noop(self): acciones.append("noop")
        def send_message(self, m): acciones.append("ENVIO")

    monkeypatch.setattr(ne.smtplib, "SMTP", SMTPFalso)
    post(bo, "/salud/probar-correo")
    assert "Conexión y autenticación correctas" in bo.get("/salud").get_data(as_text=True) and "ENVIO" not in acciones and acciones == ["conectar", "tls", "login", "noop"]

    class SMTPRechaza(SMTPFalso):
        def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, b"mal")
    monkeypatch.setattr(ne.smtplib, "SMTP", SMTPRechaza)
    post(bo, "/salud/probar-correo")
    texto = bo.get("/salud").get_data(as_text=True)
    assert "rechazó el usuario o la contraseña" in texto and "535" in texto and "mal" not in texto.replace("rechazó", "")


def test_el_aviso_de_prueba_se_envia_al_destino_de_alertas_y_queda_auditado(bo, monkeypatch):
    from app import notificaciones_email as ne
    enviados = []
    monkeypatch.setattr(ne, "ALERTAS_ADMIN_EMAIL", "jorge@guilda.cat")
    monkeypatch.setattr(ne, "_enviar", lambda destino, asunto, cuerpo: enviados.append((destino, asunto)))
    post(bo, "/salud/aviso-prueba")
    pagina = bo.get("/salud").get_data(as_text=True)
    assert enviados == [("jorge@guilda.cat", "[Guilda Work] aviso de prueba")]
    assert "Aviso de prueba enviado a j****@guilda.cat" in pagina and any(a["accion"] == "salud.aviso_prueba" for a in auth.listar_auditoria())
    monkeypatch.setattr(ne, "ALERTAS_ADMIN_EMAIL", None)
    post(bo, "/salud/aviso-prueba")
    assert "ALERTAS_ADMIN_EMAIL no está configurada" in bo.get("/salud").get_data(as_text=True)
