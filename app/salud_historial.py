"""Histórico del panel de salud (M1): cada pasada del vigilante guarda el estado y, si lo tiene, el valor numérico de cada punto. Con él, el backoffice dibuja los últimos 30 días de cada punto
(el peor estado de cada día, para ver de un vistazo cuándo falló y cuánto duró) y la tendencia de gasto, disco, base de datos y errores. Se guarda como mucho una fila por punto y hora,
salvo que cambie su estado (entonces se guarda al momento), y se borra lo de más de 90 días."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS salud_historial (
    clave TEXT NOT NULL,
    momento TEXT NOT NULL,
    estado TEXT NOT NULL,
    valor REAL,
    detalle TEXT,
    PRIMARY KEY (clave, momento)
);
CREATE INDEX IF NOT EXISTS idx_salud_historial_momento ON salud_historial(momento);
"""

CONSERVAR_DIAS = 90
MINUTOS_ENTRE_MUESTRAS = 55
GRAVEDAD = {"verde": 0, "gris": 1, "ambar": 2, "rojo": 3}
DIAS_POR_DEFECTO = 30


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def registrar(items: list[dict], ahora: datetime | None = None) -> int:
    """Guarda la pasada actual. Devuelve cuántas filas se añadieron."""
    ahora = ahora or datetime.now()
    limite = _iso(ahora - timedelta(minutes=MINUTOS_ENTRE_MUESTRAS))
    anadidas = 0
    conn = db.get_connection()
    try:
        for i in items:
            ultima = conn.execute("SELECT momento, estado FROM salud_historial WHERE clave = ? ORDER BY momento DESC LIMIT 1", (i["clave"],)).fetchone()
            if ultima and ultima["momento"] > limite and ultima["estado"] == i["estado"]:
                continue
            valor = i.get("valor")
            conn.execute("INSERT INTO salud_historial (clave, momento, estado, valor, detalle) VALUES (?, ?, ?, ?, ?) ON CONFLICT (clave, momento) DO NOTHING",
                         (i["clave"], _iso(ahora), i["estado"], float(valor) if valor is not None else None, (i.get("detalle") or "")[:300]))
            anadidas += 1
        conn.execute("DELETE FROM salud_historial WHERE momento < ?", (_iso(ahora - timedelta(days=CONSERVAR_DIAS)),))
        conn.commit()
    finally:
        conn.close()
    return anadidas


def _filas(dias: int, ahora: datetime, clave: str | None = None):
    desde = _iso(datetime.combine((ahora - timedelta(days=dias - 1)).date(), datetime.min.time()))
    conn = db.get_connection()
    try:
        if clave:
            return conn.execute("SELECT clave, momento, estado, valor FROM salud_historial WHERE momento >= ? AND clave = ? ORDER BY momento", (desde, clave)).fetchall()
        return conn.execute("SELECT clave, momento, estado, valor FROM salud_historial WHERE momento >= ? ORDER BY clave, momento", (desde,)).fetchall()
    finally:
        conn.close()


def tendencias(items: list[dict], dias: int = DIAS_POR_DEFECTO, ahora: datetime | None = None) -> dict[str, dict]:
    """Por cada punto del panel: `dias` casillas (la más antigua primero; `estado` None si ese día no hay datos), % de días sin rojo, rojos totales y la serie de valores si la tiene."""
    ahora = ahora or datetime.now()
    dias = max(1, min(int(dias), CONSERVAR_DIAS))
    jornadas = [(ahora - timedelta(days=dias - 1 - k)).date().isoformat() for k in range(dias)]
    por_clave: dict[str, dict[str, str]] = {}
    valores: dict[str, list[float]] = {}
    for f in _filas(dias, ahora):
        d = por_clave.setdefault(f["clave"], {})
        dia = f["momento"][:10]
        if GRAVEDAD.get(f["estado"], 0) >= GRAVEDAD.get(d.get(dia, "verde"), 0) or dia not in d:
            d[dia] = f["estado"]
        if f["valor"] is not None:
            valores.setdefault(f["clave"], []).append(f["valor"])
    salida = {}
    for i in items:
        d = por_clave.get(i["clave"], {})
        casillas = [{"dia": j, "estado": d.get(j)} for j in jornadas]
        con_datos = [c for c in casillas if c["estado"]]
        rojos = sum(1 for c in con_datos if c["estado"] == "rojo")
        serie = valores.get(i["clave"], [])
        salida[i["clave"]] = {"casillas": casillas, "dias_con_datos": len(con_datos), "dias_rojo": rojos,
                              "sin_rojo_pct": round(100 * (len(con_datos) - rojos) / len(con_datos)) if con_datos else None,
                              "serie": serie[-60:], "puntos": _polilinea(serie[-60:])}
    return salida


ANCHO, ALTO = 120, 28


def _polilinea(serie: list[float]) -> str:
    """Los puntos (x,y) del dibujo SVG de la serie, o «» si hay menos de dos valores."""
    if len(serie) < 2:
        return ""
    lo, hi = min(serie), max(serie)
    rango = (hi - lo) or 1.0
    paso = ANCHO / (len(serie) - 1)
    return " ".join(f"{round(k * paso, 1)},{round(ALTO - 2 - (v - lo) / rango * (ALTO - 4), 1)}" for k, v in enumerate(serie))


def incidencias(dias: int = DIAS_POR_DEFECTO, ahora: datetime | None = None) -> list[dict]:
    """Los tramos en rojo de todos los puntos (cuándo empezó, hasta cuándo, cuánto duró), de lo más reciente a lo más antiguo."""
    ahora = ahora or datetime.now()
    tramos: list[dict] = []
    abierto: dict[str, str] = {}
    ultimo: dict[str, str] = {}
    for f in _filas(dias, ahora):
        k = f["clave"]
        if f["estado"] == "rojo" and k not in abierto:
            abierto[k] = f["momento"]
        elif f["estado"] != "rojo" and k in abierto:
            tramos.append(_tramo(k, abierto.pop(k), f["momento"]))
        ultimo[k] = f["momento"]
    for k, desde in abierto.items():
        tramos.append(_tramo(k, desde, None))
    return sorted(tramos, key=lambda t: t["desde"], reverse=True)


def _tramo(clave: str, desde: str, hasta: str | None) -> dict:
    fin = datetime.fromisoformat(hasta) if hasta else datetime.now()
    minutos = max(0, int((fin - datetime.fromisoformat(desde)).total_seconds() // 60))
    return {"clave": clave, "desde": desde, "hasta": hasta, "minutos": minutos, "abierto": hasta is None}
