"""Acuse, silencio y responsable de cada punto del panel de salud. Silenciar un punto en rojo (con motivo y fecha) hace que el vigilante deje de escribir por él hasta esa fecha; se
levanta solo si el punto se arregla y vuelve a fallar, o al llegar la fecha. «Asignar» deja anotado quién se ocupa de él. Los puntos siguen viéndose en el panel, solo se calla el correo."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS salud_silencios (
    clave TEXT PRIMARY KEY,
    asignado_a TEXT,
    silenciado_hasta TEXT,
    motivo TEXT,
    actualizado_por TEXT,
    actualizado_en TEXT NOT NULL
);
"""

DIAS_VALIDOS = (1, 3, 7, 30)
MAX_TEXTO = 200


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _limpio(texto: str | None, largo: int = MAX_TEXTO) -> str:
    return " ".join((texto or "").split())[:largo]


def _guardar(clave: str, por: str | None, **campos) -> None:
    conn = db.get_connection()
    try:
        actual = conn.execute("SELECT * FROM salud_silencios WHERE clave = ?", (clave,)).fetchone()
        datos = {"asignado_a": actual["asignado_a"] if actual else None, "silenciado_hasta": actual["silenciado_hasta"] if actual else None, "motivo": actual["motivo"] if actual else None}
        datos.update(campos)
        if not any(datos.values()):
            conn.execute("DELETE FROM salud_silencios WHERE clave = ?", (clave,))
        else:
            conn.execute("INSERT INTO salud_silencios (clave, asignado_a, silenciado_hasta, motivo, actualizado_por, actualizado_en) VALUES (?, ?, ?, ?, ?, ?) "
                         "ON CONFLICT(clave) DO UPDATE SET asignado_a = excluded.asignado_a, silenciado_hasta = excluded.silenciado_hasta, motivo = excluded.motivo, "
                         "actualizado_por = excluded.actualizado_por, actualizado_en = excluded.actualizado_en",
                         (clave, datos["asignado_a"], datos["silenciado_hasta"], datos["motivo"], por, _iso(datetime.now())))
        conn.commit()
    finally:
        conn.close()


def silenciar(clave: str, dias: int, motivo: str, por: str | None = None, ahora: datetime | None = None) -> str:
    """Calla el correo de ese punto durante `dias` días. Devuelve la fecha hasta la que vale. ValueError si falta el motivo o los días no son válidos."""
    motivo = _limpio(motivo)
    if len(motivo) < 5:
        raise ValueError("Escribe el motivo (mínimo 5 caracteres): queda anotado.")
    if dias not in DIAS_VALIDOS:
        raise ValueError("Elige 1, 3, 7 o 30 días.")
    hasta = _iso((ahora or datetime.now()) + timedelta(days=dias))
    _guardar(clave, por, silenciado_hasta=hasta, motivo=motivo)
    return hasta


def quitar_silencio(clave: str, por: str | None = None) -> None:
    _guardar(clave, por, silenciado_hasta=None, motivo=None)


def asignar(clave: str, a_quien: str, por: str | None = None) -> None:
    """Anota quién se ocupa de ese punto (vacío = nadie)."""
    _guardar(clave, por, asignado_a=_limpio(a_quien, 80) or None)


def todos() -> dict[str, dict]:
    conn = db.get_connection()
    try:
        return {f["clave"]: dict(f) for f in conn.execute("SELECT * FROM salud_silencios").fetchall()}
    finally:
        conn.close()


def activos(ahora: datetime | None = None) -> set[str]:
    """Las claves cuyo silencio sigue vigente."""
    limite = _iso(ahora or datetime.now())
    return {c for c, f in todos().items() if f["silenciado_hasta"] and f["silenciado_hasta"] > limite}


def levantar_los_resueltos(claves_en_rojo: set[str], ahora: datetime | None = None) -> int:
    """Quita el silencio a los puntos que ya no están en rojo o cuya fecha pasó: si vuelven a fallar, avisarán de nuevo. Conserva el responsable. Devuelve cuántos levantó."""
    limite, n = _iso(ahora or datetime.now()), 0
    for clave, f in todos().items():
        if f["silenciado_hasta"] and (clave not in claves_en_rojo or f["silenciado_hasta"] <= limite):
            _guardar(clave, "automático", silenciado_hasta=None, motivo=None)
            n += 1
    return n


def anotar(items: list[dict], ahora: datetime | None = None) -> list[dict]:
    """Añade a cada punto del panel su `silencio` ({hasta, motivo, por}) y su `asignado_a`, si los tiene."""
    datos, vigentes = todos(), activos(ahora)
    for i in items:
        f = datos.get(i["clave"])
        i["asignado_a"] = f["asignado_a"] if f else None
        i["silencio"] = {"hasta": f["silenciado_hasta"], "motivo": f["motivo"], "por": f["actualizado_por"]} if f and i["clave"] in vigentes else None
    return items
