"""Webhooks salientes — Guilda Work avisa a una URL externa cuando pasa
algo relevante (ver `app/db.py`, tablas `webhooks`/`webhooks_entregas`,
y el backoffice para darlos de alta).

## Solo eventos de negocio concretos, no cada escritura

`emitir()` se llama desde un puñado de puntos concretos (ver
`EVENTOS` más abajo) — no hay un evento por cada nota o tarea que se
crea, sería ruido en el uso diario normal. Los cuatro eventos
iniciales tienen valor real de automatización (facturación por horas,
disparar un flujo de n8n, avisar a un CRM externo).

## Cola en memoria + un único hilo de fondo

Mismo patrón que `app/main.py:_sincronizacion_correo_periodica` (un
`threading.Thread(daemon=True)`, sin Celery/Redis/cola persistente —
no hace falta a esta escala): `emitir()` mete el trabajo en una
`queue.Queue` y vuelve al instante, sin bloquear la petición que lo
disparó; un hilo único la consume y hace el POST real. Limitación
conocida y aceptada: al ser un único hilo, un webhook lento con
reintentos retrasa la entrega de los siguientes en la cola — aceptable
al volumen de este proyecto (unos pocos eventos de negocio, no un
sistema de mensajería de alto tráfico).

## Firma — mismo esquema que GitHub/Stripe, no uno inventado

`X-Guilda-Signature: sha256=<hmac>` sobre el cuerpo JSON tal cual se
envía, con el `secreto` propio de cada webhook (ver
`db.py:crear_webhook`). Quien reciba el webhook debe recalcular el HMAC
sobre el cuerpo crudo recibido y compararlo — no fiarse solo de que la
petición "parece" venir de Guilda Work.

3 intentos con backoff (inmediato, +30s, +5min) antes de darlo por
fallido; cada intento se registra en `webhooks_entregas`, visible desde
el backoffice para depurar un webhook que no está funcionando."""
import hashlib
import hmac
import json
import queue
import threading
import time
import urllib.error
import urllib.request

from . import db

TIMEOUT_SEGUNDOS = 10
REINTENTOS_SEGUNDOS = [0, 30, 300]

EVENTOS = ["tarea.finalizada", "nota.creada", "cita.reservada", "correo.mensaje_nuevo"]

_cola: "queue.Queue[tuple[dict, str, dict]]" = queue.Queue()
_hilo_iniciado = False
_lock_hilo = threading.Lock()


def _firmar(cuerpo: bytes, secreto: str) -> str:
    return "sha256=" + hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def _entregar(webhook: dict, evento: str, payload: dict) -> None:
    cuerpo = json.dumps({"evento": evento, "datos": payload}, ensure_ascii=False).encode("utf-8")
    firma = _firmar(cuerpo, webhook["secreto"])
    cabeceras = {
        "Content-Type": "application/json",
        "X-Guilda-Signature": firma,
        "X-Guilda-Event": evento,
    }
    for intento, espera in enumerate(REINTENTOS_SEGUNDOS, start=1):
        if espera:
            time.sleep(espera)
        req = urllib.request.Request(webhook["url"], data=cuerpo, method="POST", headers=cabeceras)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
                db.registrar_entrega_webhook(webhook["id"], evento, resp.status, intento)
                return
        except urllib.error.HTTPError as e:
            db.registrar_entrega_webhook(webhook["id"], evento, e.code, intento, error=str(e))
        except (urllib.error.URLError, TimeoutError) as e:
            db.registrar_entrega_webhook(webhook["id"], evento, None, intento, error=str(e))


def _worker() -> None:
    while True:
        webhook, evento, payload = _cola.get()
        try:
            _entregar(webhook, evento, payload)
        except Exception:
            pass  # un fallo al entregar un webhook no debe tumbar el hilo
        finally:
            _cola.task_done()


def _asegurar_hilo() -> None:
    global _hilo_iniciado
    with _lock_hilo:
        if not _hilo_iniciado:
            threading.Thread(target=_worker, daemon=True).start()
            _hilo_iniciado = True


def emitir(evento: str, tenant_id: int | None, payload: dict) -> None:
    """Encola el evento para cada webhook activo suscrito a él — no
    bloquea, no lanza (un fallo al consultar webhooks o al entregar no
    debe impedir que la acción que disparó el evento se complete)."""
    try:
        webhooks = db.webhooks_para_evento(evento, tenant_id)
    except Exception:
        return
    if not webhooks:
        return
    _asegurar_hilo()
    for webhook in webhooks:
        _cola.put((dict(webhook), evento, payload))
