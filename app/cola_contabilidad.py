"""Cola de trabajo de «Facturas para contabilizar»: qué cliente atender primero. Se ordena por la **holgura** de cada cliente: los días que faltan para el próximo modelo de IVA o pagos fraccionados
menos los días que cuesta despachar lo que tiene pendiente (a `FACTURAS_POR_DIA` facturas por día). Es una estimación para decidir el orden, no una promesa: el ritmo se ajusta aquí."""
from __future__ import annotations

from datetime import date, datetime

from . import acceso, db, facturas_contables as fc, facturas_portal

FACTURAS_POR_DIA = 25
MODELOS_CON_PLAZO = facturas_portal.MODELOS_DEL_TRIMESTRE
ORDEN_RIESGO = {"vencido": 0, "alto": 1, "medio": 2, "bajo": 3, "sin_plazo": 4}
UMBRAL_MEDIO_DIAS = 5


def _dias(desde: date, texto: str | None) -> int | None:
    try:
        return (datetime.strptime((texto or "")[:10], "%Y-%m-%d").date() - desde).days
    except ValueError:
        return None


def riesgo_de(dias_hasta: int | None, trabajo: int) -> tuple[str, int | None]:
    """(nivel, holgura en días). `holgura` = días hasta el plazo menos días de trabajo; sin plazo no hay holgura."""
    if dias_hasta is None:
        return "sin_plazo", None
    necesarios = -(-trabajo // FACTURAS_POR_DIA)                                        # techo
    holgura = dias_hasta - necesarios
    if dias_hasta < 0 and trabajo > 0:
        return "vencido", holgura
    if holgura <= 0:
        return "alto", holgura
    return ("medio" if holgura <= UMBRAL_MEDIO_DIAS else "bajo"), holgura


def cola(tenant_id: int, usuario_id: int, hoy: date | None = None) -> list[dict]:
    """Los clientes con algo en marcha, del que más urge al que menos. Cada fila: nombre, trabajo del equipo (por leer, por revisar, revisadas por exportar), lo que espera al cliente (devueltas, mensajes suyos
    sin leer), la factura pendiente más antigua en días, el próximo plazo y el riesgo."""
    hoy = hoy or date.today()
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    filas = {p["cliente_fiscal_id"]: {"cliente_id": p["cliente_fiscal_id"], "nombre": p["nombre"], "por_leer": p["por_leer"] or 0, "por_revisar": (p["pendientes"] or 0) - (p["por_leer"] or 0),
                                      "revisadas": p["revisadas"] or 0, "del_portal": p["del_portal"] or 0, "antigua": p["antigua"], "devueltas": 0, "mensajes": 0}
             for p in fc.pendientes_por_cliente(tenant_id, usuario_id)}
    conn = db.get_connection()
    try:
        devueltas = [dict(r) for r in conn.execute("SELECT x.id, x.cliente_fiscal_id FROM facturas_contables x JOIN clientes_fiscales c ON c.id = x.cliente_fiscal_id WHERE x.tenant_id = ? AND x.estado = 'descartada' "
                                                    "AND x.origen = 'portal' AND c.papelera_en IS NULL", (tenant_id,))]
        eventos = facturas_portal._eventos(conn, tenant_id, [d["id"] for d in devueltas])
        mensajes = [dict(r) for r in conn.execute("SELECT x.cliente_fiscal_id, COUNT(DISTINCT m.factura_id) AS n FROM facturas_contables_mensajes m JOIN facturas_contables x ON x.id = m.factura_id AND x.tenant_id = m.tenant_id "
                                                   "WHERE m.tenant_id = ? AND m.autor = 'cliente' AND m.leido_en IS NULL GROUP BY x.cliente_fiscal_id", (tenant_id,))]
        nombres = {c["id"]: c["nombre"] for c in conn.execute("SELECT id, nombre FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL", (tenant_id,))}
        plazos = [dict(r) for r in conn.execute("SELECT cliente_fiscal_id, modelo, periodo, fecha_limite FROM vencimientos_fiscales WHERE tenant_id = ? AND estado != 'presentado' AND papelera_en IS NULL "
                                                 f"AND modelo IN ({','.join('?' * len(MODELOS_CON_PLAZO))}) ORDER BY fecha_limite", (tenant_id, *MODELOS_CON_PLAZO))]
    finally:
        conn.close()

    def fila(cid: int) -> dict | None:
        if cid not in nombres or (visibles is not None and cid not in visibles):
            return None
        return filas.setdefault(cid, {"cliente_id": cid, "nombre": nombres[cid], "por_leer": 0, "por_revisar": 0, "revisadas": 0, "del_portal": 0, "antigua": None, "devueltas": 0, "mensajes": 0})

    for d in devueltas:
        ev = eventos.get(d["id"])
        if ev and not ev["atendida"] and (f := fila(d["cliente_fiscal_id"])) is not None:
            f["devueltas"] += 1
    for m in mensajes:
        if (f := fila(m["cliente_fiscal_id"])) is not None:
            f["mensajes"] = m["n"]
    proximo: dict[int, dict] = {}
    for p in plazos:
        proximo.setdefault(p["cliente_fiscal_id"], p)                                  # ya vienen por fecha: el primero de cada cliente es el más cercano
    res = []
    for cid, f in filas.items():
        f["trabajo"] = f["por_leer"] + f["por_revisar"] + f["revisadas"]
        f["antigua_dias"] = max(0, -_dias(hoy, f["antigua"])) if f["antigua"] and _dias(hoy, f["antigua"]) is not None else None
        pl = proximo.get(cid)
        f["plazo"] = {"modelo": pl["modelo"], "periodo": pl["periodo"], "fecha": pl["fecha_limite"][:10]} if pl else None
        f["dias_hasta"] = _dias(hoy, pl["fecha_limite"]) if pl else None
        f["riesgo"], f["holgura"] = riesgo_de(f["dias_hasta"], f["trabajo"])
        if f["trabajo"] == 0 and f["devueltas"] == 0 and f["mensajes"] == 0:
            continue
        res.append(f)
    res.sort(key=lambda f: (ORDEN_RIESGO[f["riesgo"]] if f["trabajo"] else 5, f["holgura"] if f["holgura"] is not None else 10**6, -(f["antigua_dias"] or 0), f["nombre"].lower()))
    return res
