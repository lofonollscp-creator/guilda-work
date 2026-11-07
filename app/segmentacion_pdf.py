"""Un PDF con varias facturas («escaneo todo el mes de una vez») o una factura de varias páginas: decide qué páginas forman cada factura y parte el PDF.

Primero se mira el texto del PDF, que es gratis y exacto: si las páginas llevan números de factura distintos, cada cambio de número abre una factura nueva (una página sin número —la hoja
de condiciones, la segunda página de una factura larga— se pega a la anterior). Solo cuando el PDF es un escaneo sin texto se pregunta a la IA, con las páginas reducidas, y su respuesta se
valida: tiene que repartir TODAS las páginas, una sola vez y en orden, o se ignora y el PDF se trata como una sola factura (el caso seguro)."""
from __future__ import annotations

import io
import json
import logging
import re

from . import pdf_facturas

logger = logging.getLogger("guilda")

_NUMERO = re.compile(r"(?:factura|invoice|fra\.?)\s*(?:n[ºo°]\.?|num\.?|n[úu]mero|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/.]{2,24})", re.I)
PALABRAS_NO_NUMERO = {"simplificada", "rectificativa", "proforma", "original", "copia", "fecha", "importe", "total", "cliente", "emitida", "recibida", "electronica", "electrónica"}
LADO_MINIATURA = 900

PROMPT = """Recibes las páginas, en orden, de un PDF escaneado que puede contener VARIAS facturas distintas, una factura de varias páginas, o ambas cosas. Agrupa las páginas por factura. Devuelve SOLO un JSON:
{"facturas": [[1, 2], [3], [4, 5, 6]]} donde cada lista son los números de página (empezando en 1) de UNA factura, todas las páginas aparecen exactamente una vez y en orden. Una página que no empieza una factura
(condiciones, continuación de las líneas, totales) va con la factura anterior. Si todo es una sola factura, {"facturas": [[1, 2, 3]]}. No expliques nada."""


def numero_en(texto: str) -> str | None:
    """El número de factura que figura en el texto de una página («FACTURA Nº 2026/118» → «2026/118»), o None si no se ve ninguno."""
    for m in _NUMERO.finditer(texto or ""):
        token = m.group(1).strip(".-/").upper()
        if any(c.isdigit() for c in token) and token.lower() not in PALABRAS_NO_NUMERO and len(token) >= 3:
            return token
    return None


def agrupar_por_numero(numeros: list[str | None]) -> list[list[int]]:
    """Páginas (desde 1) agrupadas por factura: una página con un número distinto del vigente abre una factura nueva; las demás se pegan a la anterior."""
    grupos: list[list[int]] = []
    vigente = None
    for i, numero in enumerate(numeros, 1):
        if not grupos or (numero and numero != vigente):
            grupos.append([i])
            vigente = numero or vigente
        else:
            grupos[-1].append(i)
            vigente = vigente or numero
    return grupos


def _valida(grupos, n: int) -> bool:
    plano = [p for g in grupos if isinstance(g, list) for p in g]
    return (isinstance(grupos, list) and all(isinstance(g, list) and g and all(isinstance(p, int) for p in g) for g in grupos) and plano == list(range(1, n + 1)))


def por_texto(contenido: bytes) -> list[list[int]] | None:
    """El reparto según el texto del PDF, o None si no se puede decidir con el texto (escaneo, o alguna página sin texto)."""
    textos = pdf_facturas.texto_de_paginas(contenido)
    if not textos or len(textos) < 2 or sum(len(t.strip()) >= 40 for t in textos) < len(textos):
        return None
    return agrupar_por_numero([numero_en(t) for t in textos])


def por_ia(usuario_id: int, contenido: bytes, n: int) -> list[list[int]] | None:
    """El reparto que propone la IA para un escaneo, solo si es coherente."""
    from . import ia_asistente
    imagenes = pdf_facturas.paginas_a_imagenes(contenido, maximo=pdf_facturas.MAX_PAGINAS, lado=LADO_MINIATURA)
    if not imagenes or len(imagenes) != n:
        return None
    import base64
    partes: list[dict] = [{"type": "text", "text": f"El PDF tiene {n} páginas."}]
    for i, png in enumerate(imagenes, 1):
        partes += [{"type": "text", "text": f"Página {i}:"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}}]
    try:
        with ia_asistente.sin_consumo():
            respuesta = ia_asistente.completar_partes(usuario_id, PROMPT, partes)
        i, j = respuesta.find("{"), respuesta.rfind("}")
        grupos = json.loads(respuesta[i:j + 1]).get("facturas")
    except (ia_asistente.ErrorIA, ValueError, TypeError, AttributeError):
        return None
    return grupos if _valida(grupos, n) else None


def segmentar(usuario_id: int, contenido: bytes, usar_ia: bool = True) -> list[list[int]] | None:
    """Los grupos de páginas (cada uno una factura) cuando el PDF contiene MÁS DE UNA, o None si es una sola o no se puede saber."""
    n = pdf_facturas.numero_de_paginas(contenido)
    if not n or n < 2 or n > pdf_facturas.MAX_PAGINAS:
        return None
    grupos = por_texto(contenido)
    if grupos is None and usar_ia:
        grupos = por_ia(usuario_id, contenido, n)
    return grupos if grupos and len(grupos) > 1 else None


def partir(contenido: bytes, grupos: list[list[int]]) -> list[bytes]:
    """Un PDF por grupo de páginas (conserva el texto y la calidad: solo se copian las páginas)."""
    from pypdf import PdfReader, PdfWriter
    lector = PdfReader(io.BytesIO(contenido))
    salida = []
    for g in grupos:
        w = PdfWriter()
        for p in g:
            w.add_page(lector.pages[p - 1])
        b = io.BytesIO()
        w.write(b)
        salida.append(b.getvalue())
    return salida
