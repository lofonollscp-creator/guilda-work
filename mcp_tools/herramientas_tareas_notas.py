"""Herramientas MCP de notas y tareas.

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


# --- Notas -------------------------------------------------------------------

def buscar_semantico(texto: str, limite: int = 5) -> list[dict]:
    """Busca por SIGNIFICADO (no solo palabra exacta) en notas/tareas/
    correo del usuario actual — usa Meilisearch+embeddings locales vía
    Ollama (ver app/busqueda.py:buscar_hibrido), aislamiento por
    usuario_id verificado en vivo. Devuelve [] si Meilisearch u Ollama
    no están configurados (mejora opcional sobre listar_notas/
    historial, que siguen siendo la vía de siempre para búsqueda
    exacta). Útil para preguntas del tipo '¿qué dijo el cliente X sobre
    el IVA?' donde las palabras exactas pueden no coincidir."""
    resultados = _mt.busqueda.buscar_hibrido(_mt._uid(), texto, limite=limite)
    from app import correo_cifrado
    tenant = _mt.db.tenant_de_usuario(_mt._uid())
    if tenant is not None and correo_cifrado.configuracion(tenant["id"]) is not None:
        # El correo cifrado no se manda al buscador externo: se completa con una búsqueda por palabras en memoria (la IA no pierde el acceso al correo; solo cambia cómo se busca).
        resultados = (resultados + correo_cifrado.buscar_para_usuario(_mt._uid(), texto, limite=limite))[:max(limite, len(resultados))]
    return resultados


def listar_notas(desde: str | None = None, hasta: str | None = None, texto: str | None = None) -> list[dict]:
    """Lista notas del log de actividad (fechas 'YYYY-MM-DD', `texto` filtra por coincidencia parcial)."""
    filas = _mt.db.historial(_mt._uid(), desde=desde, hasta=hasta, texto=texto)
    return [dict(f) for f in filas if f["origen"] == "nota"]


def crear_nota(texto: str, categoria: str | int | None = None, titulo: str | None = None) -> dict:
    """Crea una nota rápida con el timestamp actual. `categoria` puede ser el nombre o el id del proyecto.
    `titulo` es opcional; el texto admite formato Markdown sencillo (**negrita**, *cursiva*, listas, enlaces)."""
    uid = _mt._uid()
    categoria_id = _mt._resolver_categoria_id(categoria)
    nota_id = _mt.db.crear_nota(uid, texto, categoria_id=categoria_id, titulo=titulo)
    return _mt._fila(_mt.db.obtener_nota(uid, nota_id))


def editar_nota(nota_id: int, texto: str, titulo: str | None = None) -> dict:
    """Edita el texto de una nota existente (y su título, si se indica)."""
    uid = _mt._uid()
    if titulo is None:
        _mt.db.editar_nota(uid, nota_id, texto)
    else:
        _mt.db.editar_nota(uid, nota_id, texto, titulo=titulo)
    nota = _mt.db.obtener_nota(uid, nota_id)
    if nota is None:
        raise ValueError(f"No existe la nota {nota_id} (o está en la papelera).")
    return _mt._fila(nota)


# --- Tareas al estilo Outlook (lista + calendario) ----------------------------

def listar_tareas(
    estado: str | None = None, prioridad: str | None = None, categoria: str | None = None,
    texto: str | None = None, desde: str | None = None, hasta: str | None = None,
) -> list[dict]:
    """Lista tareas (estilo Outlook). `desde`/`hasta` filtran por fecha de vencimiento (YYYY-MM-DD)."""
    return _mt._filas(_mt.db.listar_tareas_outlook(
        _mt._uid(), estado=estado, prioridad=prioridad, categoria_outlook=categoria, texto=texto, desde=desde, hasta=hasta,
    ))


def crear_tarea(
    asunto: str, prioridad: str = "normal", fecha_inicio: str | None = None,
    fecha_vencimiento: str | None = None, categoria: str | None = None,
    menu: str | int | None = None, cuerpo: str | None = None,
) -> dict:
    """Crea una tarea (estilo Outlook). `prioridad`: baja/normal/alta.
    `fecha_inicio`/`fecha_vencimiento` aceptan tanto solo fecha
    ('YYYY-MM-DD') como fecha y hora ('YYYY-MM-DD HH:MM') si quieres fijar
    una franja horaria concreta, p.ej. de 14:00 a 15:00. `categoria` es el
    campo de texto libre heredado de Outlook (no confundir con `menu`,
    el nombre o id de un proyecto real de Guilda Work — ver listar_notas para
    ver los proyectos existentes)."""
    uid = _mt._uid()
    tarea_id = _mt.db.crear_tarea_outlook(
        uid, asunto, cuerpo=cuerpo, prioridad=prioridad, fecha_inicio=fecha_inicio,
        fecha_vencimiento=fecha_vencimiento, categoria_outlook=categoria,
        categoria_id=_mt._resolver_categoria_id(menu),
    )
    return _mt._fila(_mt.db.obtener_tarea_outlook(uid, tarea_id))


def editar_tarea(
    tarea_id: int, asunto: str | None = None, cuerpo: str | None = None, estado: str | None = None,
    prioridad: str | None = None, fecha_inicio: str | None = None, fecha_vencimiento: str | None = None,
    categoria: str | None = None, menu: str | int | None = None,
) -> dict:
    """Edita los campos indicados de una tarea existente (solo se tocan los
    que se pasen). Mismo formato de fechas y misma distinción
    `categoria`/`menu` que crear_tarea."""
    uid = _mt._uid()
    campos = {
        "asunto": asunto, "cuerpo": cuerpo, "estado": estado, "prioridad": prioridad,
        "fecha_inicio": fecha_inicio, "fecha_vencimiento": fecha_vencimiento, "categoria_outlook": categoria,
    }
    if menu is not None:
        campos["categoria_id"] = _mt._resolver_categoria_id(menu)
    _mt.db.editar_tarea_outlook(uid, tarea_id, **{k: v for k, v in campos.items() if v is not None})
    tarea = _mt.db.obtener_tarea_outlook(uid, tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o está en la papelera).")
    return _mt._fila(tarea)


def completar_tarea(tarea_id: int) -> dict:
    """Marca una tarea como completada (100%, fecha de finalización = ahora)."""
    uid = _mt._uid()
    _mt.db.completar_tarea_outlook(uid, tarea_id)
    tarea = _mt.db.obtener_tarea_outlook(uid, tarea_id)
    if tarea is None:
        raise ValueError(f"No existe la tarea {tarea_id} (o está en la papelera).")
    return _mt._fila(tarea)


def consultar_calendario(desde: str, hasta: str) -> list[dict]:
    """Tareas con vencimiento entre `desde` y `hasta` (YYYY-MM-DD, inclusive) — para vistas tipo calendario."""
    return _mt._filas(_mt.db.listar_tareas_outlook(_mt._uid(), desde=desde, hasta=hasta))
