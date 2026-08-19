"""Portal de cliente (app/rutas_portal_cliente.py): capa BD (tokens de
acceso, documentos) y capa ruta (aislamiento entre clientes, no exponer
si un email existe, envío de correo sin configurar)."""
from datetime import datetime, timedelta

import pytest

from app import db, notificaciones_email


# --- Capa BD: clientes_fiscales_accesos ---------------------------------

def _cliente_de_prueba(nombre="Cliente Portal", email="cliente@ejemplo.com"):
    tenant_id = db.crear_tenant(f"Gestoria {nombre}")
    cliente_id = db.crear_cliente_fiscal(tenant_id, nombre, email=email)
    return tenant_id, cliente_id


def test_crear_y_consumir_token_de_un_solo_uso():
    _, cliente_id = _cliente_de_prueba()
    token = db.crear_acceso_cliente_fiscal(cliente_id, "127.0.0.1")

    assert db.consumir_acceso_cliente_fiscal(token) == cliente_id
    # Segundo consumo del MISMO token: ya usado, no vuelve a dar el cliente.
    assert db.consumir_acceso_cliente_fiscal(token) is None


def test_token_inexistente_no_se_consume():
    assert db.consumir_acceso_cliente_fiscal("token-que-no-existe") is None


def test_token_caducado_no_se_consume(monkeypatch):
    _, cliente_id = _cliente_de_prueba()
    token = db.crear_acceso_cliente_fiscal(cliente_id, "127.0.0.1")

    # Empuja el reloj más allá de los 15 minutos de vida sin esperar de verdad.
    real_now_iso = db.now_iso
    futuro = (datetime.now() + timedelta(minutes=16)).isoformat(timespec="seconds")
    monkeypatch.setattr(db, "now_iso", lambda: futuro)
    try:
        assert db.consumir_acceso_cliente_fiscal(token) is None
    finally:
        monkeypatch.setattr(db, "now_iso", real_now_iso)


def test_clientes_fiscales_por_email_insensible_a_mayusculas():
    _, cliente_id = _cliente_de_prueba(email="Mayus@Ejemplo.com")
    encontrados = db.clientes_fiscales_por_email("mayus@ejemplo.com")
    assert [c["id"] for c in encontrados] == [cliente_id]


def test_clientes_fiscales_por_email_cruza_tenants():
    """Simplificación consciente de v1: el mismo email en varios tenants
    devuelve varias filas -- lo usa /portal/entrar para mandar un enlace
    por cada una."""
    _, cliente_a = _cliente_de_prueba(nombre="A", email="compartido@ejemplo.com")
    _, cliente_b = _cliente_de_prueba(nombre="B", email="compartido@ejemplo.com")
    encontrados = {c["id"] for c in db.clientes_fiscales_por_email("compartido@ejemplo.com")}
    assert encontrados == {cliente_a, cliente_b}


# --- Capa BD: vencimientos_fiscales_documentos ---------------------------

def test_subir_y_listar_documentos_vencimiento():
    tenant_id, cliente_id = _cliente_de_prueba()
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")

    doc_id = db.subir_documento_vencimiento(v_id, "factura.pdf", "application/pdf", b"contenido-pdf")
    documentos = db.listar_documentos_vencimiento(v_id)
    assert len(documentos) == 1
    assert documentos[0]["nombre_archivo"] == "factura.pdf"

    documento = db.obtener_documento_vencimiento(doc_id)
    assert documento["contenido"] == b"contenido-pdf"


# --- Capa ruta -------------------------------------------------------------

def test_entrar_responde_igual_exista_o_no_el_email(cliente):
    _cliente_de_prueba(email="existe@ejemplo.com")

    resp_existe = cliente.post("/portal/entrar", data={"email": "existe@ejemplo.com"})
    resp_no_existe = cliente.post("/portal/entrar", data={"email": "no-existe@ejemplo.com"})

    assert resp_existe.status_code == resp_no_existe.status_code == 200
    assert resp_existe.get_data(as_text=True) == resp_no_existe.get_data(as_text=True)


def test_entrar_con_email_valido_crea_token_recuperable(cliente):
    _, cliente_id = _cliente_de_prueba(email="con-token@ejemplo.com")
    cliente.post("/portal/entrar", data={"email": "con-token@ejemplo.com"})

    assert db.ultimo_acceso_solicitado_en(cliente_id) is not None


def test_token_valido_fija_sesion_y_lista_vencimientos_propios(cliente):
    tenant_id, cliente_id = _cliente_de_prueba(email="dashboard@ejemplo.com")
    db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    token = db.crear_acceso_cliente_fiscal(cliente_id, "127.0.0.1")

    resp = cliente.get(f"/portal/entrar/{token}", follow_redirects=True)
    assert resp.status_code == 200
    assert "303" in resp.get_data(as_text=True)


def test_token_invalido_no_fija_sesion(cliente):
    resp = cliente.get("/portal/entrar/token-inventado")
    assert resp.status_code == 200
    assert "caducado" in resp.get_data(as_text=True).lower() or "usado" in resp.get_data(as_text=True).lower()

    resp_dashboard = cliente.get("/portal/")
    assert resp_dashboard.status_code == 302
    assert "/portal/entrar" in resp_dashboard.headers["Location"]


def test_cliente_no_ve_documentos_de_vencimiento_ajeno(cliente):
    tenant_a, cliente_a = _cliente_de_prueba(nombre="A", email="doc-a@ejemplo.com")
    v_a = db.crear_vencimiento_fiscal(tenant_a, cliente_a, "303", "2026-T1", "2026-04-20")

    tenant_b, cliente_b = _cliente_de_prueba(nombre="B", email="doc-b@ejemplo.com")
    v_b = db.crear_vencimiento_fiscal(tenant_b, cliente_b, "130", "2026-T1", "2026-04-20")

    token_b = db.crear_acceso_cliente_fiscal(cliente_b, "127.0.0.1")
    cliente.get(f"/portal/entrar/{token_b}")

    # Ve el suyo...
    resp_propio = cliente.get(f"/portal/vencimientos/{v_b}/documentos")
    assert resp_propio.status_code == 200

    # ...pero no el ajeno.
    resp_ajeno = cliente.get(f"/portal/vencimientos/{v_a}/documentos")
    assert resp_ajeno.status_code == 404


def test_documento_con_mime_no_permitido_se_rechaza(cliente):
    tenant_id, cliente_id = _cliente_de_prueba(email="mime@ejemplo.com")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    token = db.crear_acceso_cliente_fiscal(cliente_id, "127.0.0.1")
    cliente.get(f"/portal/entrar/{token}")

    import io
    resp = cliente.post(
        f"/portal/vencimientos/{v_id}/documentos",
        data={"documento": (io.BytesIO(b"binario"), "script.exe", "application/x-msdownload")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert not db.listar_documentos_vencimiento(v_id)


def test_documento_valido_se_guarda(cliente):
    tenant_id, cliente_id = _cliente_de_prueba(email="subida@ejemplo.com")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    token = db.crear_acceso_cliente_fiscal(cliente_id, "127.0.0.1")
    cliente.get(f"/portal/entrar/{token}")

    import io
    resp = cliente.post(
        f"/portal/vencimientos/{v_id}/documentos",
        data={"documento": (io.BytesIO(b"%PDF-1.4 contenido"), "justificante.pdf", "application/pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    documentos = db.listar_documentos_vencimiento(v_id)
    assert len(documentos) == 1
    assert documentos[0]["nombre_archivo"] == "justificante.pdf"


def test_salir_borra_sesion_de_cliente(cliente):
    _, cliente_id = _cliente_de_prueba(email="salir@ejemplo.com")
    token = db.crear_acceso_cliente_fiscal(cliente_id, "127.0.0.1")
    cliente.get(f"/portal/entrar/{token}")
    assert cliente.get("/portal/").status_code == 200

    cliente.post("/portal/salir")
    resp = cliente.get("/portal/")
    assert resp.status_code == 302
    assert "/portal/entrar" in resp.headers["Location"]


# --- notificaciones_email: sin configurar da un error legible, no un 500 ---

def test_enviar_enlace_portal_sin_configurar_lanza_error_legible(monkeypatch):
    monkeypatch.setattr(notificaciones_email, "PORTAL_SMTP_HOST", None)
    monkeypatch.setattr(notificaciones_email, "PORTAL_SMTP_USUARIO", None)
    monkeypatch.setattr(notificaciones_email, "PORTAL_SMTP_CONTRASENA", None)
    monkeypatch.setattr(notificaciones_email, "PORTAL_SMTP_REMITENTE", None)

    assert notificaciones_email.configurado() is False
    with pytest.raises(notificaciones_email.ErrorNotificacionesEmail):
        notificaciones_email.enviar_enlace_portal("alguien@ejemplo.com", "https://guildawork.com/portal/entrar/x")


# --- v2: mensajería bidireccional ------------------------------------------

def _entrar_como_cliente(cliente_http, cliente_fiscal_id):
    token = db.crear_acceso_cliente_fiscal(cliente_fiscal_id, "127.0.0.1")
    cliente_http.get(f"/portal/entrar/{token}")


def test_cliente_manda_mensaje_y_notifica_al_empleado_asignado(cliente, monkeypatch):
    from app import rutas_portal_cliente

    tenant_id, cliente_id = _cliente_de_prueba(email="mensaje-a@ejemplo.com")
    usuario_asignado = db.usuario_local_id()
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20", usuario_id=usuario_asignado)
    _entrar_como_cliente(cliente, cliente_id)

    llamadas = []
    monkeypatch.setattr(
        rutas_portal_cliente.notificaciones.push, "enviar_a_usuario",
        lambda usuario_id, titulo, cuerpo, datos=None: llamadas.append((usuario_id, titulo, datos)),
    )

    resp = cliente.post(f"/portal/vencimientos/{v_id}/mensajes", data={"texto": "¿Falta algo por mi parte?"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "¿Falta algo por mi parte?" in resp.get_data(as_text=True)

    mensajes = db.listar_mensajes_vencimiento(v_id)
    assert len(mensajes) == 1
    assert mensajes[0]["autor"] == "cliente"

    assert len(llamadas) == 1
    assert llamadas[0][0] == usuario_asignado
    assert llamadas[0][2]["vencimiento_id"] == v_id


def test_mensaje_sin_usuario_asignado_no_notifica(cliente, monkeypatch):
    from app import rutas_portal_cliente

    tenant_id, cliente_id = _cliente_de_prueba(email="mensaje-b@ejemplo.com")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")  # sin usuario_id
    _entrar_como_cliente(cliente, cliente_id)

    llamadas = []
    monkeypatch.setattr(rutas_portal_cliente.notificaciones.push, "enviar_a_usuario", lambda *a, **k: llamadas.append((a, k)))

    resp = cliente.post(f"/portal/vencimientos/{v_id}/mensajes", data={"texto": "Hola"}, follow_redirects=True)
    assert resp.status_code == 200
    assert not llamadas


def test_cliente_no_ve_mensajes_de_vencimiento_ajeno(cliente):
    tenant_a, cliente_a = _cliente_de_prueba(nombre="MsgA", email="msg-a@ejemplo.com")
    v_a = db.crear_vencimiento_fiscal(tenant_a, cliente_a, "303", "2026-T1", "2026-04-20")

    tenant_b, cliente_b = _cliente_de_prueba(nombre="MsgB", email="msg-b@ejemplo.com")
    v_b = db.crear_vencimiento_fiscal(tenant_b, cliente_b, "130", "2026-T1", "2026-04-20")

    _entrar_como_cliente(cliente, cliente_b)

    assert cliente.get(f"/portal/vencimientos/{v_b}/mensajes").status_code == 200
    assert cliente.get(f"/portal/vencimientos/{v_a}/mensajes").status_code == 404


def test_marcar_mensajes_leidos_solo_afecta_al_otro_autor():
    tenant_id, cliente_id = _cliente_de_prueba(email="leidos@ejemplo.com")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    db.crear_mensaje_vencimiento(v_id, "cliente", "Uno")
    db.crear_mensaje_vencimiento(v_id, "empleado", "Dos", usuario_id=db.usuario_local_id())

    db.marcar_mensajes_leidos(v_id, "cliente")  # lee el cliente -> marca los de "empleado"

    mensajes = {m["autor"]: m for m in db.listar_mensajes_vencimiento(v_id)}
    assert mensajes["empleado"]["leido_en"] is not None
    assert mensajes["cliente"]["leido_en"] is None


# --- v2: solicitudes de acceso al portal ------------------------------------

def test_solicitar_acceso_sin_captcha_valido_no_crea_solicitud(cliente):
    resp = cliente.post(
        "/portal/solicitar-acceso",
        data={"nombre": "Nuevo Cliente", "email": "nuevo@ejemplo.com"},
    )
    assert resp.status_code == 200
    assert not db.listar_solicitudes_acceso_portal()


def test_solicitar_acceso_con_captcha_valido_crea_solicitud(cliente, monkeypatch):
    from app import rutas_portal_cliente

    monkeypatch.setattr(rutas_portal_cliente.captcha, "verificar_solucion", lambda payload: True)
    resp = cliente.post(
        "/portal/solicitar-acceso",
        data={"nombre": "Nuevo Cliente", "email": "nuevo@ejemplo.com", "nif": "12345678Z", "mensaje": "Quiero acceso"},
    )
    assert resp.status_code == 200
    solicitudes = db.listar_solicitudes_acceso_portal()
    assert len(solicitudes) == 1
    assert solicitudes[0]["email"] == "nuevo@ejemplo.com"
    assert solicitudes[0]["atendida"] == 0


def test_backoffice_vincula_solicitud_a_cliente_existente(cliente, monkeypatch):
    from app import rutas_portal_cliente
    from tests.conftest import iniciar_sesion_de_prueba

    monkeypatch.setattr(rutas_portal_cliente.captcha, "verificar_solucion", lambda payload: True)
    cliente.post("/portal/solicitar-acceso", data={"nombre": "Vincular Test", "email": "vincular@ejemplo.com"})
    solicitud_id = db.listar_solicitudes_acceso_portal()[0]["id"]

    _, cliente_fiscal_id = _cliente_de_prueba(nombre="Existente", email=None)

    iniciar_sesion_de_prueba(cliente, "admin-vincular@ejemplo.com", "contrasena123")
    db.hacer_admin("admin-vincular@ejemplo.com")

    resp = cliente.post(
        f"/backoffice/solicitudes-portal/{solicitud_id}/vincular",
        data={"cliente_fiscal_id": cliente_fiscal_id},
    )
    assert resp.status_code == 302

    cliente_actualizado = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    assert cliente_actualizado["email"] == "vincular@ejemplo.com"
    solicitud = db.listar_solicitudes_acceso_portal()[0]
    assert solicitud["atendida"] == 1


def test_backoffice_crea_cliente_nuevo_desde_solicitud(cliente, monkeypatch):
    from app import rutas_portal_cliente
    from tests.conftest import iniciar_sesion_de_prueba

    monkeypatch.setattr(rutas_portal_cliente.captcha, "verificar_solucion", lambda payload: True)
    cliente.post(
        "/portal/solicitar-acceso",
        data={"nombre": "Cliente Nuevo Desde Solicitud", "email": "crear@ejemplo.com", "nif": "B87654321"},
    )
    solicitud_id = db.listar_solicitudes_acceso_portal()[0]["id"]

    admin_id = iniciar_sesion_de_prueba(cliente, "admin-crear@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Crear Desde Solicitud")
    db.asignar_tenant(admin_id, tenant_id)
    db.hacer_admin("admin-crear@ejemplo.com")

    resp = cliente.post(
        f"/backoffice/solicitudes-portal/{solicitud_id}/crear-cliente",
        data={"tenant_id": tenant_id},
    )
    assert resp.status_code == 302

    clientes_tenant = db.listar_clientes_fiscales(tenant_id)
    assert len(clientes_tenant) == 1
    assert clientes_tenant[0]["email"] == "crear@ejemplo.com"
    assert clientes_tenant[0]["nif"] == "B87654321"
    solicitud = db.listar_solicitudes_acceso_portal()[0]
    assert solicitud["atendida"] == 1


# --- Notificación por email al cliente cuando el equipo responde -----------

def test_responder_mensaje_notifica_por_email_si_cliente_tiene_email(cliente, monkeypatch):
    from tests.conftest import iniciar_sesion_de_prueba

    tenant_id, cliente_id = _cliente_de_prueba(email="respuesta-a@ejemplo.com")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    admin_id = iniciar_sesion_de_prueba(cliente, "empleado-a@ejemplo.com", "contrasena123")
    db.asignar_tenant(admin_id, tenant_id)

    llamadas = []
    monkeypatch.setattr(
        "app.rutas_fiscal.enviar_respuesta_portal",
        lambda email, texto, url: llamadas.append((email, texto)),
    )

    resp = cliente.post(f"/fiscal/vencimientos/{v_id}/mensajes", data={"texto": "Ya está presentado"})
    assert resp.status_code == 302
    assert len(llamadas) == 1
    assert llamadas[0] == ("respuesta-a@ejemplo.com", "Ya está presentado")


def test_responder_mensaje_sin_email_del_cliente_no_notifica(cliente, monkeypatch):
    from tests.conftest import iniciar_sesion_de_prueba

    tenant_id, cliente_id = _cliente_de_prueba(email=None)
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    admin_id = iniciar_sesion_de_prueba(cliente, "empleado-b@ejemplo.com", "contrasena123")
    db.asignar_tenant(admin_id, tenant_id)

    llamadas = []
    monkeypatch.setattr("app.rutas_fiscal.enviar_respuesta_portal", lambda *a, **k: llamadas.append(a))

    resp = cliente.post(f"/fiscal/vencimientos/{v_id}/mensajes", data={"texto": "Hola"})
    assert resp.status_code == 302
    assert not llamadas


def test_responder_mensaje_con_smtp_roto_no_rompe_la_respuesta(cliente, monkeypatch):
    from tests.conftest import iniciar_sesion_de_prueba
    from app.notificaciones_email import ErrorNotificacionesEmail

    tenant_id, cliente_id = _cliente_de_prueba(email="respuesta-c@ejemplo.com")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")
    admin_id = iniciar_sesion_de_prueba(cliente, "empleado-c@ejemplo.com", "contrasena123")
    db.asignar_tenant(admin_id, tenant_id)

    def _falla(*a, **k):
        raise ErrorNotificacionesEmail("SMTP caído")

    monkeypatch.setattr("app.rutas_fiscal.enviar_respuesta_portal", _falla)

    resp = cliente.post(f"/fiscal/vencimientos/{v_id}/mensajes", data={"texto": "Hola"})
    assert resp.status_code == 302
    mensajes = db.listar_mensajes_vencimiento(v_id)
    assert len(mensajes) == 1  # el mensaje se guardó igual, el fallo de SMTP no lo impidió
