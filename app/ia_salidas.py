"""Qué datos salen a proveedores de IA externos (W9, contador visible): por cada consulta que sale a un proveedor que no es local se anota CUÁNTOS datos personales se enmascararon (por tipo: persona, NIF, IBAN…)
y si llevaba adjuntos (imágenes o PDF, que no se pueden enmascarar). Nunca se guarda el contenido. La dirección lo ve en los ajustes de IA, para poder decir a un cliente qué se envía y qué no.

El enmascarado lo hace app/anonimizar.py; aquí solo se cuenta."""
from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timedelta

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ia_salidas_datos (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    proveedor TEXT NOT NULL,
    modelo TEXT NOT NULL DEFAULT '',
    tarea TEXT NOT NULL DEFAULT '',
    protegidos TEXT NOT NULL DEFAULT '{}',
    adjuntos INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ia_salidas_tenant ON ia_salidas_datos(tenant_id, creado_en);
"""
RETENCION_DIAS = 400
_ultimo_envio: contextvars.ContextVar[dict | None] = contextvars.ContextVar("ia_ultimo_envio", default=None)
_PARTES_ADJUNTAS = ("image_url", "file", "input_audio")


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def preparar(protegidos: dict[str, int], mensajes: list[dict]) -> None:
    """Lo que `_envio_protegido` acaba de enmascarar en esta consulta; `anotar` lo recoge cuando se sabe a qué proveedor fue."""
    adjuntos = 0
    for m in mensajes:
        c = m.get("content")
        if isinstance(c, list):
            adjuntos += sum(1 for parte in c if isinstance(parte, dict) and parte.get("type") in _PARTES_ADJUNTAS)
    _ultimo_envio.set({"protegidos": dict(protegidos), "adjuntos": adjuntos})


def anotar(tenant_id: int | None, proveedor: str, modelo: str, tarea: str, region: str) -> None:
    """Anota la salida a un proveedor EXTERNO (los de la propia red, `region == 'local'`, no sacan nada del servidor). Nunca rompe la consulta."""
    datos = _ultimo_envio.get()
    _ultimo_envio.set(None)
    if tenant_id is None or region == "local":
        return
    try:
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO ia_salidas_datos (tenant_id, proveedor, modelo, tarea, protegidos, adjuntos, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, proveedor, (modelo or "")[:120], tarea, json.dumps((datos or {}).get("protegidos", {})), (datos or {}).get("adjuntos", 0), datetime.now().isoformat(timespec="seconds")))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 -- contar es una ayuda: si falla, la consulta sigue
        logging.getLogger("guilda").warning("No se pudo anotar la salida de datos a la IA", exc_info=True)


def resumen(tenant_id: int, dias: int = 30) -> dict:
    """{consultas, con_adjuntos, enmascarados: {ETIQUETA: n}, por_proveedor: [{proveedor, consultas, adjuntos}]} de los últimos días."""
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT proveedor, protegidos, adjuntos FROM ia_salidas_datos WHERE tenant_id = ? AND creado_en >= ?", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    enmascarados: dict[str, int] = {}
    por: dict[str, dict] = {}
    for f in filas:
        for etiqueta, n in json.loads(f["protegidos"] or "{}").items():
            enmascarados[etiqueta] = enmascarados.get(etiqueta, 0) + n
        d = por.setdefault(f["proveedor"], {"proveedor": f["proveedor"], "consultas": 0, "adjuntos": 0})
        d["consultas"] += 1
        d["adjuntos"] += 1 if f["adjuntos"] else 0
    return {"consultas": len(filas), "con_adjuntos": sum(1 for f in filas if f["adjuntos"]), "enmascarados": dict(sorted(enmascarados.items())), "por_proveedor": sorted(por.values(), key=lambda d: -d["consultas"])}


def purgar(ahora: datetime | None = None) -> int:
    limite = ((ahora or datetime.now()) - timedelta(days=RETENCION_DIAS)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM ia_salidas_datos WHERE creado_en < ?", (limite,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()
