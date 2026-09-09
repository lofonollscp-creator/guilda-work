"""Tests de los filtros de plantilla puros del rediseño de Correo estilo
New Outlook (app/rutas_correo.py): avatares, fecha relativa y previsualización.

También cubre las 4 rutas de acciones en lote (/correo/mensajes/eliminar,
/marcar-leido, /destacar, /mover) -- antes sin ningún test a nivel de ruta,
el camino de "algún mensaje falla a medias" (solo posible en /mover, la
única que toca el servidor IMAP de verdad -- ver app/correo.py) estaba
completamente sin probar.
"""
from datetime import date, timedelta

from app import db, rutas_correo
from app.correo import ErrorCorreo
from app.rutas_correo import fecha_relativa, iniciales, vista_previa
from tests.conftest import iniciar_sesion_de_prueba


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


# --- Ruta: plantillas de respuesta guardadas --------------------------------

def test_crear_plantilla_requiere_login(cliente):
    resp = cliente.post("/correo/ajustes/plantillas", data={"nombre": "X", "cuerpo": "Y"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_crear_y_eliminar_plantilla_desde_la_ruta(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    iniciar_sesion_de_prueba(cliente, "plantilla-ruta@ejemplo.com", "contrasena123")

    resp = cliente.post(
        "/correo/ajustes/plantillas",
        data={"nombre": "Recordatorio", "asunto": "Docs pendientes", "cuerpo": "Hola, nos falta la factura."},
    )
    assert resp.status_code == 302

    resp = cliente.get("/correo/ajustes")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Recordatorio" in html

    import re
    match = re.search(r"/correo/ajustes/plantillas/(\d+)/eliminar", html)
    assert match is not None
    plantilla_id = match.group(1)

    resp = cliente.post(f"/correo/ajustes/plantillas/{plantilla_id}/eliminar")
    assert resp.status_code == 302
    # "Recordatorio" solo, a secas, seguiría apareciendo en el placeholder del
    # propio formulario de creación ("ej. Recordatorio de documentación") --
    # se busca el texto exacto de la fila de la lista, no la palabra suelta.
    assert "<span class=\"log-text\">Recordatorio</span>" not in cliente.get("/correo/ajustes").get_data(as_text=True)


def test_crear_plantilla_sin_nombre_muestra_error_y_no_crea(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    iniciar_sesion_de_prueba(cliente, "plantilla-sin-nombre@ejemplo.com", "contrasena123")
    resp = cliente.post("/correo/ajustes/plantillas", data={"nombre": "", "cuerpo": "algo"})
    assert resp.status_code == 200
    assert "necesita un nombre" in resp.get_data(as_text=True)


def test_plantilla_json_devuelve_asunto_y_cuerpo(cliente):
    from tests.conftest import iniciar_sesion_de_prueba

    usuario_id = iniciar_sesion_de_prueba(cliente, "plantilla-json@ejemplo.com", "contrasena123")
    plantilla_id = db.crear_plantilla_correo(usuario_id, "Saludo", "Asunto X", "<p>Cuerpo</p>")

    resp = cliente.get(f"/correo/plantillas/{plantilla_id}.json")
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos == {"asunto": "Asunto X", "cuerpo": "<p>Cuerpo</p>"}


def test_plantilla_json_de_otro_usuario_da_404(cliente):
    from tests.conftest import iniciar_sesion_de_prueba
    from app.auth import limiter
    from app.main import app as flask_app

    dueno_id = iniciar_sesion_de_prueba(cliente, "plantilla-json-dueno@ejemplo.com", "contrasena123")
    plantilla_id = db.crear_plantilla_correo(dueno_id, "Saludo", None, "cuerpo")

    flask_app.config.update(TESTING=True, SERVER_NAME="127.0.0.1:8000")
    limiter.reset()
    with flask_app.test_client() as otro_cliente:
        iniciar_sesion_de_prueba(otro_cliente, "plantilla-json-otro@ejemplo.com", "contrasena123")
        resp = otro_cliente.get(f"/correo/plantillas/{plantilla_id}.json")
        assert resp.status_code == 404


# --- Acciones en lote ------------------------------------------------------

def _crear_mensaje(cuenta_id: int, uid: str) -> int:
    return db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid=uid, asunto="Asunto", remitente="a@b.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )


def test_eliminar_mensajes_lote_borra_los_del_usuario(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "lote-eliminar@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    m1 = _crear_mensaje(cuenta_id, "1")
    m2 = _crear_mensaje(cuenta_id, "2")

    resp = cliente.post("/correo/mensajes/eliminar", json={"ids": [m1, m2]})
    assert resp.status_code == 200
    assert resp.get_json() == {"procesados": 2}
    assert db.obtener_mensaje_correo(m1) is None
    assert db.obtener_mensaje_correo(m2) is None


def test_eliminar_mensajes_lote_ignora_mensajes_de_otro_usuario(cliente):
    """_ids_propios_del_usuario debe filtrar cualquier id que no
    pertenezca al usuario que hace la petición -- no basta con
    confiar en la lista que manda el propio cliente."""
    dueno_id = iniciar_sesion_de_prueba(cliente, "lote-dueno@ejemplo.com", "contrasena123")
    cuenta_dueno = db.crear_cuenta_correo(dueno_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    m_dueno = _crear_mensaje(cuenta_dueno, "1")

    cliente.post("/logout", follow_redirects=True)
    otro_id = iniciar_sesion_de_prueba(cliente, "lote-otro@ejemplo.com", "contrasena123")
    cuenta_otro = db.crear_cuenta_correo(otro_id, "Prueba", "imap", "imap.ejemplo.com", 993, "otro@ejemplo.com")
    m_otro = _crear_mensaje(cuenta_otro, "1")

    resp = cliente.post("/correo/mensajes/eliminar", json={"ids": [m_dueno, m_otro]})
    assert resp.status_code == 200
    assert resp.get_json() == {"procesados": 1}  # solo m_otro, el del propio usuario
    assert db.obtener_mensaje_correo(m_dueno) is not None  # intacto, no es suyo
    assert db.obtener_mensaje_correo(m_otro) is None


def test_marcar_leido_mensajes_lote(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "lote-leido@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    m1 = _crear_mensaje(cuenta_id, "1")

    resp = cliente.post("/correo/mensajes/marcar-leido", json={"ids": [m1], "leido": True})
    assert resp.status_code == 200
    assert resp.get_json() == {"procesados": 1}
    assert db.obtener_mensaje_correo(m1)["leido"] == 1


def test_destacar_mensajes_lote(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "lote-destacar@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    m1 = _crear_mensaje(cuenta_id, "1")

    resp = cliente.post("/correo/mensajes/destacar", json={"ids": [m1], "destacado": True})
    assert resp.status_code == 200
    assert resp.get_json() == {"procesados": 1}
    assert db.obtener_mensaje_correo(m1)["destacado"] == 1


def test_mover_mensajes_lote_todo_exito(cliente, monkeypatch):
    usuario_id = iniciar_sesion_de_prueba(cliente, "lote-mover-ok@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    m1 = _crear_mensaje(cuenta_id, "1")
    m2 = _crear_mensaje(cuenta_id, "2")

    monkeypatch.setattr(rutas_correo.correo, "mover_mensaje", lambda usuario_id, mensaje_id, carpeta: None)

    resp = cliente.post("/correo/mensajes/mover", json={"ids": [m1, m2], "carpeta": "Archivo"})
    assert resp.status_code == 200
    assert resp.get_json() == {"procesados": 2, "errores": []}


def test_mover_mensajes_lote_reporta_fallos_parciales(cliente, monkeypatch):
    """mover_mensaje es la única de las 4 acciones en lote que toca el
    servidor IMAP de verdad (las otras tres son solo caché local, ver
    app/correo.py) y puede fallar a medias -- antes de esta ronda el
    JS ni siquiera miraba el campo `errores` de la respuesta."""
    usuario_id = iniciar_sesion_de_prueba(cliente, "lote-mover-fallo@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    m_ok = _crear_mensaje(cuenta_id, "1")
    m_falla = _crear_mensaje(cuenta_id, "2")

    def _fake_mover(usuario_id, mensaje_id, carpeta):
        if mensaje_id == m_falla:
            raise ErrorCorreo("No se ha podido mover ese mensaje.")

    monkeypatch.setattr(rutas_correo.correo, "mover_mensaje", _fake_mover)

    resp = cliente.post("/correo/mensajes/mover", json={"ids": [m_ok, m_falla], "carpeta": "Archivo"})
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos["procesados"] == 1
    assert datos["errores"] == ["No se ha podido mover ese mensaje."]


def test_acciones_en_lote_requieren_login(cliente):
    for ruta in ("eliminar", "marcar-leido", "destacar", "mover"):
        resp = cliente.post(f"/correo/mensajes/{ruta}", json={"ids": [1]})
        assert resp.status_code == 302


# --- Borradores ---------------------------------------------------------------

def test_guardar_borrador_requiere_login(cliente):
    resp = cliente.post("/correo/borradores/guardar", data={"asunto": "X"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_guardar_borrador_crea_y_reabrir_lo_precarga(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "borrador-ruta@ejemplo.com", "contrasena123")
    db.crear_cuenta_correo(
        usuario_id, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com",
        smtp_host="smtp.ejemplo.com",
    )

    resp = cliente.post(
        "/correo/borradores/guardar",
        data={"destinatarios": "a@b.com", "asunto": "Asunto guardado", "cuerpo_html": "<p>Hola</p>"},
    )
    assert resp.status_code == 200
    borrador_id = resp.get_json()["borrador_id"]

    resp = cliente.get("/correo/borradores")
    assert resp.status_code == 200
    assert "Asunto guardado" in resp.get_data(as_text=True)

    resp = cliente.get(f"/correo/redactar?borrador_id={borrador_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Asunto guardado" in html
    assert "a@b.com" in html


def test_guardar_borrador_con_id_existente_lo_actualiza_sin_duplicar(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "borrador-actualiza@ejemplo.com", "contrasena123")

    resp = cliente.post("/correo/borradores/guardar", data={"asunto": "Primero"})
    borrador_id = resp.get_json()["borrador_id"]

    resp = cliente.post("/correo/borradores/guardar", data={"borrador_id": borrador_id, "asunto": "Segundo"})
    assert resp.get_json()["borrador_id"] == borrador_id
    assert len(db.listar_borradores_correo(usuario_id)) == 1


def test_redactar_con_borrador_de_otro_usuario_da_404(cliente):
    otro_id = iniciar_sesion_de_prueba(cliente, "borrador-dueno@ejemplo.com", "contrasena123")
    borrador_id = db.guardar_borrador_correo(
        otro_id, None, cuenta_id=None, destinatarios="", cc="", bcc="",
        asunto="Ajeno", cuerpo_html="", en_respuesta_a=None,
    )
    cliente.post("/logout", follow_redirects=True)
    iniciar_sesion_de_prueba(cliente, "borrador-intruso@ejemplo.com", "contrasena123")
    resp = cliente.get(f"/correo/redactar?borrador_id={borrador_id}")
    assert resp.status_code == 404


def test_eliminar_borrador_lo_quita_de_la_lista(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "borrador-elimina@ejemplo.com", "contrasena123")
    borrador_id = db.guardar_borrador_correo(
        usuario_id, None, cuenta_id=None, destinatarios="", cc="", bcc="",
        asunto="A borrar", cuerpo_html="", en_respuesta_a=None,
    )
    resp = cliente.post(f"/correo/borradores/{borrador_id}/eliminar")
    assert resp.status_code == 302
    assert db.obtener_borrador_correo(usuario_id, borrador_id) is None


# --- Vista previa de adjuntos (imagen/PDF) en la bandeja -----------------

def test_adjunto_previsualizable_de_remitente_confiable_muestra_vista_previa(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "adjunto-confiable@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Con imagen", remitente="amigo@ejemplo.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    db.guardar_adjuntos_correo(mensaje_id, [{"nombre": "foto.png", "tipo": "image/png", "bytes": b"fake-png"}])
    db.confiar_en_remitente(usuario_id, "amigo@ejemplo.com")

    resp = cliente.get(f"/correo/?cuenta_id={cuenta_id}&mensaje_id={mensaje_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "correo-adjunto-preview-imagen" in html


def test_adjunto_previsualizable_de_remitente_no_confiable_no_muestra_vista_previa(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "adjunto-no-confiable@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Con imagen", remitente="desconocido@ejemplo.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    db.guardar_adjuntos_correo(mensaje_id, [{"nombre": "foto.png", "tipo": "image/png", "bytes": b"fake-png"}])

    resp = cliente.get(f"/correo/?cuenta_id={cuenta_id}&mensaje_id={mensaje_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "correo-adjunto-preview-imagen" not in html
    assert "foto.png" in html  # el chip de descarga se sigue mostrando


def test_adjunto_pdf_de_remitente_confiable_muestra_embed(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "adjunto-pdf@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Con PDF", remitente="amigo@ejemplo.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    db.guardar_adjuntos_correo(mensaje_id, [{"nombre": "informe.pdf", "tipo": "application/pdf", "bytes": b"%PDF-fake"}])
    db.confiar_en_remitente(usuario_id, "amigo@ejemplo.com")

    resp = cliente.get(f"/correo/?cuenta_id={cuenta_id}&mensaje_id={mensaje_id}")
    assert resp.status_code == 200
    assert "correo-adjunto-preview-pdf" in resp.get_data(as_text=True)


def test_adjunto_no_previsualizable_nunca_muestra_vista_previa(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "adjunto-zip@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Con zip", remitente="amigo@ejemplo.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    db.guardar_adjuntos_correo(mensaje_id, [{"nombre": "datos.zip", "tipo": "application/zip", "bytes": b"PK\x03\x04"}])
    db.confiar_en_remitente(usuario_id, "amigo@ejemplo.com")

    resp = cliente.get(f"/correo/?cuenta_id={cuenta_id}&mensaje_id={mensaje_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "correo-adjunto-preview-imagen" not in html
    assert "correo-adjunto-preview-pdf" not in html


def test_descargar_adjunto_imagen_sirve_content_disposition_inline(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "adjunto-descarga@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Con imagen", remitente="a@b.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    db.guardar_adjuntos_correo(mensaje_id, [{"nombre": "foto.png", "tipo": "image/png", "bytes": b"fake-png"}])
    adjunto_id = db.listar_adjuntos_correo(mensaje_id)[0]["id"]

    resp = cliente.get(f"/correo/{mensaje_id}/adjunto/{adjunto_id}")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith("inline")


def test_descargar_adjunto_zip_sigue_forzando_descarga(cliente):
    usuario_id = iniciar_sesion_de_prueba(cliente, "adjunto-descarga-zip@ejemplo.com", "contrasena123")
    cuenta_id = db.crear_cuenta_correo(usuario_id, "Prueba", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com")
    mensaje_id = db.guardar_mensaje_correo(
        cuenta_id=cuenta_id, uid="1", asunto="Con zip", remitente="a@b.com",
        destinatarios="yo@ejemplo.com", fecha=None, cuerpo_texto="cuerpo", cuerpo_html=None,
    )
    db.guardar_adjuntos_correo(mensaje_id, [{"nombre": "datos.zip", "tipo": "application/zip", "bytes": b"PK\x03\x04"}])
    adjunto_id = db.listar_adjuntos_correo(mensaje_id)[0]["id"]

    resp = cliente.get(f"/correo/{mensaje_id}/adjunto/{adjunto_id}")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith("attachment")


def test_eliminar_borrador_de_otro_usuario_no_hace_nada(cliente):
    dueno_id = iniciar_sesion_de_prueba(cliente, "borrador-dueno2@ejemplo.com", "contrasena123")
    borrador_id = db.guardar_borrador_correo(
        dueno_id, None, cuenta_id=None, destinatarios="", cc="", bcc="",
        asunto="Protegido", cuerpo_html="", en_respuesta_a=None,
    )
    cliente.post("/logout", follow_redirects=True)
    iniciar_sesion_de_prueba(cliente, "borrador-intruso2@ejemplo.com", "contrasena123")
    cliente.post(f"/correo/borradores/{borrador_id}/eliminar")
    assert db.obtener_borrador_correo(dueno_id, borrador_id) is not None
