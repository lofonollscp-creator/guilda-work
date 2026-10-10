"""Quién puede usar el servidor MCP remoto y con qué alcance. Lo usa `mcp_server_remoto.py`.

Dos tipos de credencial, ambas por `Authorization: Bearer`:
- **Token OAuth2 de Hydra** (ChatGPT, Claude Desktop...). Solo se aceptan los de clientes pensados para usar el MCP: los
  que han pasado por la pantalla de consentimiento (registro dinámico), los marcados con `metadata.mcp = true` y los de
  `MCP_REMOTO_CLIENTES` (por defecto `claude-desktop`). Un token de un servicio satélite (Outline, Element, Drive...) NO
  vale: comprometer uno de ellos no debe dar acceso a todas las herramientas del usuario.
- **Token personal de API** (`tokens_api`): hereda sus áreas y su permiso de solo lectura. Es la forma de dar a una
  integración un MCP limitado (p. ej. solo fiscal y solo lectura) sin OAuth.

El alcance viaja en los `scopes` del AccessToken (`usuario:7`, `area:fiscal`, `solo_lectura`); `mcp_tools._uid` y el
guardián de `mcp_tools.registrar_tools` los leen."""
from __future__ import annotations

import os
import time

from . import db, hydra

_CACHE_CLIENTES: dict[str, tuple[float, bool]] = {}
_TTL = 300.0


def _clientes_permitidos_por_nombre() -> set[str]:
    return {n.strip() for n in os.environ.get("MCP_REMOTO_CLIENTES", "claude-desktop").split(",") if n.strip()}


def cliente_hydra_permitido(client_id: str) -> bool:
    """¿Puede un token de este cliente OAuth2 usar el MCP? (con caché de 5 min)"""
    if not client_id:
        return False
    guardado = _CACHE_CLIENTES.get(client_id)
    if guardado and time.monotonic() - guardado[0] < _TTL:
        return guardado[1]
    try:
        cliente = hydra.obtener_cliente(client_id)
    except hydra.ErrorHydra:
        return False  # sin poder comprobarlo, cerrado
    if cliente is None:
        permitido = False
    else:
        metadata = cliente.get("metadata") or {}
        permitido = bool(metadata.get("mcp")) or cliente.get("client_name") in _clientes_permitidos_por_nombre() or not cliente.get("skip_consent")
    _CACHE_CLIENTES[client_id] = (time.monotonic(), permitido)
    return permitido


def scopes_de_token_personal(datos: dict) -> list[str]:
    """Scopes equivalentes a un token personal (ver `db.autenticar_token_completo`)."""
    scopes = [f"usuario:{datos['usuario_id']}"]
    scopes += [f"area:{a}" for a in datos["areas"]]
    if datos["permisos"] == "solo_lectura":
        scopes.append("solo_lectura")
    return scopes


def usuario_de_scopes(scopes: list[str]) -> int | None:
    for s in scopes:
        if s.startswith("usuario:") and s[8:].isdigit():
            return int(s[8:])
    return None


def alcance_de_scopes(scopes: list[str]) -> tuple[list[str], bool]:
    """(áreas, solo_lectura). Áreas vacías = sin restricción (como un token OAuth normal)."""
    return [s[5:] for s in scopes if s.startswith("area:")], "solo_lectura" in scopes
