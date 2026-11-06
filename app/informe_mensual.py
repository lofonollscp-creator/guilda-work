"""Informe mensual para la dirección de cada despacho: facturas que han entrado, vencimientos fiscales cumplidos y vencidos, clientes que no han entrado al portal en dos meses y cuánto se ha usado el
portal. Solo lee; lo manda el backoffice (`backoffice/cartera.py:informes_mensuales_si_toca`) o se lanza a mano desde la ficha del despacho."""
from __future__ import annotations

from datetime import date, datetime

from . import db

DIAS_SIN_ENTRAR = 60
MAX_NOMBRES = 8


def mes_anterior(hoy: date) -> str:
    anio, mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    return f"{anio}-{mes:02d}"


def _limites(mes: str) -> tuple[str, str]:
    anio, m = int(mes[:4]), int(mes[5:7])
    siguiente = f"{anio + (m == 12)}-{(m % 12) + 1:02d}"
    return f"{mes}-01", f"{siguiente}-01"


def datos(tenant_id: int, mes: str, hoy: date | None = None) -> dict:
    """{mes, facturas: {recibidas, por_portal, pendientes, revisadas}, vencimientos: {presentados, vencidos, fuera_plazo}, portal: {entradas, personas, subidas},
    clientes_sin_entrar: {total, nombres}}. `mes` es AAAA-MM."""
    desde, hasta = _limites(mes)
    hoy = hoy or date.today()
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT COUNT(*) AS n, SUM(CASE WHEN origen = 'portal' THEN 1 ELSE 0 END) AS portal, SUM(CASE WHEN estado = 'pendiente' THEN 1 ELSE 0 END) AS pendientes, "
                         "SUM(CASE WHEN estado IN ('revisada', 'exportada') THEN 1 ELSE 0 END) AS revisadas FROM facturas_contables WHERE tenant_id = ? AND creado_en >= ? AND creado_en < ? AND estado != 'descartada'",
                         (tenant_id, desde, hasta)).fetchone()
        v = conn.execute("SELECT SUM(CASE WHEN estado = 'presentado' AND actualizado_en >= ? AND actualizado_en < ? THEN 1 ELSE 0 END) AS presentados, "
                         "SUM(CASE WHEN estado = 'pendiente' AND fecha_limite < ? THEN 1 ELSE 0 END) AS vencidos, "
                         "SUM(CASE WHEN estado = 'fuera_plazo' AND actualizado_en >= ? AND actualizado_en < ? THEN 1 ELSE 0 END) AS fuera FROM vencimientos_fiscales WHERE tenant_id = ? AND papelera_en IS NULL",
                         (desde, hasta, hoy.isoformat(), desde, hasta, tenant_id)).fetchone()
        eventos = conn.execute("SELECT detalle FROM auditoria_eventos WHERE tenant_id = ? AND accion = 'portal.entrada' AND creado_en >= ? AND creado_en < ?", (tenant_id, desde, hasta)).fetchall()
        corte = (datetime.combine(hoy, datetime.min.time()).replace(microsecond=0)).isoformat()
        limite = date.fromordinal(hoy.toordinal() - DIAS_SIN_ENTRAR).isoformat()
        activos = conn.execute("SELECT c.id, c.nombre FROM clientes_fiscales c WHERE c.tenant_id = ? AND COALESCE(c.email, '') != '' AND c.papelera_en IS NULL ORDER BY c.nombre", (tenant_id,)).fetchall()
        con_entrada = {int(r["entidad_id"]) for r in conn.execute("SELECT DISTINCT entidad_id FROM auditoria_eventos WHERE tenant_id = ? AND accion = 'portal.entrada' AND entidad = 'cliente_fiscal' AND creado_en >= ?", (tenant_id, limite)).fetchall()
                         if r["entidad_id"] and str(r["entidad_id"]).isdigit()}
    finally:
        conn.close()
    personas = set()
    for e in eventos:
        try:
            import json
            personas.add((json.loads(e["detalle"]) or {}).get("quien") or "titular")
        except (TypeError, ValueError):
            personas.add("titular")
    sin_entrar = [c["nombre"] for c in activos if c["id"] not in con_entrada]
    return {"mes": mes, "corte": corte,
            "facturas": {"recibidas": f["n"] or 0, "por_portal": f["portal"] or 0, "pendientes": f["pendientes"] or 0, "revisadas": f["revisadas"] or 0},
            "vencimientos": {"presentados": v["presentados"] or 0, "vencidos": v["vencidos"] or 0, "fuera_plazo": v["fuera"] or 0},
            "portal": {"entradas": len(eventos), "personas": len(personas)},
            "clientes_sin_entrar": {"total": len(sin_entrar), "nombres": sin_entrar[:MAX_NOMBRES]}}


def hay_algo_que_contar(d: dict) -> bool:
    """No se escribe a un despacho que no ha usado nada ese mes."""
    return bool(d["facturas"]["recibidas"] or d["vencimientos"]["presentados"] or d["vencimientos"]["vencidos"] or d["portal"]["entradas"])
