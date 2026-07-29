"""Servidor MCP remoto de Guilda Work (streamable-http + OAuth2) — para
ChatGPT, que a diferencia de Claude Code/Desktop/Codex CLI (ver
`mcp_server.py`, `stdio` local sin autenticación) solo admite servidores
MCP **remotos por HTTPS**, con OAuth 2.1 + Registro Dinámico de Cliente
(RFC7591). Expone exactamente las mismas tools que `mcp_server.py` (ver
`mcp_tools.py`) — ningún catálogo distinto entre los dos transportes.

Arquitectura — Resource Server, no Authorization Server propio: este
proceso NO gestiona logins ni emite tokens, delega toda la autorización
real en **Ory Hydra** (ya desplegado, ver HOSTING.md sección MCP remoto),
que soporta de forma nativa el Registro Dinámico de Cliente que exige
ChatGPT (`oidc.dynamic_client_registration.enabled: true` en
`deploy/hydra/hydra.yml`). Aquí solo se valida cada token que llega
llamando a la introspección de Hydra (`app/hydra.py: verificar_token`,
Admin API, servidor-a-servidor) — si Hydra dice que el token es válido,
la petición sigue; si no, 401.

Corre FUERA de Docker, en el mismo host que `serve.py` (mismo criterio
que el resto de la app — nunca dentro del stack Docker), como un segundo
proceso persistente (systemd/Programador de tareas, ver HOSTING.md), con
Caddy como único punto de entrada real desde internet
(`mcp.HOSTNAME { reverse_proxy localhost:MCP_REMOTO_PUERTO }`).

Variables de entorno:
- `MCP_REMOTO_ORIGIN`: URL pública de este servidor (ej.
  "https://mcp.tu-hostname.sslip.io") — se usa como `resource_server_url`,
  el identificador que ChatGPT compara contra el token recibido (RFC8707).
- `HYDRA_PUBLIC_ORIGIN`: URL pública de Hydra (ej.
  "https://hydra.tu-hostname.sslip.io") — el `issuer_url` que ChatGPT
  descubre y usa para el registro dinámico de cliente y el login real.
- `MCP_REMOTO_PUERTO` (opcional, por defecto 8017): puerto en el que
  escucha este proceso — Caddy le hace de proxy inverso, nunca se publica
  directo a internet.

No se empaqueta en el .exe — se ejecuta con:

    python mcp_server_remoto.py
"""
import os

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from app import db, hydra
from mcp_tools import registrar_tools

MCP_REMOTO_ORIGIN = os.environ.get("MCP_REMOTO_ORIGIN", "http://127.0.0.1:8017")
HYDRA_PUBLIC_ORIGIN = os.environ.get("HYDRA_PUBLIC_ORIGIN", "http://127.0.0.1:4444")
MCP_REMOTO_PUERTO = int(os.environ.get("MCP_REMOTO_PUERTO", "8017"))


class VerificadorHydra(TokenVerifier):
    """Valida los tokens Bearer que llegan a este servidor llamando a la
    introspección de la Admin API de Hydra (RFC7662) — ver
    app/hydra.py: verificar_token."""

    async def verify_token(self, token: str) -> AccessToken | None:
        introspeccion = hydra.verificar_token(token)
        if introspeccion is None:
            return None
        scope = introspeccion.get("scope", "")
        return AccessToken(
            token=token,
            client_id=introspeccion.get("client_id", ""),
            scopes=scope.split() if scope else [],
            expires_at=introspeccion.get("exp"),
            subject=introspeccion.get("sub"),
        )


mcp = FastMCP(
    "guilda-work-remoto",
    host="0.0.0.0",
    port=MCP_REMOTO_PUERTO,
    token_verifier=VerificadorHydra(),
    auth=AuthSettings(
        issuer_url=HYDRA_PUBLIC_ORIGIN,
        resource_server_url=MCP_REMOTO_ORIGIN,
    ),
)
registrar_tools(mcp)

if __name__ == "__main__":
    db.init_db()  # idempotente: por si es la primera vez que se usa la app
    mcp.run(transport="streamable-http")
