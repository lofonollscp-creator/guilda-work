"""Qué pasa con el centro de ayuda público (`help.guildawork.com`, repo `guilda-help`): votos «¿Te ha servido?» por guía y búsquedas que no encontraron nada.

Es una medida ANÓNIMA y de plataforma (no de un despacho): no se guarda IP, ni cookies, ni quién vota. Lo recibe un endpoint público (app/rutas_ayuda_metricas.py) y lo lee el backoffice de Guilda para decidir
qué guía escribir o mejorar.

- **Votos**: `pagina` (la ruta de la guía, p. ej. `guilda-fiscal/empezar`), idioma y sí/no.
- **Búsquedas sin resultado**: el texto buscado, normalizado (minúsculas, espacios simples) y contado. Lo que parece un dato personal (un correo, una cifra larga) NO se guarda, y hay un tope de textos distintos para que
  nadie pueda llenar la tabla."""
from __future__ import annotations

import re

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ayuda_valoraciones (
    id INTEGER PRIMARY KEY,
    pagina TEXT NOT NULL,
    idioma TEXT NOT NULL,
    util INTEGER NOT NULL CHECK (util IN (0, 1)),
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ayuda_valoraciones_pagina ON ayuda_valoraciones(pagina, util);
CREATE TABLE IF NOT EXISTS ayuda_busquedas_vacias (
    id INTEGER PRIMARY KEY,
    idioma TEXT NOT NULL,
    consulta TEXT NOT NULL,
    veces INTEGER NOT NULL DEFAULT 1,
    primera_en TEXT NOT NULL,
    ultima_en TEXT NOT NULL,
    UNIQUE (idioma, consulta)
);
"""

IDIOMAS = ("es", "ca", "en", "fr")
PAGINA_VALIDA = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}/[a-z0-9][a-z0-9-]{0,100}$")
MAX_CONSULTA = 60
MIN_CONSULTA = 2
MAX_CONSULTAS_DISTINTAS = 5000


def crear_esquema(conn) -> None:
    for sentencia in ESQUEMA.split(";"):
        if sentencia.strip():
            conn.execute(sentencia)


def normalizar_consulta(texto: str) -> str | None:
    """Texto listo para guardar, o None si no debe guardarse (vacío, muy largo o con pinta de dato personal)."""
    t = re.sub(r"\s+", " ", (texto or "").strip().lower())
    if len(t) < MIN_CONSULTA or len(t) > MAX_CONSULTA:
        return None
    if "@" in t or re.search(r"\d[\d\s.-]{5,}\d", t) or re.search(r"\b[a-z]?\d{7,8}[a-z]\b", t):      # correo, teléfono/cifra larga, DNI/NIE
        return None
    if re.search(r"https?://|www\.", t):
        return None
    return t


def registrar_valoracion(pagina: str, idioma: str, util: bool) -> bool:
    if idioma not in IDIOMAS or not PAGINA_VALIDA.match(pagina or ""):
        return False
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO ayuda_valoraciones (pagina, idioma, util, creado_en) VALUES (?, ?, ?, ?)", (pagina, idioma, 1 if util else 0, db.now_iso()))
        conn.commit()
        return True
    finally:
        conn.close()


def registrar_busqueda(consulta: str, idioma: str) -> bool:
    texto = normalizar_consulta(consulta)
    if texto is None or idioma not in IDIOMAS:
        return False
    conn = db.get_connection()
    try:
        existe = conn.execute("SELECT 1 FROM ayuda_busquedas_vacias WHERE idioma = ? AND consulta = ?", (idioma, texto)).fetchone()
        if not existe and conn.execute("SELECT count(*) FROM ayuda_busquedas_vacias").fetchone()[0] >= MAX_CONSULTAS_DISTINTAS:
            return False
        ahora = db.now_iso()
        conn.execute(
            "INSERT INTO ayuda_busquedas_vacias (idioma, consulta, veces, primera_en, ultima_en) VALUES (?, ?, 1, ?, ?) "
            "ON CONFLICT (idioma, consulta) DO UPDATE SET veces = ayuda_busquedas_vacias.veces + 1, ultima_en = excluded.ultima_en",
            (idioma, texto, ahora, ahora))
        conn.commit()
        return True
    finally:
        conn.close()


def busquedas_sin_resultado(limite: int = 50) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, idioma, consulta, veces, ultima_en FROM ayuda_busquedas_vacias ORDER BY veces DESC, ultima_en DESC LIMIT ?", (limite,)).fetchall()]
    finally:
        conn.close()


def borrar_busqueda(busqueda_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM ayuda_busquedas_vacias WHERE id = ?", (busqueda_id,))
        conn.commit()
    finally:
        conn.close()


def valoraciones_por_guia(minimo_votos: int = 1) -> list[dict]:
    """Por guía: votos totales y porcentaje de «sí», de los menos útiles a los más (solo guías con al menos `minimo_votos`)."""
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT pagina, count(*) AS votos, sum(util) AS utiles FROM ayuda_valoraciones GROUP BY pagina HAVING count(*) >= ?", (minimo_votos,)).fetchall()
    finally:
        conn.close()
    guias = [{"pagina": f["pagina"], "votos": int(f["votos"]), "utiles": int(f["utiles"] or 0)} for f in filas]
    for g in guias:
        g["pct_util"] = round(100 * g["utiles"] / g["votos"])
    return sorted(guias, key=lambda g: (g["pct_util"], -g["votos"]))
