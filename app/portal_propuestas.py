"""Presupuestos y propuestas de servicios: la gestoría prepara una propuesta (conceptos, importes e IVA, validez), se la envía al cliente y este la **acepta o rechaza desde el portal**, también desde el móvil. Si la gestoría lo
ha previsto, al aceptar puede pagar un anticipo o el total con tarjeta en la página segura de Stripe (el importe lo fija la gestoría, nunca el cliente).

Una propuesta enviada ya no se puede cambiar: lleva una huella SHA-256 de su contenido que se guarda con la aceptación (nombre escrito, correo de quien acepta, fecha y hora), de modo que queda constancia de **qué** se aceptó y
**cuándo**. Es una aceptación electrónica con evidencia, no una firma electrónica cualificada: para un documento que la exija se sigue usando el envío a firma. Aceptar no emite factura; la factura la hace la gestoría."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask_babel import gettext as _
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import db, stripe_pagos
from .fiscal_resumen_pdf import _e, _eur

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_propuestas (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    titulo TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    lineas TEXT NOT NULL,
    total_centimos INTEGER NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'enviada', 'aceptada', 'rechazada', 'retirada')),
    valida_hasta TEXT,
    cobro_centimos INTEGER NOT NULL DEFAULT 0,
    creada_por INTEGER,
    creada_en TEXT NOT NULL,
    enviada_en TEXT,
    huella TEXT,
    respondida_en TEXT,
    respondida_por TEXT,
    nombre_firmante TEXT,
    motivo TEXT NOT NULL DEFAULT '',
    pagado_en TEXT,
    pagado_centimos INTEGER,
    stripe_session_id TEXT,
    visto_equipo INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_portal_propuestas_cliente ON portal_propuestas(tenant_id, cliente_fiscal_id, creada_en);
CREATE INDEX IF NOT EXISTS idx_portal_propuestas_estado ON portal_propuestas(tenant_id, estado);
"""
MAX_LINEAS = 30
MAX_EUROS = Decimal("1000000")
MINIMO_COBRO = 50                                   # céntimos: lo mínimo que admite Stripe


class ErrorPropuesta(ValueError):
    """Mensaje legible para quien prepara o responde una propuesta."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _decimal(texto: str) -> Decimal:
    try:
        return Decimal((texto or "").strip().replace("€", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise ErrorPropuesta("Revisa las cantidades, los precios y el IVA: alguno no es un número válido.") from None


def leer_lineas(texto: str) -> list[dict]:
    """Una línea por concepto con el formato `concepto; cantidad; precio unitario; IVA %` (la cantidad y el IVA son opcionales: 1 y 21). `ErrorPropuesta` si algo no vale."""
    lineas = []
    for crudo in (texto or "").splitlines():
        if not crudo.strip():
            continue
        partes = [p.strip() for p in crudo.split(";")]
        if len(partes) < 2 or not partes[0]:
            raise ErrorPropuesta("Cada línea necesita al menos un concepto y un precio, separados por «;».")
        if len(partes) == 2:
            concepto, cantidad, precio, iva = partes[0], "1", partes[1], "21"
        elif len(partes) == 3:
            concepto, cantidad, precio, iva = partes[0], partes[1], partes[2], "21"
        else:
            concepto, cantidad, precio, iva = partes[0], partes[1], partes[2], partes[3] or "21"
        c, p, i = _decimal(cantidad), _decimal(precio), _decimal(iva)
        if not (Decimal("0") < c <= 9999) or c != c.to_integral_value():
            raise ErrorPropuesta("La cantidad debe ser un número entero entre 1 y 9999.")
        if not (Decimal("0") <= p <= MAX_EUROS) or not (Decimal("0") <= i <= 25):
            raise ErrorPropuesta("Revisa los importes: el precio no puede ser negativo y el IVA va de 0 a 25.")
        lineas.append({"concepto": concepto[:200], "cantidad": int(c), "precio_centimos": stripe_pagos.euros_a_centimos(p), "iva": float(i) if i != i.to_integral_value() else int(i)})
    if not lineas:
        raise ErrorPropuesta("Añade al menos un concepto.")
    if len(lineas) > MAX_LINEAS:
        raise ErrorPropuesta("Como máximo 30 conceptos por propuesta.")
    return lineas


def total_de(lineas: list[dict]) -> int:
    """El total con IVA en céntimos."""
    t = Decimal(0)
    for l in lineas:
        t += Decimal(l["cantidad"]) * Decimal(l["precio_centimos"]) * (Decimal(100) + Decimal(str(l["iva"]))) / Decimal(100)
    return int(t.quantize(Decimal("1")))


def desglose(lineas: list[dict]) -> dict:
    """{base, iva, total} en céntimos."""
    base = sum(l["cantidad"] * l["precio_centimos"] for l in lineas)
    return {"base": base, "iva": total_de(lineas) - base, "total": total_de(lineas)}


def _huella(f: dict) -> str:
    contenido = {"titulo": f["titulo"], "descripcion": f["descripcion"], "lineas": f["lineas"], "total": f["total_centimos"], "valida_hasta": f["valida_hasta"], "cobro": f["cobro_centimos"]}
    return hashlib.sha256(json.dumps(contenido, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _fila(f) -> dict:
    d = dict(f)
    d["lineas"] = json.loads(d["lineas"])
    d["efectivo"] = "caducada" if d["estado"] == "enviada" and d["valida_hasta"] and d["valida_hasta"] < date.today().isoformat() else d["estado"]
    return d


# --- El despacho prepara y envía ---------------------------------------------------------------------------------------------------------------------

def crear(tenant_id: int, cliente_id: int, titulo: str, descripcion: str, texto_lineas: str, valida_hasta: str, cobro: str, usuario_id: int | None) -> int:
    """Una propuesta en borrador. `cobro`: «» o «no» (no se cobra al aceptar), «total» o un porcentaje de anticipo (1–99). `ErrorPropuesta` si algo no vale."""
    titulo = (titulo or "").strip()
    if not titulo:
        raise ErrorPropuesta("Ponle un título a la propuesta.")
    lineas = leer_lineas(texto_lineas)
    total = total_de(lineas)
    valida = (valida_hasta or "").strip() or None
    if valida:
        try:
            if date.fromisoformat(valida) < date.today():
                raise ErrorPropuesta("La fecha de validez ya ha pasado.")
        except ValueError:
            raise ErrorPropuesta("La fecha de validez no es válida.") from None
    cobro = (cobro or "no").strip().lower()
    if cobro in ("", "no"):
        cobrar = 0
    elif cobro == "total":
        cobrar = total
    else:
        try:
            pct = int(cobro)
        except ValueError:
            raise ErrorPropuesta("El cobro al aceptar no es válido.") from None
        if not 1 <= pct <= 99:
            raise ErrorPropuesta("El anticipo va del 1 al 99 por ciento del total.")
        cobrar = round(total * pct / 100)
    if cobrar and cobrar < MINIMO_COBRO:
        raise ErrorPropuesta("El importe a cobrar es demasiado pequeño para pagarlo con tarjeta.")
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM clientes_fiscales WHERE id = ? AND tenant_id = ? AND papelera_en IS NULL", (cliente_id, tenant_id)).fetchone() is None:
            raise ErrorPropuesta("Ese cliente no existe.")
        cur = conn.execute("INSERT INTO portal_propuestas (tenant_id, cliente_fiscal_id, titulo, descripcion, lineas, total_centimos, valida_hasta, cobro_centimos, creada_por, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, cliente_id, titulo[:200], (descripcion or "").strip()[:3000], json.dumps(lineas, ensure_ascii=False), total, valida, cobrar, usuario_id, _ahora()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def obtener_del_despacho(tenant_id: int, propuesta_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM portal_propuestas WHERE id = ? AND tenant_id = ?", (propuesta_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def listar_del_despacho(tenant_id: int, estado: str | None = None, limite: int = 200) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT p.*, c.nombre AS cliente FROM portal_propuestas p JOIN clientes_fiscales c ON c.id = p.cliente_fiscal_id AND c.tenant_id = p.tenant_id WHERE p.tenant_id = ?" + (" AND p.estado = ?" if estado else "")
                             + " ORDER BY p.creada_en DESC LIMIT ?", (tenant_id, estado, limite) if estado else (tenant_id, limite)).fetchall()
    finally:
        conn.close()
    return [_fila(f) for f in filas]


def enviar(tenant_id: int, propuesta_id: int) -> dict:
    """Pasa el borrador a enviada, fija su huella y avisa al cliente. Devuelve la propuesta. `ErrorPropuesta` si no es un borrador."""
    p = obtener_del_despacho(tenant_id, propuesta_id)
    if p is None or p["estado"] != "borrador":
        raise ErrorPropuesta("Solo se pueden enviar propuestas en borrador.")
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_propuestas SET estado = 'enviada', enviada_en = ?, huella = ? WHERE id = ? AND tenant_id = ? AND estado = 'borrador'", (_ahora(), _huella(p), propuesta_id, tenant_id)).rowcount
        conn.commit()
    finally:
        conn.close()
    if not n:
        raise ErrorPropuesta("Solo se pueden enviar propuestas en borrador.")
    p = obtener_del_despacho(tenant_id, propuesta_id)
    _avisar(p)
    return p


def _avisar(p: dict) -> None:
    """Un aviso al cliente (correo, móvil, SMS o WhatsApp según lo que tenga) para que la mire. Nunca lanza."""
    try:
        from flask import url_for
        from . import portal_avisos
        cliente = db.obtener_cliente_fiscal_por_id(p["cliente_fiscal_id"])
        destino = url_for("portal_cliente.propuesta", propuesta_id=p["id"])
        portal_avisos.avisar(cliente, destino, lambda: {"asunto": _("Tu gestoría te ha enviado una propuesta"), "lineas": [p["titulo"], _("Puedes aceptarla o rechazarla desde el portal.")], "boton": _("Ver la propuesta"), "push": p["titulo"]},
                             urgente=False, accion="decidir")
    except Exception:  # noqa: BLE001
        pass


def retirar(tenant_id: int, propuesta_id: int) -> bool:
    """La gestoría retira una propuesta enviada que aún no se ha respondido (o descarta un borrador)."""
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_propuestas SET estado = 'retirada', respondida_en = ? WHERE id = ? AND tenant_id = ? AND estado IN ('borrador', 'enviada')", (_ahora(), propuesta_id, tenant_id)).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def marcar_vista(tenant_id: int, propuesta_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute("UPDATE portal_propuestas SET visto_equipo = 1 WHERE id = ? AND tenant_id = ?", (propuesta_id, tenant_id))
        conn.commit()
    finally:
        conn.close()


def sin_ver(tenant_id: int) -> list[dict]:
    """Las propuestas respondidas por el cliente que el equipo aún no ha visto (para la bandeja del portal): [{id, titulo, cliente_fiscal_id, estado, desde}]."""
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, titulo, cliente_fiscal_id, estado, respondida_en AS desde FROM portal_propuestas WHERE tenant_id = ? AND estado IN ('aceptada', 'rechazada') AND visto_equipo = 0", (tenant_id,)).fetchall()]
    finally:
        conn.close()


# --- El cliente responde ------------------------------------------------------------------------------------------------------------------------------

def listar(cliente) -> list[dict]:
    """Las propuestas que la gestoría ha enviado a este cliente (las retiradas y los borradores no se ven), las más nuevas primero."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM portal_propuestas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('enviada', 'aceptada', 'rechazada') ORDER BY enviada_en DESC", (cliente["tenant_id"], cliente["id"])).fetchall()
    finally:
        conn.close()
    return [_fila(f) for f in filas]


def hay(cliente) -> bool:
    """Si la gestoría le ha enviado alguna propuesta (para enseñar o no el acceso en el menú)."""
    conn = db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM portal_propuestas WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('enviada', 'aceptada', 'rechazada') LIMIT 1", (cliente["tenant_id"], cliente["id"])).fetchone() is not None
    finally:
        conn.close()


def pendientes(cliente) -> list[dict]:
    return [p for p in listar(cliente) if p["efectivo"] == "enviada"]


def obtener(cliente, propuesta_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM portal_propuestas WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND estado IN ('enviada', 'aceptada', 'rechazada')", (propuesta_id, cliente["tenant_id"], cliente["id"])).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def aceptar(cliente, propuesta_id: int, email: str, nombre: str) -> None:
    """Registra la aceptación con el nombre escrito y el correo de quien la hace. `ErrorPropuesta` si ya no se puede (respondida, caducada o retirada) o falta el nombre."""
    nombre = (nombre or "").strip()
    if len(nombre) < 3:
        raise ErrorPropuesta("Escribe tu nombre completo para aceptar.")
    p = obtener(cliente, propuesta_id)
    if p is None or p["efectivo"] != "enviada":
        raise ErrorPropuesta("Esta propuesta ya no se puede aceptar.")
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_propuestas SET estado = 'aceptada', respondida_en = ?, respondida_por = ?, nombre_firmante = ? WHERE id = ? AND tenant_id = ? AND estado = 'enviada'",
                         (_ahora(), (email or "")[:200], nombre[:120], propuesta_id, cliente["tenant_id"])).rowcount
        conn.commit()
    finally:
        conn.close()
    if not n:
        raise ErrorPropuesta("Esta propuesta ya no se puede aceptar.")


def rechazar(cliente, propuesta_id: int, email: str, motivo: str) -> None:
    p = obtener(cliente, propuesta_id)
    if p is None or p["efectivo"] != "enviada":
        raise ErrorPropuesta("Esta propuesta ya no se puede rechazar.")
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_propuestas SET estado = 'rechazada', respondida_en = ?, respondida_por = ?, motivo = ? WHERE id = ? AND tenant_id = ? AND estado = 'enviada'",
                         (_ahora(), (email or "")[:200], (motivo or "").strip()[:1000], propuesta_id, cliente["tenant_id"])).rowcount
        conn.commit()
    finally:
        conn.close()
    if not n:
        raise ErrorPropuesta("Esta propuesta ya no se puede rechazar.")


# --- Pago al aceptar (Stripe) ------------------------------------------------------------------------------------------------------------------------

def puede_pagar(p: dict, tenant_id: int) -> bool:
    return p["estado"] == "aceptada" and p["cobro_centimos"] > 0 and not p["pagado_en"] and _cuenta_stripe(tenant_id) is not None


def cobro_disponible(tenant_id: int) -> bool:
    """Si el despacho tiene activados los pagos con tarjeta (para ofrecer el cobro al aceptar)."""
    return _cuenta_stripe(tenant_id) is not None


def _cuenta_stripe(tenant_id: int) -> str | None:
    t = db.obtener_tenant(tenant_id)
    return t["stripe_account_id"] if t and stripe_pagos.configurado() else None


def crear_pago(cliente, propuesta_id: int, url_exito: str, url_cancelar: str) -> str:
    """La URL de Checkout para pagar lo que la gestoría fijó para esta propuesta. `ErrorPropuesta` con un texto legible si no se puede."""
    p = obtener(cliente, propuesta_id)
    if p is None or p["estado"] != "aceptada" or p["cobro_centimos"] <= 0:
        raise ErrorPropuesta("No hay nada que pagar en esta propuesta.")
    if p["pagado_en"]:
        raise ErrorPropuesta("Este pago ya está hecho.")
    cuenta = _cuenta_stripe(cliente["tenant_id"])
    if cuenta is None:
        raise ErrorPropuesta("Tu gestoría todavía no tiene activados los pagos con tarjeta.")
    try:
        return stripe_pagos.crear_sesion_pago(cuenta, p["cobro_centimos"], f"{p['titulo']} — {cliente['nombre']}"[:120], url_exito, url_cancelar, metadata={"propuesta_id": p["id"], "tenant_id": cliente["tenant_id"]})
    except stripe_pagos.ErrorStripe:
        raise ErrorPropuesta("No hemos podido abrir el pago ahora mismo. Inténtalo de nuevo en unos minutos.") from None


def registrar_pago(tenant_id: int, propuesta_id: int, session_id: str, importe_centimos: int) -> bool:
    """Lo llama el webhook de Stripe. True si se anotó un pago nuevo; False si ya constaba (Stripe puede repetir la entrega) o la propuesta no es de ese despacho o no estaba aceptada."""
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_propuestas SET pagado_en = ?, pagado_centimos = ?, stripe_session_id = ? WHERE id = ? AND tenant_id = ? AND estado = 'aceptada' AND pagado_en IS NULL",
                         (_ahora(), importe_centimos, session_id, propuesta_id, tenant_id)).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


# --- PDF ------------------------------------------------------------------------------------------------------------------------------------------------------

def pdf(p: dict, cliente_nombre: str, cliente_nif: str, despacho: str) -> bytes:
    estilos = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm, title=p["titulo"])
    filas = [[Paragraph(f"<b>{_e(c)}</b>", estilos["Normal"]) for c in (_("Concepto"), _("Cantidad"), _("Precio"), _("IVA"), _("Importe"))]]
    for l in p["lineas"]:
        filas.append([Paragraph(_e(l["concepto"]), estilos["Normal"]), str(l["cantidad"]), _eur(l["precio_centimos"]), f"{l['iva']} %".replace(".", ","), _eur(round(l["cantidad"] * l["precio_centimos"] * (100 + l["iva"]) / 100))])
    d = desglose(p["lineas"])
    filas += [["", "", "", _("Base"), _eur(d["base"])], ["", "", "", _("IVA"), _eur(d["iva"])], ["", "", "", Paragraph(f"<b>{_e(_('Total'))}</b>", estilos["Normal"]), Paragraph(f"<b>{_e(_eur(d['total']))}</b>", estilos["Normal"])]]
    t = Table(filas, colWidths=[7.2 * cm, 1.8 * cm, 2.6 * cm, 2 * cm, 3.4 * cm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, len(p["lineas"])), 0.4, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f1ec")), ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    c = [Paragraph(_e(despacho), estilos["Heading3"]), Paragraph(_e(p["titulo"]), estilos["Title"]), Paragraph(f"<b>{_e(cliente_nombre)}</b> · {_e(cliente_nif)}", estilos["Normal"])]
    if p["valida_hasta"]:
        c.append(Paragraph(_e(_("Válida hasta el %(f)s", f=p["valida_hasta"])), estilos["Normal"]))
    if p["descripcion"]:
        c += [Spacer(1, 0.3 * cm), Paragraph(_e(p["descripcion"]).replace("\n", "<br/>"), estilos["Normal"])]
    c += [Spacer(1, 0.5 * cm), t]
    if p["cobro_centimos"]:
        c += [Spacer(1, 0.3 * cm), Paragraph(_e(_("Importe a pagar al aceptar: %(i)s", i=_eur(p["cobro_centimos"]))), estilos["Normal"])]
    if p["estado"] == "aceptada":
        c += [Spacer(1, 0.6 * cm), Paragraph(f"<b>{_e(_('Aceptada por %(n)s (%(e)s) el %(f)s', n=p['nombre_firmante'], e=p['respondida_por'], f=(p['respondida_en'] or '')[:16].replace('T', ' ')))}</b>", estilos["Normal"])]
    if p["huella"]:
        c.append(Paragraph(_e(_("Huella del contenido (SHA-256): %(h)s", h=p["huella"])), estilos["Italic"]))
    c += [Spacer(1, 0.4 * cm), Paragraph(_e(_("Presupuesto informativo: no es una factura. La aceptación electrónica queda registrada con el nombre, el correo, la fecha y la huella de este contenido.")), estilos["Italic"])]
    doc.build(c)
    return buf.getvalue()
