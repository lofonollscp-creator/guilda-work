"""Marca del despacho («marca blanca»): nombre, color de acento y logo que ven las personas del despacho en lugar de los de Guilda Work.

Es **solo de presentación** para quien usa la aplicación: cambia el nombre y el logo del menú lateral y el color de acento (con el contraste calculado para que los botones y enlaces se
lean). No toca los correos del sistema ni el portal del cliente. El logo se acepta solo en PNG, JPEG o WebP, se vuelve a codificar a PNG con Pillow (sin metadatos ni contenido activo)
y se reduce a 256 px. SVG no se admite a propósito: puede llevar scripts."""
from __future__ import annotations

import io
import re
import sqlite3

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tenant_marca (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    nombre TEXT,
    color TEXT,
    logo BLOB,
    actualizada_en TEXT NOT NULL
);
"""
MAX_BYTES_LOGO = 400 * 1024
LADO_LOGO = 256
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)


def _luminancia(color: str) -> float:
    """Luminancia relativa (WCAG) de `#rrggbb`."""
    canales = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contraste(l1: float, l2: float) -> float:
    a, b = max(l1, l2), min(l1, l2)
    return (a + 0.05) / (b + 0.05)


def _mezclar(color: str, con: str, peso: float) -> str:
    c, o = [int(color[i:i + 2], 16) for i in (1, 3, 5)], [int(con[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * (1 - peso) + y * peso):02x}" for x, y in zip(c, o))


def colores_derivados(color: str) -> dict:
    """Las variables de color que usa la interfaz a partir del acento: texto sobre el acento (negro o blanco, el que más contraste dé), versión oscura para hover y el acento como texto en
    tema claro (oscurecido hasta tener al menos 4,5:1 sobre blanco) y en tema oscuro (aclarado hasta tener al menos 4,5:1 sobre casi negro)."""
    color = color.lower()
    lum = _luminancia(color)
    sobre = "#0a0a0a" if _contraste(lum, _luminancia("#0a0a0a")) >= _contraste(lum, 1.0) else "#ffffff"
    texto_claro = color
    for _ in range(12):
        if _contraste(_luminancia(texto_claro), 1.0) >= 4.5:
            break
        texto_claro = _mezclar(texto_claro, "#000000", 0.15)
    texto_oscuro = color
    for _ in range(12):
        if _contraste(_luminancia(texto_oscuro), 0.004) >= 4.5:
            break
        texto_oscuro = _mezclar(texto_oscuro, "#ffffff", 0.15)
    return {"primary": color, "primary_dark": _mezclar(color, "#000000", 0.15), "on_accent": sobre, "texto_claro": texto_claro, "texto_oscuro": texto_oscuro}


def css(marca: dict | None) -> str:
    """La hoja de estilo que sobrescribe el acento (vacía si el despacho no ha elegido color)."""
    if not marca or not marca.get("color"):
        return "/* sin marca */\n"
    d = colores_derivados(marca["color"])
    return (f":root {{ --primary: {d['primary']}; --primary-dark: {d['primary_dark']}; --on-accent: {d['on_accent']}; --primary-text: {d['texto_claro']}; --focus-ring: {d['texto_claro']}; }}\n"
            f':root[data-theme="dark"] {{ --primary-text: {d["texto_oscuro"]}; --focus-ring: {d["texto_oscuro"]}; }}\n')


def obtener(tenant_id: int | None) -> dict | None:
    """`{"nombre", "color", "tiene_logo", "version"}` o None si el despacho no ha personalizado nada."""
    if tenant_id is None:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT nombre, color, logo IS NOT NULL AS tiene_logo, actualizada_en FROM tenant_marca WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    if f is None or not (f["nombre"] or f["color"] or f["tiene_logo"]):
        return None
    return {"nombre": f["nombre"], "color": f["color"], "tiene_logo": bool(f["tiene_logo"]), "version": f["actualizada_en"]}


def logo(tenant_id: int | None) -> bytes | None:
    if tenant_id is None:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT logo FROM tenant_marca WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return bytes(f["logo"]) if f and f["logo"] else None


def preparar_logo(contenido: bytes) -> bytes:
    """Valida y normaliza un logo subido: PNG/JPEG/WebP de hasta 400 KB, recodificado a PNG de como mucho 256 px. `ValueError` con un mensaje legible si no vale."""
    if not contenido:
        raise ValueError("El archivo está vacío.")
    if len(contenido) > MAX_BYTES_LOGO:
        raise ValueError("El logo pesa demasiado (máximo 400 KB).")
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(contenido)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("El logo tiene que ser PNG, JPEG o WebP.")
            im.load()
            im = im.convert("RGBA")
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError("No se ha podido leer la imagen: sube un PNG, JPEG o WebP.") from None
    im.thumbnail((LADO_LOGO, LADO_LOGO))
    salida = io.BytesIO()
    im.save(salida, "PNG", optimize=True)
    return salida.getvalue()


def guardar(tenant_id: int, *, nombre: str | None = None, color: str | None = None, logo_subido: bytes | None = None, quitar_logo: bool = False, restablecer: bool = False) -> None:
    """Guarda la marca del despacho. `restablecer` la borra entera. Un nombre vacío o un color vacío vuelven al de Guilda Work."""
    if restablecer:
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM tenant_marca WHERE tenant_id = ?", (tenant_id,))
            conn.commit()
        finally:
            conn.close()
        return
    nombre = " ".join((nombre or "").split())[:60] or None
    color = (color or "").strip().lower() or None
    if color and not _COLOR.match(color):
        raise ValueError("El color tiene que ser un código como #1a73e8.")
    nuevo_logo = preparar_logo(logo_subido) if logo_subido else None
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO tenant_marca (tenant_id, actualizada_en) VALUES (?, ?) ON CONFLICT DO NOTHING", (tenant_id, db.now_iso()))
        conn.execute("UPDATE tenant_marca SET nombre = ?, color = ?, actualizada_en = ? WHERE tenant_id = ?", (nombre, color, db.now_iso(), tenant_id))
        if nuevo_logo is not None:
            conn.execute("UPDATE tenant_marca SET logo = ? WHERE tenant_id = ?", (nuevo_logo, tenant_id))
        elif quitar_logo:
            conn.execute("UPDATE tenant_marca SET logo = NULL WHERE tenant_id = ?", (tenant_id,))
        conn.commit()
    finally:
        conn.close()


# --- Marca en los correos que salen en nombre del despacho ---

def _serializador():
    from itsdangerous import URLSafeSerializer
    try:
        from flask import current_app
        secreto = current_app.secret_key
    except RuntimeError:               # fuera de una petición (tareas programadas): la misma clave que usa la aplicación
        import os
        secreto = os.environ.get("GUILDA_SECRET_KEY")
    if not secreto:
        raise RuntimeError("Sin clave secreta no se pueden firmar enlaces de logo.")
    return URLSafeSerializer(secreto, salt="marca-logo")


def url_logo_publico(tenant_id: int, version: str, base: str) -> str:
    """Enlace público (sin sesión) al logo, para los clientes de correo. Va firmado (no se puede adivinar el de otro despacho) y lleva la versión, así que cambia al cambiar el logo."""
    return f"{base.rstrip('/')}/marca/p/{_serializador().dumps([tenant_id, version])}.png"


def tenant_de_token(token: str) -> int | None:
    from itsdangerous import BadSignature
    try:
        datos = _serializador().loads(token)
        return int(datos[0])
    except (BadSignature, ValueError, TypeError, IndexError):
        return None


def para_correo(tenant_id: int | None) -> dict | None:
    """Lo que necesita el diseño de los correos: `{"nombre", "color", "logo_url"}` (cada uno puede ser None), o None si el despacho no ha personalizado nada."""
    m = obtener(tenant_id)
    if m is None:
        return None
    from .correo_diseno import BASE
    return {"nombre": m["nombre"], "color": m["color"], "logo_url": url_logo_publico(tenant_id, m["version"], BASE) if m["tiene_logo"] else None}
