"""Fuentes citadas por el asistente: a partir de los resultados de las
herramientas de LECTURA de un turno, los enlaces internos a los correos,
notas, tareas y clientes de donde salen los datos. Se guardan en
`ia_mensajes.fuentes_json` del mensaje final y se pintan bajo la burbuja."""
from __future__ import annotations

import json
import re

from . import db

MAX_FUENTES = 8
_MAX_TITULO = 70


def _limpio(texto) -> str:
    texto = re.sub(r"<[^>]+>", " ", str(texto or ""))
    return " ".join(texto.split())[:_MAX_TITULO]


def _filas(datos) -> list[dict]:
    """Lista de dicts de un resultado de herramienta (admite listas, un dict
    suelto o un dict de secciones con listas, como `listar_tareas_hoy`)."""
    if isinstance(datos, list):
        return [d for d in datos if isinstance(d, dict)]
    if isinstance(datos, dict):
        if any(isinstance(v, list) for v in datos.values()) and "id" not in datos:
            return [d for v in datos.values() if isinstance(v, list) for d in v if isinstance(d, dict)]
        return [datos]
    return []


def _url_correo(mensaje_id, cuenta_id=None) -> str | None:
    if not isinstance(mensaje_id, int):
        return None
    if cuenta_id is None:
        try:
            fila = db.obtener_mensaje_correo(mensaje_id)
        except Exception:  # noqa: BLE001
            fila = None
        cuenta_id = fila["cuenta_id"] if fila else None
    if cuenta_id is None:
        return None
    return f"/correo/?cuenta_id={cuenta_id}&mensaje_id={mensaje_id}"


def _de_fila(nombre_herramienta: str, f: dict) -> tuple[str, str, str] | None:
    """(tipo, título, url) de una fila, o None si no se reconoce."""
    id_ = f.get("id")
    if nombre_herramienta in ("listar_bandeja_entrada", "leer_correo"):
        url = _url_correo(id_, f.get("cuenta_id"))
        return ("correo", _limpio(f.get("asunto")) or "(sin asunto)", url) if url else None
    if nombre_herramienta == "listar_notas" and isinstance(id_, int):
        return "nota", _limpio(f.get("titulo") or f.get("texto")) or f"#{id_}", f"/nota/{id_}/editar"
    if nombre_herramienta in ("listar_tareas", "listar_tareas_hoy", "consultar_calendario") and isinstance(id_, int):
        return "tarea", _limpio(f.get("asunto")) or f"#{id_}", f"/tareas/{id_}/editar"
    if nombre_herramienta in ("listar_clientes_fiscales", "resumen_cliente_fiscal") and isinstance(id_, int):
        return "cliente", _limpio(f.get("nombre")) or f"#{id_}", f"/fiscal/clientes/{id_}"
    if nombre_herramienta == "listar_vencimientos_fiscales" and isinstance(f.get("cliente_fiscal_id"), int):
        titulo = _limpio(" · ".join(str(x) for x in (f.get("modelo"), f.get("cliente_nombre")) if x)) or "Vencimiento"
        return "vencimiento", titulo, f"/fiscal/clientes/{f['cliente_fiscal_id']}"
    if nombre_herramienta == "buscar_semantico":
        tipo, _, numero = str(f.get("id") or "").partition("-")
        if not numero.isdigit():
            return None
        n = int(numero)
        titulo = _limpio(f.get("texto")) or f"{tipo} #{n}"
        if tipo == "nota":
            return "nota", titulo, f"/nota/{n}/editar"
        if tipo == "tarea":
            return "tarea", titulo, f"/tareas/{n}/editar"
        if tipo == "correo":
            url = _url_correo(n)
            return ("correo", titulo, url) if url else None
    return None


def extraer_fuentes(resultados: list[tuple[str, str]], lecturas: set[str]) -> list[dict]:
    """`resultados`: (nombre_herramienta, contenido_json) de los mensajes
    `tool` del turno. Solo cuentan las herramientas de lectura. Devuelve
    [{tipo, titulo, url}] sin repetidos y con tope."""
    fuentes: list[dict] = []
    vistas: set[str] = set()
    for nombre, contenido in resultados:
        if nombre not in lecturas:
            continue
        try:
            datos = json.loads(contenido or "null")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(datos, dict) and "error" in datos:
            continue
        for fila in _filas(datos):
            encontrada = _de_fila(nombre, fila)
            if encontrada is None or encontrada[2] in vistas:
                continue
            vistas.add(encontrada[2])
            fuentes.append({"tipo": encontrada[0], "titulo": encontrada[1], "url": encontrada[2]})
            if len(fuentes) >= MAX_FUENTES:
                return fuentes
    return fuentes
