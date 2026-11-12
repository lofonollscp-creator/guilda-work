"""Cómo se sirve en línea un archivo subido por alguien (adjuntos del chat de IA, del correo, de tiquets y de notas). Solo se muestran
en el navegador las imágenes rasterizadas y los PDF; el resto (SVG, HTML, XML...) se descarga, porque un SVG o un HTML propio
ejecutaría contenido activo con el origen de la aplicación."""
from __future__ import annotations

IMAGENES_EN_LINEA = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/avif", "image/bmp")
PDF = "application/pdf"


def tipo_limpio(tipo_mime: str | None) -> str:
    return (tipo_mime or "").lower().split(";")[0].strip()


def se_muestra_en_linea(tipo_mime: str | None, *, pdf: bool = True) -> bool:
    t = tipo_limpio(tipo_mime)
    return t in IMAGENES_EN_LINEA or (pdf and t == PDF)


def endurecer(respuesta, tipo_mime: str | None):
    """Cabeceras de una respuesta con un archivo de usuario: sin adivinar el tipo y, si es imagen, sin ninguna capacidad activa."""
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    if tipo_limpio(tipo_mime) != PDF:        # el visor de PDF del navegador no funciona dentro de un sandbox
        respuesta.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    return respuesta
