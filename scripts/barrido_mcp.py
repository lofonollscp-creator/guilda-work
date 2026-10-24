#!/usr/bin/env python3
"""Barrido de las herramientas de SOLO LECTURA del MCP contra la base de datos del entorno (fase 12): llama, como una persona real, a cada herramienta que no necesita argumentos y anota las que
fallan por la BASE DE DATOS (errores de psycopg/Citus; los ValueError de negocio —servicio no configurado, falta un permiso— son respuestas normales). No escribe datos de negocio (la auditoría
del propio MCP sí anota cada llamada, con el cliente «barrido-mcp»).

  scripts/probar.sh --ejecutar scripts/barrido_mcp.py     # en el ensayo; en producción, con el entorno de producción y como `guilda`
Código de salida 0 sin errores de base de datos, 1 con alguno."""
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.server.auth.provider import AccessToken
    from mcp.server.fastmcp import FastMCP

    import mcp_tools as mt
    from app import bd, db
    if "--sin-despacho" in sys.argv:                                       # como funcionaba antes de fijar el despacho en el MCP (para comparar)
        mt._fijar_despacho_en_bd = lambda *a, **k: None
    c = db.get_connection(plataforma=True) if bd.MOTOR == "postgres" else db.get_connection()
    personas = [r[0] for r in c.execute("SELECT kratos_identity_id FROM usuarios WHERE tenant_id IS NOT NULL AND kratos_identity_id IS NOT NULL ORDER BY id LIMIT 3").fetchall()]
    c.close()
    s = FastMCP("barrido")
    mt.registrar_tools(s, grupos=None, solo_lectura=True)
    tools = {n: t.fn for n, t in s._tool_manager._tools.items()}
    sin_args = {n: f for n, f in tools.items() if all(p.default is not inspect.Parameter.empty or p.name == "tenant" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in inspect.signature(f).parameters.values())}
    print(f"motor {bd.MOTOR} · {len(tools)} herramientas de lectura, {len(sin_args)} sin argumentos obligatorios · {len(personas)} personas")
    de_bd, negocio, bien = [], 0, 0
    for sujeto in personas:
        token = auth_context_var.set(AuthenticatedUser(AccessToken(token="t", client_id="barrido-mcp", scopes=["lectura", "escritura"], subject=sujeto)))
        for n, f in sorted(sin_args.items()):
            try:
                r = f()
                if inspect.isawaitable(r):
                    r = asyncio.run(r)
                bien += 1
            except ValueError:
                negocio += 1
            except Exception as e:                                                                   # noqa: BLE001
                de_bd.append(f"{n}: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
        auth_context_var.reset(token)
    print(f"llamadas: {bien} bien · {negocio} respuestas de negocio (ValueError) · {len(de_bd)} errores inesperados")
    for linea in sorted(set(de_bd)):
        print("  FALLA", linea)
    return 1 if de_bd else 0


if __name__ == "__main__":
    sys.exit(main())
