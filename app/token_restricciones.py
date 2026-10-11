"""Restricciones de red de un token de API: de qué direcciones IP puede usarse y desde qué orígenes web (CORS) puede
llamarse desde un navegador. Funciones puras: las usan `db.crear_token_api`, `auth.token_required` y las rutas."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

MAX_ORIGENES = 10
MAX_IPS = 20

_HOST_LOCAL = {"localhost", "127.0.0.1", "[::1]"}


def _como_lista(valor) -> list[str]:
    if valor in (None, "", []):
        return []
    if isinstance(valor, str):
        valor = re.split(r"[\s,]+", valor.strip())
    return [str(v).strip() for v in valor if str(v).strip()]


def validar_origenes(valor) -> list[str]:
    """Orígenes CORS exactos (`https://panel.ejemplo.com`, con puerto si no es el estándar). Sin comodines, sin ruta y solo
    `https` (o `http` para localhost, en desarrollo). ValueError con un mensaje claro si alguno no vale."""
    limpios: list[str] = []
    for origen in _como_lista(valor):
        if "*" in origen:
            raise ValueError("Los orígenes CORS no admiten comodines: indica cada origen exacto.")
        partes = urlsplit(origen)
        host = partes.hostname or ""
        valido = (partes.scheme == "https" or (partes.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"})) \
            and host and not partes.path.strip("/") and not partes.query and not partes.fragment and not partes.username
        if not valido:
            raise ValueError(f"Origen CORS no válido: «{origen}». Usa https://dominio[:puerto], sin ruta.")
        puerto = f":{partes.port}" if partes.port else ""
        normal = f"{partes.scheme}://{host if ':' not in host else '[' + host + ']'}{puerto}".lower()
        if normal not in limpios:
            limpios.append(normal)
    if len(limpios) > MAX_ORIGENES:
        raise ValueError(f"Máximo {MAX_ORIGENES} orígenes CORS por token.")
    return limpios


def validar_ips(valor) -> list[str]:
    """Direcciones IP o redes CIDR (`203.0.113.7`, `10.0.0.0/24`). ValueError si alguna no es válida."""
    limpias: list[str] = []
    for entrada in _como_lista(valor):
        try:
            red = ipaddress.ip_network(entrada, strict=False)
        except ValueError:
            raise ValueError(f"Dirección IP no válida: «{entrada}». Usa una IP (203.0.113.7) o una red (10.0.0.0/24).") from None
        texto = str(red.network_address) if red.num_addresses == 1 else str(red)
        if texto not in limpias:
            limpias.append(texto)
    if len(limpias) > MAX_IPS:
        raise ValueError(f"Máximo {MAX_IPS} direcciones IP por token.")
    return limpias


def ip_permitida(ip: str | None, permitidas: list[str]) -> bool:
    """Sin lista = cualquier IP. Con lista, la IP tiene que conocerse y caer en alguna entrada."""
    if not permitidas:
        return True
    if not ip:
        return False
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(direccion in ipaddress.ip_network(p, strict=False) for p in permitidas)
