"""Vigilancia de la IA del despacho (Y11): avisa a la dirección cuando el consumo del mes cruza el 80 % o el 100 % del tope, y cuando un proveedor de IA falla de forma sostenida.

Se dispara en el momento exacto en que se cruza el umbral (al contar una consulta o al anotar un fallo), así que cada aviso sale una sola vez por mes y no hace falta recordar nada. **No cambia de proveedor por su
cuenta**: pasar los datos de los clientes a otro proveedor sin que la dirección lo haya decidido sería una salida de datos nueva (RGPD); solo avisa para que se cambie a mano en los ajustes de IA."""
from __future__ import annotations

import logging

from . import db

logger = logging.getLogger("guilda")
UMBRALES_CONSUMO = (80, 100)
ERRORES_PARA_AVISAR = (5, 25)


def _direccion(tenant_id: int) -> list[int]:
    return [uid for uid in db.usuarios_de_tenant(tenant_id) if (u := db.obtener_usuario(uid)) and u["supervisor_tenant"]]


def _avisar(tenant_id: int, tipo: str, titulo: str, cuerpo: str) -> int:
    from . import notificaciones
    n = 0
    for uid in _direccion(tenant_id):
        try:
            notificaciones.crear_y_enviar(uid, tipo, titulo, cuerpo, url="/ia/ajustes", despacho_id=tenant_id)
            n += 1
        except Exception:  # noqa: BLE001
            logger.warning("No se pudo avisar a %s del consumo de IA", uid, exc_info=True)
    return n


def umbral_cruzado(antes: int, despues: int, limite: int | None) -> int | None:
    """El mayor umbral de consumo (en %) que se cruza al pasar de `antes` a `despues` consultas con ese tope, o None."""
    if not limite:
        return None
    cruzados = [u for u in UMBRALES_CONSUMO if antes * 100 < u * limite <= despues * 100]
    return max(cruzados) if cruzados else None


def avisar_consumo(tenant_id: int, antes: int, despues: int, limite: int | None) -> int:
    """Notifica a la dirección si el consumo acaba de cruzar un umbral. Devuelve a cuántas personas avisó."""
    from flask_babel import gettext as _
    u = umbral_cruzado(antes, despues, limite)
    if u is None:
        return 0
    if u >= 100:
        return _avisar(tenant_id, "ia_consumo", _("Tu despacho ha agotado el límite mensual de IA"), _("Has usado las %(n)s consultas del mes. Se renueva el día 1; si lo necesitas antes, contacta con soporte.", n=limite))
    return _avisar(tenant_id, "ia_consumo", _("Tu despacho ha usado el %(p)s %% del límite mensual de IA", p=u), _("Van %(d)s de %(l)s consultas este mes.", d=despues, l=limite))


def avisar_fallos(tenant_id: int, proveedor: str, errores: int, llamadas: int) -> int:
    """Notifica a la dirección cuando un proveedor acumula `ERRORES_PARA_AVISAR` fallos en el mes y fallan al menos tantas consultas como salen bien."""
    from flask_babel import gettext as _
    if errores not in ERRORES_PARA_AVISAR or errores < llamadas:
        return 0
    return _avisar(tenant_id, "ia_proveedor", _("El proveedor de IA «%(p)s» está fallando", p=proveedor),
                   _("Lleva %(e)s consultas fallidas este mes frente a %(l)s correctas. Revisa la clave y el modelo en los ajustes de IA o cambia de proveedor.", e=errores, l=llamadas))
