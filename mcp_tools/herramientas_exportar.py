"""Herramientas MCP de exportar e importar, la papelera y las estadísticas.

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


# --- Exportar / importar --------------------------------------------------------

def exportar_historial(formato: str = "json", desde: str | None = None, hasta: str | None = None, categoria: str | None = None) -> str:
    """Exporta notas y tareas con duración. `formato`: json, csv o md."""
    uid = _mt._uid()
    categoria_id = _mt._resolver_categoria_id(categoria)
    if formato == "csv":
        return _mt.export.a_csv(uid, desde, hasta, categoria_id)
    if formato == "md":
        return _mt.export.a_markdown(uid, desde, hasta, categoria_id)
    return _mt.export.a_json(uid, desde, hasta, categoria_id)


def importar_historial(contenido: str, formato: str = "json") -> dict:
    """Importa notas y tareas con duración desde un JSON o CSV (mismo formato que exportar_historial)."""
    uid = _mt._uid()
    if formato == "csv":
        return _mt.importador.importar_csv(uid, contenido)
    return _mt.importador.importar_json(uid, contenido)


def exportar_tareas(formato: str = "ics", desde: str | None = None, hasta: str | None = None) -> str:
    """Exporta tareas estilo Outlook a .ics o .csv, compatibles con Microsoft Outlook."""
    tareas = _mt.db.listar_tareas_outlook(_mt._uid(), desde=desde, hasta=hasta)
    if formato == "csv":
        return _mt.outlook_ics.exportar_csv_outlook(tareas)
    return _mt.outlook_ics.exportar_ics(tareas)


def importar_tareas(contenido: str, formato: str = "ics") -> dict:
    """Importa tareas desde un archivo .ics o .csv exportado de Outlook (o de Guilda Work)."""
    uid = _mt._uid()
    if formato == "csv":
        return _mt.outlook_ics.importar_csv_outlook(uid, contenido)
    return _mt.outlook_ics.importar_ics(uid, contenido)


def listar_papelera() -> list[dict]:
    """Lista lo que hay en la papelera del usuario actual (proyectos, tareas,
    notas y tareas outlook eliminados pero no purgados todavía). Cada
    elemento trae un campo `origen` (menu/tarea/nota/tarea_outlook) que
    hace falta pasar a restaurar_de_papelera."""
    return _mt.db.papelera(_mt._uid())


def restaurar_de_papelera(origen: str, id: int) -> dict:
    """Restaura un elemento de la papelera (lo saca de ahí, vuelve a estar
    activo). `origen` es el campo que devuelve listar_papelera: menu, tarea,
    nota o tarea_outlook."""
    funcion = _mt._PAPELERA_RESTAURAR.get(origen)
    if funcion is None:
        raise ValueError(f"Origen de papelera no válido: {origen!r}. Usa uno de: {', '.join(_mt._PAPELERA_RESTAURAR)}.")
    funcion(_mt._uid(), id)
    return {"restaurado": True, "origen": origen, "id": id}


# --- Estadísticas --------------------------------------------------------------

def estadisticas_por_categoria(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Tiempo dedicado a tareas con duración ya finalizadas, agrupado por
    proyecto, del usuario actual. `desde`/`hasta` en formato YYYY-MM-DD."""
    return _mt.db.estadisticas_por_categoria(_mt._uid(), desde, hasta)


def estadisticas_por_dia(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Igual que estadisticas_por_categoria pero agrupado por día (y proyecto
    dentro de cada día)."""
    return _mt.db.estadisticas_por_dia(_mt._uid(), desde, hasta)
