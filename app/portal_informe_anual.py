"""El informe del año para el cliente: un PDF con lo que su gestoría hizo por él en un ejercicio — los modelos presentados, los documentos que firmó, los honorarios (y si están pagados), las facturas que envió y los documentos que subió.

Se genera al pedirlo con los datos de ese momento y solo con lo que el cliente ya ve en su portal (nada interno). Es un resumen informativo: no sustituye a los justificantes de presentación."""
from __future__ import annotations

import io

from flask_babel import gettext as _
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import db, facturas_contables as fc, portal_pagos, verticales
from .fiscal_resumen_pdf import _e, _eur
from .vencimientos_fiscales import MODELOS_INTERNOS


def datos(cliente, anio: int) -> dict:
    """Todo lo que lleva el informe, sin maquetar: {presentados, firmados, honorarios, facturas: {recibida, emitida, devueltas}, documentos}."""
    vencimientos = [v for v in db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"], sin_internos=True)
                    if (v["fecha_limite"] or "")[:4] == str(anio) and v["modelo"] not in MODELOS_INTERNOS]
    presentados = [v for v in vencimientos if v["estado"] == "presentado"]
    firmados = [v for v in vencimientos if v["documenso_firmado_en"]]
    documentos = sum(1 for v in vencimientos for d in db.listar_documentos_vencimiento(v["id"], origen="cliente"))
    facturas = {"recibida": 0, "emitida": 0, "devueltas": 0}
    if verticales.esta_activo(cliente["tenant_id"], "contabilizacion"):
        from . import facturas_portal
        for f in facturas_portal.facturas_del_cliente(cliente["id"], 2000):
            if f["fecha"][:4] != str(anio):
                continue
            if f["devuelta"] is not None:
                facturas["devueltas"] += 1
            elif f["estado"] != "descartada":
                facturas[f["tipo"]] += 1
    return {"vencimientos": len(vencimientos), "presentados": presentados, "firmados": firmados, "honorarios": portal_pagos.del_anio(cliente, anio), "facturas": facturas, "documentos": documentos}


def generar(cliente, anio: int) -> bytes:
    d = datos(cliente, anio)
    despacho = db.obtener_tenant(cliente["tenant_id"])
    estilos = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2.2 * cm, bottomMargin=2 * cm, title=_("Informe del año %(a)s", a=anio))

    def tabla(cabecera, filas, anchos):
        t = Table([[Paragraph(f"<b>{_e(c)}</b>", estilos["Normal"]) for c in cabecera]] + [[Paragraph(_e(c), estilos["Normal"]) for c in f] for f in filas], colWidths=anchos, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f1ec")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return t
    contenido = [Paragraph(_e(despacho["nombre"] if despacho else ""), estilos["Heading3"]), Paragraph(_("Informe del año %(a)s", a=anio), estilos["Title"]),
                 Paragraph(f"<b>{_e(cliente['nombre'])}</b> · {_e(cliente['nif'])}", estilos["Normal"]), Spacer(1, 0.5 * cm)]
    contenido += [Paragraph(_e(_("Modelos presentados: %(n)s de %(total)s", n=len(d["presentados"]), total=d["vencimientos"])), estilos["Heading4"])]
    if d["presentados"]:
        contenido.append(tabla([_("Modelo"), _("Periodo"), _("Fecha límite")], [[v["modelo"], v["periodo"], (v["fecha_limite"] or "")[:10]] for v in d["presentados"]], [4 * cm, 6 * cm, 5.6 * cm]))
    else:
        contenido.append(Paragraph(_e(_("Todavía no hay modelos presentados este año.")), estilos["Normal"]))
    if d["firmados"]:
        contenido += [Spacer(1, 0.4 * cm), Paragraph(_e(_("Documentos firmados: %(n)s", n=len(d["firmados"]))), estilos["Heading4"]),
                      tabla([_("Modelo"), _("Periodo"), _("Firmado el")], [[v["modelo"], v["periodo"], v["documenso_firmado_en"][:10]] for v in d["firmados"]], [4 * cm, 6 * cm, 5.6 * cm])]
    if d["honorarios"]:
        total = sum(h["importe"] for h in d["honorarios"])
        pagado = sum(h["importe"] for h in d["honorarios"] if h["pagado"])
        contenido += [Spacer(1, 0.4 * cm), Paragraph(_e(_("Honorarios: %(total)s, de los que están pagados %(pagado)s", total=_eur(total), pagado=_eur(pagado))), estilos["Heading4"]),
                      tabla([_("Modelo"), _("Concepto"), _("Importe"), _("Estado")], [[f"{h['modelo']} {h['periodo']}", h["concepto"], _eur(h["importe"]), _("Pagado") if h["pagado"] else _("Pendiente")] for h in d["honorarios"]], [3.6 * cm, 7 * cm, 2.8 * cm, 2.2 * cm])]
    f = d["facturas"]
    if any(f.values()):
        contenido += [Spacer(1, 0.4 * cm), Paragraph(_e(_("Facturas que has enviado")), estilos["Heading4"]),
                      Paragraph(_e(_("Gastos: %(r)s · Ventas: %(e)s · Devueltas para corregir: %(d)s", r=f["recibida"], e=f["emitida"], d=f["devueltas"])), estilos["Normal"])]
    if d["documentos"]:
        contenido += [Spacer(1, 0.4 * cm), Paragraph(_e(_("Documentos que has subido a tus modelos: %(n)s", n=d["documentos"])), estilos["Normal"])]
    contenido += [Spacer(1, 0.6 * cm), Paragraph(_e(_("Documento informativo generado con los datos de tu portal. No sustituye a los justificantes de presentación de la Agencia Tributaria.")), estilos["Italic"])]
    doc.build(contenido)
    return buf.getvalue()
