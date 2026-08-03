"""Tests del cliente de Jitsi Meet (app/jitsi.py) — sin ningún Jitsi
real: la firma JWT es pura (HMAC-SHA256 a mano, sin llamadas de red), así
que se prueba directamente.

El diseño en sí (ENABLE_AUTH/AUTH_TYPE=jwt como función gratuita del
self-hosted, sin add-on de pago; aislamiento real por el nombre de sala
grabado dentro del propio JWT, no por el secreto en sí, que es
compartido) se verificó en vivo contra un stack real de 4 contenedores
durante el desarrollo — ver el docstring del propio módulo, incluida la
parte que NO se pudo verificar de punta a punta en este entorno
concreto. La corrección de la firma HS256 hecha a mano se verificó de
forma cruzada con PyJWT (independiente de este código) durante el
desarrollo — aquí solo se prueba que app/jitsi.py construye el payload
correcto."""
import base64
import hashlib
import hmac
import json

import pytest

from app import jitsi as j


def _mock_config(monkeypatch, app_id="guilda_work", secret="secreto-de-prueba-suficientemente-largo"):
    monkeypatch.setattr(j, "JITSI_JWT_APP_ID", app_id)
    monkeypatch.setattr(j, "JITSI_JWT_APP_SECRET", secret)


def _decodificar_sin_verificar(token: str) -> dict:
    """Decodifica el payload de un JWT (base64url) sin verificar la
    firma — solo para inspeccionar qué se firmó, la verificación de la
    firma en sí la hace test_firma_es_valida_para_pyjwt más abajo."""
    _, payload_b64, _ = token.split(".")
    relleno = "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + relleno))


# --- nombre_sala -------------------------------------------------------------

def test_nombre_sala_usa_el_slug_del_tenant_como_prefijo():
    assert j.nombre_sala("Cliente Alfa", "abc123") == "cliente-alfa-abc123"


def test_nombre_sala_normaliza_caracteres_raros():
    assert j.nombre_sala("Cliente & Cía. S.L.", "xyz") == "cliente-c-a-s-l-xyz"


# --- generar_jwt_sala --------------------------------------------------------

def test_generar_jwt_sala_sin_credenciales_lanza_error(monkeypatch):
    monkeypatch.setattr(j, "JITSI_JWT_APP_ID", None)
    monkeypatch.setattr(j, "JITSI_JWT_APP_SECRET", None)
    with pytest.raises(j.ErrorJitsi):
        j.generar_jwt_sala("Lueira", "Ana", "lueira-abc")


def test_generar_jwt_sala_incluye_los_campos_correctos(monkeypatch):
    _mock_config(monkeypatch)
    token = j.generar_jwt_sala("Lueira", "Ana", "lueira-abc123", moderador=True)
    payload = _decodificar_sin_verificar(token)

    assert payload["room"] == "lueira-abc123"
    assert payload["aud"] == "guilda_work"
    assert payload["iss"] == "guilda_work"
    assert payload["sub"] == "*"
    assert payload["context"]["user"]["name"] == "Ana"
    assert payload["context"]["user"]["moderator"] is True
    assert payload["exp"] > payload["iat"]


def test_generar_jwt_sala_respeta_moderador_false(monkeypatch):
    _mock_config(monkeypatch)
    token = j.generar_jwt_sala("Lueira", "Invitado", "lueira-abc123", moderador=False)
    payload = _decodificar_sin_verificar(token)
    assert payload["context"]["user"]["moderator"] is False


def test_generar_jwt_sala_respeta_minutos_validez(monkeypatch):
    _mock_config(monkeypatch)
    token = j.generar_jwt_sala("Lueira", "Ana", "lueira-abc123", minutos_validez=5)
    payload = _decodificar_sin_verificar(token)
    assert payload["exp"] - payload["iat"] == 5 * 60


def test_firma_es_valida_verificacion_manual_hmac(monkeypatch):
    """Reconstruye la verificación HMAC a mano (sin PyJWT, que no es una
    dependencia del proyecto) para confirmar que la firma es la que
    correspondería a header+payload con el secreto configurado."""
    _mock_config(monkeypatch, secret="otro-secreto-para-esta-prueba-en-concreto")
    token = j.generar_jwt_sala("Lueira", "Ana", "lueira-abc123")
    cabecera_b64, payload_b64, firma_b64 = token.split(".")

    firmante = f"{cabecera_b64}.{payload_b64}".encode("ascii")
    firma_esperada = hmac.new(
        b"otro-secreto-para-esta-prueba-en-concreto", firmante, hashlib.sha256
    ).digest()
    firma_esperada_b64 = base64.urlsafe_b64encode(firma_esperada).rstrip(b"=").decode("ascii")

    assert firma_b64 == firma_esperada_b64


def test_firmas_distintas_para_secretos_distintos(monkeypatch):
    _mock_config(monkeypatch, secret="secreto-uno-bien-largo-de-verdad")
    token_a = j.generar_jwt_sala("Lueira", "Ana", "lueira-abc123")
    _mock_config(monkeypatch, secret="secreto-dos-completamente-distinto")
    token_b = j.generar_jwt_sala("Lueira", "Ana", "lueira-abc123")
    assert token_a.split(".")[2] != token_b.split(".")[2]


# --- url_sala ----------------------------------------------------------------

def test_url_sala_incluye_la_sala_y_el_jwt():
    url = j.url_sala("lueira-abc123", "un.jwt.falso")
    assert url == f"{j.JITSI_URL}/lueira-abc123?jwt=un.jwt.falso"
