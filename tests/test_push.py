"""Cliente de Firebase Cloud Messaging (app/push.py) -- sin tests hasta
ahora. Mismo patrón de mock de urllib que tests/test_facturascripts.py,
adaptado a FCM HTTP v1 (respuesta de éxito vacía, error 400/404 con
"UNREGISTERED" en el cuerpo para el caso de token inválido)."""
import io
import urllib.error

import pytest

from app import db, push


class _RespuestaFalsa:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(codigo: int, cuerpo: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://fcm.googleapis.com/v1/projects/x/messages:send",
        codigo, "error", {}, io.BytesIO(cuerpo.encode("utf-8")),
    )


@pytest.fixture(autouse=True)
def _sin_credenciales_reales(monkeypatch):
    """Todas las pruebas de este fichero evitan tocar credenciales de
    Google de verdad -- _access_token queda mockeado siempre, cada test
    decide el comportamiento de urlopen."""
    monkeypatch.setattr(push, "_access_token", lambda: "token-de-prueba")
    monkeypatch.setattr(push, "_project_id", "proyecto-de-prueba")


# --- configurado() ------------------------------------------------------

def test_configurado_false_sin_variable_de_entorno(monkeypatch):
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", None)
    assert push.configurado() is False


def test_configurado_false_si_el_fichero_no_existe(monkeypatch):
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", "/no/existe/credenciales.json")
    assert push.configurado() is False


def test_configurado_true_si_el_fichero_existe(monkeypatch, tmp_path):
    fichero = tmp_path / "credenciales.json"
    fichero.write_text("{}")
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", str(fichero))
    assert push.configurado() is True


# --- _enviar_a_token: interpretación de la respuesta de FCM -------------

def test_enviar_a_token_true_si_fcm_acepta(monkeypatch):
    monkeypatch.setattr(push.urllib.request, "urlopen", lambda *a, **k: _RespuestaFalsa())
    assert push._enviar_a_token("token-x", "Título", "Cuerpo", None) is True


def test_enviar_a_token_false_si_token_no_registrado(monkeypatch):
    def fake_urlopen(*a, **k):
        raise _http_error(404, '{"error": {"details": [{"errorCode": "UNREGISTERED"}]}}')
    monkeypatch.setattr(push.urllib.request, "urlopen", fake_urlopen)
    assert push._enviar_a_token("token-x", "Título", "Cuerpo", None) is False


def test_enviar_a_token_true_si_es_un_error_distinto_a_unregistered(monkeypatch):
    """Un 400 que NO sea "UNREGISTERED" (cuota, payload mal formado...) no
    debe borrar el token -- solo se limpia cuando FCM confirma que el
    dispositivo ya no existe."""
    def fake_urlopen(*a, **k):
        raise _http_error(400, '{"error": {"status": "INVALID_ARGUMENT"}}')
    monkeypatch.setattr(push.urllib.request, "urlopen", fake_urlopen)
    assert push._enviar_a_token("token-x", "Título", "Cuerpo", None) is True


def test_enviar_a_token_true_si_falla_la_red(monkeypatch):
    def fake_urlopen(*a, **k):
        raise urllib.error.URLError("timeout")
    monkeypatch.setattr(push.urllib.request, "urlopen", fake_urlopen)
    assert push._enviar_a_token("token-x", "Título", "Cuerpo", None) is True


# --- enviar_a_usuario: punto de entrada, nunca lanza ---------------------

def test_enviar_a_usuario_no_hace_nada_si_no_esta_configurado(monkeypatch, usuario_id):
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", None)
    llamado = []
    monkeypatch.setattr(push.urllib.request, "urlopen", lambda *a, **k: llamado.append(1))
    push.enviar_a_usuario(usuario_id, "Título", "Cuerpo")
    assert llamado == []


def test_enviar_a_usuario_sin_dispositivos_no_hace_nada(monkeypatch, tmp_path, usuario_id):
    fichero = tmp_path / "credenciales.json"
    fichero.write_text("{}")
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", str(fichero))
    llamado = []
    monkeypatch.setattr(push.urllib.request, "urlopen", lambda *a, **k: llamado.append(1))
    push.enviar_a_usuario(usuario_id, "Título", "Cuerpo")
    assert llamado == []


def test_enviar_a_usuario_limpia_tokens_invalidos(monkeypatch, tmp_path, usuario_id):
    fichero = tmp_path / "credenciales.json"
    fichero.write_text("{}")
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", str(fichero))
    db.registrar_dispositivo_push(usuario_id, "token-invalido", "android")
    db.registrar_dispositivo_push(usuario_id, "token-valido", "ios")

    def fake_urlopen(request, timeout=None):
        if "token-invalido" in request.data.decode("utf-8"):
            raise _http_error(404, '{"error": {"details": [{"errorCode": "UNREGISTERED"}]}}')
        return _RespuestaFalsa()
    monkeypatch.setattr(push.urllib.request, "urlopen", fake_urlopen)

    push.enviar_a_usuario(usuario_id, "Título", "Cuerpo")

    restantes = db.tokens_push_de_usuario(usuario_id)
    assert restantes == ["token-valido"]


def test_enviar_a_usuario_nunca_lanza_aunque_falle_todo(monkeypatch, tmp_path, usuario_id):
    fichero = tmp_path / "credenciales.json"
    fichero.write_text("{}")
    monkeypatch.setattr(push, "FIREBASE_CREDENTIALS_PATH", str(fichero))
    db.registrar_dispositivo_push(usuario_id, "token-x", "android")

    def fake_urlopen(*a, **k):
        raise Exception("boom")
    monkeypatch.setattr(push.urllib.request, "urlopen", fake_urlopen)

    push.enviar_a_usuario(usuario_id, "Título", "Cuerpo")  # no debe lanzar
