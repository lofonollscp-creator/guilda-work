"""Tests de webhooks salientes (app/eventos.py) — se mockea
urllib.request.urlopen y time.sleep, sin red real ni esperas reales.

El mecanismo en sí (cola en memoria + un único hilo de fondo, mismo
patrón que app/main.py:_sincronizacion_correo_periodica; entrega real
por HTTP con firma HMAC-SHA256 verificada de forma independiente; y un
webhook real recibiendo un evento real de punta a punta) se verificó en
vivo durante el desarrollo — ver el docstring del propio módulo. Aquí
solo se comprueba que app/eventos.py ORQUESTA las llamadas correctas."""
import hashlib
import hmac
import json
import queue
import time
import urllib.error

import pytest

from app import db, eventos as ev


@pytest.fixture(autouse=True)
def _hilo_limpio(monkeypatch):
    """Cada test se monta su propia cola y "hilo ya iniciado" a mano
    (llamando _entregar directamente) en vez de depender del hilo de
    fondo real — evita condiciones de carrera entre tests."""
    monkeypatch.setattr(ev, "_cola", queue.Queue())
    monkeypatch.setattr(ev, "_hilo_iniciado", False)
    monkeypatch.setattr(time, "sleep", lambda s: None)


class _RespuestaFalsa:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- _firmar -------------------------------------------------------------

def test_firmar_coincide_con_hmac_sha256_calculado_a_mano():
    cuerpo = b'{"evento":"nota.creada"}'
    firma = ev._firmar(cuerpo, "mi-secreto")
    esperada = "sha256=" + hmac.new(b"mi-secreto", cuerpo, hashlib.sha256).hexdigest()
    assert firma == esperada


# --- emitir ----------------------------------------------------------------

def test_emitir_sin_webhooks_suscritos_no_hace_nada(usuario_id, monkeypatch):
    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debería llamar")))
    ev.emitir("tarea.finalizada", None, {"tarea_id": 1})
    ev._cola.join()  # no debería haber nada que esperar


def test_emitir_encola_para_cada_webhook_suscrito(usuario_id, monkeypatch):
    db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook1", ["tarea.finalizada"])
    db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook2", ["nota.creada"])  # no suscrito, no debe recibir nada

    llamadas = []

    def fake_urlopen(req, timeout=None):
        llamadas.append(req.full_url)
        return _RespuestaFalsa(200)

    monkeypatch.setattr(ev.urllib.request, "urlopen", fake_urlopen)
    ev.emitir("tarea.finalizada", None, {"tarea_id": 1})
    ev._cola.join()

    assert llamadas == ["https://ejemplo.com/hook1"]


def test_emitir_un_fallo_al_consultar_webhooks_no_lanza(monkeypatch):
    monkeypatch.setattr(ev.db, "webhooks_para_evento", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ev.emitir("tarea.finalizada", None, {})  # no debe lanzar


# --- _entregar: firma, cabeceras y registro de la entrega -------------------

def test_entregar_manda_la_firma_y_cabeceras_correctas(usuario_id, monkeypatch):
    webhook = dict(db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook", ["nota.creada"]))
    capturado = {}

    def fake_urlopen(req, timeout=None):
        capturado["url"] = req.full_url
        capturado["headers"] = dict(req.headers)
        capturado["body"] = req.data
        return _RespuestaFalsa(200)

    monkeypatch.setattr(ev.urllib.request, "urlopen", fake_urlopen)
    ev._entregar(webhook, "nota.creada", {"nota_id": 5})

    assert capturado["url"] == webhook["url"]
    assert capturado["headers"]["X-guilda-event"] == "nota.creada"
    firma_esperada = "sha256=" + hmac.new(webhook["secreto"].encode(), capturado["body"], hashlib.sha256).hexdigest()
    assert capturado["headers"]["X-guilda-signature"] == firma_esperada
    cuerpo = json.loads(capturado["body"])
    assert cuerpo == {"evento": "nota.creada", "datos": {"nota_id": 5}}


def test_entregar_exito_registra_la_entrega_con_estado_http(usuario_id, monkeypatch):
    webhook = dict(db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook", ["nota.creada"]))
    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda req, timeout=None: _RespuestaFalsa(200))

    ev._entregar(webhook, "nota.creada", {})

    entregas = db.entregas_de_webhook(webhook["id"])
    assert len(entregas) == 1
    assert entregas[0]["estado_http"] == 200
    assert entregas[0]["intento_num"] == 1
    assert entregas[0]["error"] is None


def test_entregar_reintenta_hasta_3_veces_y_registra_cada_intento(usuario_id, monkeypatch):
    webhook = dict(db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook", ["nota.creada"]))

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("conexión rechazada")

    monkeypatch.setattr(ev.urllib.request, "urlopen", fake_urlopen)
    ev._entregar(webhook, "nota.creada", {})

    entregas = db.entregas_de_webhook(webhook["id"])
    assert len(entregas) == 3
    assert [e["intento_num"] for e in entregas] == [3, 2, 1]  # orden descendente (más reciente primero)
    assert all(e["estado_http"] is None and e["error"] for e in entregas)


def test_entregar_deja_de_reintentar_tras_un_exito(usuario_id, monkeypatch):
    webhook = dict(db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook", ["nota.creada"]))
    llamadas = {"n": 0}

    def fake_urlopen(req, timeout=None):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise urllib.error.URLError("fallo transitorio")
        return _RespuestaFalsa(200)

    monkeypatch.setattr(ev.urllib.request, "urlopen", fake_urlopen)
    ev._entregar(webhook, "nota.creada", {})

    assert llamadas["n"] == 2
    entregas = db.entregas_de_webhook(webhook["id"])
    assert len(entregas) == 2
    assert entregas[0]["estado_http"] == 200  # el más reciente


def test_entregar_http_error_registra_el_codigo_de_estado(usuario_id, monkeypatch):
    webhook = dict(db.crear_webhook(usuario_id, None, "https://ejemplo.com/hook", ["nota.creada"]))

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "error interno", {}, None)

    monkeypatch.setattr(ev.urllib.request, "urlopen", fake_urlopen)
    ev._entregar(webhook, "nota.creada", {})

    entregas = db.entregas_de_webhook(webhook["id"])
    assert all(e["estado_http"] == 500 for e in entregas)
