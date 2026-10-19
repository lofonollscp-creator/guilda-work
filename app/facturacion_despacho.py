"""Facturación conectada al trabajo del despacho: facturar desde un expediente, ver el estado de cobro de un cliente y detectar las facturas vencidas sin cobrar.

La facturación vive en FacturaScripts (un contenedor por despacho, ver app/facturascripts.py). Aquí no se duplica nada de ella: se crea la factura allí, se guarda solo la relación expediente → factura
(`facturacion_expedientes`) y el estado (pagada, vencida) se lee siempre de FacturaScripts, con una caché corta para no llamarla en cada pantalla. Si FacturaScripts no está o falla, todo lo demás sigue
funcionando y esta parte se calla."""
from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation

from . import auditoria, db, facturascripts, nucleo

CACHE_SEGUNDOS = 120
MAX_IMPORTE = Decimal("1000000")
MAX_FACTURAS_LEIDAS = 500

ESQUEMA = """
CREATE TABLE IF NOT EXISTS facturacion_expedientes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    idfactura TEXT,
    codigo TEXT,
    concepto TEXT NOT NULL,
    base_centimos INTEGER NOT NULL,
    creado_por INTEGER,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facturacion_expedientes ON facturacion_expedientes(tenant_id, expediente_id);
"""

_cache: dict[tuple, tuple[float, list]] = {}


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def configurada(tenant) -> bool:
    return bool(tenant and tenant["facturascripts_url"] and tenant["facturascripts_api_key"])


def _facturas(tenant_id: int, codcliente: str | None = None, limite: int = MAX_FACTURAS_LEIDAS, usar_cache: bool = True) -> list[dict]:
    """Facturas de cliente de FacturaScripts (de un cliente o todas), con caché corta. `[]` si no está configurada o falla."""
    clave = (tenant_id, codcliente, limite)
    ahora = time.monotonic()
    if usar_cache and clave in _cache and ahora - _cache[clave][0] < CACHE_SEGUNDOS:
        return _cache[clave][1]
    tenant = db.obtener_tenant(tenant_id)
    if not configurada(tenant):
        return []
    try:
        res = facturascripts.listar_facturas(tenant["facturascripts_url"], tenant["facturascripts_api_key"], cliente_codigo=codcliente, limite=limite)
    except facturascripts.ErrorFacturaScripts:
        return []
    _cache[clave] = (ahora, res)
    return res


def olvidar_cache(tenant_id: int) -> None:
    for k in [k for k in _cache if k[0] == tenant_id]:
        _cache.pop(k, None)


def _eur(centimos: int) -> str:
    """Céntimos → «1.234,56 €»."""
    return f"{centimos / 100:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".") + " €"


def _euros(valor) -> Decimal:
    try:
        return Decimal(str(valor if valor not in (None, "") else 0))
    except InvalidOperation:
        return Decimal(0)


def estado_de(f: dict) -> str:
    """`pagada`, `vencida` (sin cobrar y pasada de fecha según FacturaScripts) o `pendiente`."""
    if f.get("pagada") in (True, 1, "1", "true"):
        return "pagada"
    return "vencida" if f.get("vencida") in (True, 1, "1", "true") else "pendiente"


def resumen_cobro(facturas: list[dict]) -> dict:
    """Totales de un conjunto de facturas: facturado, cobrado, pendiente (incluye lo vencido) y vencido, en euros, y cuántas hay vencidas."""
    facturado = cobrado = vencido = Decimal(0)
    n_vencidas = 0
    for f in facturas:
        total = _euros(f.get("total"))
        facturado += total
        est = estado_de(f)
        if est == "pagada":
            cobrado += total
        elif est == "vencida":
            vencido += total
            n_vencidas += 1
    return {"facturado": facturado, "cobrado": cobrado, "pendiente": facturado - cobrado, "vencido": vencido, "n_vencidas": n_vencidas, "n": len(facturas)}


def cobro_de_cliente(tenant_id: int, cliente_fiscal) -> dict | None:
    """El estado de cobro de un cliente fiscal ya vinculado con FacturaScripts (None si no lo está): `{resumen, facturas}`."""
    if cliente_fiscal is None or not cliente_fiscal["facturascripts_cliente_codigo"]:
        return None
    facturas = _facturas(tenant_id, cliente_fiscal["facturascripts_cliente_codigo"])
    return {"resumen": resumen_cobro(facturas), "facturas": [dict(f, estado=estado_de(f)) for f in facturas[:10]]}


# --- Facturar desde un expediente ---------------------------------------------------------------------------------------------------------------------

def importe_valido(texto) -> Decimal:
    """«1234,56», «1.234,56» o «1234.56» → Decimal positivo (base imponible, sin IVA). `ValueError` con un mensaje legible si no vale."""
    t = str(texto or "").strip().replace("€", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", t):
        t = t.replace(".", "").replace(",", ".")
    elif "," in t and "." not in t:
        t = t.replace(",", ".")
    try:
        v = Decimal(t).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError("El importe no es válido: escríbelo como 1.234,56.") from None
    if v <= 0:
        raise ValueError("El importe debe ser mayor que cero.")
    if v > MAX_IMPORTE:
        raise ValueError("El importe es demasiado grande.")
    return v


def _cliente_fiscal_del_expediente(tenant_id: int, expediente) -> dict | None:
    c = nucleo.obtener_cliente(tenant_id, expediente["cliente_id"])
    if c is None or not c["cliente_fiscal_id"]:
        return None
    return db.obtener_cliente_fiscal(tenant_id, c["cliente_fiscal_id"])


def puede_facturar(tenant_id: int, usuario_id: int, supervisor: bool, expediente) -> bool:
    """La dirección y la coordinación, o quien lleva el expediente."""
    return bool(supervisor or expediente["responsable_id"] == usuario_id or (expediente["responsable_id"] is None and expediente["creado_por"] == usuario_id))


def situacion(tenant_id: int, usuario_id: int, supervisor: bool, expediente) -> dict:
    """Lo que necesita el panel de facturación de un expediente: si se puede facturar y, si no, por qué."""
    tenant = db.obtener_tenant(tenant_id)
    if not configurada(tenant):
        return {"disponible": False, "motivo": None}            # sin FacturaScripts no se enseña nada
    fiscal = _cliente_fiscal_del_expediente(tenant_id, expediente)
    if not puede_facturar(tenant_id, usuario_id, supervisor, expediente):
        return {"disponible": True, "puede": False, "motivo": "permiso", "fiscal": fiscal}
    if fiscal is None:
        return {"disponible": True, "puede": False, "motivo": "sin_gestion_fiscal", "fiscal": None}
    if not fiscal["facturascripts_cliente_codigo"]:
        return {"disponible": True, "puede": False, "motivo": "sin_vincular", "fiscal": fiscal}
    return {"disponible": True, "puede": True, "motivo": None, "fiscal": fiscal}


def facturar_expediente(tenant_id: int, usuario_id: int, supervisor: bool, expediente_id: int, concepto: str, importe) -> dict:
    """Crea en FacturaScripts una factura de una línea (base imponible `importe`, el IVA lo pone FacturaScripts) para el cliente del expediente y deja la relación y una anotación en el expediente.
    `ValueError` si algo no vale (sin permiso, cliente sin vincular, importe…); `ErrorFacturaScripts` si FacturaScripts falla (entonces no se guarda nada)."""
    exp = nucleo.obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor)
    if exp is None:
        raise ValueError("Expediente no encontrado.")
    estado = situacion(tenant_id, usuario_id, supervisor, exp)
    if not estado["disponible"]:
        raise ValueError("Este despacho no tiene FacturaScripts configurado.")
    if not estado["puede"]:
        raise ValueError({"permiso": "Solo la dirección, la coordinación o quien lleva el expediente puede facturarlo.",
                          "sin_gestion_fiscal": "El cliente no tiene gestión fiscal activada: actívala en su ficha para poder vincularlo con FacturaScripts.",
                          "sin_vincular": "Vincula primero al cliente con FacturaScripts desde su ficha fiscal."}[estado["motivo"]])
    concepto = (concepto or "").strip()
    if not concepto:
        raise ValueError("Escribe el concepto de la factura.")
    if len(concepto) > 200:
        raise ValueError("El concepto es demasiado largo (máx. 200 caracteres).")
    base = importe_valido(importe)
    tenant = db.obtener_tenant(tenant_id)
    creada = facturascripts.crear_factura(tenant["facturascripts_url"], tenant["facturascripts_api_key"], estado["fiscal"]["facturascripts_cliente_codigo"],
                                          [{"descripcion": concepto, "cantidad": 1, "precio": float(base)}])
    idfactura = str(creada.get("idfactura") or "") or None
    codigo = None
    try:
        detalle = facturascripts.obtener_factura(tenant["facturascripts_url"], tenant["facturascripts_api_key"], idfactura) if idfactura else None
        codigo = (detalle or {}).get("codigo")
    except facturascripts.ErrorFacturaScripts:
        pass                                                   # la factura ya existe: no se pierde la relación por no poder leer su código
    centimos = int(base * 100)
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO facturacion_expedientes (tenant_id, expediente_id, idfactura, codigo, concepto, base_centimos, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, expediente_id, idfactura, codigo, concepto, centimos, usuario_id, db.now_iso()))
        nucleo._evento(conn, expediente_id, "factura", f"Factura {codigo or ('#' + idfactura if idfactura else '')} creada: {concepto} ({_eur(centimos)} + IVA)".replace("  ", " "), usuario_id)
        auditoria.registrar(tenant_id, usuario_id, "factura.creada", "expediente", expediente_id, {"idfactura": idfactura, "codigo": codigo, "base": str(base), "concepto": concepto}, conn=conn)
        conn.commit()
        registro = cur.lastrowid
    finally:
        conn.close()
    olvidar_cache(tenant_id)
    return {"id": registro, "idfactura": idfactura, "codigo": codigo, "base": base}


MAX_PARTES_POR_FACTURA = 60


def horas_sin_facturar(tenant_id: int, expediente_id: int) -> list[dict]:
    """Los partes de horas facturables del expediente que aún no van en ninguna factura, con su importe a la tarifa con la que se registraron (0 si no tenían tarifa)."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT p.id, p.fecha, p.descripcion, p.segundos, p.tarifa_hora_centimos, COALESCE(pr.nombre_mostrado, u.email) AS usuario FROM partes_tiempo p "
                             "JOIN usuarios u ON u.id = p.usuario_id LEFT JOIN usuario_perfil pr ON pr.usuario_id = p.usuario_id "
                             "WHERE p.tenant_id = ? AND p.expediente_id = ? AND p.facturable = 1 AND p.facturado_en IS NULL AND p.papelera_en IS NULL ORDER BY p.fecha, p.id LIMIT 300",
                             (tenant_id, expediente_id)).fetchall()
    finally:
        conn.close()
    return [dict(f, importe_centimos=nucleo.importe_centimos(f["segundos"], f["tarifa_hora_centimos"])) for f in filas]


def _linea_de_horas(p: dict) -> dict:
    h, m = divmod(p["segundos"] // 60, 60)
    return {"descripcion": f"{p['fecha']} · {p['descripcion'][:120]} ({h}:{m:02d} h × {p['tarifa_hora_centimos'] / 100:.2f} €/h)", "cantidad": 1, "precio": p["importe_centimos"] / 100}


def facturar_horas(tenant_id: int, usuario_id: int, supervisor: bool, expediente_id: int, parte_ids: list[int]) -> dict:
    """Factura en FacturaScripts las horas elegidas del expediente (una línea por parte, a la tarifa con la que se registró) y las marca como facturadas. Las horas se reservan antes de crear la factura
    (dos envíos a la vez no las facturan dos veces) y se liberan si FacturaScripts falla. `ValueError` si algo no vale; `ErrorFacturaScripts` si FacturaScripts falla (entonces no queda nada marcado)."""
    exp = nucleo.obtener_expediente(tenant_id, expediente_id, usuario_id, supervisor)
    if exp is None:
        raise ValueError("Expediente no encontrado.")
    estado = situacion(tenant_id, usuario_id, supervisor, exp)
    if not estado["disponible"]:
        raise ValueError("Este despacho no tiene FacturaScripts configurado.")
    if not estado["puede"]:
        raise ValueError({"permiso": "Solo la dirección, la coordinación o quien lleva el expediente puede facturarlo.",
                          "sin_gestion_fiscal": "El cliente no tiene gestión fiscal activada: actívala en su ficha para poder vincularlo con FacturaScripts.",
                          "sin_vincular": "Vincula primero al cliente con FacturaScripts desde su ficha fiscal."}[estado["motivo"]])
    ids = sorted({int(i) for i in parte_ids})
    if not ids:
        raise ValueError("Elige al menos un parte de horas.")
    if len(ids) > MAX_PARTES_POR_FACTURA:
        raise ValueError(f"Como máximo {MAX_PARTES_POR_FACTURA} partes por factura.")
    libres = {p["id"]: p for p in horas_sin_facturar(tenant_id, expediente_id)}
    if any(i not in libres for i in ids):
        raise ValueError("Alguna de esas horas ya se ha facturado o no es de este expediente.")
    partes = [libres[i] for i in ids]
    if any(p["importe_centimos"] <= 0 for p in partes):
        raise ValueError("Hay horas sin tarifa: fija la tarifa por hora de quien las registró o quítalas de la selección.")
    hoy = db.now_iso()[:10]
    marcas = ",".join("?" * len(ids))
    conn = db.get_connection()
    try:       # reserva atómica: solo sigue quien consigue marcarlas todas
        cur = conn.execute(f"UPDATE partes_tiempo SET facturado_en = ? WHERE tenant_id = ? AND expediente_id = ? AND facturable = 1 AND facturado_en IS NULL AND papelera_en IS NULL AND id IN ({marcas})",
                           [hoy, tenant_id, expediente_id, *ids])
        if cur.rowcount != len(ids):
            conn.rollback()
            raise ValueError("Alguna de esas horas ya se ha facturado.")
        conn.commit()
    finally:
        conn.close()
    tenant = db.obtener_tenant(tenant_id)
    try:
        creada = facturascripts.crear_factura(tenant["facturascripts_url"], tenant["facturascripts_api_key"], estado["fiscal"]["facturascripts_cliente_codigo"], [_linea_de_horas(p) for p in partes])
    except Exception:
        conn = db.get_connection()
        try:
            conn.execute(f"UPDATE partes_tiempo SET facturado_en = NULL WHERE tenant_id = ? AND id IN ({marcas})", [tenant_id, *ids])
            conn.commit()
        finally:
            conn.close()
        raise
    idfactura = str(creada.get("idfactura") or "") or None
    codigo = None
    try:
        detalle = facturascripts.obtener_factura(tenant["facturascripts_url"], tenant["facturascripts_api_key"], idfactura) if idfactura else None
        codigo = (detalle or {}).get("codigo")
    except facturascripts.ErrorFacturaScripts:
        pass
    centimos = sum(p["importe_centimos"] for p in partes)
    segundos = sum(p["segundos"] for p in partes)
    concepto = f"Horas ({len(partes)} partes, {segundos // 3600}:{segundos % 3600 // 60:02d} h)"
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO facturacion_expedientes (tenant_id, expediente_id, idfactura, codigo, concepto, base_centimos, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, expediente_id, idfactura, codigo, concepto, centimos, usuario_id, db.now_iso()))
        nucleo._evento(conn, expediente_id, "factura", f"Factura {codigo or ('#' + idfactura if idfactura else '')} creada con horas: {concepto} ({_eur(centimos)} + IVA)".replace("  ", " "), usuario_id)
        auditoria.registrar(tenant_id, usuario_id, "factura.horas", "expediente", expediente_id, {"idfactura": idfactura, "codigo": codigo, "partes": ids, "base_centimos": centimos}, conn=conn)
        conn.commit()
        registro = cur.lastrowid
    finally:
        conn.close()
    olvidar_cache(tenant_id)
    return {"id": registro, "idfactura": idfactura, "codigo": codigo, "base_centimos": centimos, "partes": len(partes)}


def facturas_del_expediente(tenant_id: int, expediente_id: int) -> list[dict]:
    """Las facturas creadas desde el expediente, con su estado de cobro leído de FacturaScripts (`estado` es None si no se ha podido consultar)."""
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute("SELECT * FROM facturacion_expedientes WHERE tenant_id = ? AND expediente_id = ? ORDER BY id DESC", (tenant_id, expediente_id))]
    finally:
        conn.close()
    if not filas:
        return []
    por_id = {str(f.get("idfactura")): f for f in _facturas(tenant_id)}
    for f in filas:
        fs = por_id.get(str(f["idfactura"])) if f["idfactura"] else None
        f["estado"] = estado_de(fs) if fs else None
        f["codigo"] = f["codigo"] or (fs or {}).get("codigo")
        f["total"] = (fs or {}).get("total")
        f["base"] = _eur(f["base_centimos"])
    return filas


# --- Facturas vencidas sin cobrar ----------------------------------------------------------------------------------------------------------------------

def vencidas_sin_cobrar(tenant_id: int, usuario_id: int, supervisor: bool) -> list[dict]:
    """Facturas vencidas y sin cobrar que la persona debe mirar: todas si supervisa; si no, solo las de los expedientes que lleva. Cada una con el enlace a donde resolverla."""
    vencidas = [f for f in _facturas(tenant_id) if estado_de(f) == "vencida"]
    if not vencidas:
        return []
    conn = db.get_connection()
    try:
        mapa = {str(f["idfactura"]): f["expediente_id"] for f in conn.execute("SELECT idfactura, expediente_id FROM facturacion_expedientes WHERE tenant_id = ? AND idfactura IS NOT NULL", (tenant_id,))}
        fiscales = {f["facturascripts_cliente_codigo"]: f["cliente_id"] for f in conn.execute(
            "SELECT facturascripts_cliente_codigo, cliente_id FROM clientes_fiscales WHERE tenant_id = ? AND facturascripts_cliente_codigo IS NOT NULL AND papelera_en IS NULL", (tenant_id,))}
        llevo = {f["id"] for f in conn.execute("SELECT id FROM expedientes WHERE tenant_id = ? AND (responsable_id = ? OR (responsable_id IS NULL AND creado_por = ?))", (tenant_id, usuario_id, usuario_id))}
    finally:
        conn.close()
    res = []
    for f in vencidas:
        exp_id = mapa.get(str(f.get("idfactura")))
        if not supervisor and exp_id not in llevo:
            continue
        res.append({"codigo": f.get("codigo") or f.get("numero") or f"#{f.get('idfactura')}", "cliente": f.get("nombrecliente"), "total": f.get("total"), "fecha": f.get("fecha"),
                    "expediente_id": exp_id, "cliente_id": fiscales.get(f.get("codcliente"))})
    return res
