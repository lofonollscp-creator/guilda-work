"""Cuadre del IVA de las facturas para contabilizar con el modelo 303 simulado de Guilda Fiscal (J13): ¿el IVA que sale de las facturas revisadas o exportadas es el mismo que acaba en las casillas 27 (cuota
devengada) y 45 (total a deducir)? Una diferencia suele ser una factura que no llegó a Guilda Fiscal (se sacó de ahí, o no se ha aprobado su apunte) o una operación que lleva IVA en las dos casillas.
Solo se comparan las operaciones interiores (tipo de operación 01): las intracomunitarias, la inversión del sujeto pasivo y las importaciones suman en las dos casillas y no se cotejan. Es un aviso, no cambia nada."""
from __future__ import annotations

from . import db, facturas_contables as fc


def _periodo(trimestre: str) -> tuple[int, str]:
    fc.rango_del_trimestre(trimestre)
    return int(trimestre[:4]), f"{trimestre[-1]}T"


def iva_de_las_facturas(tenant_id: int, cliente_fiscal_id: int, trimestre: str) -> dict:
    """{repercutido, soportado, facturas} en céntimos, de las facturas revisadas o exportadas del trimestre que cuentan para Guilda Fiscal, solo operaciones interiores. Los abonos restan."""
    desde, hasta = fc.rango_del_trimestre(trimestre)
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT x.id, x.tipo, x.abono, l.cuota_iva FROM facturas_contables x JOIN facturas_contables_lineas l ON l.factura_id = x.id WHERE x.tenant_id = ? AND x.cliente_fiscal_id = ? "
                             "AND x.estado IN ('revisada', 'exportada') AND COALESCE(x.incluir_en_fiscal, 1) = 1 AND x.fecha BETWEEN ? AND ? AND l.subtipo = '01' AND l.sujeta_iva = 1",
                             (tenant_id, cliente_fiscal_id, desde, hasta)).fetchall()
    finally:
        conn.close()
    res = {"repercutido": 0, "soportado": 0}
    for f in filas:
        res["repercutido" if f["tipo"] == "emitida" else "soportado"] += (-1 if f["abono"] else 1) * f["cuota_iva"]
    res["facturas"] = len({f["id"] for f in filas})
    return res


def cuadrar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str) -> dict:
    """{trimestre, disponible, motivo, facturas: {...}, modelo_303: {devengado, deducible}, diferencia: {repercutido, soportado}} (céntimos). `disponible` es False, con su `motivo`, si Guilda Fiscal no
    está activo, el titular no tiene perfil o el 303 está bloqueado: entonces no hay nada con qué comparar."""
    from . import consultas_fiscal
    ejercicio, periodo = _periodo(trimestre)
    nuestras = iva_de_las_facturas(tenant_id, cliente_fiscal_id, trimestre)
    base = {"trimestre": trimestre, "facturas": nuestras, "disponible": False, "motivo": None}
    try:
        sim = consultas_fiscal.simular_303(tenant_id, usuario_id, cliente_fiscal_id, ejercicio, periodo)
    except (ValueError, consultas_fiscal.ErrorFiscal) as e:
        return {**base, "motivo": str(e)}
    if sim["bloqueos"] or not sim["casillas"]:
        return {**base, "motivo": "; ".join(sim["bloqueos"]) or "El modelo 303 no se puede calcular todavía."}
    devengado, deducible = round(sim["casillas"].get("27", 0) * 100), round(sim["casillas"].get("45", 0) * 100)
    return {**base, "disponible": True, "modelo_303": {"devengado": devengado, "deducible": deducible},
            "diferencia": {"repercutido": nuestras["repercutido"] - devengado, "soportado": nuestras["soportado"] - deducible}}
