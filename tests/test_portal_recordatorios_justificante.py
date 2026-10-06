"""Bloque 7: recordatorios por correo del portal, subida de varios documentos,
justificante oficial y constancia de presentación."""
import io
from datetime import datetime, timedelta

import pytest

from app import constancia_presentacion, db, notificaciones_email, portal_recordatorios
from tests.conftest import iniciar_sesion_de_prueba

HOY = datetime(2026, 4, 13, 9, 0)


def _cliente(nombre="Cliente", email="cliente@ejemplo.com", tenant_id=None):
    tenant_id = tenant_id or db.crear_tenant(f"Gestoria {nombre}")
    return tenant_id, db.crear_cliente_fiscal(tenant_id, nombre, email=email)


def _dias(n):
    return (HOY + timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture
def smtp(monkeypatch):
    enviados = []
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda dest, asunto, cuerpo: enviados.append((dest, asunto, cuerpo)))
    monkeypatch.setenv("GUILDA_URL_PUBLICA", "https://work.ejemplo.com/")
    return enviados


# --- recordatorios ----------------------------------------------------------

def test_recordatorio_a_7_y_2_dias_una_sola_vez(smtp):
    tenant, cid = _cliente("Panadería", "pan@ejemplo.com")
    siete = db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T1", _dias(7))
    dos = db.crear_vencimiento_fiscal(tenant, cid, "130", "2026-T1", _dias(2))
    db.crear_vencimiento_fiscal(tenant, cid, "111", "2026-T1", _dias(4))  # a 4 días: no toca
    assert portal_recordatorios.procesar_recordatorios(HOY) == 2
    asuntos = sorted(a for _, a, _ in smtp)
    assert asuntos == ["Recordatorio: el 130 vence dentro de 2 días", "Recordatorio: el 303 vence dentro de 7 días"]
    assert all(d == "pan@ejemplo.com" for d, _, _ in smtp)
    assert "https://work.ejemplo.com/portal/entrar" in smtp[0][2] and "Gestoria Panadería" in smtp[0][2]
    assert portal_recordatorios.procesar_recordatorios(HOY) == 0  # sin duplicados
    assert len(smtp) == 2
    # al día siguiente el de 7 días ya está a 6: no se reenvía, y el de 2 está a 1: tampoco
    assert portal_recordatorios.procesar_recordatorios(HOY + timedelta(days=1)) == 0


def test_no_recuerda_presentados_sin_email_papelera_ni_opt_out(smtp):
    tenant, c1 = _cliente("Presentado", "a@ejemplo.com")
    v1 = db.crear_vencimiento_fiscal(tenant, c1, "303", "2026-T1", _dias(7))
    db.marcar_presentado_vencimiento_fiscal(tenant, v1)
    _, c2 = _cliente("SinEmail", None, tenant)
    db.crear_vencimiento_fiscal(tenant, c2, "303", "2026-T1", _dias(7))
    _, c3 = _cliente("OptOut", "optout@ejemplo.com", tenant)
    db.crear_vencimiento_fiscal(tenant, c3, "303", "2026-T1", _dias(7))
    db.editar_cliente_fiscal(tenant, c3, recordatorios_portal=0)
    _, c4 = _cliente("Papelera", "papelera@ejemplo.com", tenant)
    v4 = db.crear_vencimiento_fiscal(tenant, c4, "303", "2026-T1", _dias(7))
    db.eliminar_vencimiento_fiscal(tenant, v4)
    assert portal_recordatorios.procesar_recordatorios(HOY) == 0 and smtp == []


def test_sin_smtp_no_envia_ni_marca_y_el_fallo_de_uno_no_frena_a_los_demas(monkeypatch):
    tenant, cid = _cliente("Sin smtp", "s@ejemplo.com")
    db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T1", _dias(2))
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: False)
    assert portal_recordatorios.procesar_recordatorios(HOY) == 0
    # configurado ya: sale (no se marcó nada antes)
    enviados = []
    monkeypatch.setattr(notificaciones_email, "configurado", lambda: True)

    def _enviar(dest, asunto, cuerpo):
        if dest == "roto@ejemplo.com":
            raise notificaciones_email.ErrorNotificacionesEmail("buzón lleno")
        enviados.append(dest)

    monkeypatch.setattr(notificaciones_email, "_enviar", _enviar)
    _, roto = _cliente("Roto", "roto@ejemplo.com", tenant)
    db.crear_vencimiento_fiscal(tenant, roto, "303", "2026-T1", _dias(2))
    assert portal_recordatorios.procesar_recordatorios(HOY) == 1 and enviados == ["s@ejemplo.com"]
    # el roto no quedó marcado: se reintenta en la siguiente pasada del día
    enviados.clear()
    monkeypatch.setattr(notificaciones_email, "_enviar", lambda d, a, c: enviados.append(d))
    assert portal_recordatorios.procesar_recordatorios(HOY) == 1 and enviados == ["roto@ejemplo.com"]


def test_sin_url_publica_el_correo_sale_sin_enlace(smtp, monkeypatch):
    monkeypatch.delenv("GUILDA_URL_PUBLICA", raising=False)
    tenant, cid = _cliente("SinUrl", "u@ejemplo.com")
    db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T1", _dias(7))
    assert portal_recordatorios.url_portal() is None
    assert portal_recordatorios.procesar_recordatorios(HOY) == 1 and "portal/entrar" not in smtp[0][2]


def test_la_ficha_del_cliente_activa_y_desactiva_los_recordatorios(cliente):
    gestor = iniciar_sesion_de_prueba(cliente, "b7-ficha@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Gestoria Ficha B7")
    db.asignar_tenant(gestor, tenant)
    _, cid = _cliente("Ficha", "ficha@ejemplo.com", tenant)
    assert db.obtener_cliente_fiscal(tenant, cid)["recordatorios_portal"] == 1
    cliente.post(f"/fiscal/clientes/{cid}/editar", data={"nombre": "Ficha", "email": "ficha@ejemplo.com", "pais": "ES"})
    assert db.obtener_cliente_fiscal(tenant, cid)["recordatorios_portal"] == 0
    cliente.post(f"/fiscal/clientes/{cid}/editar", data={"nombre": "Ficha", "pais": "ES", "recordatorios_portal": "on"})
    assert db.obtener_cliente_fiscal(tenant, cid)["recordatorios_portal"] == 1
    assert "recordatorios por correo" in cliente.get(f"/fiscal/clientes/{cid}/editar").get_data(as_text=True)


# --- subida de varios documentos --------------------------------------------

def _entrar_como_cliente(cliente_http, email):
    tenant, cid = _cliente("Subida", email)
    v = db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T1", "2026-04-20")
    cliente_http.get(f"/portal/entrar/{db.crear_acceso_cliente_fiscal(cid, '127.0.0.1')}")
    return tenant, cid, v


def _archivo(nombre, mime="application/pdf", contenido=b"%PDF-1.4 x"):
    return (io.BytesIO(contenido), nombre, mime)


def test_subida_multiple_valida_cada_archivo(cliente):
    _, _, v = _entrar_como_cliente(cliente, "multi@ejemplo.com")
    resp = cliente.post(
        f"/portal/vencimientos/{v}/documentos", content_type="multipart/form-data",
        data={"documento": [_archivo("a.pdf"), _archivo("malo.exe", "application/x-msdownload"), _archivo("c.png", "image/png")]},
    )
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and "a.pdf" in html and "malo.exe" in html and "Subido." in html
    nombres = sorted(d["nombre_archivo"] for d in db.listar_documentos_vencimiento(v))
    assert nombres == ["a.pdf", "c.png"]  # el válido de cada uno se guarda, el inválido no


def test_subida_multiple_todo_valido_redirige_y_tope_de_10(cliente):
    _, _, v = _entrar_como_cliente(cliente, "multi2@ejemplo.com")
    ok = cliente.post(f"/portal/vencimientos/{v}/documentos", content_type="multipart/form-data",
                      data={"documento": [_archivo(f"{i}.pdf") for i in range(3)]})
    assert ok.status_code == 302 and len(db.listar_documentos_vencimiento(v)) == 3
    demasiados = cliente.post(f"/portal/vencimientos/{v}/documentos", content_type="multipart/form-data",
                              data={"documento": [_archivo(f"x{i}.pdf") for i in range(11)]})
    assert demasiados.status_code == 200 and "hasta 10 archivos" in demasiados.get_data(as_text=True)
    assert len(db.listar_documentos_vencimiento(v)) == 3  # no se guardó ninguno


def test_documento_demasiado_grande_se_rechaza(cliente):
    _, _, v = _entrar_como_cliente(cliente, "grande@ejemplo.com")
    grande = b"0" * (db.TAMANO_MAXIMO_DOCUMENTO_VENCIMIENTO + 1)
    resp = cliente.post(f"/portal/vencimientos/{v}/documentos", content_type="multipart/form-data",
                        data={"documento": _archivo("grande.pdf", contenido=grande)})
    assert resp.status_code == 200 and db.listar_documentos_vencimiento(v) == []


# --- justificante y constancia ----------------------------------------------

def test_la_solicitud_de_documento_solo_se_resuelve_con_lo_que_sube_el_cliente(cliente):
    tenant, cid, v = _entrar_como_cliente(cliente, "solicitud@ejemplo.com")
    db.editar_vencimiento_fiscal(tenant, v, documento_solicitado="Factura de compra")
    db.subir_documento_vencimiento(v, "constancia.pdf", "application/pdf", b"%PDF", origen="constancia")
    assert "Factura de compra" in cliente.get("/portal/").get_data(as_text=True)  # sigue pendiente
    db.subir_documento_vencimiento(v, "factura.pdf", "application/pdf", b"%PDF")
    assert db.listar_documentos_vencimiento(v, origen="cliente")[0]["nombre_archivo"] == "factura.pdf"


def test_marcar_presentado_genera_la_constancia_y_el_cliente_la_descarga(cliente):
    gestor = iniciar_sesion_de_prueba(cliente, "b7-presentado@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Gestoria Presentado")
    db.asignar_tenant(gestor, tenant)
    _, cid = _cliente("Cliente Presentado", "cp@ejemplo.com", tenant)
    v = db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T1", "2026-04-20")
    resp = cliente.post(
        f"/fiscal/vencimientos/{v}/presentado", content_type="multipart/form-data",
        data={"justificante": _archivo("justificante-aeat.pdf")},
    )
    assert resp.status_code == 302
    origenes = {d["origen"]: d for d in db.listar_documentos_vencimiento(v)}
    assert set(origenes) == {"justificante", "constancia"}
    constancia = db.contenido_documento_vencimiento(db.obtener_documento_vencimiento(origenes["constancia"]["id"]))
    assert constancia.startswith(b"%PDF")
    # volver a presentar no duplica la constancia
    cliente.post(f"/fiscal/vencimientos/{v}/constancia")
    assert [d["origen"] for d in db.listar_documentos_vencimiento(v)].count("constancia") == 1

    # el cliente (otro navegador) ve y descarga ambos, y solo los de SU vencimiento
    from app.auth import limiter
    from app.main import app as flask_app
    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as portal:
        portal.get(f"/portal/entrar/{db.crear_acceso_cliente_fiscal(cid, '127.0.0.1')}")
        pagina = portal.get(f"/portal/vencimientos/{v}/documentos").get_data(as_text=True)
        assert "Justificante oficial" in pagina and "Constancia de presentación" in pagina
        descarga = portal.get(f"/portal/vencimientos/{v}/documentos/{origenes['constancia']['id']}")
        assert descarga.status_code == 200 and descarga.data.startswith(b"%PDF")
        assert "attachment" in descarga.headers["Content-Disposition"]
        _, otro_cid = _cliente("Otro", "otro@ejemplo.com", tenant)
        otro_v = db.crear_vencimiento_fiscal(tenant, otro_cid, "130", "2026-T1", "2026-04-20")
        doc_ajeno = db.subir_documento_vencimiento(otro_v, "secreto.pdf", "application/pdf", b"%PDF", origen="justificante")
        assert portal.get(f"/portal/vencimientos/{otro_v}/documentos/{doc_ajeno}").status_code == 404
        assert portal.get(f"/portal/vencimientos/{v}/documentos/{doc_ajeno}").status_code == 404


def test_subir_justificante_despues_actualiza_la_constancia_y_rechaza_archivos_invalidos(cliente):
    gestor = iniciar_sesion_de_prueba(cliente, "b7-just@ejemplo.com", "contrasena123")
    tenant = db.crear_tenant("Gestoria Justificante")
    db.asignar_tenant(gestor, tenant)
    _, cid = _cliente("CJ", "cj@ejemplo.com", tenant)
    v = db.crear_vencimiento_fiscal(tenant, cid, "303", "2026-T1", "2026-04-20")
    cliente.post(f"/fiscal/vencimientos/{v}/presentado")  # sin justificante todavía
    assert [d["origen"] for d in db.listar_documentos_vencimiento(v)] == ["constancia"]
    mala = cliente.post(f"/fiscal/vencimientos/{v}/justificante", content_type="multipart/form-data",
                        data={"justificante": _archivo("x.exe", "application/x-msdownload")})
    assert mala.status_code == 400
    buena = cliente.post(f"/fiscal/vencimientos/{v}/justificante", content_type="multipart/form-data",
                         data={"justificante": _archivo("oficial.pdf")})
    assert buena.status_code == 302
    assert sorted(d["origen"] for d in db.listar_documentos_vencimiento(v)) == ["constancia", "justificante"]
    # de otro tenant: 404
    otro_tenant = db.crear_tenant("Otra gestoría")
    _, c2 = _cliente("Ajeno", "ajeno@ejemplo.com", otro_tenant)
    v2 = db.crear_vencimiento_fiscal(otro_tenant, c2, "303", "2026-T1", "2026-04-20")
    assert cliente.post(f"/fiscal/vencimientos/{v2}/justificante", content_type="multipart/form-data",
                        data={"justificante": _archivo("a.pdf")}).status_code == 404


def test_pdf_de_constancia_contiene_el_aviso_y_escapa_el_texto(app_context=None):
    from app.main import app as flask_app
    with flask_app.test_request_context("/"):
        pdf = constancia_presentacion.generar_pdf(
            "Gestoría <b>X</b> & Cía", "Cliente <script>", None, "303", "2026-T1", "2026-04-20",
            datetime(2026, 4, 13, 10, 0), con_justificante=False,
        )
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000
