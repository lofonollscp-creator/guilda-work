"""Las tareas periódicas de la plataforma vistas desde el backoffice: cuándo pasó cada una por última vez, si acabó bien y cuál es su intervalo, y la posibilidad de relanzar a mano las que
son seguras de repetir (cada envío queda registrado, así que una pasada de más no duplica nada). Las demás (sincronización de correo, cola de envíos…) se dejan al planificador."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from . import db, salud

logger = logging.getLogger("guilda")


def _recordatorios_portal() -> str:
    from . import portal_avisos, portal_recordatorios
    enviados = portal_recordatorios.procesar_recordatorios()
    otros = portal_avisos.procesar()
    return f"{enviados} enviado(s), {otros['recordatorios']} de seguimiento, {otros['resumenes']} resumen(es)"


def _vigilante_salud() -> str:
    avisados = salud.vigilar()
    return f"{len(avisados)} punto(s) avisado(s)"


def _recordatorios_tareas() -> str:
    from . import recordatorios_tareas
    recordatorios_tareas.procesar_recordatorios()
    return "pasada hecha"


# nombre del latido -> (qué hace, intervalo en segundos con el que lo anota el planificador)
RELANZABLES = {
    "recordatorios_portal": (_recordatorios_portal, 6 * 3600),
    "vigilante_salud": (_vigilante_salud, 15 * 60),
    "recordatorios_tareas": (_recordatorios_tareas, 180),
}
_en_marcha: set[str] = set()
_cerrojo = threading.Lock()


def listar(ahora: datetime | None = None) -> list[dict]:
    """Una fila por tarea conocida: {nombre, etiqueta, estado, detalle, ultimo_ok, ultimo_error, intervalo_segundos, relanzable, en_marcha}."""
    ahora = ahora or datetime.now()
    try:
        latidos = db.listar_latidos()
    except Exception:  # noqa: BLE001
        latidos = {}
    filas = []
    for nombre, etiqueta in salud.ETIQUETAS_LATIDOS.items():
        fila = latidos.get(nombre)
        item = salud._estado_latido(nombre, fila, ahora)
        filas.append({"nombre": nombre, "etiqueta": etiqueta(), "estado": item["estado"], "detalle": item["detalle"], "ultimo_ok": fila["ultimo_ok"] if fila else None,
                      "ultimo_error": fila["ultimo_error"] if fila else None, "intervalo_segundos": fila["intervalo_segundos"] if fila else None,
                      "relanzable": nombre in RELANZABLES, "en_marcha": nombre in _en_marcha})
    orden = {salud.ROJO: 0, salud.AMBAR: 1, salud.GRIS: 2, salud.VERDE: 3}
    return sorted(filas, key=lambda f: (orden.get(f["estado"], 4), f["etiqueta"]))


def relanzar(nombre: str, esperar: bool = False) -> bool:
    """Lanza ahora una pasada de esa tarea en segundo plano (o aquí mismo con `esperar`). False si no se puede relanzar a mano o ya hay una en curso."""
    if nombre not in RELANZABLES:
        return False
    with _cerrojo:
        if nombre in _en_marcha:
            return False
        _en_marcha.add(nombre)
    funcion, intervalo = RELANZABLES[nombre]

    def _correr():
        try:
            detalle = funcion()
            salud.registrar_ok(nombre, intervalo, f"{detalle} (relanzada a mano)")
        except Exception as e:  # noqa: BLE001 -- se anota como error de la tarea; nunca se propaga
            logger.exception("Fallo al relanzar la tarea %s", nombre)
            salud.registrar_error(nombre, intervalo, f"{type(e).__name__}: {e} (relanzada a mano)")
        finally:
            with _cerrojo:
                _en_marcha.discard(nombre)

    if esperar:
        _correr()
    else:
        threading.Thread(target=_correr, daemon=True, name=f"relanzar-{nombre}").start()
    return True
