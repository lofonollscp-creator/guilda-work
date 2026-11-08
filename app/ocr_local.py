"""OCR local con Tesseract: el texto de un escaneo o de una foto sin mandar nada a un tercero.

Sirve para dos cosas (se elige por despacho en Ajustes del Asistente IA): de respaldo, cuando el modelo no puede leer la imagen (no tiene visión o el escaneo es malo) y, en el modo «nada sale del servidor»,
como única forma de pasar un documento a un modelo local. Tesseract es lento y se equivoca más que un modelo con visión: por eso su texto nunca se da por bueno sin que lo revise una persona."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from functools import lru_cache

from . import pdf_facturas

logger = logging.getLogger("guilda")

IDIOMAS_PREFERIDOS = ("spa", "cat", "fra", "eng")
MAX_PAGINAS = 4
LADO_PDF = 2400                         # un A4 a unos 200 ppp: lo que Tesseract necesita para leer letra pequeña
LADO_MINIMO = 1500                      # una foto más pequeña se amplía
TIEMPO_POR_PAGINA = 90


@lru_cache(maxsize=1)
def _idiomas() -> str:
    """Los idiomas instalados de entre los que usamos, unidos con «+» (vacío si no hay Tesseract)."""
    exe = shutil.which("tesseract")
    if not exe:
        return ""
    try:
        salida = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=15).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return ""
    return "+".join(i for i in IDIOMAS_PREFERIDOS if i in salida)


def disponible() -> bool:
    return bool(_idiomas())


def _preparar(imagen: bytes) -> bytes | None:
    """La imagen en gris y con tamaño suficiente (OpenCV ya es dependencia del lector de QR)."""
    try:
        import cv2
        import numpy as np
        gris = cv2.imdecode(np.frombuffer(imagen, np.uint8), cv2.IMREAD_GRAYSCALE)
        if gris is None:
            return None
        lado = max(gris.shape)
        if lado < LADO_MINIMO:
            f = LADO_MINIMO / lado
            gris = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        ok, png = cv2.imencode(".png", gris)
        return png.tobytes() if ok else None
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo preparar la imagen para el OCR", exc_info=True)
        return None


def _leer_pagina(png: bytes) -> str:
    try:
        r = subprocess.run([shutil.which("tesseract") or "tesseract", "stdin", "stdout", "-l", _idiomas(), "--psm", "6", "--oem", "1"], input=png, capture_output=True, timeout=TIEMPO_POR_PAGINA,
                           env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    except (OSError, subprocess.SubprocessError):
        logger.warning("Tesseract no pudo leer la página", exc_info=True)
        return ""
    return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""


def texto_de(contenido: bytes, mime: str) -> str:
    """El texto reconocido en las primeras páginas de un PDF o en una imagen, con el mismo formato que el texto de la capa de un PDF; vacío si no hay OCR o no se reconoció nada."""
    if not disponible():
        return ""
    if mime == "application/pdf" or contenido[:5] == b"%PDF-":
        imagenes = pdf_facturas.paginas_a_imagenes(contenido, MAX_PAGINAS, LADO_PDF) or []
    elif mime.startswith("image/"):
        imagenes = [contenido]
    else:
        return ""
    paginas = []
    for i, img in enumerate(imagenes, 1):
        png = _preparar(img)
        texto = _leer_pagina(png) if png else ""
        if texto:
            paginas.append(f"--- página {i} ---\n{texto}")
    return "\n\n".join(paginas)
