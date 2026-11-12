"""Rendimiento de la web, visto desde dentro (AB1).

Mide cada petición de la app (no del backoffice): deja la duración en la cabecera `Server-Timing`, escribe un aviso en el registro
cuando una tarda más de `GUILDA_PETICION_LENTA_MS` (1000 por defecto; solo la ruta, nunca la URL con sus parámetros) y cuenta las veces
que waitress avisa de que todos sus hilos están ocupados (la cola que deja la página «clavada»). Cada minuto como mucho se vuelca
un resumen a `data/backups/rendimiento_estado.json`, que es lo que lee la fila «Rendimiento de la web» de Salud (el backoffice es otro proceso).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

logger = logging.getLogger("guilda")

LENTA_MS = int(os.environ.get("GUILDA_PETICION_LENTA_MS", "1000"))
VENTANA_S = 3600
VOLCAR_CADA_S = 60
MAX_REGISTROS = 5000

_lock = threading.Lock()
_peticiones: deque = deque(maxlen=MAX_REGISTROS)     # (instante, ruta, método, estado, ms)
_colas: deque = deque(maxlen=1000)                   # instantes en que waitress avisó de cola
_ultimo_volcado = 0.0

# Rutas que no cuentan: se piden muy a menudo y no dicen nada del rendimiento de las pantallas.
_IGNORAR = ("/static/", "/notificaciones/recientes", "/sw.js")


def registrar(ruta: str, metodo: str, estado: int, ms: float, ahora: float | None = None) -> None:
    ahora = time.time() if ahora is None else ahora
    with _lock:
        _peticiones.append((ahora, ruta, metodo, estado, ms))


def registrar_cola(ahora: float | None = None) -> None:
    with _lock:
        _colas.append(time.time() if ahora is None else ahora)


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    v = sorted(valores)
    return v[min(len(v) - 1, int(len(v) * p))]


def resumen(ahora: float | None = None) -> dict:
    """Lo que ha pasado en la última hora: percentiles, peticiones lentas, rutas más lentas y avisos de cola saturada."""
    ahora = time.time() if ahora is None else ahora
    corte = ahora - VENTANA_S
    with _lock:
        recientes = [p for p in _peticiones if p[0] >= corte]
        colas_hora = sum(1 for c in _colas if c >= corte)
        colas_dia = sum(1 for c in _colas if c >= ahora - 86400)
    ms = [p[4] for p in recientes]
    por_ruta: dict[str, list[float]] = defaultdict(list)
    for _t, ruta, metodo, _e, d in recientes:
        por_ruta[f"{metodo} {ruta}"].append(d)
    peores = sorted(((k, len(v), _percentil(v, .95), max(v)) for k, v in por_ruta.items()), key=lambda x: -x[2])[:5]
    return {
        "fecha": datetime.fromtimestamp(ahora).isoformat(timespec="seconds"),
        "peticiones": len(recientes),
        "p50_ms": round(_percentil(ms, .5)), "p95_ms": round(_percentil(ms, .95)), "max_ms": round(max(ms)) if ms else 0,
        "lentas": sum(1 for d in ms if d >= LENTA_MS),
        "errores_5xx": sum(1 for p in recientes if p[3] >= 500),
        "peores": [{"ruta": k, "n": n, "p95_ms": round(p95), "max_ms": round(mx)} for k, n, p95, mx in peores],
        "cola_saturada_hora": colas_hora, "cola_saturada_dia": colas_dia,
        "swap_proceso_mb": _swap_del_proceso_mb(),
    }


def _swap_del_proceso_mb() -> int | None:
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("VmSwap:"):
                    return int(linea.split()[1]) // 1024
    except OSError:
        pass
    return None


def volcar(ruta_fichero, forzar: bool = False) -> bool:
    """Escribe el resumen (como mucho una vez por minuto). Nunca rompe la petición que lo dispara."""
    global _ultimo_volcado
    ahora = time.time()
    if not forzar and ahora - _ultimo_volcado < VOLCAR_CADA_S:
        return False
    _ultimo_volcado = ahora
    try:
        tmp = str(ruta_fichero) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(resumen(ahora), f, ensure_ascii=False)
        os.replace(tmp, ruta_fichero)
        return True
    except OSError:
        logger.debug("No se pudo volcar el estado de rendimiento", exc_info=True)
        return False


class _AvisoDeCola(logging.Handler):
    """waitress escribe «Task queue depth is N» (WARNING, logger `waitress.queue`) cuando no quedan hilos libres."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            if "queue depth" in record.getMessage():
                registrar_cola()
        except Exception:  # noqa: BLE001 -- un manejador de registro nunca debe romper nada
            pass


def instalar(app, ruta_fichero) -> None:
    """Engancha la medición a la app de Flask. Idempotente."""
    from flask import g, request

    if getattr(app, "_rendimiento_instalado", False):
        return
    app._rendimiento_instalado = True
    cola = logging.getLogger("waitress.queue")
    if not any(isinstance(h, _AvisoDeCola) for h in cola.handlers):
        cola.addHandler(_AvisoDeCola())

    @app.before_request
    def _inicio_medicion():
        g._rendimiento_t0 = time.perf_counter()

    @app.after_request
    def _fin_medicion(respuesta):
        t0 = g.get("_rendimiento_t0")
        if t0 is None:
            return respuesta
        ms = (time.perf_counter() - t0) * 1000
        respuesta.headers["Server-Timing"] = f"app;dur={ms:.0f}"
        if request.path.startswith(_IGNORAR):
            return respuesta
        ruta = request.url_rule.rule if request.url_rule else "(sin ruta)"
        registrar(ruta, request.method, respuesta.status_code, ms)
        if ms >= LENTA_MS:
            logger.warning("Petición lenta: %s %s -> %s en %.0f ms (id %s)", request.method, ruta, respuesta.status_code, ms, g.get("request_id"))
        volcar(ruta_fichero)
        return respuesta
