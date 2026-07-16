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
