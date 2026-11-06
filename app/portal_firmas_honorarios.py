"""Las dos «bandejas» del cliente en un sitio: lo que tiene por **firmar** (y lo ya firmado) y sus **honorarios** (lo pendiente de pagar y lo pagado, con un recibo descargable de cada pago). Todo sale de lo que el
portal ya enseña modelo a modelo; aquí solo se reúne. El recibo es un justificante informativo del pago con tarjeta: la factura de los honorarios es la que emite la gestoría."""
from __future__ import annotations

import io

from flask_babel import gettext as _
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import db, portal_firma, portal_pagos
from .fiscal_resumen_pdf import _e, _eur
from .vencimientos_fiscales import MODELOS_INTERNOS


def _vencimientos(cliente):
    return [v for v in db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"], sin_internos=True) if v["modelo"] not in MODELOS_INTERNOS]


def firmas(cliente) -> dict:
    """{pendientes: [...], firmadas: [...]} de los documentos enviados a firma de ese cliente; cada uno {id, modelo, periodo, firmado_en}."""
    vs = _vencimientos(cliente)
    pend = [{"id": v["id"], "modelo": v["modelo"], "periodo": v["periodo"], "firmado_en": None} for v in portal_firma.pendientes(vs)]
    hechas = sorted(({"id": v["id"], "modelo": v["modelo"], "periodo": v["periodo"], "firmado_en": v["documenso_firmado_en"]} for v in vs if v["documenso_documento_id"] and v["documenso_firmado_en"]),
                    key=lambda f: f["firmado_en"], reverse=True)
    return {"pendientes": pend, "firmadas": hechas}


def _ultimo_pago(vencimiento_id: int):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT id, importe_centimos, pagado_en FROM vencimientos_fiscales_pagos WHERE vencimiento_id = ? ORDER BY id DESC LIMIT 1", (vencimiento_id,)).fetchone()
    finally:
        conn.close()


def honorarios(cliente) -> dict:
    """{pendientes: [...], pagados: [...], debe: céntimos} con cada honorario {vencimiento_id, modelo, periodo, concepto, importe, referencia, puede_pagar, pagado_en, pago_id}."""
    vs = {v["id"]: v for v in _vencimientos(cliente)}
    pendientes, pagados = [], []
    for vid, c in portal_pagos.cobros(cliente, list(vs.values())).items():
        v = vs[vid]
        fila = {"vencimiento_id": vid, "modelo": v["modelo"], "periodo": v["periodo"], "concepto": c["concepto"], "importe": c["importe"], "referencia": c["referencia"], "puede_pagar": c["puede_pagar"], "pagado_en": None, "pago_id": None}
        if c["pagado"]:
            p = _ultimo_pago(vid)
            fila["pagado_en"], fila["pago_id"] = (p["pagado_en"] if p else None), (p["id"] if p else None)
            pagados.append(fila)
        else:
            pendientes.append(fila)
    pagados.sort(key=lambda f: f["pagado_en"] or "", reverse=True)
    return {"pendientes": pendientes, "pagados": pagados, "debe": sum(f["importe"] for f in pendientes)}


def recibo_pdf(cliente, vencimiento_id: int) -> bytes | None:
    """El recibo de pago de los honorarios de un modelo, o None si ese modelo no está pagado (o no es de ese cliente)."""
    fila = next((f for f in honorarios(cliente)["pagados"] if f["vencimiento_id"] == vencimiento_id and f["pago_id"]), None)
    if fila is None:
        return None
    despacho = db.obtener_tenant(cliente["tenant_id"])
    estilos = getSampleStyleSheet()
    buf = io.BytesIO()
    numero = f"R-{vencimiento_id}-{fila['pago_id']}"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2.2 * cm, bottomMargin=2 * cm, title=_("Recibo de pago %(n)s", n=numero))
    t = Table([[Paragraph(f"<b>{_e(a)}</b>", estilos["Normal"]), Paragraph(_e(b), estilos["Normal"])] for a, b in (
        (_("Concepto"), fila["concepto"] or f"{fila['modelo']} {fila['periodo']}"), (_("Modelo"), f"{fila['modelo']} {fila['periodo']}"), (_("Importe pagado"), _eur(fila["importe"])),
        (_("Fecha del pago"), (fila["pagado_en"] or "")[:10]), (_("Forma de pago"), _("Tarjeta (pago seguro de Stripe)")), (_("Factura de los honorarios"), fila["referencia"] or "—"))], colWidths=[5.6 * cm, 10 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f1ec")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    doc.build([Paragraph(_e(despacho["nombre"] if despacho else ""), estilos["Heading3"]), Paragraph(_e(_("Recibo de pago")), estilos["Title"]), Paragraph(_e(_("Número %(n)s", n=numero)), estilos["Normal"]),
               Spacer(1, 0.4 * cm), Paragraph(f"<b>{_e(cliente['nombre'])}</b> · {_e(cliente['nif'] or '')}", estilos["Normal"]), Spacer(1, 0.5 * cm), t, Spacer(1, 0.6 * cm),
               Paragraph(_e(_("Justificante informativo del pago de tus honorarios. La factura de los honorarios es la que emite tu gestoría.")), estilos["Italic"])])
    return buf.getvalue()
