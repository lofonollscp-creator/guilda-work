"""Notas de voz del cliente (K7): apagadas por defecto, nada sale si el despacho exige «solo local» y la transcripción usa la clave del despacho."""
import io
import json

import pytest

from app import db, portal_compromiso as pcm, portal_voz as pv
from tests.test_portal_bandeja import _escenario


class _Resp:
    def __init__(self, cuerpo): self._c = cuerpo
    def read(self): return json.dumps(self._c).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _con_proveedor(monkeypatch, cliente, proveedor="openai"):
    monkeypatch.setattr(pv.portal_lectura_previa, "lector_de", lambda c: 1)
    monkeypatch.setattr(pv.ia_asistente, "candidatos", lambda uid, tarea: [{"proveedor": proveedor, "modelo": "m", "claves": ["k1", "k2"], "url_base": None, "origen": "despacho"}])


def test_apagado_por_defecto_y_sin_proveedor_que_transcriba(cliente, monkeypatch):
    t, u, c, f1, c2, f2 = _escenario()
    _con_proveedor(monkeypatch, cliente)
    assert pv.disponible(f1) is False                                                      # el despacho no la ha encendido
    pcm.fijar(t, voz_cliente=True)
    assert pv.disponible(f1) is True
    _con_proveedor(monkeypatch, cliente, "anthropic")
    assert pv.disponible(f1) is False                                                      # Claude no transcribe audio


def test_solo_local_impide_que_el_audio_salga(cliente, monkeypatch):
    t, u, c, f1, c2, f2 = _escenario()
    _con_proveedor(monkeypatch, cliente)
    pcm.fijar(t, voz_cliente=True)
    conn = db.get_connection(); conn.execute("INSERT INTO ia_config_despacho (tenant_id, ocr_local, actualizado_en) VALUES (?, 'solo_local', ?) ON CONFLICT (tenant_id) DO UPDATE SET ocr_local = 'solo_local'", (t, db.now_iso())); conn.commit(); conn.close()
    assert pv.disponible(f1) is False


def test_transcribe_con_la_clave_buena_y_valida_el_audio(cliente, monkeypatch):
    t, u, c, f1, c2, f2 = _escenario()
    _con_proveedor(monkeypatch, cliente)
    pcm.fijar(t, voz_cliente=True)
    llamadas = []

    def abrir(req, timeout=0):
        llamadas.append((req.full_url, req.headers.get("Authorization"), req.data))
        if len(llamadas) == 1:
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 429, "límite", {}, io.BytesIO(b"{}"))
        return _Resp({"text": "  Hola, os mando la factura de la luz.  "})
    monkeypatch.setattr(pv.urllib.request, "urlopen", abrir)
    assert pv.transcribir(f1, b"\x1aE\xdf\xa3audio", "audio/webm;codecs=opus", "es") == "Hola, os mando la factura de la luz."
    assert [x[1] for x in llamadas] == ["Bearer k1", "Bearer k2"] and llamadas[0][0].endswith("/audio/transcriptions") and b'name="language"' in llamadas[0][2]
    for malo, mime in ((b"", "audio/webm"), (b"x", "video/mp4"), (b"x" * (pv.MAX_BYTES + 1), "audio/webm")):
        with pytest.raises(ValueError):
            pv.transcribir(f1, malo, mime)


def test_un_fallo_del_proveedor_da_un_mensaje_para_el_cliente(cliente, monkeypatch):
    t, u, c, f1, c2, f2 = _escenario()
    _con_proveedor(monkeypatch, cliente)
    pcm.fijar(t, voz_cliente=True)
    import urllib.error

    def falla(req, timeout=0):
        raise urllib.error.URLError("sin red")
    monkeypatch.setattr(pv.urllib.request, "urlopen", falla)
    with pytest.raises(ValueError, match="No se ha podido pasar"):
        pv.transcribir(f1, b"audio", "audio/ogg")
    monkeypatch.setattr(pv.urllib.request, "urlopen", lambda req, timeout=0: _Resp({"text": "   "}))
    with pytest.raises(ValueError, match="No se ha entendido"):
        pv.transcribir(f1, b"audio", "audio/ogg")
