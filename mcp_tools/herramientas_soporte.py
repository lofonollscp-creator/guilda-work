"""Herramientas MCP de los adjuntos del chat de IA y de los tiquets de soporte interno.

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


def leer_adjunto_chat(adjunto_id: int) -> dict:
    """Devuelve el texto de un adjunto que el usuario subió al chat del
    Asistente de IA (botón de clip, ver app/rutas_ia.py:subir_adjunto) --
    solo texto/CSV (ya validado como UTF-8 al subirlo), truncado si es
    muy largo. El adjunto es privado a quien lo subió."""
    adjunto = _mt.db.obtener_adjunto_ia(_mt._uid(), adjunto_id)
    if adjunto is None:
        raise ValueError(f"No existe el adjunto #{adjunto_id} (o no es tuyo).")
    texto = adjunto["contenido"].decode("utf-8")
    truncado = len(texto) > _mt._ADJUNTO_MAX_CARACTERES
    return {
        "nombre_archivo": adjunto["nombre_archivo"],
        "texto": texto[:_mt._ADJUNTO_MAX_CARACTERES],
        "truncado": truncado,
    }


def listar_tiquets(estado: str | None = None, tipo: str | None = None) -> list[dict]:
    """Lista tiquets de soporte (errores/sugerencias sobre Guilda Work).
    Tablero compartido: devuelve los de TODOS los usuarios, no solo los
    propios. `estado`: sin_revisar/en_revision/finalizado. `tipo`: error/sugerencia."""
    return _mt._filas(_mt.db.listar_tiquets(estado=estado, tipo=tipo))


def crear_tiquet(tipo: str, titulo: str, descripcion: str | None = None) -> dict:
    """Crea un tiquet nuevo (tipo: "error" o "sugerencia"), a nombre del
    usuario actual. Empieza siempre en estado "sin_revisar"."""
    uid = _mt._uid()
    tiquet_id = _mt.db.crear_tiquet(uid, tipo=tipo, titulo=titulo, descripcion=descripcion)
    return _mt._fila(_mt.db.obtener_tiquet(tiquet_id))


def editar_tiquet(
    tiquet_id: int, titulo: str | None = None, descripcion: str | None = None, tipo: str | None = None,
) -> dict:
    """Edita un tiquet propio, solo mientras siga "sin_revisar" (una vez
    entra en revisión, ya no se puede tocar el contenido)."""
    tiquet = _mt.db.obtener_tiquet(tiquet_id)
    if tiquet is None:
        raise ValueError(f"No existe el tiquet #{tiquet_id}.")
    if tiquet["usuario_id"] != _mt._uid():
        raise ValueError(f"El tiquet #{tiquet_id} no es tuyo, no lo puedes editar.")
    if tiquet["estado"] != "sin_revisar":
        raise ValueError(f"El tiquet #{tiquet_id} ya está en revisión, no se puede editar.")
    ok = _mt.db.editar_tiquet(
        _mt._uid(), tiquet_id,
        titulo=titulo if titulo is not None else tiquet["titulo"],
        descripcion=descripcion if descripcion is not None else tiquet["descripcion"],
        tipo=tipo if tipo is not None else tiquet["tipo"],
    )
    if not ok:
        raise ValueError(f"No se ha podido editar el tiquet #{tiquet_id}.")
    return _mt._fila(_mt.db.obtener_tiquet(tiquet_id))


def eliminar_tiquet(tiquet_id: int) -> dict:
    """Elimina un tiquet propio, o cualquiera si eres administrador."""
    uid = _mt._uid()
    tiquet = _mt.db.obtener_tiquet(tiquet_id)
    if tiquet is None:
        raise ValueError(f"No existe el tiquet #{tiquet_id}.")
    if tiquet["usuario_id"] != uid and not _mt.db.es_admin(uid):
        raise ValueError(f"El tiquet #{tiquet_id} no es tuyo, no lo puedes eliminar.")
    _mt.db.eliminar_tiquet(tiquet_id)
    return {"eliminado": True, "id": tiquet_id}


def cambiar_estado_tiquet(tiquet_id: int, estado: str) -> dict:
    """Mueve un tiquet a otro estado del Kanban (sin_revisar/en_revision/
    finalizado). Solo administradores."""
    if not _mt.db.es_admin(_mt._uid()):
        raise ValueError("Solo un administrador puede mover tiquets de estado.")
    if _mt.db.obtener_tiquet(tiquet_id) is None:
        raise ValueError(f"No existe el tiquet #{tiquet_id}.")
    _mt.db.cambiar_estado_tiquet(tiquet_id, estado)
    return _mt._fila(_mt.db.obtener_tiquet(tiquet_id))
