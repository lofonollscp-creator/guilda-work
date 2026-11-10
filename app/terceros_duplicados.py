"""Terceros duplicados de un cliente (L20): el mismo NIF escrito con nombres distintos («Papelería Sol S.L.», «PAPELERIA SOL») y el mismo nombre con NIF distintos (casi siempre un NIF mal leído). Unos y otros acaban en
subcuentas repetidas en a3. Aquí se encuentran y se unifican; solo se tocan las facturas pendientes o revisadas, nunca las ya exportadas (esas ya están en a3)."""
from __future__ import annotations

from . import auditoria, db, facturas_contables as fc, lectura_historial

ESTADOS_EDITABLES = ("pendiente", "revisada")


def _clave_de_nombre(nombre: str) -> str:
    return " ".join(sorted(lectura_historial._palabras(nombre)))


def _facturas(tenant_id: int, cliente_fiscal_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT id, tipo, tercero_nombre, tercero_nif, estado FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartada'", (tenant_id, cliente_fiscal_id))]
    finally:
        conn.close()


def encontrar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> dict:
    """{mismo_nif: [{tipo, nif, nombres: [{nombre, facturas, editables}]}], mismo_nombre: [{tipo, nombre, nifs: [{nif, facturas, editables}]}]}. Proveedores (recibidas) y clientes (emitidas) por separado."""
    fc._cliente(tenant_id, usuario_id, cliente_fiscal_id)
    por_nif: dict[tuple[str, str], dict[str, dict]] = {}
    por_nombre: dict[tuple[str, str], dict[str, dict]] = {}
    for f in _facturas(tenant_id, cliente_fiscal_id):
        nif, nombre = fc._nif(f["tercero_nif"]), (f["tercero_nombre"] or "").strip()
        clave = _clave_de_nombre(nombre)
        editable = f["estado"] in ESTADOS_EDITABLES
        if nif:
            d = por_nif.setdefault((f["tipo"], nif), {}).setdefault(nombre, {"nombre": nombre, "facturas": 0, "editables": 0, "clave": clave})
            d["facturas"] += 1; d["editables"] += editable
        if clave and nif:
            d = por_nombre.setdefault((f["tipo"], clave), {}).setdefault(nif, {"nif": nif, "facturas": 0, "editables": 0, "nombre": nombre})
            d["facturas"] += 1; d["editables"] += editable
    mismo_nif = []
    for (tipo, nif), nombres in sorted(por_nif.items()):
        if len({n["clave"] for n in nombres.values()}) > 1 or len(nombres) > 1:
            mismo_nif.append({"tipo": tipo, "nif": nif, "nombres": sorted(({k: v for k, v in n.items() if k != "clave"} for n in nombres.values()), key=lambda n: -n["facturas"])})
    mismo_nombre = []
    for (tipo, _clave), nifs in sorted(por_nombre.items()):
        if len(nifs) > 1:
            mismo_nombre.append({"tipo": tipo, "nombre": max(nifs.values(), key=lambda n: n["facturas"])["nombre"], "nifs": sorted(({k: v for k, v in n.items() if k != "nombre"} for n in nifs.values()), key=lambda n: -n["facturas"])})
    return {"mismo_nif": mismo_nif, "mismo_nombre": mismo_nombre}


def unificar_nombre(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, nif: str, nombre: str) -> int:
    """Pone `nombre` en todas las facturas pendientes o revisadas de ese NIF. Devuelve cuántas cambió."""
    fc._cliente(tenant_id, usuario_id, cliente_fiscal_id)
    nombre = (nombre or "").strip()[:100]
    if not nombre or tipo not in fc.TIPOS or not fc._nif(nif):
        raise ValueError("Indica el nombre correcto, el tipo (emitida o recibida) y el NIF.")
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE facturas_contables SET tercero_nombre = ?, actualizado_en = ? WHERE tenant_id = ? AND cliente_fiscal_id = ? AND tipo = ? AND tercero_nif = ? AND estado IN ('pendiente', 'revisada') "
                           "AND tercero_nombre != ?", (nombre, db.now_iso(), tenant_id, cliente_fiscal_id, tipo, fc._nif(nif), nombre))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.terceros_unificados", "cliente_fiscal", cliente_fiscal_id, {"tipo": tipo, "nif": fc._nif(nif), "nombre": nombre, "facturas": cur.rowcount}, conn=conn)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def corregir_nif(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, tipo: str, nif_mal: str, nif_bien: str) -> int:
    """Cambia un NIF mal leído por el bueno en las facturas pendientes o revisadas. Devuelve cuántas cambió. Las exportadas no se tocan."""
    fc._cliente(tenant_id, usuario_id, cliente_fiscal_id)
    mal, bien = fc._nif(nif_mal), fc._nif(nif_bien)
    if not mal or not bien or mal == bien or len(bien) > 20 or tipo not in fc.TIPOS:
        raise ValueError("Indica el NIF que está mal, el correcto (distinto) y el tipo (emitida o recibida).")
    conn = db.get_connection()
    try:
        cur = conn.execute("UPDATE facturas_contables SET tercero_nif = ?, actualizado_en = ? WHERE tenant_id = ? AND cliente_fiscal_id = ? AND tipo = ? AND tercero_nif = ? AND estado IN ('pendiente', 'revisada')",
                           (bien, db.now_iso(), tenant_id, cliente_fiscal_id, tipo, mal))
        auditoria.registrar(tenant_id, usuario_id, "contabilidad.nif_corregido", "cliente_fiscal", cliente_fiscal_id, {"tipo": tipo, "de": mal, "a": bien, "facturas": cur.rowcount}, conn=conn)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
