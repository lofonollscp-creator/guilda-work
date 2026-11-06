"""El panel de situación del cliente: ingresos, gastos e IVA estimado de los últimos trimestres, y el trimestre actual frente al mismo del año anterior.

Es una **estimación** hecha con las facturas que la gestoría ya ha revisado (no incluye las pendientes de tratar, que se cuentan aparte) y con el IVA de sus líneas; no es la declaración ni la sustituye. Los abonos restan.
Sin tablas nuevas: lo calcula al vuelo de las facturas del cliente."""
from __future__ import annotations

from datetime import date

from . import db, facturas_contables as fc, facturas_portal

TRIMESTRES = 5                      # el actual y los cuatro anteriores: se ve el mismo trimestre del año pasado
ALTO, ANCHO = 140, 520              # del dibujo, en unidades de su viewBox


def _trimestres_hasta(actual: str, n: int) -> list[str]:
    anio, t, res = int(actual[:4]), int(actual[-1]), []
    for _ in range(n):
        res.append(f"{anio}-T{t}")
        t -= 1
        if t == 0:
            anio, t = anio - 1, 4
    return list(reversed(res))


def calcular(cliente, hoy: date | None = None) -> dict | None:
    """{trimestres: [{trimestre, etiqueta, ingresos, gastos, iva_repercutido, iva_soportado, iva_estimado, facturas}], actual, anterior, pendientes, barras, max} (importes en céntimos) o None si aún no hay ninguna factura tratada."""
    hoy = hoy or date.today()
    ultimo = facturas_portal.trimestre_actual(hoy)
    lista = _trimestres_hasta(ultimo, TRIMESTRES)
    desde = fc.rango_del_trimestre(lista[0])[0]
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT f.id, f.tipo, f.estado, f.fecha, f.abono, COALESCE(SUM(l.base_centimos), 0) AS base, COALESCE(SUM(l.cuota_iva), 0) AS iva FROM facturas_contables f "
            "LEFT JOIN facturas_contables_lineas l ON l.factura_id = f.id WHERE f.tenant_id = ? AND f.cliente_fiscal_id = ? AND f.estado != 'descartada' AND f.fecha >= ? "
            "GROUP BY f.id, f.tipo, f.estado, f.fecha, f.abono", (cliente["tenant_id"], cliente["id"], desde)).fetchall()
    finally:
        conn.close()
    por = {t: {"trimestre": t, "etiqueta": facturas_portal.etiqueta_trimestre(t), "ingresos": 0, "gastos": 0, "iva_repercutido": 0, "iva_soportado": 0, "facturas": 0} for t in lista}
    pendientes = 0
    for f in filas:
        t = fc.trimestre_de(f["fecha"])
        if t not in por:
            continue
        if f["estado"] == "pendiente":
            pendientes += 1
            continue
        signo = -1 if f["abono"] else 1
        d = por[t]
        d["facturas"] += 1
        if f["tipo"] == "emitida":
            d["ingresos"] += signo * f["base"]
            d["iva_repercutido"] += signo * f["iva"]
        else:
            d["gastos"] += signo * f["base"]
            d["iva_soportado"] += signo * f["iva"]
    trimestres = list(por.values())
    for d in trimestres:
        d["iva_estimado"] = d["iva_repercutido"] - d["iva_soportado"]
    if not any(d["facturas"] for d in trimestres):
        return None
    tope = max([abs(d["ingresos"]) for d in trimestres] + [abs(d["gastos"]) for d in trimestres] + [1])
    ancho_grupo = ANCHO / len(trimestres)
    barras = []
    for i, d in enumerate(trimestres):
        for k, (clave, clase) in enumerate((("ingresos", "ingreso"), ("gastos", "gasto"))):
            alto = round(max(0, d[clave]) / tope * (ALTO - 24), 1)
            barras.append({"trimestre": d["trimestre"], "clase": clase, "x": round(i * ancho_grupo + ancho_grupo * 0.14 + k * ancho_grupo * 0.36, 1), "ancho": round(ancho_grupo * 0.32, 1),
                           "y": round(ALTO - 20 - alto, 1), "alto": alto, "valor": d[clave], "etiqueta_x": round(i * ancho_grupo + ancho_grupo / 2, 1), "actual": d["trimestre"] == ultimo})
    return {"trimestres": trimestres, "actual": trimestres[-1], "anterior": trimestres[-1 - 4] if len(trimestres) > 4 else None, "pendientes": pendientes, "barras": barras, "alto": ALTO, "ancho": ANCHO,
            "ancho_grupo": round(ancho_grupo, 1)}
