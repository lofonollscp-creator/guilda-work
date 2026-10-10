"""Webhooks salientes (app/eventos.py): cola persistente con reintentos, firma HMAC, entrega «al menos una vez».
Se mockea urllib.request.urlopen; nunca hay red ni esperas reales."""
import hashlib
import hmac
import json
import urllib.error
from datetime import datetime, timedelta

import pytest

from app import db, eventos as ev


@pytest.fixture(autouse=True)
def _sin_hilo(monkeypatch):
    """Los tests llaman a procesar_pendientes() a mano: el hilo de fondo no debe arrancar."""
    monkeypatch.setattr(ev, "iniciar_worker", lambda: None)


class _Resp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _webhook(usuario_id, eventos=("nota.creada",), tenant_id=None):
    return db.crear_webhook(usuario_id, tenant_id, "https://ejemplo.com/hook", list(eventos))


def _futuro(segundos):
    return datetime.now() + timedelta(seconds=segundos)


def test_firmar_coincide_con_hmac_sha256_calculado_a_mano():
    cuerpo = b'{"evento":"nota.creada"}'
    assert ev._firmar(cuerpo, "mi-secreto") == "sha256=" + hmac.new(b"mi-secreto", cuerpo, hashlib.sha256).hexdigest()


def test_emitir_sin_webhooks_no_encola_nada(usuario_id):
    ev.emitir("nota.creada", None, {"a": 1})
    assert db.cola_webhook_resumen() == {}


def test_emitir_encola_solo_para_los_suscritos_y_sobrevive_en_la_base(usuario_id):
    a = _webhook(usuario_id, ["nota.creada"])
    b = _webhook(usuario_id, ["nota.creada", "tarea.creada"])
    _webhook(usuario_id, ["tarea.creada"])
    ev.emitir("nota.creada", None, {"nota_id": 5})
    assert db.cola_webhook_resumen() == {"pendiente": 2}
    assert {c["id"] for c in db.cola_webhook_de(a["id"])} and db.cola_webhook_de(b["id"])[0]["evento"] == "nota.creada"


def test_un_fallo_al_consultar_webhooks_no_lanza(monkeypatch):
    monkeypatch.setattr(ev.db, "webhooks_para_evento", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ev.emitir("nota.creada", None, {})


def test_entrega_correcta_firma_cabeceras_y_cuerpo(usuario_id, monkeypatch):
    w = _webhook(usuario_id)
    ev.emitir("nota.creada", None, {"nota_id": 5})
    capturado = {}

    def fake(req, timeout=None):
        capturado.update(req=req, timeout=timeout)
        return _Resp(200)

    monkeypatch.setattr(ev.urllib.request, "urlopen", fake)
    assert ev.procesar_pendientes() == 1
    req = capturado["req"]
    cuerpo = req.data
    cab = {k.lower(): v for k, v in req.header_items()}
    assert cab["x-guilda-signature"] == "sha256=" + hmac.new(w["secreto"].encode(), cuerpo, hashlib.sha256).hexdigest()
    assert cab["x-guilda-event"] == "nota.creada" and cab["x-guilda-delivery"].isdigit()
    datos = json.loads(cuerpo)
    assert datos["evento"] == "nota.creada" and datos["datos"] == {"nota_id": 5} and datos["id"] == f"evt_{cab['x-guilda-delivery']}" and datos["fecha"]
    assert db.cola_webhook_resumen() == {"entregado": 1}
    assert db.entregas_de_webhook(w["id"])[0]["estado_http"] == 200
    assert ev.procesar_pendientes() == 0                                  # no se entrega dos veces


def test_reintentos_con_retroceso_hasta_dar_por_fallido(usuario_id, monkeypatch):
    w = _webhook(usuario_id)
    ev.emitir("nota.creada", None, {})
    intentos = []

    def falla(req, timeout=None):
        intentos.append(1)
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(ev.urllib.request, "urlopen", falla)
    reloj = datetime.now()
    for n, espera in enumerate(ev.REINTENTOS_SEGUNDOS):
        assert ev.procesar_pendientes(reloj) == 1, n
        assert ev.procesar_pendientes(reloj) == 0                          # aún no toca el siguiente
        if n + 1 < len(ev.REINTENTOS_SEGUNDOS):
            reloj = reloj + timedelta(seconds=ev.REINTENTOS_SEGUNDOS[n + 1] + 5)
    assert len(intentos) == len(ev.REINTENTOS_SEGUNDOS) == 6
    assert db.cola_webhook_resumen() == {"fallido": 1}
    assert max(e["intento_num"] for e in db.entregas_de_webhook(w["id"])) == 6


def test_un_fallo_y_luego_exito_deja_entregado(usuario_id, monkeypatch):
    _webhook(usuario_id)
    ev.emitir("nota.creada", None, {})
    respuestas = [urllib.error.URLError("sin red"), _Resp(204)]

    def fake(req, timeout=None):
        r = respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(ev.urllib.request, "urlopen", fake)
    ev.procesar_pendientes()
    assert db.cola_webhook_resumen() == {"pendiente": 1}
    ev.procesar_pendientes(_futuro(60))
    assert db.cola_webhook_resumen() == {"entregado": 1}


def test_un_webhook_lento_o_roto_no_bloquea_a_los_demas(usuario_id, monkeypatch):
    malo = db.crear_webhook(usuario_id, None, "https://malo.example/h", ["nota.creada"])
    bueno = db.crear_webhook(usuario_id, None, "https://bueno.example/h", ["nota.creada"])
    ev.emitir("nota.creada", None, {})

    def fake(req, timeout=None):
        if "malo" in req.full_url:
            raise TimeoutError("lento")
        return _Resp(200)

    monkeypatch.setattr(ev.urllib.request, "urlopen", fake)
    assert ev.procesar_pendientes() == 2
    assert db.cola_webhook_de(bueno["id"])[0]["estado"] == "entregado" and db.cola_webhook_de(malo["id"])[0]["estado"] == "pendiente"


def test_lo_atascado_tras_una_caida_se_recupera(usuario_id, monkeypatch):
    _webhook(usuario_id)
    ev.emitir("nota.creada", None, {})
    reclamadas = db.cola_webhook_reclamar(datetime.now().isoformat(timespec="seconds"), 10)     # el proceso «muere» aquí
    assert len(reclamadas) == 1 and db.cola_webhook_resumen() == {"entregando": 1}
    assert ev.procesar_pendientes() == 0                                                         # reciente: se respeta
    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda req, timeout=None: _Resp(200))
    assert ev.procesar_pendientes(_futuro(ev.ATASCADO_SEGUNDOS + 60)) == 1
    assert db.cola_webhook_resumen() == {"entregado": 1}


def test_dos_procesos_no_entregan_lo_mismo_dos_veces(usuario_id):
    _webhook(usuario_id)
    ev.emitir("nota.creada", None, {})
    ahora = datetime.now().isoformat(timespec="seconds")
    assert len(db.cola_webhook_reclamar(ahora, 10)) == 1 and db.cola_webhook_reclamar(ahora, 10) == []


def test_webhook_borrado_o_desactivado_cierra_el_envio(usuario_id, monkeypatch):
    w = _webhook(usuario_id)
    ev.emitir("nota.creada", None, {})
    conn = db.get_connection()
    conn.execute("UPDATE webhooks SET activo = 0 WHERE id = ?", (w["id"],)); conn.commit(); conn.close()
    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debería llamar")))
    ev.procesar_pendientes()
    assert db.cola_webhook_resumen() == {"fallido": 1}
    db.borrar_webhook(w["id"])
    assert db.cola_webhook_resumen() == {}


def test_prueba_ping_y_reintento_manual(usuario_id, monkeypatch):
    w = _webhook(usuario_id, ["tarea.creada"])                           # no suscrito a ping, da igual
    assert ev.enviar_prueba(w["id"]) and not ev.enviar_prueba(9999)
    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("x")))
    reloj = datetime.now()
    for espera in ev.REINTENTOS_SEGUNDOS:
        ev.procesar_pendientes(reloj)
        reloj += timedelta(seconds=espera + 1000000)
    cola_id = db.cola_webhook_de(w["id"])[0]["id"]
    assert db.cola_webhook_resumen() == {"fallido": 1}
    assert db.cola_webhook_reintentar(cola_id) and not db.cola_webhook_reintentar(cola_id)
    assert db.cola_webhook_resumen() == {"pendiente": 1}


def test_purga_de_entregados_y_fallidos_antiguos(usuario_id, monkeypatch):
    _webhook(usuario_id)
    ev.emitir("nota.creada", None, {})
    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda req, timeout=None: _Resp(200))
    ev.procesar_pendientes()
    db.cola_webhook_purgar("2000-01-01T00:00:00", "2000-01-01T00:00:00")
    assert db.cola_webhook_resumen() == {"entregado": 1}                   # reciente: se queda
    db.cola_webhook_purgar("2999-01-01T00:00:00", "2999-01-01T00:00:00")
    assert db.cola_webhook_resumen() == {}


def test_eventos_nuevos_estan_en_el_catalogo():
    assert {"cliente.creado", "correo.sin_respuesta"} <= set(ev.EVENTOS)


def test_crear_cliente_fiscal_emite_cliente_creado(usuario_id):
    t = db.crear_tenant("Despacho eventos")
    db.crear_webhook(usuario_id, t, "https://ejemplo.com/h", ["cliente.creado"])
    db.crear_cliente_fiscal(t, "Cliente Nuevo SL", nif="B123")
    cola = db.cola_webhook_de(db.listar_webhooks(t)[0]["id"])
    assert len(cola) == 1 and cola[0]["evento"] == "cliente.creado"
