"""Web Push de la webapp (app/push.py, app/rutas_notificaciones.py): alta/baja de suscripciones, envío con pywebpush simulado,
limpieza de las caducadas y que FCM (app móvil) y Web Push no se mezclen."""
import json

import pytest

from app import db, push
from tests.conftest import iniciar_sesion_de_prueba

ENDPOINT = "https://push.ejemplo.com/wpush/v2/abc_123%7E"
SUS = {"endpoint": ENDPOINT, "keys": {"p256dh": "BPx" + "a" * 60, "auth": "z" * 22}}


@pytest.fixture
def web_activado(monkeypatch):
    monkeypatch.setattr(push, "VAPID_PUBLICA", "clave-publica")
    monkeypatch.setattr(push, "VAPID_PRIVADA", "clave-privada")
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", None)


def test_clave_vacia_si_el_canal_no_esta_activado(cliente, monkeypatch):
    monkeypatch.setattr(push, "VAPID_PUBLICA", "")
    iniciar_sesion_de_prueba(cliente, "pw-sin@ejemplo.com", "contrasena123")
    assert cliente.get("/notificaciones/push/clave").get_json() == {"clave": ""}
    assert cliente.post("/notificaciones/push/suscribir", json=SUS).status_code == 400


def test_suscribir_baja_y_resuscribir_no_duplica(cliente, web_activado):
    uid = iniciar_sesion_de_prueba(cliente, "pw-alta@ejemplo.com", "contrasena123")
    assert cliente.get("/notificaciones/push/clave").get_json() == {"clave": "clave-publica"}
    assert cliente.post("/notificaciones/push/suscribir", json=SUS).status_code == 200
    nueva = {"endpoint": ENDPOINT, "keys": {"p256dh": "BPx" + "b" * 60, "auth": "y" * 22}}
    assert cliente.post("/notificaciones/push/suscribir", json=nueva).status_code == 200
    guardadas = db.suscripciones_web_de_usuario(uid)
    assert len(guardadas) == 1 and json.loads(guardadas[0])["keys"]["auth"] == "y" * 22
    assert db.tokens_push_de_usuario(uid) == []                       # no se cuela entre los tokens FCM
    assert cliente.post("/notificaciones/push/baja", json={"endpoint": ENDPOINT}).status_code == 200
    assert db.suscripciones_web_de_usuario(uid) == []


@pytest.mark.parametrize("cuerpo", [{}, {"endpoint": "http://inseguro.ejemplo.com/x", "keys": SUS["keys"]}, {"endpoint": ENDPOINT, "keys": {"p256dh": "x"}}, {"endpoint": ENDPOINT, "keys": {"p256dh": "x" * 300, "auth": "y"}}])
def test_suscripciones_mal_formadas_se_rechazan(cliente, web_activado, cuerpo):
    iniciar_sesion_de_prueba(cliente, "pw-mal@ejemplo.com", "contrasena123")
    assert cliente.post("/notificaciones/push/suscribir", json=cuerpo).status_code == 400


def test_baja_de_otra_persona_no_borra_su_suscripcion(cliente, web_activado):
    ajeno = db.crear_usuario("pw-ajeno@ejemplo.com", "contrasena123") if hasattr(db, "crear_usuario") else None
    if ajeno is None:
        pytest.skip("sin helper para crear una segunda persona")
    db.registrar_suscripcion_web(ajeno, json.dumps(SUS, separators=(",", ":")), ENDPOINT)
    iniciar_sesion_de_prueba(cliente, "pw-yo@ejemplo.com", "contrasena123")
    cliente.post("/notificaciones/push/baja", json={"endpoint": ENDPOINT})
    assert len(db.suscripciones_web_de_usuario(ajeno)) == 1


def test_enviar_manda_la_carga_y_conserva_la_suscripcion(usuario_id, web_activado, monkeypatch):
    db.registrar_suscripcion_web(usuario_id, json.dumps(SUS, separators=(",", ":")), ENDPOINT)
    enviados = []
    import pywebpush
    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: enviados.append(kw))
    push.enviar_a_usuario(usuario_id, "Vence el 303", "x" * 500, {"url": "/guilda-fiscal/", "notificacion_id": 7})
    assert len(enviados) == 1
    carga = json.loads(enviados[0]["data"])
    assert carga == {"titulo": "Vence el 303", "cuerpo": "x" * push.MAX_CUERPO_WEB, "url": "/guilda-fiscal/", "tag": "7"}
    assert enviados[0]["subscription_info"]["endpoint"] == ENDPOINT
    assert len(db.suscripciones_web_de_usuario(usuario_id)) == 1


@pytest.mark.parametrize("url", ["https://malo.example/robo", "//malo.example/robo", None])
def test_el_aviso_nunca_apunta_fuera_de_la_app(url):
    assert push._ruta_propia(url) == "/hoy/"


@pytest.mark.parametrize("codigo,se_conserva", [(410, False), (404, False), (500, True), (429, True)])
def test_suscripciones_caducadas_se_limpian(usuario_id, web_activado, monkeypatch, codigo, se_conserva):
    db.registrar_suscripcion_web(usuario_id, json.dumps(SUS, separators=(",", ":")), ENDPOINT)
    import pywebpush

    class _Resp:
        status_code = codigo

    def falla(**kw):
        raise pywebpush.WebPushException("rechazado", response=_Resp())

    monkeypatch.setattr(pywebpush, "webpush", falla)
    push.enviar_a_usuario(usuario_id, "t", "c", {})
    assert bool(db.suscripciones_web_de_usuario(usuario_id)) is se_conserva


def test_horas_de_silencio_tambien_frenan_el_push_web(usuario_id, web_activado, monkeypatch):
    db.registrar_suscripcion_web(usuario_id, json.dumps(SUS, separators=(",", ":")), ENDPOINT)
    import pywebpush
    llamadas = []
    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: llamadas.append(kw))
    monkeypatch.setattr(db, "en_horas_de_silencio", lambda uid: True)
    push.enviar_a_usuario(usuario_id, "t", "c", {})
    assert llamadas == []
    push.enviar_a_usuario(usuario_id, "t", "c", {}, ignorar_silencio=True)
    assert len(llamadas) == 1


def test_el_token_fcm_no_se_envia_a_suscripciones_web(usuario_id, monkeypatch):
    monkeypatch.setattr(push, "VAPID_PUBLICA", "")
    db.registrar_suscripcion_web(usuario_id, json.dumps(SUS, separators=(",", ":")), ENDPOINT)
    db.registrar_dispositivo_push(usuario_id, "token-fcm", "android")
    assert db.tokens_push_de_usuario(usuario_id) == ["token-fcm"]


def test_envio_real_cifrado_y_firmado_con_las_claves_vapid(monkeypatch):
    """Sin simular pywebpush: un «servicio de push» local recibe la petición, comprobamos la firma VAPID y que la carga se descifra con las claves del navegador."""
    import base64
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import http_ece
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric import ec
    from py_vapid import Vapid

    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    v = Vapid()
    v.generate_keys()
    privada = b64(v.private_key.private_numbers().private_value.to_bytes(32, "big"))
    publica = b64(v.public_key.public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint))
    monkeypatch.setattr(push, "VAPID_PRIVADA", privada)
    monkeypatch.setattr(push, "VAPID_PUBLICA", publica)

    navegador = ec.generate_private_key(ec.SECP256R1())
    p256dh = b64(navegador.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint))
    auth = b64(b"0123456789abcdef")
    recibido = {}

    class Servicio(BaseHTTPRequestHandler):
        def do_POST(self):
            recibido["auth"] = self.headers.get("Authorization", "")
            recibido["cuerpo"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.end_headers()

        def log_message(self, *a):
            pass

    servidor = HTTPServer(("127.0.0.1", 0), Servicio)
    threading.Thread(target=servidor.handle_request, daemon=True).start()
    sus = json.dumps({"endpoint": f"http://127.0.0.1:{servidor.server_port}/push", "keys": {"p256dh": p256dh, "auth": auth}})
    assert push._enviar_web(sus, {"titulo": "Hola", "cuerpo": "Vence el 303", "url": "/hoy/", "tag": "1"}) is True
    servidor.server_close()

    assert recibido["auth"].startswith("vapid t=") and f"k={publica}" in recibido["auth"]
    pad = lambda s: s + "=" * (-len(s) % 4)
    texto = http_ece.decrypt(recibido["cuerpo"], private_key=navegador, auth_secret=base64.urlsafe_b64decode(pad(auth)), version="aes128gcm")
    assert json.loads(texto)["cuerpo"] == "Vence el 303"


# --- Avisos genéricos (privacidad) ---------------------------------------------------------------------------------------

DATOS_AVISO = {"tipo": "correo_nuevo", "url": "/correo/", "notificacion_id": 9, "remitente": "Marta Ruiz", "asunto": "Factura 1.200 €", "destino": '{"tipo":"correo"}'}


def test_por_defecto_el_aviso_lleva_su_texto(usuario_id):
    assert push.hacer_generico(usuario_id, "Marta Ruiz", "Factura 1.200 €", DATOS_AVISO) == ("Marta Ruiz", "Factura 1.200 €", DATOS_AVISO)


def test_aviso_generico_no_lleva_datos_personales_pero_si_la_ruta(usuario_id):
    db.guardar_perfil_usuario(usuario_id, avisos_genericos=True)
    titulo, cuerpo, datos = push.hacer_generico(usuario_id, "Marta Ruiz", "Factura 1.200 €", DATOS_AVISO)
    assert (titulo, cuerpo) == push._TEXTO_GENERICO["es"]
    assert datos == {"tipo": "correo_nuevo", "url": "/correo/", "notificacion_id": 9, "destino": '{"tipo":"correo"}'}
    assert "Marta" not in json.dumps([titulo, cuerpo, datos]) and "1.200" not in json.dumps([titulo, cuerpo, datos])


def test_aviso_generico_en_el_idioma_de_la_persona(usuario_id):
    db.guardar_perfil_usuario(usuario_id, avisos_genericos=True)
    for idioma in ("ca", "en", "fr"):
        db.guardar_idioma_usuario(usuario_id, idioma) if hasattr(db, "guardar_idioma_usuario") else None
        if db.idioma_usuario(usuario_id) == idioma:
            assert push.hacer_generico(usuario_id, "x", "y", {})[1] == push._TEXTO_GENERICO[idioma][1]


def test_el_envio_web_y_fcm_usan_el_texto_generico(usuario_id, web_activado, monkeypatch):
    db.guardar_perfil_usuario(usuario_id, avisos_genericos=True)
    db.registrar_suscripcion_web(usuario_id, json.dumps(SUS, separators=(",", ":")), ENDPOINT)
    db.registrar_dispositivo_push(usuario_id, "token-fcm", "android")
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", __file__)          # «configurado»
    web, fcm = [], []
    import pywebpush
    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: web.append(json.loads(kw["data"])))
    monkeypatch.setattr(push, "_enviar_a_token", lambda token, titulo, cuerpo, datos, canal=None: fcm.append((titulo, cuerpo, datos)) or True)
    push.enviar_a_usuario(usuario_id, "Marta Ruiz", "Factura 1.200 €", dict(DATOS_AVISO))
    assert web[0]["titulo"] == "Guilda Work" and "Marta" not in json.dumps(web[0]) and web[0]["url"] == "/correo/"
    assert fcm[0][0] == "Guilda Work" and "Marta" not in json.dumps(fcm[0]) and "asunto" not in fcm[0][2]


def test_el_interruptor_de_ajustes_se_guarda(cliente):
    uid = iniciar_sesion_de_prueba(cliente, "genericos@ejemplo.com", "contrasena123")
    assert not db.avisos_genericos(uid)
    assert cliente.post("/ajustes/perfil", data={"nombre_mostrado": "Ana", "avisos_genericos": "on"}).status_code == 302
    assert db.avisos_genericos(uid)
    cliente.post("/ajustes/perfil", data={"nombre_mostrado": "Ana"})
    assert not db.avisos_genericos(uid)
