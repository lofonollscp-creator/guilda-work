"""Genera Guilda_Work_Presentacion.pdf — el guión no técnico en PDF para
presentar Guilda Work a clientes (ver README.md). No forma parte de la
app en sí (no se importa desde ningún otro módulo); se ejecuta a mano
cuando el catálogo de herramientas cambia:

    .venv/Scripts/python.exe scripts/generar_presentacion.py

Usa las capturas reales guardadas en assets/_captura_*.png (regenéralas
a mano si la UI cambia de forma visible: entra en la app con
STALWART/... configurado o no, según el caso, y captura la pantalla).
Solo reportlab (ya en requirements.txt vía la skill de PDF del equipo).
"""
import os
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(RAIZ, "assets")
SALIDA = os.path.join(RAIZ, "Guilda_Work_Presentacion.pdf")

# --- Paleta (calcada de app/static/style.css, tema oscuro) -----------------
BG = colors.HexColor("#0a0a0c")
SURFACE = colors.HexColor("#101113")
SURFACE_2 = colors.HexColor("#16171a")
BORDER = colors.HexColor("#2a2d33")
LIME = colors.HexColor("#a6e600")
LIME_DIM = colors.HexColor("#5c6b1a")
TEXT = colors.HexColor("#e8e9ec")
TEXT_MUTED = colors.HexColor("#9a9ea6")
DANGER = colors.HexColor("#e0555a")

PAGE_W, PAGE_H = letter
MARGIN = 20 * mm

# --- Tipografías: monoespaciada para acentos/labels, sans para cuerpo ------
try:
    pdfmetrics.registerFont(TTFont("Mono", r"C:\Windows\Fonts\consola.ttf"))
    pdfmetrics.registerFont(TTFont("Mono-Bold", r"C:\Windows\Fonts\consolab.ttf"))
    FUENTE_MONO, FUENTE_MONO_B = "Mono", "Mono-Bold"
except Exception:
    FUENTE_MONO, FUENTE_MONO_B = "Courier", "Courier-Bold"

FUENTE, FUENTE_B = "Helvetica", "Helvetica-Bold"

estilo_titulo_portada = ParagraphStyle("titulo_portada", fontName=FUENTE_B, fontSize=34, leading=38, textColor=colors.white)
estilo_subtitulo_portada = ParagraphStyle("subtitulo_portada", fontName=FUENTE, fontSize=13, leading=18, textColor=TEXT_MUTED)
estilo_parrafo_portada = ParagraphStyle("parrafo_portada", fontName=FUENTE, fontSize=10.5, leading=15, textColor=TEXT_MUTED, alignment=TA_LEFT)
estilo_kicker = ParagraphStyle("kicker", fontName=FUENTE_MONO_B, fontSize=9, leading=12, textColor=LIME)
estilo_h1 = ParagraphStyle("h1", fontName=FUENTE_B, fontSize=19, leading=23, textColor=colors.white, spaceBefore=2, spaceAfter=8)
estilo_h2 = ParagraphStyle("h2", fontName=FUENTE_MONO_B, fontSize=10, leading=13, textColor=TEXT_MUTED, spaceBefore=10, spaceAfter=4)
estilo_cuerpo = ParagraphStyle("cuerpo", fontName=FUENTE, fontSize=10, leading=15, textColor=TEXT, spaceAfter=6)
estilo_cuerpo_bold_inline = ParagraphStyle("cuerpo_bi", parent=estilo_cuerpo)
estilo_bullet = ParagraphStyle("bullet", fontName=FUENTE, fontSize=9.7, leading=14.5, textColor=TEXT, spaceAfter=5, leftIndent=12, bulletIndent=0)
estilo_caption = ParagraphStyle("caption", fontName=FUENTE_MONO, fontSize=7.5, leading=10, textColor=TEXT_MUTED, alignment=1, spaceBefore=4)
estilo_card_titulo = ParagraphStyle("card_titulo", fontName=FUENTE_B, fontSize=11, leading=14, textColor=colors.white)
estilo_card_desc = ParagraphStyle("card_desc", fontName=FUENTE, fontSize=8.7, leading=12, textColor=TEXT_MUTED)
estilo_card_badge_nuevo = ParagraphStyle("badge_nuevo", fontName=FUENTE_MONO_B, fontSize=7, leading=9, textColor=BG)
estilo_stat_num = ParagraphStyle("stat_num", fontName=FUENTE_MONO_B, fontSize=22, leading=26, textColor=LIME, alignment=1)
estilo_stat_label = ParagraphStyle("stat_label", fontName=FUENTE_MONO, fontSize=7.3, leading=10, textColor=TEXT_MUTED, alignment=1)
estilo_footer = ParagraphStyle("footer", fontName=FUENTE_MONO, fontSize=8, leading=10, textColor=TEXT_MUTED)


class TarjetaHerramienta(Flowable):
    """Tarjeta rectangular redondeada con acento de color, imitando
    .tool-card de app/static/style.css: fondo oscuro, borde sutil, barra
    de acento arriba, título + descripción, y una franja "NUEVO" opcional."""

    def __init__(self, titulo: str, descripcion: str, color_acento, ancho: float, alto: float = 30 * mm, nuevo: bool = False):
        super().__init__()
        self.titulo = titulo
        self.descripcion = descripcion
        self.color_acento = color_acento
        self.width = ancho
        self.height = alto
        self.nuevo = nuevo

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        c = self.canv
        r = 4
        c.setFillColor(SURFACE)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.width, self.height, r, fill=1, stroke=1)
        # barra de acento superior
        c.setFillColor(self.color_acento)
        c.roundRect(0, self.height - 2.6, self.width, 2.6, r, fill=1, stroke=0)
        c.rect(0, self.height - 2.6, self.width, 2.6 - r, fill=1, stroke=0)

        pad = 4.2 * mm
        p_titulo = Paragraph(self.titulo, estilo_card_titulo)
        p_desc = Paragraph(self.descripcion, estilo_card_desc)
        aw = self.width - 2 * pad
        _, h_titulo = p_titulo.wrap(aw, self.height)
        p_titulo.drawOn(c, pad, self.height - pad - h_titulo + 2)
        _, h_desc = p_desc.wrap(aw, self.height)
        p_desc.drawOn(c, pad, self.height - pad - h_titulo - h_desc - 1)

        if self.nuevo:
            texto = "NUEVO"
            tw = pdfmetrics.stringWidth(texto, FUENTE_MONO_B, 7) + 3.4 * mm
            th = 4.6 * mm
            x = self.width - pad - tw
            y = self.height - pad - h_titulo + (h_titulo - th) / 2 + 1
            c.setFillColor(LIME)
            c.roundRect(x, y, tw, th, 1.2, fill=1, stroke=0)
            c.setFillColor(BG)
            c.setFont(FUENTE_MONO_B, 7)
            c.drawCentredString(x + tw / 2, y + th / 2 - 2.4, texto)


def _fondo_pagina(c, doc):
    c.saveState()
    c.setFillColor(BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # rejilla sutil de puntos, igual que --grid-line del tema oscuro
    c.setFillColor(colors.HexColor("#1c1d20"))
    paso = 6 * mm
    y = 0.0
    while y < PAGE_H:
        x = 0.0
        while x < PAGE_W:
            c.circle(x, y, 0.35, fill=1, stroke=0)
            x += paso
        y += paso
    c.restoreState()


def _cabecera_interior(c, doc):
    _fondo_pagina(c, doc)
    c.saveState()
    y_barra = PAGE_H - 13 * mm
    c.setFillColor(LIME)
    c.rect(0, PAGE_H - 2.2 * mm, PAGE_W, 2.2 * mm, fill=1, stroke=0)
    c.setFont(FUENTE_MONO_B, 8.5)
    c.setFillColor(TEXT_MUTED)
    c.drawString(MARGIN, y_barra, "GUILDA WORK")
    c.setFillColor(LIME)
    c.rect(PAGE_W - MARGIN - 2.2 * mm, y_barra + 0.6 * mm, 2.2 * mm, 2.2 * mm, fill=1, stroke=0)
    # pie
    c.setFont(FUENTE_MONO, 7.5)
    c.setFillColor(TEXT_MUTED)
    c.drawRightString(PAGE_W - MARGIN, 12 * mm, str(doc.page))
    c.drawString(MARGIN, 12 * mm, "guilda.cat")
    c.restoreState()


def _portada(c, doc):
    _fondo_pagina(c, doc)
    c.saveState()
    c.setFillColor(LIME)
    c.rect(0, PAGE_H - 2.2 * mm, PAGE_W, 2.2 * mm, fill=1, stroke=0)
    c.restoreState()


def stat_row(items: list[tuple[str, str]], ancho_total: float) -> Table:
    n = len(items)
    col_w = ancho_total / n
    celdas = []
    for numero, etiqueta in items:
        celdas.append([Paragraph(numero, estilo_stat_num), Paragraph(etiqueta, estilo_stat_label)])
    fila_num = [c[0] for c in celdas]
    fila_lab = [c[1] for c in celdas]
    t = Table([fila_num, fila_lab], colWidths=[col_w] * n)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def badge_row(textos: list[str], ancho_total: float) -> Table:
    n = len(textos)
    col_w = ancho_total / n
    celdas = [[Paragraph(t, ParagraphStyle("badge", fontName=FUENTE_MONO_B, fontSize=7.6, leading=10, textColor=LIME, alignment=1))] for t in textos]
    t = Table([celdas], colWidths=[col_w] * n)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, LIME_DIM),
        ("INNERGRID", (0, 0), (-1, -1), 0.7, LIME_DIM),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def grid_tarjetas(items: list[tuple[str, str, colors.Color, bool]], ancho_disponible: float, columnas: int = 2, alto: float = 24 * mm, gap: float = 4 * mm) -> Table:
    col_w = (ancho_disponible - gap * (columnas - 1)) / columnas
    filas = []
    fila = []
    for i, (titulo, desc, color, nuevo) in enumerate(items):
        fila.append(TarjetaHerramienta(titulo, desc, color, col_w, alto, nuevo))
        if len(fila) == columnas:
            filas.append(fila)
            fila = []
    if fila:
        while len(fila) < columnas:
            fila.append(Spacer(col_w, alto))
        filas.append(fila)
    t = Table(filas, colWidths=[col_w] * columnas, rowHeights=[alto] * len(filas))
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), gap),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def imagen_con_pie(ruta: str, ancho_maximo: float, pie: str):
    from PIL import Image as PILImage
    im = PILImage.open(ruta)
    w, h = im.size
    ratio = h / w
    ancho = ancho_maximo
    alto = ancho * ratio
    img = Image(ruta, width=ancho, height=alto)
    return [img, Paragraph(pie.upper(), estilo_caption)]


# Colores de acento para tarjetas (mismos hex que los logos reales, igual
# que .tool-card de app/static/style.css / app/herramientas.py)
COLOR_CONOCIMIENTO = colors.HexColor("#7c3aed")
COLOR_PRODUCTIVIDAD = colors.HexColor("#22c55e")
COLOR_DOCUMENTOS = colors.HexColor("#0ea5e9")
COLOR_INFRA = colors.HexColor("#e0555a")


def construir():
    doc = SimpleDocTemplate(
        SALIDA, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
    )
    ancho_util = PAGE_W - 2 * MARGIN
    story = []

    # --- Página 1: portada -------------------------------------------------
    story.append(Spacer(1, 55 * mm))
    logo_path = os.path.join(RAIZ, "app", "static", "logo.png")
    if os.path.exists(logo_path):
        story.append(Image(logo_path, width=20 * mm, height=20 * mm))
        story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("// SISTEMA CONECTADO", ParagraphStyle("kicker_centro", parent=estilo_kicker, alignment=1)))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Guilda Work", ParagraphStyle("titulo_centro", parent=estilo_titulo_portada, alignment=1)))
    story.append(Paragraph("Tu centro de operaciones digital, en un solo sitio", ParagraphStyle("subt_centro", parent=estilo_subtitulo_portada, alignment=1)))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "Registro de actividad, gestión de clientes y proyectos, comunicación, documentos, "
        "correo propio y facturación — con un asistente de inteligencia artificial que sabe usarlo todo por ti.",
        ParagraphStyle("parr_centro", parent=estilo_parrafo_portada, alignment=1),
    ))
    story.append(Spacer(1, 8 * mm))
    story.append(badge_row(["REGISTRO", "MULTI-CLIENTE", "18 HERRAMIENTAS", "ASISTENTE IA", "AUTOALOJADO"], ancho_util))
    story.append(PageBreak())

    # --- Página 2: qué es + registro diario --------------------------------
    story.append(Paragraph("// 01", estilo_kicker))
    story.append(Paragraph("¿Qué es Guilda Work?", estilo_h1))
    story.append(Paragraph(
        "Guilda Work es el punto de partida del día a día de tu equipo: un registro de actividad organizado por "
        "clientes o proyectos, con tareas, notas y un calendario, todo en un solo lugar. A partir de ahí, se conecta "
        "—de forma opcional, según lo que necesite tu negocio— con un catálogo de 18 herramientas ya preparadas "
        "para gestionar clientes, proyectos, soporte, documentos, firmas, facturación, reserva de citas, envíos de "
        "correo masivo y correo propio.", estilo_cuerpo,
    ))
    story.append(Paragraph(
        "La pieza diferencial es el <b>asistente de inteligencia artificial</b>: no hace falta entrar herramienta por "
        "herramienta. Le pides algo en una sola conversación —“crea una tarea para preparar la reunión del jueves”, "
        "“búscame los últimos contactos de este cliente”, “envíame las facturas pendientes de este mes”— y él sabe "
        "en qué herramienta hacerlo y cómo.", estilo_cuerpo,
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(stat_row([("18", "HERRAMIENTAS CONECTADAS"), ("84", "ACCIONES DE IA DISPONIBLES"), ("100%", "AUTOALOJADO")], ancho_util))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("EN UNA FRASE", ParagraphStyle("en_frase", fontName=FUENTE_B, fontSize=9, textColor=colors.white, spaceAfter=3)))
    story.append(Paragraph(
        "Todo lo que tu negocio necesita para organizarse, con una IA que sabe moverse por todo ello — sin "
        "depender de que cada persona aprenda a usar diez programas distintos.", estilo_cuerpo,
    ))

    story.append(Paragraph("// 02", estilo_kicker))
    story.append(Paragraph("El registro diario de actividad", estilo_h1))
    story.append(Paragraph(
        "El núcleo de Guilda Work: un registro cronológico organizado en <b>menús</b> (un carril por cliente, "
        "proyecto o área) que no interfieren entre sí. Puedes tener varias cosas en marcha a la vez sin perder "
        "el hilo de ninguna.", estilo_cuerpo,
    ))
    bullets2 = [
        ("Notas rápidas y eventos instantáneos", "anota algo en un par de clics, con fecha y hora exactas."),
        ("Tareas con duración", "inicia, pausa/reanuda y finaliza; el tiempo dedicado se calcula solo."),
        ("Histórico y estadísticas", "cuánto tiempo se ha dedicado a cada cliente o proyecto, con gráficos, filtrable por fecha."),
        ("Exportación", "a JSON, CSV o un resumen en texto legible."),
        ("Correo integrado", "cuentas conectadas, con su propia bandeja, categorías y firma, sin salir de la app."),
        ("Copias de seguridad automáticas", "y una papelera de la que se puede restaurar cualquier cosa borrada por error."),
    ]
    for titulo, resto in bullets2:
        story.append(Paragraph(f"● <b>{titulo}</b> — {resto}", estilo_bullet))
    story.append(PageBreak())

    # --- Página 3: dashboard + organización por clientes --------------------
    cap_dash = os.path.join(ASSETS, "_captura_dashboard.png")
    if os.path.exists(cap_dash):
        for flow in imagen_con_pie(cap_dash, ancho_util * 0.72, "Panel de inicio — vista real de la aplicación"):
            story.append(flow)
        story.append(Spacer(1, 2 * mm))

    story.append(Paragraph("// 03", estilo_kicker))
    story.append(Paragraph("Organización por clientes", estilo_h1))
    story.append(Paragraph(
        "Si tu negocio trabaja para varios clientes o gestiona varias marcas/unidades, Guilda Work las mantiene "
        "completamente separadas: cada una es un <b>tenant</b> con sus propios usuarios, y sus datos <b>nunca</b> "
        "son visibles para otra. Esto aplica tanto al registro de actividad como a cada una de las 18 herramientas "
        "conectadas del catálogo siguiente — cada cliente ve solo lo suyo.", estilo_cuerpo,
    ))
    story.append(Paragraph(
        "Dar de alta un cliente nuevo es un solo paso desde el panel de administración: el sistema prepara "
        "automáticamente su propio espacio en cada herramienta conectada, sin configuración manual añadida en la "
        "gran mayoría de los casos.", estilo_cuerpo,
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(stat_row([("1", "ALTA POR CLIENTE"), ("0", "DATOS VISIBLES ENTRE CLIENTES"), ("N", "CLIENTES SIMULTÁNEOS")], ancho_util))
    story.append(PageBreak())

    # --- Página 4: catálogo completo -----------------------------------------
    story.append(Paragraph("// 04", estilo_kicker))
    story.append(Paragraph("Catálogo de herramientas conectadas", estilo_h1))
    story.append(Paragraph(
        "Un stack completo de herramientas de negocio, ya preparado y conectado — se activa según lo que "
        "necesite cada cliente, sin tener que contratar ni mantener cada aplicación por separado.", estilo_cuerpo,
    ))

    story.append(Paragraph("CONOCIMIENTO Y COMUNICACIÓN", estilo_h2))
    story.append(grid_tarjetas([
        ("Documentación", "Guías internas y base de conocimiento del equipo, siempre a mano y buscable.", COLOR_CONOCIMIENTO, False),
        ("Chat", "Mensajería del equipo en tiempo real, propia y privada.", COLOR_CONOCIMIENTO, False),
    ], ancho_util))

    story.append(Paragraph("CLIENTES Y PROYECTOS", estilo_h2))
    story.append(grid_tarjetas([
        ("CRM", "Gestión de clientes, contactos y oportunidades — el embudo de ventas en un sitio.", COLOR_PRODUCTIVIDAD, False),
        ("Proyectos", "Tareas de equipo con vistas Kanban y calendario.", COLOR_PRODUCTIVIDAD, False),
        ("Soporte", "Bandeja de atención al cliente unificada, para no perder ninguna consulta.", COLOR_PRODUCTIVIDAD, False),
        ("Automatizaciones", "Flujos que conectan las herramientas entre sí y hacen tareas repetitivas solas.", COLOR_PRODUCTIVIDAD, False),
        ("Reserva de citas", "Agenda online para que tus clientes reserven cita contigo solos.", COLOR_PRODUCTIVIDAD, True),
        ("Newsletter", "Envíos masivos y campañas de correo a listas de tus clientes.", COLOR_PRODUCTIVIDAD, True),
    ], ancho_util))

    story.append(Paragraph("DOCUMENTOS Y DATOS", estilo_h2))
    story.append(grid_tarjetas([
        ("Almacenamiento de archivos", "Un espacio en la nube propio, tipo Drive, para compartir dentro del equipo.", COLOR_DOCUMENTOS, False),
        ("Gestión documental", "Escaneos y PDFs con reconocimiento de texto automático (OCR).", COLOR_DOCUMENTOS, False),
        ("Firma electrónica", "Envía documentos a firmar y haz seguimiento, sin papel.", COLOR_DOCUMENTOS, False),
        ("Hojas de cálculo", "Listados y bases de datos estructuradas, tipo Airtable.", COLOR_DOCUMENTOS, False),
        ("Analítica", "Paneles y cuadros de mando sobre la actividad del negocio.", COLOR_DOCUMENTOS, False),
        ("Facturación", "Cada cliente con su propia contabilidad, facturas y presupuestos, separada de la de los demás.", COLOR_DOCUMENTOS, True),
    ], ancho_util))

    story.append(KeepTogether([
        Paragraph("INFRAESTRUCTURA Y COMUNICACIONES", estilo_h2),
        grid_tarjetas([
            ("Almacenamiento técnico", "Copias de seguridad y archivos grandes.", COLOR_INFRA, False),
            ("Gestor de contraseñas", "Uso exclusivamente humano — nunca accesible por la IA.", COLOR_INFRA, False),
            ("Correo propio", "Servidor de correo con dominio propio de cada cliente y API moderna para la IA.", COLOR_INFRA, True),
        ], ancho_util, columnas=2),
    ]))
    story.append(PageBreak())

    # --- Página 5: novedades recientes ---------------------------------------
    story.append(Paragraph("// 05", estilo_kicker))
    story.append(Paragraph("Últimas incorporaciones al catálogo", estilo_h1))
    story.append(Paragraph(
        "Cuatro piezas nuevas, añadidas para cubrir el ciclo completo de un negocio de servicios: agendar, "
        "facturar, comunicar por email masivo y tener correo propio con dominio de cada cliente.", estilo_cuerpo,
    ))

    novedades = [
        ("Facturación", "Facturas, presupuestos y contabilidad — con la información de cada cliente completamente separada de la de los demás, como el resto del sistema."),
        ("Reserva de citas", "Tus clientes reservan hora contigo directamente desde un enlace propio, sin llamadas ni idas y venidas de correos para cuadrar una hora."),
        ("Newsletter", "Envíos masivos y campañas de correo segmentadas por lista, para comunicar novedades u ofertas a tus contactos."),
        ("Correo propio", "Cada cliente puede tener su propio servidor de correo, con su propio dominio (el de su empresa), gestionable también desde el asistente de IA."),
    ]
    for titulo, desc in novedades:
        story.append(KeepTogether([
            Paragraph(f'<font color="#a6e600">●</font> <b>{titulo}</b>', ParagraphStyle("nov_t", fontName=FUENTE_B, fontSize=11.5, textColor=colors.white, spaceBefore=8, spaceAfter=2)),
            Paragraph(desc, estilo_cuerpo),
        ]))

    cap_herr = os.path.join(ASSETS, "_captura_herramientas.png")
    if os.path.exists(cap_herr):
        story.append(Spacer(1, 3 * mm))
        for flow in imagen_con_pie(cap_herr, ancho_util * 0.85, "Pantalla “Herramientas” — vista real de la aplicación, con las nuevas incorporaciones"):
            story.append(flow)
    story.append(PageBreak())

    # --- Página 6: IA + seguridad --------------------------------------------
    story.append(Paragraph("// 06", estilo_kicker))
    story.append(Paragraph("El asistente de IA: la pieza que lo conecta todo", estilo_h1))
    story.append(Paragraph(
        "Aquí está el verdadero salto respecto a tener estas herramientas por separado. Guilda Work incluye un "
        "<b>asistente de inteligencia artificial</b> que no se limita a responder preguntas: sabe <b>actuar</b> "
        "dentro de cada una de las 18 herramientas conectadas, en tu nombre y bajo tu supervisión.", estilo_cuerpo,
    ))
    story.append(Paragraph(
        "Puedes hablar con él desde dentro de la propia app, o conectar tu asistente de IA favorito de fuera "
        "—Claude, ChatGPT— directamente contra tu Guilda Work. En ambos casos, la conversación es el único "
        "sitio donde tienes que estar: le pides algo una vez, y él decide sobre qué herramienta actuar.", estilo_cuerpo,
    ))
    story.append(Paragraph("ALGUNOS EJEMPLOS DE LO QUE SE LE PUEDE PEDIR", ParagraphStyle("ejemplos_h", fontName=FUENTE_MONO_B, fontSize=8.3, textColor=TEXT_MUTED, spaceBefore=4, spaceAfter=4)))
    ejemplos = [
        "“Apunta que hoy he llamado al cliente X sobre el contrato.”",
        "“Búscame los contactos de la empresa Y y la última conversación que tuvimos.”",
        "“Crea una tarea: revisar el diseño antes del viernes.”",
        "“Prepara una factura para este cliente con estas dos líneas.”",
        "“Reserva un hueco de cita con este cliente para el martes.”",
        "“Mándale la newsletter de este mes a la lista de clientes activos.”",
    ]
    filas_ej = []
    for i in range(0, len(ejemplos), 2):
        par_estilo = ParagraphStyle("ej", fontName=FUENTE, fontSize=8.6, leading=12, textColor=TEXT)
        izq = Paragraph(ejemplos[i], par_estilo)
        der = Paragraph(ejemplos[i + 1], par_estilo) if i + 1 < len(ejemplos) else ""
        filas_ej.append([izq, der])
    t_ej = Table(filas_ej, colWidths=[ancho_util / 2 - 2 * mm, ancho_util / 2 - 2 * mm])
    t_ej.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE_2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    story.append(t_ej)
    story.append(Paragraph(
        "Todo esto ocurre con las mismas reglas de seguridad que si lo hicieras tú a mano: cada cliente sigue "
        "completamente aislado de los demás, y las acciones más delicadas —como mandar un correo de verdad— "
        "piden confirmación explícita antes de ejecutarse. El gestor de contraseñas queda fuera del alcance de la "
        "IA por completo, sin excepción.", estilo_cuerpo,
    ))

    story.append(Paragraph("// 07", estilo_kicker))
    story.append(Paragraph("Seguridad y privacidad", estilo_h1))
    seguridad = [
        ("Autoalojado", "todo corre en infraestructura propia, no en servidores de terceros: los datos de tu negocio (y los de tus clientes) no salen de tu control."),
        ("Aislamiento real entre clientes", "verificado herramienta por herramienta contra la aplicación real, no solo asumido — un cliente nunca puede ver ni acceder a los datos de otro."),
        ("Copias de seguridad automáticas", "del registro de actividad, con purga controlada y posibilidad de restaurar."),
        ("El gestor de contraseñas queda fuera del alcance de la IA", "por decisión de diseño — ninguna automatización puede tocarlo."),
        ("Acciones sensibles con confirmación", "la IA nunca manda un correo sin que se revise antes el contenido."),
    ]
    for titulo, resto in seguridad:
        story.append(Paragraph(f"● <b>{titulo}</b> — {resto}", estilo_bullet))
    story.append(PageBreak())

    # --- Página 7: próximos pasos ---------------------------------------------
    story.append(Spacer(1, 60 * mm))
    story.append(Paragraph("// PRÓXIMOS PASOS", ParagraphStyle("kicker_centro2", parent=estilo_kicker, alignment=1)))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Este documento es un resumen pensado para verse en una reunión, no una lista cerrada — el catálogo de "
        "herramientas conectadas crece según lo que necesite cada negocio, y cada una se activa solo si aporta "
        "valor real al caso de uso concreto.", ParagraphStyle("pp1", parent=estilo_parrafo_portada, alignment=1, fontSize=11, leading=17),
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "Para ver cualquiera de estas herramientas en funcionamiento, o para hablar sobre qué combinación tiene "
        "más sentido para tu caso, este es el momento de preguntar.",
        ParagraphStyle("pp2", parent=estilo_parrafo_portada, alignment=1, fontSize=11, leading=17),
    ))

    doc.build(story, onFirstPage=_portada, onLaterPages=_cabecera_interior)


if __name__ == "__main__":
    construir()
    print(f"Generado: {SALIDA}")
