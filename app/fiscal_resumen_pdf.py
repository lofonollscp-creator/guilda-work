"""Resumen en PDF de una declaración del 303 para enseñárselo al cliente: el resultado en lenguaje llano, las casillas principales con su nombre y la fecha límite. Es un borrador informativo:
no sustituye a la presentación en la AEAT ni al justificante (se dice en el propio documento)."""
from __future__ import annotations

import io

from flask_babel import gettext as _
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PRINCIPALES = ("01", "03", "04", "06", "07", "09", "27", "28", "29", "45", "46", "66", "69", "71")        # casillas que un cliente entiende: bases y cuotas por tipo, totales y resultado


def _e(texto) -> str:
    return str(texto if texto not in (None, "") else "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _eur(centimos: int) -> str:
    entero, dec = f"{abs(centimos) / 100:,.2f}".split(".")
    return f"{'-' if centimos < 0 else ''}{entero.replace(',', '.')},{dec} €"


def frase_resultado(tipo: str, centimos: int) -> str:
    if centimos > 0:
        return _("Resultado: a ingresar %(i)s.", i=_eur(centimos))
    if centimos < 0:
        return (_("Resultado: a devolver %(i)s (se ha pedido la devolución).", i=_eur(-centimos)) if tipo == "D"
                else _("Resultado: a favor del contribuyente, %(i)s, que se compensa en los periodos siguientes.", i=_eur(-centimos)))
    return _("Resultado: cero, no hay nada que ingresar.")


def generar(*, titular: str, nif: str | None, ejercicio: int, periodo: str, estado: str, casillas: dict[str, int], etiqueta, tipo_declaracion: str, fecha_limite: str | None, gestoria: str) -> bytes:
    estilos = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2.2 * cm, bottomMargin=2 * cm, title=_("Resumen del modelo 303"))
    resultado = casillas.get("71", 0)
    contenido = [Paragraph(_e(gestoria), estilos["Heading3"]), Paragraph(_("Resumen del modelo 303 (IVA)"), estilos["Title"]),
                 Paragraph(f"<b>{_e(titular)}</b> · {_e(nif)}<br/>{_('Periodo')}: {_e(ejercicio)} {_e(periodo)}" + (f" · {_('Fecha límite')}: {_e(fecha_limite)}" if fecha_limite else ""), estilos["Normal"]),
                 Spacer(1, 0.5 * cm), Paragraph(f"<b>{_e(frase_resultado(tipo_declaracion, resultado))}</b>", estilos["Heading4"]), Spacer(1, 0.3 * cm)]
    filas = [[Paragraph(f"<b>{_('Casilla')}</b>", estilos["Normal"]), Paragraph(f"<b>{_('Concepto')}</b>", estilos["Normal"]), Paragraph(f"<b>{_('Importe')}</b>", estilos["Normal"])]]
    for k in PRINCIPALES:
        if k in casillas and (casillas[k] or k in ("27", "45", "71")):
            filas.append([k, Paragraph(_e(etiqueta(k)), estilos["Normal"]), (f"{casillas[k] / 100:g} %" if k == "65" else _eur(casillas[k]))])
    tabla = Table(filas, colWidths=[2 * cm, 10.4 * cm, 3.2 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f1ec")), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    contenido += [tabla, Spacer(1, 0.6 * cm),
                  Paragraph(_e(_("Documento informativo con el estado «%(e)s» en el momento de generarlo. No sustituye a la presentación en la Agencia Tributaria ni a su justificante.", e=estado)), estilos["Italic"])]
    doc.build(contenido)
    return buf.getvalue()
