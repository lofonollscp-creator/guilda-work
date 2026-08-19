"""Tests de los filtros de plantilla puros del rediseño de Correo estilo
New Outlook (app/rutas_correo.py): avatares, fecha relativa y previsualización.
"""
from datetime import date, timedelta

from app import db
from app.rutas_correo import fecha_relativa, iniciales, vista_previa


def test_iniciales_con_nombre_y_apellido():
    assert iniciales("Juan Pérez <juan@ejemplo.com>") == "JP"


def test_iniciales_con_una_sola_palabra():
    assert iniciales("Juan <juan@ejemplo.com>") == "JU"


def test_iniciales_sin_nombre_usa_el_email():
    assert iniciales("boletin@ejemplo.com") == "BO"


def test_iniciales_sin_remitente():
    assert iniciales(None) == "?"
    assert iniciales("") == "?"


def test_fecha_relativa_hoy_muestra_hora():
    ahora = date.today().isoformat() + "T14:32:00"
    assert fecha_relativa(ahora) == "14:32"


def test_fecha_relativa_ayer():
    ayer = (date.today() - timedelta(days=1)).isoformat() + "T09:00:00"
    assert fecha_relativa(ayer) == "Ayer"


def test_fecha_relativa_esta_semana_usa_abreviatura_de_dia():
    hace_tres_dias = date.today() - timedelta(days=3)
    valor = hace_tres_dias.isoformat() + "T09:00:00"
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    assert fecha_relativa(valor) == dias[hace_tres_dias.weekday()]


def test_fecha_relativa_antigua_usa_dia_y_mes():
    hace_un_mes = date.today() - timedelta(days=35)
    valor = hace_un_mes.isoformat() + "T09:00:00"
    assert fecha_relativa(valor) == f"{hace_un_mes.day} {['','ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'][hace_un_mes.month]}"


def test_fecha_relativa_vacia():
    assert fecha_relativa(None) == ""
    assert fecha_relativa("") == ""


def test_vista_previa_usa_cuerpo_texto(usuario_id):
    tid = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    db.guardar_mensaje_correo(
        cuenta_id=tid, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com",
        fecha=None, cuerpo_texto="Este   es\nun cuerpo  con espacios raros", cuerpo_html=None,
    )
    mensaje = db.listar_mensajes_correo(tid)[0]
    assert vista_previa(mensaje) == "Este es un cuerpo con espacios raros"


def test_vista_previa_usa_html_si_no_hay_texto_plano(usuario_id):
    tid = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    db.guardar_mensaje_correo(
        cuenta_id=tid, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com",
        fecha=None, cuerpo_texto=None, cuerpo_html="<p>Solo <b>HTML</b></p>",
    )
    mensaje = db.listar_mensajes_correo(tid)[0]
    assert vista_previa(mensaje) == "Solo HTML"


def test_vista_previa_recorta_a_la_longitud_pedida(usuario_id):
    tid = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    db.guardar_mensaje_correo(
        cuenta_id=tid, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com",
        fecha=None, cuerpo_texto="a" * 200, cuerpo_html=None,
    )
    mensaje = db.listar_mensajes_correo(tid)[0]
    assert len(vista_previa(mensaje, longitud=50)) == 50


def test_vista_previa_sin_cuerpo(usuario_id):
    tid = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    db.guardar_mensaje_correo(
        cuenta_id=tid, uid="1", asunto="Hola", remitente="a@b.com", destinatarios="yo@ejemplo.com",
        fecha=None, cuerpo_texto=None, cuerpo_html=None,
    )
    mensaje = db.listar_mensajes_correo(tid)[0]
    assert vista_previa(mensaje) == ""


# --- Ruta: vincular un correo a un cliente fiscal --------------------------

def test_asignar_cliente_fiscal_requiere_login(cliente):
    resp = cliente.post("/correo/1/cliente-fiscal", data={"cliente_fiscal_id": "1"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_asignar_cliente_fiscal_vincula_el_mensaje(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    usuario_id = iniciar_sesion_de_prueba(cliente, "correo-cliente-fiscal@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Correo Ruta")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_fiscal_id = db.crear_cliente_fiscal(tenant_id, "Panaderia Ruta")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Consulta", remitente="a@b.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="", cuerpo_html=None,
    )

    resp = cliente.post(f"/correo/{mensaje_id}/cliente-fiscal", data={"cliente_fiscal_id": str(cliente_fiscal_id)})
    assert resp.status_code == 302
    mensaje = db.listar_mensajes_correo(cuenta_id)[0]
    assert mensaje["cliente_fiscal_id"] == cliente_fiscal_id


def test_asignar_cliente_fiscal_sin_tenant_no_hace_nada(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    usuario_id = iniciar_sesion_de_prueba(cliente, "correo-sin-tenant@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Consulta", remitente="a@b.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="", cuerpo_html=None,
    )

    resp = cliente.post(f"/correo/{mensaje_id}/cliente-fiscal", data={"cliente_fiscal_id": "1"})
    assert resp.status_code == 302
    mensaje = db.listar_mensajes_correo(cuenta_id)[0]
    assert mensaje["cliente_fiscal_id"] is None


def test_asignar_cliente_fiscal_de_mensaje_ajeno_da_404(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    from app.auth import limiter
    from app.main import app as flask_app

    dueno_id = iniciar_sesion_de_prueba(cliente, "correo-dueno@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Dueno")
    db.asignar_tenant(dueno_id, tenant_id)
    cuenta_id = db.crear_cuenta_correo(dueno_id, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Consulta", remitente="a@b.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="", cuerpo_html=None,
    )

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as otro_cliente:
        otro_id = iniciar_sesion_de_prueba(otro_cliente, "correo-otro@ejemplo.com", "contrasena123")
        db.asignar_tenant(otro_id, tenant_id)
        resp = otro_cliente.post(f"/correo/{mensaje_id}/cliente-fiscal", data={"cliente_fiscal_id": "1"})
        assert resp.status_code == 404
