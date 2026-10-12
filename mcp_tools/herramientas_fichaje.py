"""Herramientas MCP del fichaje.

Parte de la antigua `__init__.py`, dividida por dominios sin cambiar su comportamiento: todo lo que no está aquí (la conexión, las constantes y las funciones de otros
dominios) se usa a través de `_mt`, que sigue siendo el único espacio de nombres (`_mt.nombre` funciona igual que antes y se puede parchear en los tests)."""
from __future__ import annotations
import base64
import contextvars
import mimetypes
import secrets
import sqlite3
import uuid
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from app import (
    baserow,
    busqueda,
    calcom,
    chatwoot,
    correo,
    db,
    documenso,
    espocrm,
    eventos,
    export,
    facturascripts,
    importador,
    jitsi,
    kratos,
    listmonk,
    metabase,
    minio_cliente,
    n8n,
    nextcloud,
    ntfy,
    openproject,
    outline,
    outlook_ics,
    paperless,
    stalwart,
    synapse,
    umami,
    uptime_kuma,
)

import mcp_tools as _mt


def fichar(tipo: str) -> dict:
    """Marca un fichaje del usuario actual: tipo = "entrada" | "pausa_inicio"
    | "pausa_fin" | "salida". Lanza un error legible si la secuencia no es
    válida (p.ej. fichar salida sin haber fichado entrada antes)."""
    uid = _mt._uid()
    tenant = _mt.db.tenant_de_usuario(uid)
    if not _mt.db.fichaje_datos_completos(uid):
        raise ValueError("Antes de fichar hace falta rellenar nombre completo y DNI/NIE en Fichaje → Mis datos.")
    fichaje_id = _mt.db.fichar(uid, tenant["id"] if tenant else None, tipo, origen="ia")
    return {"id": fichaje_id, "tipo": tipo, "estado_actual": _mt.db.estado_actual_fichaje(uid)}


def listar_mis_fichajes(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Historial de fichajes del usuario actual, opcionalmente filtrado
    por fecha (YYYY-MM-DD)."""
    return _mt._filas(_mt.db.listar_fichajes(_mt._uid(), desde=desde, hasta=hasta))
