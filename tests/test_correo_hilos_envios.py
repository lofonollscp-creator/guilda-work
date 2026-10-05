"""Bloque 3B/3C: conversaciones (hilos) y cola de envío (deshacer envío y
envíos programados)."""
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

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


def _montar(cliente, email, smtp=True):
    uid = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    tenant = db.crear_tenant("Gestoria " + email)
    db.asignar_tenant(uid, tenant)
    cuenta = db.crear_cuenta_correo(
        uid, "Trabajo", "imap", "imap.ejemplo.com", 993, "yo@ejemplo.com",
        smtp_host="smtp.ejemplo.com" if smtp else None, smtp_puerto=587 if smtp else None,
    )
    return uid, cuenta


def _msg(cuenta, uid, asunto="Asunto", remitente="ana@ejemplo.com", dest="yo@ejemplo.com", **kw):
    return db.guardar_mensaje_correo(
        cuenta_id=cuenta, uid=uid, asunto=asunto, remitente=remitente, destinatarios=dest,
        fecha=kw.pop("fecha", "2026-03-10T10:00:00"), cuerpo_texto="cuerpo", cuerpo_html=None, **kw,
    )


def _hilo(mid):
    return db.obtener_mensaje_correo(mid)["hilo_clave"]


# --- hilos ------------------------------------------------------------------

def test_normalizar_asunto_quita_prefijos_repetidos():
    assert db.normalizar_asunto("RE: Re: Rv: Fwd: Modelo  303 ") == "modelo 303"
    assert db.normalizar_asunto("Re[2]: Hola") == "hola"
    assert db.normalizar_asunto(None) == ""


def test_mismo_asunto_y_contraparte_comparten_hilo_y_enviados_tambien(cliente):
    _, cuenta = _montar(cliente, "c3b-hilo@ejemplo.com")
    a = _msg(cuenta, "1", "Presupuesto", "Ana <ana@ejemplo.com>")
    b = _msg(cuenta, "2", "Re: Presupuesto", "Ana <ana@ejemplo.com>")
    mio = _msg(cuenta, "3", "RE: Presupuesto", "Yo <yo@ejemplo.com>", dest="Ana <ana@ejemplo.com>", carpeta="Sent")
    otro = _msg(cuenta, "4", "Presupuesto", "luis@otro.com")
    assert _hilo(a) == _hilo(b) == _hilo(mio) is not None
    assert _hilo(otro) != _hilo(a)


def test_las_cabeceras_in_reply_to_y_references_prevalecen(cliente):
    _, cuenta = _montar(cliente, "c3b-cabeceras@ejemplo.com")
    raiz = _msg(cuenta, "1", "Consulta inicial", message_id="<raiz@x>")
    respuesta = _msg(cuenta, "2", "Asunto cambiado", "otra@persona.com", in_reply_to="<raiz@x>")
    tercera = _msg(cuenta, "3", "Otro más", "tercera@persona.com", referencias="<viejo@x> <raiz@x>")
    assert _hilo(raiz) == _hilo(respuesta) == _hilo(tercera)


def test_asunto_vacio_no_agrupa(cliente):
    _, cuenta = _montar(cliente, "c3b-vacio@ejemplo.com")
    assert _hilo(_msg(cuenta, "1", "")) is None and _hilo(_msg(cuenta, "2", None)) is None


def test_migracion_rellena_hilos_de_mensajes_antiguos_y_es_idempotente(cliente):
    _, cuenta = _montar(cliente, "c3b-migra@ejemplo.com")
    a = _msg(cuenta, "1", "Factura marzo", "prov@x.com")
    b = _msg(cuenta, "2", "Re: Factura marzo", "prov@x.com")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE correo_mensajes SET hilo_clave = NULL")
        conn.commit()
        db._rellenar_hilos_correo(conn)
        db._rellenar_hilos_correo(conn)
    finally:
        conn.close()
    assert _hilo(a) == _hilo(b) == "factura marzo|prov@x.com"


def test_bandeja_colapsa_la_conversacion_y_la_lectura_lista_el_resto(cliente):
    _, cuenta = _montar(cliente, "c3b-bandeja@ejemplo.com")
    _msg(cuenta, "1", "Reunión", fecha="2026-03-01T10:00:00")
    ultimo = _msg(cuenta, "2", "Re: Reunión", fecha="2026-03-02T10:00:00")
    _msg(cuenta, "3", "Otra cosa", "pepe@x.com", fecha="2026-03-03T10:00:00")
    html = cliente.get(f"/correo/?cuenta_id={cuenta}").get_data(as_text=True)
    assert html.count("correo-fila-wrap") == 2  # 2 filas: el hilo y "Otra cosa"
    assert 'class="correo-hilo-contador"' in html
    lectura = cliente.get(f"/correo/?cuenta_id={cuenta}&mensaje_id={ultimo}").get_data(as_text=True)
    assert "Conversación (2)" in lectura


# --- cola de envío ----------------------------------------------------------

DATOS = {"destinatarios": "ana@ejemplo.com", "asunto": "Hola", "cuerpo_html": "<p>Texto</p>"}


@pytest.fixture
def smtp_falso(monkeypatch):
    enviados = []
    monkeypatch.setattr(correo, "construir_y_enviar", lambda *a, **k: enviados.append((a, k)))
    return enviados


def _enviar(cliente, cuenta, **extra):
    return cliente.post("/correo/enviar", data={"cuenta_id": cuenta, **DATOS, **extra})


def test_enviar_por_defecto_encola_con_ventana_de_deshacer(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-enviar@ejemplo.com")
    borrador = db.guardar_borrador_correo(uid, None, cuenta_id=cuenta, destinatarios="a", cc="", bcc="", asunto="x", cuerpo_html="x", en_respuesta_a=None)
    resp = _enviar(cliente, cuenta, borrador_id=borrador)
    assert resp.status_code == 302 and "envio_id=" in resp.headers["Location"]
    assert smtp_falso == []  # todavía no ha salido nada
    assert db.obtener_borrador_correo(uid, borrador) is None
    html = cliente.get(resp.headers["Location"]).get_data(as_text=True)
    assert "correo-envio-banner" in html and "Deshacer" in html


def test_con_deshacer_desactivado_se_envia_al_momento(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-ya@ejemplo.com")
    db.guardar_preferencias_correo(uid, "normal", True, 50, deshacer_segundos=0)
    resp = _enviar(cliente, cuenta)
    assert resp.status_code == 302 and "envio_id" not in resp.headers["Location"]
    assert len(smtp_falso) == 1


def test_error_de_validacion_se_muestra_en_el_editor_sin_encolar(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-valida@ejemplo.com")
    resp = cliente.post("/correo/enviar", data={"cuenta_id": cuenta, "destinatarios": "", "asunto": "x", "cuerpo_html": "<p>x</p>"})
    assert resp.status_code == 200 and "al menos un destinatario" in resp.get_data(as_text=True)
    assert db.contar_envios_programados(uid) == 0


def test_deshacer_devuelve_el_correo_a_borradores_y_no_se_envia(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-deshacer@ejemplo.com")
    envio_id = int(_enviar(cliente, cuenta).headers["Location"].split("envio_id=")[1])
    resp = cliente.post(f"/correo/envios/{envio_id}/deshacer")
    assert resp.status_code == 302 and "borrador_id=" in resp.headers["Location"]
    borrador = db.listar_borradores_correo(uid)[0]
    assert borrador["asunto"] == "Hola" and borrador["destinatarios"] == "ana@ejemplo.com"
    futuro = datetime.now() + timedelta(hours=1)
    assert correo.procesar_envios_pendientes(futuro) == 0 and smtp_falso == []


def test_deshacer_con_adjuntos_avisa_de_que_se_pierden(cliente, smtp_falso):
    import io
    uid, cuenta = _montar(cliente, "c3b-adj@ejemplo.com")
    resp = cliente.post("/correo/enviar", data={"cuenta_id": cuenta, **DATOS, "adjuntos": (io.BytesIO(b"datos"), "a.txt")}, content_type="multipart/form-data")
    envio_id = int(resp.headers["Location"].split("envio_id=")[1])
    destino = cliente.post(f"/correo/envios/{envio_id}/deshacer").headers["Location"]
    assert "sin_adjuntos=1" in destino
    assert "Vuelve a adjuntar" in cliente.get(destino).get_data(as_text=True)


def test_el_hilo_envia_cuando_llega_la_hora_y_solo_una_vez(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-worker@ejemplo.com")
    envio_id = int(_enviar(cliente, cuenta).headers["Location"].split("envio_id=")[1])
    assert correo.procesar_envios_pendientes() == 0  # aún dentro de la ventana
    futuro = datetime.now() + timedelta(seconds=60)
    assert correo.procesar_envios_pendientes(futuro) == 1
    assert correo.procesar_envios_pendientes(futuro) == 0
    assert len(smtp_falso) == 1 and smtp_falso[0][0][3] == "Hola"
    assert db.obtener_envio_correo(uid, envio_id)["estado"] == "enviado"
    # ya enviado: deshacer avisa y no crea borrador
    destino = cliente.post(f"/correo/envios/{envio_id}/deshacer").headers["Location"]
    assert "borrador_id" not in destino and db.listar_borradores_correo(uid) == []


def test_reclamar_un_envio_solo_funciona_una_vez(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-reclamar@ejemplo.com")
    envio_id = correo.encolar_envio(uid, cuenta, "a@b.com", "x", "<p>x</p>", enviar_en=db.now_iso())
    assert db.reclamar_envio_correo(envio_id) is True
    assert db.reclamar_envio_correo(envio_id) is False
    assert db.cancelar_envio_correo(uid, envio_id) is False  # ya se está enviando


def test_envio_fallido_no_pierde_el_correo(cliente, monkeypatch):
    uid, cuenta = _montar(cliente, "c3b-fallo@ejemplo.com")

    def roto(*a, **k):
        raise correo.ErrorCorreo("SMTP caído")

    monkeypatch.setattr(correo, "construir_y_enviar", roto)
    monkeypatch.setattr(correo.notificaciones.push, "enviar_a_usuario", lambda *a, **k: None)
    envio_id = int(_enviar(cliente, cuenta).headers["Location"].split("envio_id=")[1])
    assert correo.procesar_envios_pendientes(datetime.now() + timedelta(minutes=1)) == 0
    envio = db.obtener_envio_correo(uid, envio_id)
    assert envio["estado"] == "error" and "SMTP caído" in envio["error"]
    assert db.listar_borradores_correo(uid)[0]["asunto"] == "Hola"


def test_envio_atascado_en_enviando_se_rescata_como_error(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-atascado@ejemplo.com")
    envio_id = correo.encolar_envio(uid, cuenta, "a@b.com", "x", "<p>x</p>", enviar_en=db.now_iso())
    db.reclamar_envio_correo(envio_id)
    ahora = datetime.now() + timedelta(minutes=11)
    correo.procesar_envios_pendientes(ahora)
    assert db.obtener_envio_correo(uid, envio_id)["estado"] == "error"


def test_programar_envio_futuro_pasado_y_cancelar(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-programar@ejemplo.com")
    ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = _enviar(cliente, cuenta, programar="1", programar_para=ayer)
    assert r.status_code == 200 and "tiene que ser futura" in r.get_data(as_text=True)
    r = _enviar(cliente, cuenta, programar="1", programar_para="")
    assert r.status_code == 200 and "Elige la fecha" in r.get_data(as_text=True)

    manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = _enviar(cliente, cuenta, programar="1", programar_para=manana)
    assert r.status_code == 302
    assert db.contar_envios_programados(uid) == 1
    pagina = cliente.get("/correo/programados").get_data(as_text=True)
    assert "Hola" in pagina and "ana@ejemplo.com" in pagina
    assert correo.procesar_envios_pendientes() == 0
    envio = db.listar_envios_programados(uid)[0]
    assert cliente.post(f"/correo/envios/{envio['id']}/deshacer").status_code == 302
    assert db.contar_envios_programados(uid) == 0 and len(db.listar_borradores_correo(uid)) == 1
    # y llegada su hora, uno programado sí sale
    r = _enviar(cliente, cuenta, programar="1", programar_para=manana)
    assert correo.procesar_envios_pendientes(datetime.now() + timedelta(days=2)) == 1 and len(smtp_falso) == 1


def test_envio_ajeno_no_se_puede_deshacer(cliente, smtp_falso):
    uid, cuenta = _montar(cliente, "c3b-ajeno@ejemplo.com")
    envio_id = int(_enviar(cliente, cuenta).headers["Location"].split("envio_id=")[1])
    with _otro_cliente("c3b-ajeno-otro@ejemplo.com") as (otro, _):
        assert otro.post(f"/correo/envios/{envio_id}/deshacer").status_code == 404
    assert db.obtener_envio_correo(uid, envio_id)["estado"] == "pendiente"


def test_preferencia_deshacer_se_guarda_y_rechaza_valores_raros(cliente):
    uid, _ = _montar(cliente, "c3b-pref@ejemplo.com")
    assert db.obtener_preferencias_correo(uid)["deshacer_segundos"] == 10
    cliente.post("/correo/ajustes/preferencias", data={"densidad": "normal", "limite_mensajes": "50", "deshacer_segundos": "30"})
    assert db.obtener_preferencias_correo(uid)["deshacer_segundos"] == 30
    cliente.post("/correo/ajustes/preferencias", data={"densidad": "normal", "limite_mensajes": "50", "deshacer_segundos": "15"})
    assert db.obtener_preferencias_correo(uid)["deshacer_segundos"] == 30
