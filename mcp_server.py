"""Servidor MCP local de Guilda Work (stdio) — para Claude Code, Claude
Desktop y Codex CLI. Expone TODAS las tools de `mcp_tools.py` (notas,
tareas, calendario, correo, export/import, y desde la Fase MCP el resto
del stack Docker conectado — CRM, Drive, OpenProject, Chatwoot, Metabase,
n8n, Outline, Synapse, MinIO, Uptime Kuma).

No se empaqueta en el .exe — se ejecuta con:

    python mcp_server.py

y se registra en el cliente MCP que corresponda (ver README.md).

Confianza local sin autenticación (proceso `stdio`, quien lo ejecuta ya
tiene acceso al sistema) — para ChatGPT, que exige un servidor MCP
**remoto** con OAuth2 real, ver `mcp_server_remoto.py`.
"""
from mcp.server.fastmcp import FastMCP

from app import db
from mcp_tools import registrar_tools

mcp = FastMCP("guilda-work")
registrar_tools(mcp)

if __name__ == "__main__":
    db.init_db()  # idempotente: por si es la primera vez que se usa la app
    mcp.run()
