"""Cliente de Stripe (app/stripe_pagos.py) -- Connect (bloque 5) y
facturación de plataforma (bloque 6). Sin cuenta Stripe real todavía
(bloqueante externo, ver HOSTING.md) -- todo mockeado, mismo patrón que
tests/test_facturascripts.py: se comprueba que ESTE código construye
las peticiones correctas e interpreta bien la respuesta, no que Stripe
en sí funcione."""
import hashlib
import hmac
import json
import time
import urllib.error

import pytest

from app import stripe_pagos as sp


class _RespuestaFalsa:
    def __init__(self, cuerpo: dict):
        self._cuerpo = json.dumps(cuerpo).encode("utf-8")

    def read(self):
        return self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(codigo: int, mensaje: str) -> urllib.error.HTTPError:
    import io
    cuerpo = json.dumps({"error": {"message": mensaje}}).encode("utf-8")
    return urllib.error.HTTPError("https://api.stripe.com/v1/x", codigo, "error", {}, io.BytesIO(cuerpo))


@pytest.fixture(autouse=True)
def _clave_de_prueba(monkeypatch):
    monkeypatch.setattr(sp, "STRIPE_SECRET_KEY", "sk_test_falsa")


# --- configurado() -------------------------------------------------------

def test_configurado_false_sin_clave(monkeypatch):
    monkeypatch.setattr(sp, "STRIPE_SECRET_KEY", None)
    assert sp.configurado() is False


def test_configurado_true_con_clave():
    assert sp.configurado() is True


# --- _peticion sin clave -------------------------------------------------

def test_peticion_sin_clave_lanza_error(monkeypatch):
    monkeypatch.setattr(sp, "STRIPE_SECRET_KEY", None)
    with pytest.raises(sp.ErrorStripe):
        sp._peticion("/accounts")


def test_peticion_error_http_extrae_el_mensaje(monkeypatch):
    monkeypatch.setattr(sp.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(_http_error(402, "Tarjeta rechazada")))
    with pytest.raises(sp.ErrorStripe, match="Tarjeta rechazada"):
        sp._peticion("/charges", metodo="POST", cuerpo={"x": 1})


# --- _aplanar --------------------------------------------------------------

def test_aplanar_dict_simple():
    assert dict(sp._aplanar({"a": 1, "b": "x"})) == {"a": 1, "b": "x"}


def test_aplanar_dict_anidado():
    pares = dict(sp._aplanar({"payment_intent_data": {"transfer_data": {"destination": "acct_1"}}}))
    assert pares == {"payment_intent_data[transfer_data][destination]": "acct_1"}


def test_aplanar_lista_de_dicts():
    pares = dict(sp._aplanar({"line_items": [{"quantity": 1}, {"quantity": 2}]}))
    assert pares == {"line_items[0][quantity]": 1, "line_items[1][quantity]": 2}


def test_aplanar_booleano_se_convierte_a_texto():
    assert dict(sp._aplanar({"activo": True})) == {"activo": "true"}
    assert dict(sp._aplanar({"activo": False})) == {"activo": "false"}


# --- verificar_firma_webhook -----------------------------------------------

def _firmar(payload: bytes, secreto: str, timestamp: int) -> str:
    mensaje = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    firma = hmac.new(secreto.encode("utf-8"), mensaje, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={firma}"


def test_verificar_firma_webhook_valida(monkeypatch):
    monkeypatch.setattr(sp, "STRIPE_WEBHOOK_SECRET", "whsec_falso")
    payload = json.dumps({"type": "checkout.session.completed", "id": "evt_1"}).encode("utf-8")
    cabecera = _firmar(payload, "whsec_falso", int(time.time()))
    evento = sp.verificar_firma_webhook(payload, cabecera)
    assert evento["type"] == "checkout.session.completed"


def test_verificar_firma_webhook_firma_incorrecta(monkeypatch):
    monkeypatch.setattr(sp, "STRIPE_WEBHOOK_SECRET", "whsec_falso")
    payload = b'{"type": "x"}'
    cabecera = _firmar(payload, "whsec_INCORRECTO", int(time.time()))
    with pytest.raises(sp.ErrorStripe, match="inválida"):
        sp.verificar_firma_webhook(payload, cabecera)


def test_verificar_firma_webhook_caducado(monkeypatch):
    monkeypatch.setattr(sp, "STRIPE_WEBHOOK_SECRET", "whsec_falso")
    payload = b'{"type": "x"}'
    cabecera = _firmar(payload, "whsec_falso", int(time.time()) - 1000)
    with pytest.raises(sp.ErrorStripe, match="caducado"):
        sp.verificar_firma_webhook(payload, cabecera)


def test_verificar_firma_webhook_cabecera_mal_formada(monkeypatch):
    monkeypatch.setattr(sp, "STRIPE_WEBHOOK_SECRET", "whsec_falso")
    with pytest.raises(sp.ErrorStripe, match="mal formada"):
        sp.verificar_firma_webhook(b"{}", "no-es-una-cabecera-valida")


def test_verificar_firma_webhook_sin_secreto_configurado(monkeypatch):
    monkeypatch.setattr(sp, "STRIPE_WEBHOOK_SECRET", None)
    with pytest.raises(sp.ErrorStripe):
        sp.verificar_firma_webhook(b"{}", "t=1,v1=x")


# --- Bloque 5: Connect -----------------------------------------------------

def test_crear_cuenta_connect(monkeypatch):
    llamadas = []

    def fake_urlopen(req, timeout=None):
        llamadas.append(req.full_url)
        if "accounts" in req.full_url:
            return _RespuestaFalsa({"id": "acct_123"})
        return _RespuestaFalsa({"url": "https://connect.stripe.com/setup/acct_123"})

    monkeypatch.setattr(sp.urllib.request, "urlopen", fake_urlopen)
    account_id, url = sp.crear_cuenta_connect("tenant@ejemplo.com", "Gestoria X", "https://x/retorno", "https://x/refrescar")
    assert account_id == "acct_123"
    assert url == "https://connect.stripe.com/setup/acct_123"
    assert len(llamadas) == 2


def test_cuenta_connect_lista_true(monkeypatch):
    monkeypatch.setattr(sp.urllib.request, "urlopen", lambda *a, **k: _RespuestaFalsa({"charges_enabled": True}))
    assert sp.cuenta_connect_lista("acct_123") is True


def test_cuenta_connect_lista_false(monkeypatch):
    monkeypatch.setattr(sp.urllib.request, "urlopen", lambda *a, **k: _RespuestaFalsa({"charges_enabled": False}))
    assert sp.cuenta_connect_lista("acct_123") is False


def test_crear_sesion_pago(monkeypatch):
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["data"] = req.data.decode("utf-8")
        return _RespuestaFalsa({"url": "https://checkout.stripe.com/pay/cs_123"})

    monkeypatch.setattr(sp.urllib.request, "urlopen", fake_urlopen)
    url = sp.crear_sesion_pago("acct_123", 8000, "Modelo 303 T2", "https://x/exito", "https://x/cancelar")
    assert url == "https://checkout.stripe.com/pay/cs_123"
    assert "payment_intent_data%5Btransfer_data%5D%5Bdestination%5D=acct_123" in capturado["data"]
    assert "unit_amount%5D=8000" in capturado["data"]


def test_crear_sesion_pago_incluye_metadata(monkeypatch):
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["data"] = req.data.decode("utf-8")
        return _RespuestaFalsa({"url": "https://checkout.stripe.com/pay/cs_123"})

    monkeypatch.setattr(sp.urllib.request, "urlopen", fake_urlopen)
    sp.crear_sesion_pago("acct_123", 8000, "Modelo 303 T2", "https://x/exito", "https://x/cancelar",
                          metadata={"vencimiento_id": 42})
    assert "metadata%5Bvencimiento_id%5D=42" in capturado["data"]


def test_crear_sesion_pago_sin_metadata_no_la_incluye(monkeypatch):
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["data"] = req.data.decode("utf-8")
        return _RespuestaFalsa({"url": "https://checkout.stripe.com/pay/cs_123"})

    monkeypatch.setattr(sp.urllib.request, "urlopen", fake_urlopen)
    sp.crear_sesion_pago("acct_123", 8000, "Modelo 303 T2", "https://x/exito", "https://x/cancelar")
    assert "metadata" not in capturado["data"]


# --- Bloque 6: facturación de plataforma -----------------------------------

def test_sincronizar_plan_sin_precio_no_llama_a_stripe(monkeypatch):
    llamado = []
    monkeypatch.setattr(sp.urllib.request, "urlopen", lambda *a, **k: llamado.append(1))
    assert sp.sincronizar_plan("Básico", None) is None
    assert llamado == []


def test_sincronizar_plan_con_precio(monkeypatch):
    def fake_urlopen(req, timeout=None):
        if "/products" in req.full_url:
            return _RespuestaFalsa({"id": "prod_1"})
        return _RespuestaFalsa({"id": "price_1"})
    monkeypatch.setattr(sp.urllib.request, "urlopen", fake_urlopen)
    assert sp.sincronizar_plan("Básico", 2900) == "price_1"


def test_sincronizar_extra_sin_precio_no_llama_a_stripe(monkeypatch):
    llamado = []
    monkeypatch.setattr(sp.urllib.request, "urlopen", lambda *a, **k: llamado.append(1))
    assert sp.sincronizar_extra("Usuario adicional", None) is None
    assert llamado == []


def test_crear_cliente_plataforma(monkeypatch):
    monkeypatch.setattr(sp.urllib.request, "urlopen", lambda *a, **k: _RespuestaFalsa({"id": "cus_1"}))
    assert sp.crear_cliente_plataforma("tenant@ejemplo.com", "Gestoria X") == "cus_1"


def test_crear_suscripcion(monkeypatch):
    monkeypatch.setattr(sp.urllib.request, "urlopen", lambda *a, **k: _RespuestaFalsa({"id": "sub_1"}))
    assert sp.crear_suscripcion("cus_1", "price_1") == "sub_1"


def test_crear_sesion_suscripcion(monkeypatch):
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["data"] = req.data.decode("utf-8")
        return _RespuestaFalsa({"url": "https://checkout.stripe.com/pay/cs_sub_1"})

    monkeypatch.setattr(sp.urllib.request, "urlopen", fake_urlopen)
    url = sp.crear_sesion_suscripcion("cus_1", "price_1", "https://x/exito", "https://x/cancelar")
    assert url == "https://checkout.stripe.com/pay/cs_sub_1"
    assert "mode=subscription" in capturado["data"]
    assert "customer=cus_1" in capturado["data"]


def test_anadir_extra_a_suscripcion(monkeypatch):
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["url"] = req.full_url
        capturado["data"] = req.data.decode("utf-8")
        return _RespuestaFalsa({"id": "ii_1"})

    monkeypatch.setattr(sp.urllib.request, "urlopen", fake_urlopen)
    sp.anadir_extra_a_suscripcion("cus_1", "sub_1", "price_extra", cantidad=2)
    # Vía /v1/invoiceitems, NO /v1/subscription_items -- un Price sin
    # `recurring` (como el que crea sincronizar_extra) no es válido en
    # un subscription_item, Stripe lo rechazaría.
    assert capturado["url"].endswith("/invoiceitems")
    assert "customer=cus_1" in capturado["data"]
    assert "subscription=sub_1" in capturado["data"]
    assert "quantity=2" in capturado["data"]


def test_listar_facturas_cliente(monkeypatch):
    monkeypatch.setattr(sp.urllib.request, "urlopen", lambda *a, **k: _RespuestaFalsa({"data": [{"id": "in_1"}]}))
    facturas = sp.listar_facturas_cliente("cus_1")
    assert facturas == [{"id": "in_1"}]
