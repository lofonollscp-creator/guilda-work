"""Avisos de seguridad de la cuenta (Y10): cuando alguien añade o quita una passkey, el segundo factor (app de autenticación) o los códigos de recuperación de una cuenta, la persona recibe una notificación,
por si no fue ella. Los cambios los hace la propia persona en Kratos a través del proxy `/.ory/` (app/rutas_kratos_proxy.py): el proxy toma una foto de los métodos antes de reenviar el envío de ajustes y otra después,
y aquí se comparan. Un fallo de Kratos o de las notificaciones nunca estropea el cambio."""
from __future__ import annotations

import logging

from . import db, kratos

logger = logging.getLogger(__name__)
SEGUIMIENTO = {"passkey": "una passkey", "totp": "la verificación en dos pasos (app de autenticación)", "lookup_secret": "los códigos de recuperación"}


def instantanea(usuario_id: int) -> set[str] | None:
    """Los métodos de acceso que tiene la persona ahora mismo, o None si no se pueden consultar."""
    u = db.obtener_usuario(usuario_id)
    if u is None or u["es_local"] or not u["kratos_identity_id"]:
        return None
    try:
        return kratos.credenciales_de(u["kratos_identity_id"])
    except Exception:  # noqa: BLE001
        return None


def cambios(antes: set[str] | None, despues: set[str] | None) -> list[tuple[str, str]]:
    """[(método, 'añadido'|'quitado')] entre dos fotos; vacío si alguna falta."""
    if antes is None or despues is None:
        return []
    salida = [(m, "añadido") for m in SEGUIMIENTO if m in despues and m not in antes]
    return salida + [(m, "quitado") for m in SEGUIMIENTO if m in antes and m not in despues]


def avisar(usuario_id: int, antes: set[str] | None, despues: set[str] | None) -> list[tuple[str, str]]:
    """Notifica cada cambio a la persona y lo deja en la auditoría de la plataforma. Devuelve los cambios detectados."""
    from flask_babel import gettext as _
    from . import notificaciones
    hechos = cambios(antes, despues)
    for metodo, que in hechos:
        try:
            titulo = {"passkey": _("Se ha añadido una passkey a tu cuenta") if que == "añadido" else _("Se ha quitado una passkey de tu cuenta"),
                      "totp": _("Se ha activado la verificación en dos pasos en tu cuenta") if que == "añadido" else _("Se ha quitado la verificación en dos pasos de tu cuenta"),
                      "lookup_secret": _("Se han generado códigos de recuperación en tu cuenta") if que == "añadido" else _("Se han quitado los códigos de recuperación de tu cuenta")}[metodo]
            notificaciones.crear_y_enviar(usuario_id, "seguridad_cuenta", titulo, _("Si no has sido tú, cambia la contraseña y avisa a la dirección de tu despacho."), url="/ajustes/cuenta", ignorar_silencio=True)
            db.registrar_auditoria(None, "cuenta.metodo_" + que, f"usuario {usuario_id}: {metodo}")
        except Exception:  # noqa: BLE001
            logger.warning("No se pudo avisar del cambio de seguridad de la cuenta %s", usuario_id, exc_info=True)
    return hechos
