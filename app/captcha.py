"""Captcha de prueba de trabajo (ALTCHA, https://altcha.org — licencia MIT,
sin CDN externo ni servicio de terceros) para la pantalla de login (ver
app/rutas_kratos_proxy.py) cuando una IP acumula demasiados fallos
seguidos, en vez de banearla directamente (eso lo sigue haciendo CrowdSec,
como red de respaldo).

Usa la API v1 de la librería `altcha` (paquete `altcha` en PyPI, cero
dependencias) — más simple que la v2, y es la que entiende por defecto el
widget `<altcha-widget>` vendido en app/static/altcha.min.js. El reto se
firma con GUILDA_SECRET_KEY, la misma clave que ya firma la cookie de
sesión (app/main.py) — no hace falta una variable de entorno nueva."""
import os
from datetime import datetime, timedelta

import altcha

_HMAC_KEY = os.environ.get("GUILDA_SECRET_KEY") or "clave-de-desarrollo-no-usar-en-produccion"
EXPIRA_MINUTOS = 5


def generar_reto() -> dict:
    """Devuelve el reto en el formato que espera `<altcha-widget
    challengeurl="...">` -- claves en minúscula sin guion bajo
    (`maxnumber`, no `max_number`), tal cual las define el propio widget
    JS de ALTCHA."""
    reto = altcha.create_challenge_v1(
        hmac_key=_HMAC_KEY,
        expires=datetime.now() + timedelta(minutes=EXPIRA_MINUTOS),
    )
    return {
        "algorithm": reto.algorithm,
        "challenge": reto.challenge,
        "maxnumber": reto.max_number,
        "salt": reto.salt,
        "signature": reto.signature,
    }


def verificar_solucion(payload: str | None) -> bool:
    """True si `payload` (el campo `altcha` que manda el formulario, un
    JSON en base64 que el propio widget rellena al resolver el reto) es
    una solución válida y no caducada."""
    if not payload:
        return False
    # altcha.verify_solution (sin sufijo) resuelve al símbolo v2, con una
    # firma distinta -- hay que llamar explícitamente a la variante v1,
    # misma que create_challenge_v1() de generar_reto().
    valido, _error = altcha.verify_solution_v1(payload, _HMAC_KEY, check_expires=True)
    return valido
