"""Respuestas rápidas: frases hechas del despacho para contestar a sus clientes en un clic (el aviso de que falta un documento, la confirmación de que un modelo está presentado…), compartidas por todo el equipo.

Se insertan en el cuadro de texto de cualquier conversación con el cliente (modelos, facturas, trabajos) y se pueden editar antes de enviar. `{cliente}` se sustituye por el nombre del cliente y `{despacho}` por el del despacho."""
from __future__ import annotations

import re

from . import db

MAX_RESPUESTAS = 50
MAX_TITULO = 60
MAX_TEXTO = 1000


def listar(tenant_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, titulo, texto FROM portal_respuestas_rapidas WHERE tenant_id = ? ORDER BY titulo, id", (tenant_id,))]
    finally:
        conn.close()


def crear(tenant_id: int, usuario_id: int | None, titulo: str, texto: str) -> int:
    titulo, texto = re.sub(r"\s+", " ", titulo or "").strip(), (texto or "").strip()
    if not titulo or not texto:
        raise ValueError("Escribe un título y el texto de la respuesta.")
    if len(titulo) > MAX_TITULO or len(texto) > MAX_TEXTO:
        raise ValueError(f"El título admite {MAX_TITULO} caracteres y el texto {MAX_TEXTO}.")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM portal_respuestas_rapidas WHERE tenant_id = ?", (tenant_id,)).fetchone()[0] >= MAX_RESPUESTAS:
            raise ValueError(f"Cada despacho puede tener hasta {MAX_RESPUESTAS} respuestas rápidas.")
        cur = conn.execute("INSERT INTO portal_respuestas_rapidas (tenant_id, titulo, texto, creado_por, creado_en) VALUES (?, ?, ?, ?, ?)", (tenant_id, titulo, texto, usuario_id, db.now_iso()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def borrar(tenant_id: int, respuesta_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM portal_respuestas_rapidas WHERE id = ? AND tenant_id = ?", (respuesta_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def para_cliente(tenant_id: int, cliente) -> list[dict]:
    """Las respuestas con `{cliente}` y `{despacho}` ya sustituidos, listas para insertar en el cuadro de texto."""
    despacho = db.obtener_tenant(tenant_id)
    nombre_despacho = despacho["nombre"] if despacho else ""
    nombre = cliente["nombre"] if cliente is not None else ""
    return [{"id": r["id"], "titulo": r["titulo"], "texto": r["texto"].replace("{cliente}", nombre).replace("{despacho}", nombre_despacho)} for r in listar(tenant_id)]
