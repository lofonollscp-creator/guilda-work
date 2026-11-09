"""«Mis ventas»: el cliente emite sus facturas desde el portal y las hace FacturaScripts (la instancia de su gestoría), a nombre de su propia empresa dentro de ella. Sin Veri*Factu por parte de Guilda Work: la factura la crea,
numera y guarda FacturaScripts, que es quien cumple lo que le toque; aquí solo se pide y se enseña.

Está **apagado por cliente**: la gestoría lo enciende en su ficha y le indica la empresa de FacturaScripts (`facturascripts_idempresa`) y, si quiere, la serie. Cada cliente solo ve y usa **sus** clientes (se guardan aquí con su
código de FacturaScripts) y **sus** facturas. El IVA lo aplica FacturaScripts según su configuración, igual que en las facturas de honorarios; el PDF de aquí es una copia informativa hecha con los datos guardados, y el
documento original está en FacturaScripts."""
from __future__ import annotations

import io
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from . import db, facturacion_despacho as fd, facturascripts

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_ventas_clientes (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    codcliente TEXT NOT NULL,
    nombre TEXT NOT NULL,
    nif TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL,
    UNIQUE (tenant_id, cliente_fiscal_id, codcliente)
);
CREATE TABLE IF NOT EXISTS portal_ventas_facturas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    venta_cliente_id INTEGER NOT NULL,
    idfactura TEXT NOT NULL,
    codigo TEXT NOT NULL DEFAULT '',
    fecha TEXT NOT NULL,
    lineas TEXT NOT NULL,
    neto_centimos INTEGER NOT NULL DEFAULT 0,
    total_centimos INTEGER NOT NULL DEFAULT 0,
    creada_por TEXT NOT NULL DEFAULT '',
    creada_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portal_ventas_facturas ON portal_ventas_facturas(tenant_id, cliente_fiscal_id, creada_en);
"""
MAX_LINEAS = 20
MAX_CLIENTES = 500
MAX_IMPORTE = Decimal("1000000")


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def activa_para(cliente) -> bool:
    """¿Puede este cliente facturar desde el portal? Encendido en su ficha, con empresa indicada y FacturaScripts configurado en su despacho."""
    if cliente is None or not cliente["ventas_portal"] or not cliente["facturascripts_idempresa"]:
        return False
    return fd.configurada(db.obtener_tenant(cliente["tenant_id"]))


def _tenant(cliente):
    return db.obtener_tenant(cliente["tenant_id"])


def clientes(cliente) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, codcliente, nombre, nif, email FROM portal_ventas_clientes WHERE tenant_id = ? AND cliente_fiscal_id = ? ORDER BY nombre", (cliente["tenant_id"], cliente["id"])).fetchall()]
    finally:
        conn.close()


def anadir_cliente(cliente, nombre: str, nif: str, email: str = "") -> int:
    """Da de alta a un cliente del cliente en FacturaScripts y lo apunta como suyo. `ValueError` con un mensaje legible si falta algo o no se pudo."""
    from . import facturas_contables as fc
    nombre, email = " ".join((nombre or "").split())[:120], (email or "").strip()[:120]
    nif = fc._nif(nif)
    if not nombre or not nif:
        raise ValueError("Indica el nombre y el NIF de tu cliente.")
    if "@" not in email and email:
        raise ValueError("El correo no es válido.")
    if not activa_para(cliente):
        raise ValueError("Facturar desde el portal no está activado para tu cuenta.")
    if len(clientes(cliente)) >= MAX_CLIENTES:
        raise ValueError("Has llegado al máximo de clientes.")
    t = _tenant(cliente)
    try:
        creado = facturascripts.crear_cliente(t["facturascripts_url"], t["facturascripts_api_key"], nombre, nif=nif, email=email)
    except facturascripts.ErrorFacturaScripts:
        raise ValueError("No se ha podido dar de alta al cliente ahora mismo. Inténtalo de nuevo en unos minutos.") from None
    cod = str(creado.get("codcliente") or "")
    if not cod:
        raise ValueError("No se ha podido dar de alta al cliente.")
    conn = db.get_connection()
    try:
        ya = conn.execute("SELECT id FROM portal_ventas_clientes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND codcliente = ?", (cliente["tenant_id"], cliente["id"], cod)).fetchone()
        if ya:
            return ya["id"]
        cur = conn.execute("INSERT INTO portal_ventas_clientes (tenant_id, cliente_fiscal_id, codcliente, nombre, nif, email, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], cod, nombre, nif, email, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _numero(valor, campo: str = "") -> Decimal:
    try:
        n = Decimal(str(valor).replace(",", ".").strip())
    except (InvalidOperation, AttributeError):
        raise ValueError("Escribe un número válido en la cantidad y el precio.") from None
    return n


def lineas_validas(formulario) -> list[dict]:
    """Las líneas escritas en el formulario (`descripcion_i`, `cantidad_i`, `precio_i`), sin las vacías. `ValueError` con un mensaje legible si no vale."""
    res = []
    for i in range(MAX_LINEAS):
        d = " ".join(str(formulario.get(f"descripcion_{i}", "")).split())[:200]
        c, p = str(formulario.get(f"cantidad_{i}", "")).strip(), str(formulario.get(f"precio_{i}", "")).strip()
        if not d and not c and not p:
            continue
        if not d or not p:
            raise ValueError("Cada línea necesita una descripción y un precio.")
        cant, precio = _numero(c or "1", "Cantidad"), _numero(p, "Precio")
        if cant <= 0 or precio <= 0 or cant * precio > MAX_IMPORTE or cant > 100000:
            raise ValueError("La cantidad y el precio deben ser positivos y razonables.")
        res.append({"descripcion": d, "cantidad": float(cant), "precio": float(precio)})
    if not res:
        raise ValueError("Añade al menos una línea.")
    return res


def emitir(cliente, venta_cliente_id: int, lineas: list[dict], quien: str, fecha: str | None = None) -> dict:
    """Pide a FacturaScripts la factura a nombre de la empresa del cliente y la guarda. Devuelve {id, idfactura, codigo}. `ValueError` si no se puede (mensaje legible)."""
    if not activa_para(cliente):
        raise ValueError("Facturar desde el portal no está activado para tu cuenta.")
    conn = db.get_connection()
    try:
        c = conn.execute("SELECT codcliente FROM portal_ventas_clientes WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ?", (venta_cliente_id, cliente["tenant_id"], cliente["id"])).fetchone()
    finally:
        conn.close()
    if c is None:
        raise ValueError("Elige uno de tus clientes.")
    try:
        f = date.fromisoformat(fecha).isoformat() if fecha else date.today().isoformat()
    except ValueError:
        raise ValueError("Escribe una fecha válida.") from None
    t = _tenant(cliente)
    try:
        creada = facturascripts.crear_factura(t["facturascripts_url"], t["facturascripts_api_key"], c["codcliente"], lineas,
                                              extra={"idempresa": cliente["facturascripts_idempresa"], "codserie": cliente["facturascripts_serie"], "fecha": f})
    except facturascripts.ErrorFacturaScripts:
        raise ValueError("No se ha podido emitir la factura ahora mismo. No se ha creado nada: inténtalo de nuevo en unos minutos.") from None
    idfactura = str(creada.get("idfactura") or "")
    if not idfactura:
        raise ValueError("FacturaScripts no ha confirmado la factura. Avisa a tu gestoría antes de volver a intentarlo.")
    codigo, neto, total = "", 0, 0
    try:
        det = facturascripts.obtener_factura(t["facturascripts_url"], t["facturascripts_api_key"], idfactura) or {}
        codigo, neto, total = str(det.get("codigo") or ""), round(float(det.get("neto") or 0) * 100), round(float(det.get("total") or 0) * 100)
    except (facturascripts.ErrorFacturaScripts, TypeError, ValueError):
        neto = round(sum(x["cantidad"] * x["precio"] for x in lineas) * 100)          # la factura ya existe: no se pierde por no poder leer su detalle
        total = neto
    fd.olvidar_cache(cliente["tenant_id"])
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO portal_ventas_facturas (tenant_id, cliente_fiscal_id, venta_cliente_id, idfactura, codigo, fecha, lineas, neto_centimos, total_centimos, creada_por, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], venta_cliente_id, idfactura, codigo, f, json.dumps(lineas, ensure_ascii=False), neto, total, (quien or "")[:120], datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        return {"id": cur.lastrowid, "idfactura": idfactura, "codigo": codigo}
    finally:
        conn.close()


def listar(cliente, limite: int = 200) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT f.*, c.nombre AS cliente_nombre FROM portal_ventas_facturas f JOIN portal_ventas_clientes c ON c.id = f.venta_cliente_id WHERE f.tenant_id = ? AND f.cliente_fiscal_id = ? "
                             "ORDER BY f.id DESC LIMIT ?", (cliente["tenant_id"], cliente["id"], limite)).fetchall()
    finally:
        conn.close()
    return [dict(f, lineas=json.loads(f["lineas"])) for f in filas]


def obtener(cliente, factura_id: int) -> dict | None:
    return next((f for f in listar(cliente, 1000) if f["id"] == factura_id), None)


def pdf(cliente, f: dict) -> bytes:
    """La copia informativa de la factura con los datos guardados (el original está en FacturaScripts)."""
    from flask_babel import gettext as _
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from .fiscal_resumen_pdf import _e, _eur
    conn = db.get_connection()
    try:
        vc = conn.execute("SELECT nombre, nif, email FROM portal_ventas_clientes WHERE id = ? AND tenant_id = ?", (f["venta_cliente_id"], cliente["tenant_id"])).fetchone()
    finally:
        conn.close()
    est = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm, title=_("Factura %(n)s", n=f["codigo"] or f["idfactura"]))
    c = [Paragraph(_e(cliente["nombre"]), est["Heading3"]), Paragraph(_e(cliente["nif"] or ""), est["Normal"]), Spacer(1, 0.4 * cm),
         Paragraph(_e(_("Factura %(n)s", n=f["codigo"] or f["idfactura"])), est["Title"]), Paragraph(_e(_("Fecha: %(f)s", f=f["fecha"])), est["Normal"]),
         Paragraph(_e(_("Cliente: %(n)s · %(nif)s", n=vc["nombre"] if vc else "", nif=vc["nif"] if vc else "")), est["Normal"]), Spacer(1, 0.5 * cm)]
    filas = [[Paragraph(f"<b>{_e(x)}</b>", est["Normal"]) for x in (_("Concepto"), _("Cantidad"), _("Precio"), _("Importe"))]]
    for l in f["lineas"]:
        filas.append([Paragraph(_e(l["descripcion"]), est["Normal"]), f"{l['cantidad']:g}", _eur(round(l["precio"] * 100)), _eur(round(l["cantidad"] * l["precio"] * 100))])
    t = Table(filas, colWidths=[8.5 * cm, 2.2 * cm, 3 * cm, 3 * cm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f1ec")), ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    c += [t, Spacer(1, 0.3 * cm), Paragraph(_e(_("Base: %(b)s · Total con IVA: %(t)s", b=_eur(f["neto_centimos"]), t=_eur(f["total_centimos"]))), est["Normal"]), Spacer(1, 0.4 * cm),
          Paragraph(_e(_("Copia informativa. La factura original está en FacturaScripts.")), est["Italic"])]
    doc.build(c)
    return buf.getvalue()
