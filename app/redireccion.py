"""Destinos de redirección que vienen del cliente (`volver_a`, `volver`, el referrer): solo se admiten direcciones de esta misma aplicación,
para que un enlace o un formulario ajeno no pueda mandar al usuario a otra web (open redirect)."""
from __future__ import annotations

from urllib.parse import urlsplit

from flask import request


def es_local(valor: str | None) -> bool:
    """`/ruta?x=1`, o una URL absoluta de este mismo host. Nunca `//otro.sitio`, `/\\otro.sitio`, `javascript:` ni nada con saltos de línea."""
    v = (valor or "").strip()
    if not v or len(v) > 2000 or any(ord(c) < 32 or c == "\\" for c in v):
        return False
    if v.startswith("/"):
        return not v.startswith("//")
    p = urlsplit(v)
    return p.scheme in ("http", "https") and p.netloc == request.host


def destino_local(*candidatos: str | None, por_defecto: str) -> str:
    """El primer candidato local (`request.form.get("volver_a")`, `request.referrer`...) o `por_defecto`."""
    return next((c.strip() for c in candidatos if es_local(c)), por_defecto)
