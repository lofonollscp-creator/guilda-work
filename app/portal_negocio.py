"""«Tu negocio este trimestre»: lo que el cliente quiere saber a mitad de trimestre sin esperar a que acabe — una previsión del IVA, sus mayores gastos y avisos útiles cuando algo se sale de lo normal.

Todo es una **estimación** con las facturas que su gestoría ya ha revisado (las pendientes de revisar se cuentan aparte): no es la declaración. La previsión solo se enseña cuando ya ha pasado bastante trimestre para que
no sea una tontería, y los avisos solo saltan con diferencias claras (y de importe relevante) frente a la media de los tres trimestres anteriores, para no marear con ruido."""
from __future__ import annotations

from datetime import date, timedelta

from . import db, facturas_portal

DIAS_MINIMOS_PREVISION = 20
UMBRAL_GASTOS = 1.4                  # un 40 % por encima de la media
UMBRAL_VENTAS = 0.7                  # un 30 % por debajo
IMPORTE_MINIMO = 30000               # céntimos: por debajo de 300 € no se avisa de nada
MAX_PROVEEDORES = 5


def _totales(conn, cliente, desde: str, hasta: str) -> dict:
    filas = conn.execute("SELECT f.tipo, f.estado, f.abono, COALESCE(SUM(l.base_centimos), 0) AS base, COALESCE(SUM(l.cuota_iva), 0) AS iva FROM facturas_contables f LEFT JOIN facturas_contables_lineas l ON l.factura_id = f.id "
                         "WHERE f.tenant_id = ? AND f.cliente_fiscal_id = ? AND f.estado != 'descartada' AND f.fecha >= ? AND f.fecha <= ? GROUP BY f.id, f.tipo, f.estado, f.abono", (cliente["tenant_id"], cliente["id"], desde, hasta)).fetchall()
    t = {"ventas": 0, "gastos": 0, "iva_rep": 0, "iva_sop": 0, "pendientes": 0}
    for f in filas:
        if f["estado"] == "pendiente":
            t["pendientes"] += 1
            continue
        s = -1 if f["abono"] else 1
        if f["tipo"] == "emitida":
            t["ventas"] += s * f["base"]
            t["iva_rep"] += s * f["iva"]
        else:
            t["gastos"] += s * f["base"]
            t["iva_sop"] += s * f["iva"]
    return t


def _trimestre(hoy: date) -> tuple[date, date]:
    inicio = date(hoy.year, 3 * ((hoy.month - 1) // 3) + 1, 1)
    fin = date(hoy.year + (inicio.month == 10), (inicio.month + 3 - 1) % 12 + 1, 1) - timedelta(days=1)
    return inicio, fin


def _anteriores(inicio: date, n: int = 3) -> list[tuple[date, date]]:
    res, fin = [], inicio - timedelta(days=1)
    for _i in range(n):
        ini = date(fin.year, 3 * ((fin.month - 1) // 3) + 1, 1)
        res.append((ini, fin))
        fin = ini - timedelta(days=1)
    return res


def calcular(cliente, hoy: date | None = None) -> dict | None:
    """{trimestre, etiqueta, dias_pasados, dias_totales, actual: {...}, prevision_iva, proveedores: [{nombre, base}], avisos: [clave], pendientes} o None si aún no hay nada revisado en este trimestre ni en los anteriores."""
    hoy = hoy or date.today()
    ini, fin = _trimestre(hoy)
    dias_totales, dias_pasados = (fin - ini).days + 1, (hoy - ini).days + 1
    conn = db.get_connection()
    try:
        actual = _totales(conn, cliente, ini.isoformat(), fin.isoformat())
        previos = [_totales(conn, cliente, a.isoformat(), b.isoformat()) for a, b in _anteriores(ini)]
        prov = [dict(f) for f in conn.execute(
            "SELECT f.tercero_nombre AS nombre, COALESCE(SUM(l.base_centimos), 0) AS base FROM facturas_contables f LEFT JOIN facturas_contables_lineas l ON l.factura_id = f.id WHERE f.tenant_id = ? AND f.cliente_fiscal_id = ? "
            "AND f.tipo = 'recibida' AND f.estado IN ('revisada', 'exportada') AND f.abono = 0 AND f.fecha >= ? AND f.fecha <= ? GROUP BY f.tercero_nombre ORDER BY base DESC LIMIT ?", (cliente["tenant_id"], cliente["id"], ini.isoformat(), fin.isoformat(), MAX_PROVEEDORES))]
    finally:
        conn.close()
    if not any(actual[k] for k in ("ventas", "gastos", "iva_rep", "iva_sop")) and not any(p["ventas"] or p["gastos"] for p in previos):
        return None
    iva_ahora = actual["iva_rep"] - actual["iva_sop"]
    prevision = round(iva_ahora * dias_totales / dias_pasados) if dias_pasados >= DIAS_MINIMOS_PREVISION else None
    avisos = []
    con_historia = [p for p in previos if p["ventas"] or p["gastos"]]
    if dias_pasados >= DIAS_MINIMOS_PREVISION and len(con_historia) >= 2:
        media_g = sum(p["gastos"] for p in con_historia) / len(con_historia)
        media_v = sum(p["ventas"] for p in con_historia) / len(con_historia)
        gastos_fin = actual["gastos"] * dias_totales / dias_pasados
        ventas_fin = actual["ventas"] * dias_totales / dias_pasados
        if media_g and gastos_fin > media_g * UMBRAL_GASTOS and gastos_fin - media_g >= IMPORTE_MINIMO:
            avisos.append({"clave": "gastos_altos", "pct": round((gastos_fin / media_g - 1) * 100)})
        if media_v and ventas_fin < media_v * UMBRAL_VENTAS and media_v - ventas_fin >= IMPORTE_MINIMO:
            avisos.append({"clave": "ventas_bajas", "pct": round((1 - ventas_fin / media_v) * 100)})
    if prevision is not None and prevision > 0 and not avisos and prevision >= IMPORTE_MINIMO:
        avisos.append({"clave": "iva_a_pagar", "importe": prevision})
    return {"trimestre": facturas_portal.trimestre_actual(hoy), "etiqueta": facturas_portal.etiqueta_trimestre(facturas_portal.trimestre_actual(hoy)), "dias_pasados": dias_pasados, "dias_totales": dias_totales,
            "actual": actual, "iva_ahora": iva_ahora, "prevision_iva": prevision, "proveedores": [p for p in prov if p["base"] > 0], "avisos": avisos, "pendientes": actual["pendientes"]}
