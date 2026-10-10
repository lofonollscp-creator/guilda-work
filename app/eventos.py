"""Webhooks salientes — Guilda Work avisa a una URL externa cuando pasa
algo relevante (ver `app/db.py`, tablas `webhooks`/`webhooks_entregas`,
y el backoffice para darlos de alta).

## Solo eventos de negocio concretos, no cada escritura

`emitir()` se llama desde un puñado de puntos concretos (ver
`EVENTOS` más abajo) — no hay un evento por cada nota o tarea que se
crea, sería ruido en el uso diario normal. Cada evento tiene valor
real de automatización (facturación por horas, disparar un flujo de
n8n, avisar a un CRM externo, marcar en un ERP externo que un modelo
ya se presentó).

## Cola persistente + reintentos con retroceso

`emitir()` guarda el trabajo en la tabla `webhooks_cola` (sobrevive a reinicios: antes vivía en memoria y se perdía) y
vuelve al instante, sin bloquear la petición que lo disparó. Un hilo de fondo recoge lo que toca entregar y lo reparte en
varios hilos de entrega (un webhook lento ya no retrasa a los demás). Si falla, se reintenta con retroceso
(inmediato, 30 s, 5 min, 30 min, 2 h, 12 h) y, agotados los intentos, queda como `fallido` en la cola. Cada intento se
registra en `webhooks_entregas`. Los envíos que se quedaron `entregando` por una caída se recuperan solos al cabo de
5 minutos. Para el receptor, cada entrega lleva `X-Guilda-Delivery` (id estable entre reintentos): sirve para
descartar duplicados, porque la entrega es «al menos una vez».

## Firma — mismo esquema que GitHub/Stripe, no uno inventado

`X-Guilda-Signature: sha256=<hmac>` sobre el cuerpo JSON tal cual se envía, con el `secreto` propio de cada webhook
(ver `db.py:crear_webhook`). Quien reciba el webhook debe recalcular el HMAC sobre el cuerpo crudo recibido y compararlo
— no fiarse solo de que la petición «parece» venir de Guilda Work.
"""
import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import db

TIMEOUT_SEGUNDOS = 10
# Espera antes de cada intento (el primero, inmediato). 6 intentos en total.
REINTENTOS_SEGUNDOS = [0, 30, 300, 1800, 7200, 43200]
HILOS_ENTREGA = 4
LOTE = 20
ATASCADO_SEGUNDOS = 300
PURGA_ENTREGADOS_DIAS = 7
PURGA_FALLIDOS_DIAS = 30

EVENTOS = [
    "tarea.finalizada", "nota.creada", "cita.reservada", "correo.mensaje_nuevo",
    "vencimiento.presentado", "factura.emitida", "documento.enviado_a_firma",
    "factura.cobrada",
    "tarea.creada", "tarea.completada", "tarea.asignada", "correo.enviado", "nota.editada",
    "cliente.creado", "correo.sin_respuesta",
]


_hilo_iniciado = False
_lock_hilo = threading.Lock()
_despertar = threading.Event()


def _firmar(cuerpo: bytes, secreto: str) -> str:
    return "sha256=" + hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _cuerpo(cola_id: int, evento: str, payload: dict, creado_en: str) -> bytes:
    return json.dumps({"id": f"evt_{cola_id}", "evento": evento, "fecha": creado_en, "datos": payload}, ensure_ascii=False).encode("utf-8")


def _entregar(webhook: dict, cola_id: int, evento: str, payload: dict, creado_en: str, intento: int) -> tuple[bool, int | None, str | None]:
    """Un único intento de entrega. Registra el intento y devuelve (ok, estado_http, error)."""
    cuerpo = _cuerpo(cola_id, evento, payload, creado_en)
    cabeceras = {
        "Content-Type": "application/json",
        "X-Guilda-Signature": _firmar(cuerpo, webhook["secreto"]),
        "X-Guilda-Event": evento,
        "X-Guilda-Delivery": str(cola_id),
    }
    req = urllib.request.Request(webhook["url"], data=cuerpo, method="POST", headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            estado, error = resp.status, None
    except urllib.error.HTTPError as e:
        estado, error = e.code, str(e)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        estado, error = None, str(e)
    db.registrar_entrega_webhook(webhook["id"], evento, estado, intento, error=error)
    return (estado is not None and 200 <= estado < 300), estado, error


def _procesar_una(fila: dict) -> None:
    webhook = db.obtener_webhook(fila["webhook_id"])
    if webhook is None or not webhook["activo"]:
        db.cola_webhook_cerrar(fila["id"], "fallido", "El webhook ya no existe o está desactivado.")
        return
    intento = fila["intentos"] + 1
    try:
        ok, estado, error = _entregar(dict(webhook), fila["id"], fila["evento"], json.loads(fila["payload_json"]), fila["creado_en"], intento)
    except Exception as e:  # un fallo inesperado nunca debe tumbar el hilo
        ok, estado, error = False, None, f"{type(e).__name__}: {e}"
    if ok:
        db.cola_webhook_cerrar(fila["id"], "entregado", None, intentos=intento)
    elif intento >= len(REINTENTOS_SEGUNDOS):
        db.cola_webhook_cerrar(fila["id"], "fallido", error or f"HTTP {estado}", intentos=intento)
    else:
        db.cola_webhook_reprogramar(fila["id"], intento, _iso(datetime.now() + timedelta(seconds=REINTENTOS_SEGUNDOS[intento])), error or f"HTTP {estado}")


def procesar_pendientes(ahora: datetime | None = None) -> int:
    """Entrega lo que toca (en paralelo) y devuelve cuántos envíos ha intentado. Lo llama el hilo de fondo; los tests
    lo llaman directamente."""
    ahora = ahora or datetime.now()
    db.cola_webhook_recuperar_atascados(_iso(ahora - timedelta(seconds=ATASCADO_SEGUNDOS)))
    filas = db.cola_webhook_reclamar(_iso(ahora), LOTE)
    if not filas:
        return 0
    with ThreadPoolExecutor(max_workers=min(HILOS_ENTREGA, len(filas))) as pool:
        list(pool.map(_procesar_una, filas))
    return len(filas)


def _worker() -> None:
    ultima_purga = 0.0
    while True:
        try:
            trabajado = procesar_pendientes()
            if time.monotonic() - ultima_purga > 3600:
                db.cola_webhook_purgar(_iso(datetime.now() - timedelta(days=PURGA_ENTREGADOS_DIAS)), _iso(datetime.now() - timedelta(days=PURGA_FALLIDOS_DIAS)))
                ultima_purga = time.monotonic()
        except Exception:
            trabajado = 0
        if not trabajado:
            _despertar.wait(timeout=5)
        _despertar.clear()


def iniciar_worker() -> None:
    """Arranca el hilo de entrega (una sola vez por proceso). `emitir()` también lo arranca si hace falta."""
    global _hilo_iniciado
    with _lock_hilo:
        if not _hilo_iniciado:
            threading.Thread(target=_worker, daemon=True, name="webhooks").start()
            _hilo_iniciado = True


def emitir(evento: str, tenant_id: int | None, payload: dict) -> None:
    """Guarda el evento en la cola para cada webhook activo suscrito a él — no bloquea, no lanza (un fallo al
    consultar webhooks o al guardar no debe impedir que la acción que disparó el evento se complete)."""
    try:
        webhooks = db.webhooks_para_evento(evento, tenant_id)
        if not webhooks:
            return
        for webhook in webhooks:
            db.cola_webhook_encolar(webhook["id"], evento, payload)
    except Exception:
        return
    iniciar_worker()
    _despertar.set()


def enviar_prueba(webhook_id: int) -> bool:
    """Encola un evento `ping` para ese webhook (aunque no esté suscrito a él) para comprobar que llega."""
    if db.obtener_webhook(webhook_id) is None:
        return False
    db.cola_webhook_encolar(webhook_id, "ping", {"mensaje": "Evento de prueba de Guilda Work"})
    iniciar_worker()
    _despertar.set()
    return True
