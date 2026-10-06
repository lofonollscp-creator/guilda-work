"""Constancia de presentación en PDF: un comprobante interno que genera la app
al marcar un vencimiento como presentado. NO sustituye al justificante oficial
de la administración (se dice en el propio documento)."""
import io
from datetime import datetime

from flask_babel import gettext as _
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _escapar(texto) -> str:
    return str(texto or "—").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generar_pdf(
    gestoria: str, cliente: str, nif: str | None, modelo: str, periodo: str, fecha_limite: str,
    presentado_en: datetime, con_justificante: bool,
) -> bytes:
    estilos = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2.2 * cm, bottomMargin=2 * cm,
                            title=_("Constancia de presentación"))
    contenido = [
        Paragraph(_escapar(gestoria), estilos["Heading3"]),
        Paragraph(_("Constancia de presentación"), estilos["Title"]),
        Spacer(1, 0.4 * cm),
    ]
    filas = [
        [_("Cliente"), _escapar(cliente)],
        [_("NIF"), _escapar(nif)],
        [_("Modelo"), _escapar(modelo)],
        [_("Periodo"), _escapar(periodo)],
        [_("Fecha límite"), _escapar(fecha_limite[:10])],
        [_("Marcado como presentado el"), presentado_en.strftime("%d/%m/%Y %H:%M")],
        [_("Justificante oficial"), _("Adjunto en el portal") if con_justificante else _("Pendiente de adjuntar")],
    ]
    tabla = Table([[Paragraph(f"<b>{_escapar(a)}</b>", estilos["Normal"]), Paragraph(b, estilos["Normal"])] for a, b in filas],
                  colWidths=[6 * cm, 9.6 * cm])
    tabla.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f1ec")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    contenido += [
        tabla, Spacer(1, 0.7 * cm),
        Paragraph(
            _escapar(_("Este documento es una constancia interna emitida por %(gestoria)s y no sustituye al justificante "
                       "oficial de presentación emitido por la administración tributaria.", gestoria=gestoria)),
            estilos["Italic"],
        ),
    ]
    doc.build(contenido)
    return buf.getvalue()
