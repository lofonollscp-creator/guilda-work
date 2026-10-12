"""Capa única de informes en PDF: cabecera con el nombre del despacho, pie con la fecha y «Página X de Y», fuentes con soporte completo de
catalán y francés y celdas que ajustan el texto. Todo informe de Guilda Work (históricos, fichajes, informes de la IA, informe mensual al
cliente, módulos) pasa por aquí para tener el mismo aspecto y no duplicar estilos.

Los bloques son datos simples (`titulo`, `parrafo`, `claves`, `tabla`, `espacio`) para que quien llama no toque reportlab."""
from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape as _esc

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FILAS_MAXIMAS = 2000
_FUENTES = (("DejaVuSans", "DejaVuSans.ttf"), ("DejaVuSans-Bold", "DejaVuSans-Bold.ttf"), ("DejaVuSans-Oblique", "DejaVuSans-Oblique.ttf"))
_DIRS = (Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"), Path("/usr/local/share/fonts"))
_fuente_normal = _fuente_negrita = None


def _fuentes() -> tuple[str, str]:
    """(normal, negrita). DejaVu cubre catalán, francés y casi cualquier alfabeto latino; si no está en el sistema se usa Helvetica (Latin-1)."""
    global _fuente_normal, _fuente_negrita
    if _fuente_normal is None:
        try:
            for nombre, archivo in _FUENTES:
                ruta = next((d / archivo for d in _DIRS if (d / archivo).exists()), None)
                if ruta is None:
                    raise FileNotFoundError(archivo)
                if nombre not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(nombre, str(ruta)))
            pdfmetrics.registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold", italic="DejaVuSans-Oblique", boldItalic="DejaVuSans-Bold")
            _fuente_normal, _fuente_negrita = "DejaVuSans", "DejaVuSans-Bold"
        except Exception:  # sin la fuente en el sistema: se sigue con la estándar
            _fuente_normal, _fuente_negrita = "Helvetica", "Helvetica-Bold"
    return _fuente_normal, _fuente_negrita


def _estilos() -> dict[str, ParagraphStyle]:
    normal, negrita = _fuentes()
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("t", parent=base["Title"], fontName=negrita, fontSize=18, leading=22, alignment=0, spaceAfter=4),
        "subtitulo": ParagraphStyle("st", parent=base["Normal"], fontName=normal, fontSize=9, textColor=colors.HexColor("#555a63")),
        "seccion": ParagraphStyle("s", parent=base["Heading2"], fontName=negrita, fontSize=12, spaceBefore=10, spaceAfter=4),
        "normal": ParagraphStyle("n", parent=base["Normal"], fontName=normal, fontSize=9.5, leading=13),
        "celda": ParagraphStyle("c", parent=base["Normal"], fontName=normal, fontSize=8, leading=10),
        "celda_cab": ParagraphStyle("cc", parent=base["Normal"], fontName=negrita, fontSize=8, leading=10, textColor=colors.white),
    }


def _texto(valor) -> str:
    return "" if valor is None else _esc(str(valor)).replace("\n", "<br/>")


def _lienzo_numerado(despacho: str | None, titulo: str, generado: str):
    normal, _negrita = _fuentes()

    class _Lienzo(canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._paginas: list[dict] = []

        def showPage(self):
            self._paginas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas)
            for estado in self._paginas:
                self.__dict__.update(estado)
                self._decorar(total)
                super().showPage()
            super().save()

        def _decorar(self, total: int):
            ancho, alto = self._pagesize
            self.setFont(normal, 8)
            self.setFillColor(colors.HexColor("#555a63"))
            if despacho:
                self.drawString(1.5 * cm, alto - 1 * cm, despacho[:90])
            self.drawRightString(ancho - 1.5 * cm, alto - 1 * cm, titulo[:70])
            self.setStrokeColor(colors.HexColor("#d8dbe1"))
            self.line(1.5 * cm, alto - 1.15 * cm, ancho - 1.5 * cm, alto - 1.15 * cm)
            self.line(1.5 * cm, 1.2 * cm, ancho - 1.5 * cm, 1.2 * cm)
            self.drawString(1.5 * cm, 0.8 * cm, f"Guilda Work · {generado}")
            self.drawRightString(ancho - 1.5 * cm, 0.8 * cm, f"{self._pageNumber} / {total}")

    return _Lienzo


def construir_pdf(titulo: str, bloques: list[tuple], *, despacho: str | None = None, subtitulo: str | None = None, apaisado: bool = False,
                  generado: str | None = None) -> bytes:
    """`bloques`: ("seccion", texto) · ("parrafo", texto) · ("claves", [(clave, valor), ...]) · ("tabla", columnas, filas) · ("espacio",).
    Todo el texto se escapa; las tablas se truncan a `FILAS_MAXIMAS` filas avisándolo en el propio documento."""
    from . import db
    est = _estilos()
    generado = generado or db.now_iso()[:16].replace("T", " ")
    pagina = landscape(A4) if apaisado else portrait(A4)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagina, title=titulo, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.8 * cm, bottomMargin=1.7 * cm)
    ancho_util = pagina[0] - 3 * cm
    el: list = [Paragraph(_texto(titulo), est["titulo"])]
    if subtitulo:
        el.append(Paragraph(_texto(subtitulo), est["subtitulo"]))
    el.append(Spacer(1, 0.4 * cm))
    for b in bloques:
        tipo = b[0]
        if tipo == "seccion":
            el.append(Paragraph(_texto(b[1]), est["seccion"]))
        elif tipo == "parrafo":
            for linea in str(b[1])[:60000].splitlines():
                el.append(Paragraph(_texto(linea), est["normal"]) if linea.strip() else Spacer(1, 0.25 * cm))
        elif tipo == "claves":
            filas = [[Paragraph(f"<b>{_texto(k)}</b>", est["celda"]), Paragraph(_texto(v), est["celda"])] for k, v in b[1]]
            if filas:
                t = Table(filas, colWidths=[ancho_util * 0.32, ancho_util * 0.68])
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8dbe1")), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f5f7")),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                el.append(t)
        elif tipo == "tabla":
            columnas, filas = b[1], list(b[2])
            aviso = None
            if len(filas) > FILAS_MAXIMAS:
                aviso = f"(truncado a las primeras {FILAS_MAXIMAS} de {len(filas)} filas)"
                filas = filas[:FILAS_MAXIMAS]
            datos = [[Paragraph(_texto(c), est["celda_cab"]) for c in columnas]] + [[Paragraph(_texto(v), est["celda"]) for v in fila] for fila in filas]
            t = Table(datos, repeatRows=1, colWidths=[ancho_util / max(len(columnas), 1)] * len(columnas))
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1d23")), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8dbe1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            el.append(t)
            if aviso:
                el.append(Paragraph(_texto(aviso), est["subtitulo"]))
        elif tipo == "espacio":
            el.append(Spacer(1, 0.4 * cm))
    doc.build(el, canvasmaker=_lienzo_numerado(despacho, titulo, generado))
    return buf.getvalue()


def nombre_despacho(tenant_id: int | None) -> str | None:
    from . import db
    if not tenant_id:
        return None
    t = db.obtener_tenant(tenant_id)
    return t["nombre"] if t else None
