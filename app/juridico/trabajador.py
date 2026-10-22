"""Mantenimiento periódico del asistente jurídico: sincroniza las fuentes habilitadas con conector, reconcilia una ventana reciente y purga los adjuntos vencidos.

Apagado por defecto: solo corre con `LEGAL_AI_SYNC=1` (y `LEGAL_AI_ENABLED=1`). Nunca sincroniza una fuente sin política que lo permita (el motor de ingesta lo comprueba), una fuente que falla conserva
su última versión utilizable y se anota como incidencia, y un fallo de una fuente no impide las demás. Ventana de reconciliación propuesta: 7 días (configurable con `LEGAL_AI_VENTANA_DIAS`); es una
decisión nuestra, no un compromiso de ninguna fuente: una ventana corta no garantiza detectar correcciones muy tardías."""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta

from . import adjuntos, catalogo, corpus, ingesta, modulo

logger = logging.getLogger(__name__)
INTERVALO_SEGUNDOS = int(os.environ.get("LEGAL_AI_INTERVALO", 6 * 3600))


def activo() -> bool:
    return modulo.habilitado() and os.environ.get("LEGAL_AI_SYNC", "").strip().lower() in ("1", "true", "yes", "si", "sí")


def ejecutar_ciclo(hoy: date | None = None, conectores: dict | None = None) -> dict:
    """Un ciclo: devuelve {fuente_id: resumen o error}. `conectores` permite inyectar los de prueba."""
    hoy = hoy or date.today()
    ventana = int(os.environ.get("LEGAL_AI_VENTANA_DIAS", 7))
    desde, hasta = (hoy - timedelta(days=ventana)).isoformat(), hoy.isoformat()
    salida = {}
    for f in corpus.listar_fuentes():
        if not f["habilitada"]:
            continue
        try:
            conector = (conectores or {}).get(f["id"]) or catalogo.crear_conector(f["id"])
            if not conector.capacidades.descubrir:
                continue
            r = ingesta.sincronizar(f["id"], conector, desde, hasta)
            salida[f["id"]] = {"estado": r["estado"], "contadores": r["contadores"], "error": r["error"]}
        except Exception as e:  # noqa: BLE001 -- una fuente rota no tumba el ciclo
            salida[f["id"]] = {"estado": "error", "error": str(e)}
            logger.warning("Sincronización jurídica de %s fallida: %s", f["id"], e)
    try:
        salida["adjuntos_purgados"] = adjuntos.purgar_vencidos()
    except Exception as e:  # noqa: BLE001
        logger.warning("Purga de adjuntos jurídicos fallida: %s", e)
    return salida


def bucle() -> None:
    """Hilo demonio (lo arranca app/main.py solo si `activo()`)."""
    time.sleep(60)
    while True:
        try:
            ejecutar_ciclo()
        except Exception:  # noqa: BLE001
            logger.exception("Ciclo jurídico fallido")
        time.sleep(INTERVALO_SEGUNDOS)
