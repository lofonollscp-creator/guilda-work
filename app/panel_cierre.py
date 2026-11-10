"""«Qué falta para cerrar» (F1): por cada cliente del despacho y trimestre, en qué punto está su contabilización (por leer, por revisar, listas para exportar, exportadas sin confirmar en a3) y cuántos días
quedan para el plazo de presentación. Es una vista sobre `facturas_contables`: no guarda nada. La confirmación en a3 solo se exige a los clientes que ya la usan (alguna factura suya confirmada)."""
from __future__ import annotations

from datetime import date

from . import acceso, db, facturas_contables as fc

PLAZO_DEL_TRIMESTRE = {1: (4, 20), 2: (7, 20), 3: (10, 20), 4: (1, 30)}        # mes y día de presentación del modelo 303 (el del cuarto trimestre es de enero del año siguiente)


def plazo(trimestre: str) -> date:
    fc.rango_del_trimestre(trimestre)
    anio, t = int(trimestre[:4]), int(trimestre[-1])
    mes, dia = PLAZO_DEL_TRIMESTRE[t]
    return date(anio + (t == 4), mes, dia)


def trimestre_actual(hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    return f"{hoy.year}-T{(hoy.month - 1) // 3 + 1}"


def trimestre_anterior(hoy: date | None = None) -> str:
    """El que se está cerrando ahora: el anterior al que corre (en enero, abril, julio y octubre es el de la presentación)."""
    hoy = hoy or date.today()
    t = (hoy.month - 1) // 3
    return f"{hoy.year - (t == 0)}-T{t or 4}"


def panel(tenant_id: int, usuario_id: int, trimestre: str | None = None, hoy: date | None = None) -> dict:
    """{trimestre, plazo, dias, clientes: [...], resumen}. Cada cliente: id, nombre, total, sin_leer, por_revisar, listas (revisadas), sin_confirmar, exportadas, usa_retorno, cerrado, listo, faltan.
    Los que tienen algo que hacer van primero y, entre ellos, los que más les falta."""
    hoy = hoy or date.today()
    trimestre = trimestre or trimestre_anterior(hoy)
    desde, hasta = fc.rango_del_trimestre(trimestre)
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT x.cliente_fiscal_id, c.nombre, COUNT(*) AS total, "
                             "SUM(CASE WHEN x.estado = 'pendiente' AND x.lectura IN ('pendiente', 'fallida') THEN 1 ELSE 0 END) AS sin_leer, "
                             "SUM(CASE WHEN x.estado = 'pendiente' AND COALESCE(x.lectura, '') NOT IN ('pendiente', 'fallida') THEN 1 ELSE 0 END) AS por_revisar, "
                             "SUM(CASE WHEN x.estado = 'revisada' THEN 1 ELSE 0 END) AS listas, SUM(CASE WHEN x.estado = 'exportada' THEN 1 ELSE 0 END) AS exportadas, "
                             "SUM(CASE WHEN x.estado = 'exportada' AND x.confirmada_en IS NULL THEN 1 ELSE 0 END) AS sin_confirmar "
                             "FROM facturas_contables x JOIN clientes_fiscales c ON c.id = x.cliente_fiscal_id WHERE x.tenant_id = ? AND x.fecha BETWEEN ? AND ? AND x.estado != 'descartada' "
                             "AND c.papelera_en IS NULL GROUP BY x.cliente_fiscal_id, c.nombre", (tenant_id, desde, hasta)).fetchall()
        configurados = {r["cliente_fiscal_id"]: r["nombre"] for r in conn.execute(
            "SELECT k.cliente_fiscal_id, c.nombre FROM contabilidad_clientes k JOIN clientes_fiscales c ON c.id = k.cliente_fiscal_id WHERE k.tenant_id = ? AND k.a3_empresa IS NOT NULL AND c.papelera_en IS NULL", (tenant_id,))}
        con_retorno = {r["cliente_fiscal_id"] for r in conn.execute("SELECT DISTINCT cliente_fiscal_id FROM facturas_contables WHERE tenant_id = ? AND confirmada_en IS NOT NULL", (tenant_id,))}
    finally:
        conn.close()
    por_id = {f["cliente_fiscal_id"]: dict(f) for f in filas}
    for cid, nombre in configurados.items():
        por_id.setdefault(cid, {"cliente_fiscal_id": cid, "nombre": nombre, "total": 0, "sin_leer": 0, "por_revisar": 0, "listas": 0, "exportadas": 0, "sin_confirmar": 0})
    clientes = []
    for cid, c in por_id.items():
        if visibles is not None and cid not in visibles:
            continue
        c = {k: (v or 0) if k not in ("nombre", "cliente_fiscal_id") else v for k, v in c.items()}
        c["usa_retorno"] = cid in con_retorno
        if not c["usa_retorno"]:
            c["sin_confirmar"] = 0
        c["cerrado"] = bool(fc.periodos_cerrados(tenant_id, cid, [trimestre]).get(trimestre))
        c["faltan"] = c["sin_leer"] + c["por_revisar"] + c["listas"] + c["sin_confirmar"]
        c["listo"] = c["total"] > 0 and c["faltan"] == 0
        c["sin_facturas"] = c["total"] == 0
        clientes.append(c)
    clientes.sort(key=lambda c: (c["cerrado"], c["listo"], -c["faltan"], c["sin_facturas"] is False, c["nombre"].lower()))
    limite = plazo(trimestre)
    return {"trimestre": trimestre, "plazo": limite.isoformat(), "dias": (limite - hoy).days, "clientes": clientes,
            "resumen": {"clientes": len(clientes), "listos": sum(1 for c in clientes if c["listo"] or c["cerrado"]), "sin_facturas": sum(1 for c in clientes if c["sin_facturas"] and not c["cerrado"]),
                        "faltan": sum(c["faltan"] for c in clientes if not c["cerrado"])}}
