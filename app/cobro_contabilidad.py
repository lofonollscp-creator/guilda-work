"""Cobro por uso de «Facturas para contabilizar»: tarifas, medición del mes, límite y liquidación mensual para facturar.

El módulo se vende como extra de pago y su uso se cobra según el plan (tier) del despacho. Aquí no se cobra nada solo: se **mide** y se **calcula** lo que corresponde, y el backoffice lo enseña y lo cierra
mes a mes para que alguien lo facture (a mano o con Stripe, más adelante). Sin tarifa aplicable no hay cargo ni límite, que es como funcionaba hasta ahora.

Tarifa = `unidad` (qué se cuenta: facturas `anotadas` en el mes o facturas `exportadas` a a3), `incluidas` (las del plan), `precio_extra_centimos` (por cada una de más) y, solo con `anotadas`, un
`limite_duro` opcional (a partir de él no se pueden anotar más ese mes). Se resuelve por este orden: la del propio despacho, la de su plan y la general. Importes en céntimos de euro, sin IVA."""
from __future__ import annotations

from . import db, facturas_contables as fc

UNIDADES = ("anotadas", "exportadas")
AMBITOS = ("defecto", "plan", "tenant")
ESTADOS = ("abierta", "cerrada", "facturada")
MAX_CENTIMOS = 1_000_000


def _mes(mes: str | None) -> str:
    mes = mes or db.now_iso()[:7]
    if len(mes) != 7 or mes[4] != "-" or not (mes[:4] + mes[5:]).isdigit() or not 1 <= int(mes[5:]) <= 12:
        raise ValueError("El mes debe tener el formato AAAA-MM.")
    return mes


# --- Tarifas ------------------------------------------------------------------------------------------------------------------------------------------

def _validar(ambito: str, referencia_id: int, unidad: str, incluidas, precio_extra_centimos, limite_duro) -> tuple:
    if ambito not in AMBITOS:
        raise ValueError("El ámbito de la tarifa debe ser general, de un plan o de un despacho.")
    if (ambito == "defecto") != (not referencia_id):
        raise ValueError("Indica el plan o el despacho al que se aplica la tarifa.")
    if unidad not in UNIDADES:
        raise ValueError("La unidad debe ser facturas anotadas o facturas exportadas.")
    try:
        incl = int(incluidas or 0)
        precio = int(precio_extra_centimos or 0)
        limite = None if limite_duro in (None, "") else int(limite_duro)
    except (TypeError, ValueError):
        raise ValueError("Las facturas incluidas, el precio y el límite deben ser números.") from None
    if incl < 0 or incl > 10_000_000:
        raise ValueError("Las facturas incluidas deben estar entre 0 y 10.000.000.")
    if not 0 <= precio <= MAX_CENTIMOS:
        raise ValueError("El precio de cada factura de más no es válido.")
    if limite is not None:
        if unidad != "anotadas":
            raise ValueError("El límite solo se puede poner contando facturas anotadas (no se bloquean las exportaciones).")
        if limite < 0 or limite < incl:
            raise ValueError("El límite no puede ser menor que las facturas incluidas.")
    return ambito, int(referencia_id or 0), unidad, incl, precio, limite


def guardar_tarifa(ambito: str, referencia_id: int | None, unidad: str, incluidas, precio_extra_centimos, limite_duro=None) -> dict:
    ambito, ref, unidad, incl, precio, limite = _validar(ambito, referencia_id or 0, unidad, incluidas, precio_extra_centimos, limite_duro)
    conn = db.get_connection()
    try:
        if ambito == "plan" and conn.execute("SELECT id FROM planes_guilda WHERE id = ?", (ref,)).fetchone() is None:
            raise ValueError("Ese plan no existe.")
        if ambito == "tenant" and conn.execute("SELECT id FROM tenants WHERE id = ?", (ref,)).fetchone() is None:
            raise ValueError("Ese despacho no existe.")
        conn.execute("INSERT INTO contabilidad_tarifas (ambito, referencia_id, unidad, incluidas, precio_extra_centimos, limite_duro, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(ambito, referencia_id) DO UPDATE SET unidad = excluded.unidad, incluidas = excluded.incluidas, precio_extra_centimos = excluded.precio_extra_centimos, "
                     "limite_duro = excluded.limite_duro, actualizado_en = excluded.actualizado_en", (ambito, ref, unidad, incl, precio, limite, db.now_iso()))
        conn.commit()
    finally:
        conn.close()
    return {"ambito": ambito, "referencia_id": ref, "unidad": unidad, "incluidas": incl, "precio_extra_centimos": precio, "limite_duro": limite}


def borrar_tarifa(ambito: str, referencia_id: int | None) -> bool:
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM contabilidad_tarifas WHERE ambito = ? AND referencia_id = ?", (ambito, int(referencia_id or 0))).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def listar_tarifas() -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT t.*, CASE t.ambito WHEN 'plan' THEN (SELECT nombre FROM planes_guilda WHERE id = t.referencia_id) WHEN 'tenant' THEN (SELECT nombre FROM tenants WHERE id = t.referencia_id) END AS nombre "
            "FROM contabilidad_tarifas t ORDER BY CASE t.ambito WHEN 'defecto' THEN 0 WHEN 'plan' THEN 1 ELSE 2 END, nombre")]
    finally:
        conn.close()


def tarifa_de(tenant_id: int) -> dict | None:
    """La tarifa que se aplica a un despacho (con `origen`: tenant, plan o defecto), o None si no tiene ninguna."""
    conn = db.get_connection()
    try:
        plan = conn.execute("SELECT plan_id FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        plan_id = plan["plan_id"] if plan else None
        for ambito, ref in (("tenant", tenant_id), ("plan", plan_id or 0), ("defecto", 0)):
            if ambito == "plan" and not plan_id:
                continue
            f = conn.execute("SELECT * FROM contabilidad_tarifas WHERE ambito = ? AND referencia_id = ?", (ambito, ref)).fetchone()
            if f:
                return {**dict(f), "origen": ambito}
    finally:
        conn.close()
    return None


# --- Medición ---------------------------------------------------------------------------------------------------------------------------------------

def _unidades(tenant_id: int, unidad: str, mes: str) -> int:
    u = fc.uso_del_mes(tenant_id, mes)
    return u["exportadas"] if unidad == "exportadas" else u["anotadas"]


def consumo(tenant_id: int, mes: str | None = None) -> dict:
    """Lo consumido por un despacho en un mes y lo que cuesta: `{mes, tarifa, unidad, unidades, incluidas, extra, precio_extra_centimos, importe_centimos, limite_duro, restantes}`."""
    mes = _mes(mes)
    t = tarifa_de(tenant_id)
    unidad = t["unidad"] if t else "anotadas"
    unidades = _unidades(tenant_id, unidad, mes)
    incl = t["incluidas"] if t else 0
    precio = t["precio_extra_centimos"] if t else 0
    extra = max(0, unidades - incl) if t else 0
    limite = t["limite_duro"] if t else None
    return {"mes": mes, "tarifa": t, "unidad": unidad, "unidades": unidades, "incluidas": incl if t else None, "extra": extra, "precio_extra_centimos": precio, "importe_centimos": extra * precio,
            "limite_duro": limite, "restantes": None if limite is None else max(0, limite - unidades)}


def comprobar_cupo(tenant_id: int, nuevas: int = 1, desde_portal: bool = False) -> None:
    """`ValueError` si anotar `nuevas` facturas más superaría el límite mensual del despacho. Sin tarifa o sin límite, no hace nada (ni mide)."""
    t = tarifa_de(tenant_id)
    if t is None or t["limite_duro"] is None or t["unidad"] != "anotadas":
        return
    if _unidades(tenant_id, "anotadas", _mes(None)) + nuevas > t["limite_duro"]:
        if desde_portal:
            raise ValueError("Tu gestoría no puede recibir más facturas este mes por este medio. Avísala para que lo resuelva.")
        raise ValueError(f"Se ha alcanzado el límite de {t['limite_duro']} facturas al mes de este plan. Para anotar más, amplía el plan o espera al mes que viene.")


# --- Liquidación mensual -------------------------------------------------------------------------------------------------------------------------

def _con_modulo() -> list[tuple[int, str]]:
    from . import verticales
    conn = db.get_connection()
    try:
        filas = [(r["id"], r["nombre"]) for r in conn.execute("SELECT id, nombre FROM tenants ORDER BY nombre")]
    finally:
        conn.close()
    return [(i, n) for i, n in filas if verticales.esta_activo(i, "contabilizacion")]


def liquidar(mes: str | None = None) -> list[dict]:
    """Calcula (o recalcula) la liquidación del mes de cada despacho con el módulo activo. Las ya cerradas o facturadas no se tocan: son una foto de lo que se cobró. Devuelve todas, con su estado."""
    mes = _mes(mes)
    ahora = db.now_iso()
    calculos = [(tid, consumo(tid, mes)) for tid, _nombre in _con_modulo()]       # se mide antes de abrir la conexión de escritura
    conn = db.get_connection()
    try:
        for tid, c in calculos:
            actual = conn.execute("SELECT estado FROM contabilidad_liquidaciones WHERE tenant_id = ? AND mes = ?", (tid, mes)).fetchone()
            if actual is not None and actual["estado"] != "abierta":
                continue
            if c["tarifa"] is None and c["unidades"] == 0 and actual is None:
                continue
            conn.execute("INSERT INTO contabilidad_liquidaciones (tenant_id, mes, unidad, unidades, incluidas, extra, precio_extra_centimos, importe_centimos, estado, calculada_en) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'abierta', ?) ON CONFLICT(tenant_id, mes) DO UPDATE SET unidad = excluded.unidad, unidades = excluded.unidades, incluidas = excluded.incluidas, "
                         "extra = excluded.extra, precio_extra_centimos = excluded.precio_extra_centimos, importe_centimos = excluded.importe_centimos, calculada_en = excluded.calculada_en",
                         (tid, mes, c["unidad"], c["unidades"], c["incluidas"], c["extra"], c["precio_extra_centimos"], c["importe_centimos"], ahora))
        conn.commit()
    finally:
        conn.close()
    return listar_liquidaciones(mes)


def vista_del_mes(mes: str | None = None) -> list[dict]:
    """Una fila por despacho con el módulo activo: lo guardado si la liquidación está cerrada o facturada (es una foto) y, si no, lo que llevan ahora. `estado`: sin calcular · abierta · cerrada · facturada."""
    mes = _mes(mes)
    guardadas = {l["tenant_id"]: l for l in listar_liquidaciones(mes)}
    filas = []
    for tid, nombre in _con_modulo():
        l = guardadas.get(tid)
        if l is not None and l["estado"] != "abierta":
            filas.append({"tenant_id": tid, "tenant": nombre, "unidad": l["unidad"], "unidades": l["unidades"], "incluidas": l["incluidas"], "extra": l["extra"],
                          "precio_extra_centimos": l["precio_extra_centimos"], "importe_centimos": l["importe_centimos"], "estado": l["estado"], "limite_duro": None, "origen": None})
            continue
        c = consumo(tid, mes)
        filas.append({"tenant_id": tid, "tenant": nombre, "unidad": c["unidad"], "unidades": c["unidades"], "incluidas": c["incluidas"], "extra": c["extra"],
                      "precio_extra_centimos": c["precio_extra_centimos"], "importe_centimos": c["importe_centimos"], "estado": "abierta" if l else "sin calcular",
                      "limite_duro": c["limite_duro"], "origen": c["tarifa"]["origen"] if c["tarifa"] else None})
    return filas


def euros_a_centimos(texto) -> int:
    """«0,10», «0.1» o «1.234,56» → céntimos. `ValueError` si no es un importe válido."""
    from decimal import Decimal, InvalidOperation
    t = str(texto or "").strip().replace("€", "").replace(" ", "")
    if not t:
        return 0
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        v = Decimal(t)
    except InvalidOperation:
        raise ValueError("El precio no es un importe válido: escríbelo como 0,10.") from None
    if v < 0 or v > MAX_CENTIMOS // 100:
        raise ValueError("El precio no es válido.")
    return int((v * 100).quantize(Decimal("1")))


def listar_liquidaciones(mes: str | None = None) -> list[dict]:
    mes = _mes(mes)
    conn = db.get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT l.*, t.nombre AS tenant FROM contabilidad_liquidaciones l JOIN tenants t ON t.id = l.tenant_id WHERE l.mes = ? ORDER BY t.nombre", (mes,))]
    finally:
        conn.close()


def cambiar_estado_liquidacion(tenant_id: int, mes: str, estado: str) -> None:
    """Abierta → cerrada (se congela) → facturada. Se puede volver atrás (reabrir) mientras no se haya facturado."""
    mes = _mes(mes)
    if estado not in ESTADOS:
        raise ValueError("Estado de liquidación no válido.")
    conn = db.get_connection()
    try:
        actual = conn.execute("SELECT estado FROM contabilidad_liquidaciones WHERE tenant_id = ? AND mes = ?", (tenant_id, mes)).fetchone()
        if actual is None:
            raise ValueError("Esa liquidación no existe: calcúlala primero.")
        if actual["estado"] == "facturada" and estado != "facturada":
            raise ValueError("Una liquidación ya facturada no se puede reabrir.")
        conn.execute("UPDATE contabilidad_liquidaciones SET estado = ?, cerrada_en = CASE WHEN ? = 'abierta' THEN NULL ELSE COALESCE(cerrada_en, ?) END WHERE tenant_id = ? AND mes = ?",
                     (estado, estado, db.now_iso(), tenant_id, mes))
        conn.commit()
    finally:
        conn.close()


def cerrar_mes(mes: str) -> int:
    """Congela todas las liquidaciones abiertas del mes (recalculándolas antes por última vez). Devuelve cuántas."""
    filas = liquidar(mes)
    n = 0
    for f in filas:
        if f["estado"] == "abierta":
            cambiar_estado_liquidacion(f["tenant_id"], mes, "cerrada")
            n += 1
    return n


def csv_del_mes(mes: str) -> str:
    """Las liquidaciones del mes en CSV (separador «;» y coma decimal, para abrirlo en una hoja de cálculo en español)."""
    def eur(c): return f"{c / 100:.2f}".replace(".", ",")
    lineas = ["Despacho;Mes;Unidad;Facturas;Incluidas;De más;Precio por factura de más;Importe (sin IVA);Estado"]
    for f in listar_liquidaciones(mes):
        nombre = str(f["tenant"]).replace(";", ",").replace("\n", " ").replace('"', "'")
        if nombre[:1] in "=+-@":                    # evita que una hoja de cálculo lo interprete como fórmula
            nombre = "'" + nombre
        lineas.append(";".join([nombre, f["mes"], f["unidad"], str(f["unidades"]), str(f["incluidas"] if f["incluidas"] is not None else ""), str(f["extra"]), eur(f["precio_extra_centimos"]),
                                eur(f["importe_centimos"]), f["estado"]]))
    return "\r\n".join(lineas) + "\r\n"


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM contabilidad_liquidaciones WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM contabilidad_tarifas WHERE ambito = 'tenant' AND referencia_id = ?", (tenant_id,))
