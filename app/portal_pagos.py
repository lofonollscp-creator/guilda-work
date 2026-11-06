"""Honorarios en el portal: el cliente ve el importe que su gestoría ha confirmado por cada modelo (si el despacho lo activa en su ficha) y puede pagarlo con tarjeta en la página segura de Stripe.

**El importe lo pone el despacho** (honorarios confirmados o facturados de ese vencimiento, `app/honorarios.py`): el cliente no escribe ninguna cifra. La sesión de pago se crea en el momento de pulsar «Pagar» (así no caduca como un
enlace enviado por correo) y lleva el `vencimiento_id`: el webhook de Stripe que ya existe registra el cobro. Guilda Work nunca ve datos de tarjeta."""
from __future__ import annotations

from . import db, honorarios, stripe_pagos


def _pagado(vencimiento_id: int) -> int:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COALESCE(SUM(importe_centimos), 0) FROM vencimientos_fiscales_pagos WHERE vencimiento_id = ?", (vencimiento_id,)).fetchone()[0]
    finally:
        conn.close()


def _stripe_del_despacho(tenant_id: int) -> str | None:
    t = db.obtener_tenant(tenant_id)
    return t["stripe_account_id"] if t and stripe_pagos.configurado() else None


def cobros(cliente: dict, vencimientos) -> dict[int, dict]:
    """{vencimiento_id: {importe, pagado, puede_pagar, concepto}} de los modelos con honorarios confirmados. Vacío si el despacho no le ha activado los honorarios."""
    if not cliente["portal_honorarios"]:
        return {}
    pagos_ok = _stripe_del_despacho(cliente["tenant_id"]) is not None
    res = {}
    for v in vencimientos:
        a = honorarios.aplicado_de(cliente["tenant_id"], v["id"])
        if not a or a["estado"] == "anulado" or not a["importe_centimos"]:
            continue
        pagado = _pagado(v["id"]) >= a["importe_centimos"]
        res[v["id"]] = {"importe": a["importe_centimos"], "concepto": a["concepto"], "estado": a["estado"], "referencia": a["referencia_factura"] or "", "pagado": pagado, "puede_pagar": pagos_ok and not pagado}
    return res


def crear_pago(cliente: dict, vencimiento_id: int, url_exito: str, url_cancelar: str) -> str:
    """La URL de Checkout para pagar los honorarios de ese modelo. `ValueError` con un texto legible si no se puede."""
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT id, modelo, periodo FROM vencimientos_fiscales WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND papelera_en IS NULL", (vencimiento_id, cliente["tenant_id"], cliente["id"])).fetchone()
    finally:
        conn.close()
    if v is None:
        raise ValueError("Ese modelo no existe.")
    c = cobros(cliente, [dict(v)]).get(v["id"])
    if c is None:
        raise ValueError("No hay nada que pagar por este modelo.")
    if c["pagado"]:
        raise ValueError("Este pago ya está hecho.")
    cuenta = _stripe_del_despacho(cliente["tenant_id"])
    if cuenta is None:
        raise ValueError("Tu gestoría todavía no tiene activados los pagos con tarjeta.")
    try:
        return stripe_pagos.crear_sesion_pago(cuenta, c["importe"], f"{c['concepto']} — {cliente['nombre']}"[:120], url_exito, url_cancelar, metadata={"vencimiento_id": v["id"]})
    except stripe_pagos.ErrorStripe:
        raise ValueError("No hemos podido abrir el pago ahora mismo. Inténtalo de nuevo en unos minutos.") from None


def del_anio(cliente: dict, anio: int) -> list[dict]:
    """Los honorarios confirmados o facturados de los modelos de ese año (por la fecha límite del modelo), con si están pagados. Vacío si el despacho no le ha activado los honorarios."""
    if not cliente["portal_honorarios"]:
        return []
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute("SELECT h.vencimiento_id, h.concepto, h.importe_centimos, h.estado, h.referencia_factura, v.modelo, v.periodo, v.fecha_limite FROM honorarios_aplicados h JOIN vencimientos_fiscales v "
                                               "ON v.id = h.vencimiento_id WHERE h.tenant_id = ? AND h.cliente_fiscal_id = ? AND h.estado != 'anulado' AND v.papelera_en IS NULL ORDER BY v.fecha_limite, h.id",
                                               (cliente["tenant_id"], cliente["id"]))]
    finally:
        conn.close()
    res = []
    for f in filas:
        if (f["fecha_limite"] or "")[:4] != str(anio):
            continue
        res.append({"vencimiento_id": f["vencimiento_id"], "modelo": f["modelo"], "periodo": f["periodo"], "concepto": f["concepto"], "importe": f["importe_centimos"], "estado": f["estado"],
                    "referencia": f["referencia_factura"] or "", "pagado": _pagado(f["vencimiento_id"]) >= f["importe_centimos"]})
    return res
