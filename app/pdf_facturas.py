"""PDF e imágenes de facturas: texto de las páginas que lo tienen (pypdf) y página a imagen (pypdfium2) para los proveedores de IA que no leen PDF y para el visor de revisión.

Nada de esto llama a la red. Todo falla en silencio hacia «no se pudo»: quien lo usa tiene siempre el camino de mandar el archivo tal cual al modelo."""
from __future__ import annotations

import io
import logging

logger = logging.getLogger("guilda")

MAX_PAGINAS = 12
LADO_MAXIMO = 1800                      # píxeles del lado mayor de la imagen que se manda al modelo: legible sin pasarse de peso


def numero_de_paginas(contenido: bytes) -> int | None:
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(contenido)).pages)
    except Exception:  # noqa: BLE001 -- PDF roto, cifrado o sin la librería
        return None


def texto_de_paginas(contenido: bytes) -> list[str] | None:
    """El texto de cada página (la lista tiene una entrada por página, vacía si esa página no tiene capa de texto), o None si el PDF no se puede leer."""
    try:
        from pypdf import PdfReader
        lector = PdfReader(io.BytesIO(contenido))
        if lector.is_encrypted:
            return None
        return [(p.extract_text() or "") for p in lector.pages[:MAX_PAGINAS * 4]]
    except Exception:  # noqa: BLE001
        return None


def paginas_a_imagenes(contenido: bytes, maximo: int = MAX_PAGINAS, lado: int = LADO_MAXIMO) -> list[bytes] | None:
    """Cada página como PNG (lado mayor `lado` px), o None si no se puede renderizar. Pensado para PDF pequeños: una factura tiene pocas páginas."""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(contenido)
        imagenes = []
        for i in range(min(len(pdf), maximo)):
            pagina = pdf[i]
            ancho, alto = pagina.get_size()
            escala = min(4.0, max(1.0, lado / max(ancho, alto)))
            salida = io.BytesIO()
            pagina.render(scale=escala).to_pil().convert("RGB").save(salida, "PNG", optimize=True)
            imagenes.append(salida.getvalue())
        return imagenes or None
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo renderizar el PDF a imágenes", exc_info=True)
        return None


def pagina_a_imagen(contenido: bytes, indice: int, lado: int = LADO_MAXIMO) -> bytes | None:
    """La página `indice` (desde 0) como PNG, o None si no existe o no se puede renderizar."""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(contenido)
        if not 0 <= indice < len(pdf):
            return None
        pagina = pdf[indice]
        ancho, alto = pagina.get_size()
        escala = min(4.0, max(0.5, lado / max(ancho, alto)))
        salida = io.BytesIO()
        pagina.render(scale=escala).to_pil().convert("RGB").save(salida, "PNG", optimize=True)
        return salida.getvalue()
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo renderizar una página del PDF", exc_info=True)
        return None
