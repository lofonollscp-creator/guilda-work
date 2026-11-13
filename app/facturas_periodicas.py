"""Facturas periódicas que faltan (L19): un proveedor que manda una factura casi todos los meses (la luz, el alquiler, un seguro) y este mes no ha llegado. Es el equivalente por proveedor de «Sin entregas este mes»: el
cliente que se ha dejado de mandar la de la luz no suele darse cuenta. Se mira la fecha de la factura (no la de alta) y solo las recibidas; no se escribe nada."""
from __future__ import annotations

from datetime import date

from . import db, facturas_contables as fc

MESES_DE_HISTORIAL = 6               # cuántos meses anteriores se miran
MESES_PARA_SER_PERIODICA = 3         # con factura en al menos tantos de ellos, el proveedor es periódico
DIA_DEL_MES_PARA_AVISAR = 10         # hasta entonces es normal que aún no haya llegado
RECIENTE = 2                         # y la última tuvo que ser de los últimos tantos meses (no se avisa de un proveedor que ya no se usa)


def _mes(a: int, m: int, n: int = 0) -> str:
    m -= n
    while m < 1:
        m += 12
        a -= 1
    return f"{a:04d}-{m:02d}"


def por_cliente(tenant_id: int, hoy: date | None = None) -> dict[int, list[dict]]:
    """{cliente_fiscal_id: [{nif, nombre, meses, ultima}]}: los proveedores periódicos de cada cliente de los que no hay factura este mes. Vacío antes del día 10."""
    hoy = hoy or date.today()
    if hoy.day < DIA_DEL_MES_PARA_AVISAR:
        return {}
    actual = _mes(hoy.year, hoy.month)
    desde = _mes(hoy.year, hoy.month, MESES_DE_HISTORIAL) + "-01"
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT cliente_fiscal_id, tercero_nif, MAX(tercero_nombre) AS nombre, substr(fecha, 1, 7) AS mes FROM facturas_contables WHERE tenant_id = ? AND tipo = 'recibida' AND abono = 0 "
                             "AND estado != 'descartada' AND tercero_nif IS NOT NULL AND tercero_nif != '' AND fecha >= ? GROUP BY cliente_fiscal_id, tercero_nif, substr(fecha, 1, 7)", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    meses: dict[tuple[int, str], dict] = {}
    for f in filas:
        d = meses.setdefault((f["cliente_fiscal_id"], fc._nif(f["tercero_nif"])), {"nombre": f["nombre"], "meses": set()})
        d["meses"].add(f["mes"])
    recientes = {_mes(hoy.year, hoy.month, i) for i in range(1, RECIENTE + 1)}
    res: dict[int, list[dict]] = {}
    for (cliente, nif), d in meses.items():
        previos = d["meses"] - {actual}
        if actual in d["meses"] or len(previos) < MESES_PARA_SER_PERIODICA or not (previos & recientes):
            continue
        res.setdefault(cliente, []).append({"nif": nif, "nombre": d["nombre"], "meses": len(previos), "ultima": max(previos)})
    for lista in res.values():
        lista.sort(key=lambda x: (-x["meses"], x["nombre"].lower()))
    return res


def que_faltan(tenant_id: int, cliente_fiscal_id: int, hoy: date | None = None) -> list[dict]:
    return por_cliente(tenant_id, hoy).get(cliente_fiscal_id, [])


def por_cliente_del_trimestre(tenant_id: int, trimestre: str, hoy: date | None = None) -> dict[int, list[dict]]:
    """Lo mismo, pero mirando el trimestre que se va a cerrar (AC8): {cliente_fiscal_id: [{nif, nombre, meses, faltan: [AAAA-MM…]}]} de los proveedores periódicos (factura en al menos 3 de los 6 meses anteriores
    al trimestre, la última de los 2 últimos) a los que les falta la factura en alguno de los meses del trimestre. Un mes solo cuenta como «falta» pasado su día 10; no se escribe nada."""
    hoy = hoy or date.today()
    desde, hasta = fc.rango_del_trimestre(trimestre)
    a, m0 = int(desde[:4]), int(desde[5:7])
    del_trimestre = [_mes(a, m0 + i) for i in range(3)]
    pasados = [mes for mes in del_trimestre if mes < _mes(hoy.year, hoy.month) or (mes == _mes(hoy.year, hoy.month) and hoy.day >= DIA_DEL_MES_PARA_AVISAR)]
    if not pasados:
        return {}
    previos_rango = [_mes(a, m0, i) for i in range(1, MESES_DE_HISTORIAL + 1)]
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT cliente_fiscal_id, tercero_nif, MAX(tercero_nombre) AS nombre, substr(fecha, 1, 7) AS mes FROM facturas_contables WHERE tenant_id = ? AND tipo = 'recibida' AND abono = 0 "
                             "AND estado != 'descartada' AND tercero_nif IS NOT NULL AND tercero_nif != '' AND fecha >= ? AND fecha <= ? GROUP BY cliente_fiscal_id, tercero_nif, substr(fecha, 1, 7)",
                             (tenant_id, previos_rango[-1] + "-01", hasta)).fetchall()
    finally:
        conn.close()
    datos: dict[tuple[int, str], dict] = {}
    for f in filas:
        d = datos.setdefault((f["cliente_fiscal_id"], fc._nif(f["tercero_nif"])), {"nombre": f["nombre"], "meses": set()})
        d["meses"].add(f["mes"])
    res: dict[int, list[dict]] = {}
    for (cliente, nif), d in datos.items():
        previos = d["meses"] & set(previos_rango)
        if len(previos) < MESES_PARA_SER_PERIODICA or not (previos & set(previos_rango[:RECIENTE])):
            continue
        faltan = [mes for mes in pasados if mes not in d["meses"]]
        if faltan:
            res.setdefault(cliente, []).append({"nif": nif, "nombre": d["nombre"], "meses": len(previos), "faltan": faltan})
    for lista in res.values():
        lista.sort(key=lambda x: (-len(x["faltan"]), -x["meses"], x["nombre"].lower()))
    return res
