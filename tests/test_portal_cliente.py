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
