"""Comprobación de un NIF-IVA intracomunitario en VIES (el servicio de la Comisión Europea). Solo se pregunta por números de otro país de la UE y con prudencia: tiempo de espera corto, resultado en
caché 24 horas y, si el servicio no responde (que pasa a menudo), «no se sabe», nunca «no válido». Lo usa la lectura de facturas para avisar de un NIF-IVA que no existe."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"
TIMEOUT_SEGUNDOS = 6
CACHE_SEGUNDOS = 24 * 3600
PAISES = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI"}   # sin ES (es nacional)
_cache: dict[str, tuple[float, bool | None]] = {}


def separar(nif: str) -> tuple[str, str] | None:
    """(país, número) de un NIF-IVA de otro país de la UE («DE123456789»), o None si no lo es (un NIF español, uno sin prefijo, un país fuera de la UE)."""
    t = re.sub(r"[\s.\-]", "", (nif or "")).upper()
    m = re.fullmatch(r"([A-Z]{2})([A-Z0-9]{2,14})", t)
    return (m.group(1), m.group(2)) if m and m.group(1) in PAISES else None


def valido(nif: str, ahora: float | None = None) -> bool | None:
    """True/False si VIES lo confirma o lo niega; None si no es de otro país de la UE o el servicio no ha contestado."""
    partes = separar(nif)
    if partes is None:
        return None
    clave = partes[0] + partes[1]
    ahora = ahora if ahora is not None else time.time()
    previo = _cache.get(clave)
    if previo and ahora - previo[0] < CACHE_SEGUNDOS:
        return previo[1]
    try:
        peticion = urllib.request.Request(URL, data=json.dumps({"countryCode": partes[0], "vatNumber": partes[1]}).encode(), method="POST", headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEGUNDOS) as r:
            datos = json.loads(r.read().decode("utf-8"))
        resultado = bool(datos["valid"]) if isinstance(datos, dict) and isinstance(datos.get("valid"), bool) else None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError):
        return None                                                           # sin respuesta no se cachea: se volverá a preguntar
    _cache[clave] = (ahora, resultado)
    return resultado
