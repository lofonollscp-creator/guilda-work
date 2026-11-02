"""Documentos prehechos que se generan desde la ficha del cliente y se firman con Documenso: hoja de encargo, orden de domiciliación SEPA, autorización de representación ante la AEAT,
información y consentimiento RGPD y consentimiento de comunicaciones comerciales (textos en `documentos_firma_textos.py`).

Reglas, explícitas:
- **Un documento = un borrador que se revisa antes de enviarse.** Se rellena con los datos del cliente y del despacho; si falta algo imprescindible (NIF, dirección, correo…) no se genera y se
  dice qué falta. Lo que se envía a firmar es EXACTAMENTE el texto del borrador (queda guardado con su huella SHA-256): cambiarlo obliga a crear otro.
- **Enviar a firma es una acción externa**: la persona la confirma en pantalla. Sin token de Documenso del despacho solo se puede descargar el PDF.
- **Textos de serie sin validar**; cada despacho puede sustituirlos por los suyos (con las mismas variables) y volver a los de serie cuando quiera.
- **Al firmarse** el PDF firmado se guarda en los documentos del cliente y, si el documento tiene un efecto registrado (p. ej. el consentimiento comercial), se aplica con su prueba.
- Quien solo audita no genera ni envía. Todo queda en la auditoría."""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta

from . import acceso, almacen_documentos, auditoria, db, documenso, nucleo
from .documentos_firma_textos import (AUTORIZACION_AEAT, CONSENTIMIENTO_COMERCIAL, CONSENTIMIENTO_RGPD, HOJA_ENCARGO, MANDATO_SEPA, TEXTO_ESQUEMA_B2B, TEXTO_ESQUEMA_CORE)
from .fiscal_modelos import iban as iban_mod

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos_plantillas (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    clave TEXT NOT NULL,
    cuerpo TEXT,
    ajustes TEXT NOT NULL DEFAULT '{}',
    actualizado_en TEXT NOT NULL,
    actualizado_por INTEGER REFERENCES usuarios(id),
    PRIMARY KEY (tenant_id, clave)
);
CREATE TABLE IF NOT EXISTS documentos_firma (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    plantilla TEXT NOT NULL,
    titulo TEXT NOT NULL,
    datos TEXT NOT NULL DEFAULT '{}',
    texto TEXT NOT NULL,
    firmante_email TEXT NOT NULL,
    firmante_nombre TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'enviado', 'firmado', 'rechazado', 'cancelado')),
    documenso_id TEXT,
    pdf_sha256 TEXT NOT NULL,
    documento_firmado_id INTEGER,
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    enviado_en TEXT,
    firmado_en TEXT,
    actualizado_en TEXT,
    recordado_en TEXT,
    recordatorios INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documentos_firma_cliente ON documentos_firma(tenant_id, cliente_id, creado_en);
"""

AJUSTES = "general"                                    # fila de `documentos_plantillas` con los valores que se repiten (acreedor SEPA, contacto RGPD, lugar…)
CLAVES_AJUSTES = ("acreedor_sepa", "contacto_rgpd", "lugar")
LARGO_TEXTO = 20000
MAX_RECORDATORIOS = 3                                  # veces que se reenvía el aviso de firma a quien no firma; luego, que lo gestione una persona
MAX_DIAS_RECORDATORIO = 30
FIRMA = (55.0, 87.0, 35.0, 6.0)                        # x, y, ancho y alto del campo de firma en % de la página (el PDF deja ese hueco libre)

# Efectos al firmarse: `{clave de plantilla: función(tenant_id, usuario_id, documento)}`; los registra quien los necesita (p. ej. marketing).
AL_FIRMAR: dict = {}


class ErrorDocumento(ValueError):
    """Un error de negocio con un mensaje apto para enseñárselo a la persona."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "documentos_firma", "recordado_en", "TEXT")                     # bases anteriores a los recordatorios de firma
    db._asegurar_columna(conn, "documentos_firma", "recordatorios", "INTEGER NOT NULL DEFAULT 0")


# --- Catálogo ---------------------------------------------------------------------------------------------------------------

def _campo(clave, etiqueta, tipo="texto", obligatorio=True, defecto="", ayuda="", opciones=()):
    return {"clave": clave, "etiqueta": etiqueta, "tipo": tipo, "obligatorio": obligatorio, "defecto": defecto, "ayuda": ayuda, "opciones": tuple(opciones)}


_VIGENCIA_ENCARGO = "El encargo tiene duración indefinida y se renueva tácitamente por periodos anuales. Cualquiera de las partes puede resolverlo con un preaviso escrito de 30 días."
_ALCANCE_AEAT = "Presentar declaraciones y autoliquidaciones, consultar los datos fiscales y el estado de los trámites, y recibir las comunicaciones y notificaciones electrónicas."

PLANTILLAS = {
    "hoja_encargo": {
        "titulo": "Hoja de encargo profesional", "texto": HOJA_ENCARGO,
        "descripcion": "Los servicios que presta el despacho, sus honorarios y las obligaciones de cada parte.",
        "campos": (_campo("servicios", "Servicios del encargo", "area", ayuda="Uno por línea, p. ej. «Contabilidad y declaraciones trimestrales de IVA e IRPF»."),
                   _campo("honorarios", "Honorarios y forma de pago", "area", ayuda="Importe, periodicidad y medio de pago."),
                   _campo("vigencia", "Duración y resolución", "area", defecto=_VIGENCIA_ENCARGO)),
    },
    "mandato_sepa": {
        "titulo": "Orden de domiciliación SEPA", "texto": MANDATO_SEPA,
        "descripcion": "Autoriza al despacho a cobrar sus honorarios por adeudo directo en la cuenta del cliente.",
        "campos": (_campo("iban", "IBAN del cliente", "iban"),
                   _campo("esquema", "Esquema", "select", defecto="CORE", opciones=("CORE", "B2B"), ayuda="CORE es el habitual; B2B solo entre empresas o profesionales y el banco debe registrarlo."),
                   _campo("recurrencia", "Tipo de pago", "select", defecto="Recurrente", opciones=("Recurrente", "Único")),
                   _campo("acreedor_sepa", "Identificador del acreedor SEPA del despacho", ayuda="Lo asigna el banco al despacho (p. ej. ES12ZZZ12345678). Se recuerda para los siguientes."),
                   _campo("referencia", "Referencia de la orden", obligatorio=False, ayuda="Si la dejas vacía se genera una (máx. 35 caracteres, sin espacios).")),
    },
    "autorizacion_aeat": {
        "titulo": "Autorización de representación ante la AEAT", "texto": AUTORIZACION_AEAT,
        "descripcion": "El cliente autoriza al despacho a actuar en su nombre ante la Agencia Tributaria.",
        "campos": (_campo("alcance", "Trámites autorizados", "area", defecto=_ALCANCE_AEAT),
                   _campo("vigencia", "Vigencia", "area", defecto="Hasta que el obligado tributario la revoque."),
                   _campo("representante_cliente", "Quien firma por el cliente (si es una sociedad)", obligatorio=False, ayuda="Nombre, NIF y cargo, p. ej. «D. Ana Pérez, NIF 00000000A, administradora única».")),
    },
    "consentimiento_rgpd": {
        "titulo": "Información y consentimiento RGPD", "texto": CONSENTIMIENTO_RGPD,
        "descripcion": "Cómo trata el despacho los datos del cliente y su consentimiento al tratamiento.",
        "campos": (_campo("contacto_rgpd", "Correo para ejercer derechos de protección de datos", ayuda="Se recuerda para los siguientes."),),
    },
    "consentimiento_comercial": {
        "titulo": "Consentimiento de comunicaciones comerciales", "texto": CONSENTIMIENTO_COMERCIAL,
        "descripcion": "Permiso, aparte y opcional, para enviar al cliente información comercial por email. Al firmarse queda registrado como consentimiento de marketing.",
        "campos": (_campo("contacto_rgpd", "Correo para retirar el consentimiento y ejercer derechos", ayuda="Se recuerda para los siguientes."),),
    },
}
CLAVES = tuple(PLANTILLAS)
VARIABLES_COMUNES = ("cliente.nombre", "cliente.nif", "cliente.direccion", "cliente.email", "cliente.telefono", "despacho.nombre", "despacho.cif", "despacho.direccion", "fecha", "lugar")
_VARIABLE = re.compile(r"\{\{\s*([a-z_][a-z0-9_.]*)\s*\}\}")


def variables_de(clave: str) -> list[str]:
    """Las variables que admite el texto de esta plantilla: las comunes y las campos propios del documento."""
    propias = [c["clave"] for c in PLANTILLAS[clave]["campos"]]
    extra = ["texto_esquema"] if clave == "mandato_sepa" else []
    return list(VARIABLES_COMUNES) + [v for v in propias + extra if v not in VARIABLES_COMUNES]


def _plantilla(clave: str) -> dict:
    if clave not in PLANTILLAS:
        raise ErrorDocumento("Documento desconocido.")
    return PLANTILLAS[clave]


# --- Permisos y ajustes -----------------------------------------------------------------------------------------------------

def _exigir_escritura(tenant_id: int, usuario_id: int) -> None:
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ErrorDocumento("Tu rol solo permite consultar.")


def _exigir_direccion(usuario_id: int) -> None:
    if not acceso.es_directivo(usuario_id):
        raise ErrorDocumento("Solo la dirección del despacho cambia los textos de los documentos.")


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ajustes(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT ajustes FROM documentos_plantillas WHERE tenant_id = ? AND clave = ?", (tenant_id, AJUSTES)).fetchone()
    finally:
        conn.close()
    try:
        valores = json.loads(f["ajustes"]) if f else {}
    except ValueError:
        valores = {}
    return {k: str(valores.get(k) or "") for k in CLAVES_AJUSTES}


def _recordar(conn, tenant_id: int, usuario_id: int, nuevos: dict) -> None:
    """Guarda los valores que se repiten (acreedor, contacto RGPD, lugar) para ofrecerlos la próxima vez."""
    f = conn.execute("SELECT ajustes FROM documentos_plantillas WHERE tenant_id = ? AND clave = ?", (tenant_id, AJUSTES)).fetchone()
    try:
        actuales = json.loads(f["ajustes"]) if f else {}
    except ValueError:
        actuales = {}
    cambios = {k: str(v).strip()[:200] for k, v in nuevos.items() if k in CLAVES_AJUSTES and str(v or "").strip()}
    if not cambios or all(actuales.get(k) == v for k, v in cambios.items()):
        return
    actuales.update(cambios)
    conn.execute(
        "INSERT INTO documentos_plantillas (tenant_id, clave, cuerpo, ajustes, actualizado_en, actualizado_por) VALUES (?, ?, NULL, ?, ?, ?) "
        "ON CONFLICT (tenant_id, clave) DO UPDATE SET ajustes = excluded.ajustes, actualizado_en = excluded.actualizado_en, actualizado_por = excluded.actualizado_por",
        (tenant_id, AJUSTES, json.dumps(actuales, ensure_ascii=False), _ahora(), usuario_id))


# --- Textos del despacho -----------------------------------------------------------------------------------------------------

def texto_de(tenant_id: int, clave: str) -> tuple[str, bool]:
    """(texto vigente, ¿es el del despacho?): el que haya guardado el despacho o, si no, el de serie."""
    p = _plantilla(clave)
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT cuerpo FROM documentos_plantillas WHERE tenant_id = ? AND clave = ?", (tenant_id, clave)).fetchone()
    finally:
        conn.close()
    if f and f["cuerpo"]:
        return f["cuerpo"], True
    return p["texto"], False


def comprobar_texto(clave: str, texto: str) -> list[str]:
    """Las variables del texto que no existen para este documento (vacío = el texto es válido)."""
    admitidas = set(variables_de(clave))
    return sorted({v for v in _VARIABLE.findall(texto or "") if v not in admitidas})


def guardar_texto(tenant_id: int, usuario_id: int, clave: str, texto: str) -> None:
    _plantilla(clave)
    _exigir_direccion(usuario_id)
    texto = (texto or "").replace("\r\n", "\n").strip()
    if not texto:
        raise ErrorDocumento("El texto no puede quedar vacío; para volver al de serie usa «Restaurar».")
    if len(texto) > LARGO_TEXTO:
        raise ErrorDocumento("El texto es demasiado largo.")
    mal = comprobar_texto(clave, texto)
    if mal:
        raise ErrorDocumento("Variables que este documento no tiene: " + ", ".join("{{" + v + "}}" for v in mal) + ".")
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO documentos_plantillas (tenant_id, clave, cuerpo, ajustes, actualizado_en, actualizado_por) VALUES (?, ?, ?, '{}', ?, ?) "
            "ON CONFLICT (tenant_id, clave) DO UPDATE SET cuerpo = excluded.cuerpo, actualizado_en = excluded.actualizado_en, actualizado_por = excluded.actualizado_por",
            (tenant_id, clave, texto, _ahora(), usuario_id))
        auditoria.registrar(tenant_id, usuario_id, "documento_firma.texto_guardado", "documentos_plantillas", clave, {"largo": len(texto)}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def restaurar_texto(tenant_id: int, usuario_id: int, clave: str) -> None:
    _plantilla(clave)
    _exigir_direccion(usuario_id)
    conn = db.get_connection()
    try:
        conn.execute("UPDATE documentos_plantillas SET cuerpo = NULL, actualizado_en = ?, actualizado_por = ? WHERE tenant_id = ? AND clave = ?", (_ahora(), usuario_id, tenant_id, clave))
        auditoria.registrar(tenant_id, usuario_id, "documento_firma.texto_restaurado", "documentos_plantillas", clave, None, conn=conn)
        conn.commit()
    finally:
        conn.close()


def catalogo(tenant_id: int) -> list[dict]:
    """Los documentos disponibles, indicando si el despacho tiene su propio texto."""
    return [{"clave": k, "titulo": p["titulo"], "descripcion": p["descripcion"], "propio": texto_de(tenant_id, k)[1]} for k, p in PLANTILLAS.items()]


# --- Composición ------------------------------------------------------------------------------------------------------------

def _fecha_larga(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _despacho(tenant_id: int) -> dict:
    t = db.obtener_tenant(tenant_id)
    return {"nombre": (t["nombre"] if t else "") or "", "cif": (t["cif"] if t and "cif" in t.keys() else "") or "", "direccion": (t["direccion_fiscal"] if t and "direccion_fiscal" in t.keys() else "") or ""}


def _cliente(tenant_id: int, cliente_id: int):
    c = nucleo.obtener_cliente(tenant_id, cliente_id)
    if c is None:
        raise ErrorDocumento("Cliente no encontrado.")
    return c


def _firmante_por_defecto(cliente) -> tuple[str, str]:
    """El correo y el nombre de quien firma si no se indica otro: el contacto principal del cliente con correo o, si no, el propio cliente."""
    for k in nucleo.listar_contactos(cliente["tenant_id"], cliente["id"]):
        if k["principal"] and (k["email"] or "").strip():
            return k["email"].strip(), k["nombre"]
    return (cliente["email"] or "").strip(), cliente["nombre"]


def formulario(tenant_id: int, cliente_id: int, clave: str) -> dict:
    """Lo que necesita la pantalla para pedir los datos de un documento: sus campos con valores por defecto (los recordados del despacho, el firmante propuesto) y lo que falta de la ficha."""
    p = _plantilla(clave)
    c = _cliente(tenant_id, cliente_id)
    recordados = ajustes(tenant_id)
    campos = [dict(f, valor=recordados.get(f["clave"]) or f["defecto"]) for f in p["campos"]]
    email, nombre = _firmante_por_defecto(c)
    return {"clave": clave, "titulo": p["titulo"], "descripcion": p["descripcion"], "campos": campos, "firmante_email": email, "firmante_nombre": nombre,
            "lugar": recordados["lugar"], "faltan": datos_que_faltan(tenant_id, c, clave)}


def datos_que_faltan(tenant_id: int, cliente, clave: str) -> list[str]:
    """Lo imprescindible de la ficha del cliente y del despacho que no está rellenado todavía."""
    faltan = []
    exigidos = [("nif", "NIF del cliente"), ("direccion", "Dirección del cliente")]
    if clave == "consentimiento_comercial":
        exigidos = [("email", "Correo del cliente")]
    elif clave == "consentimiento_rgpd":
        exigidos = [("nif", "NIF del cliente")]
    for campo, etiqueta in exigidos:
        if not (cliente[campo] or "").strip():
            faltan.append(etiqueta)
    d = _despacho(tenant_id)
    for campo, etiqueta in (("cif", "CIF del despacho"), ("direccion", "Dirección fiscal del despacho")):
        if not d[campo].strip():
            faltan.append(etiqueta)
    return faltan


def _limpiar(texto, largo=2000) -> str:
    return re.sub(r"[ \t]+", " ", str(texto or "").replace("\r\n", "\n")).strip()[:largo]


def _datos_validados(tenant_id: int, clave: str, datos: dict) -> dict:
    """Los campos del documento limpios y validados (IBAN con sus dígitos de control, opciones permitidas, obligatorios)."""
    limpios = {}
    for f in _plantilla(clave)["campos"]:
        valor = _limpiar(datos.get(f["clave"]) if f["clave"] in datos else f["defecto"], 2000 if f["tipo"] == "area" else 300)
        if f["tipo"] == "select":
            valor = valor if valor in f["opciones"] else (f["defecto"] or f["opciones"][0])
        if not valor and f["obligatorio"]:
            raise ErrorDocumento(f"Falta «{f['etiqueta']}».")
        if f["tipo"] == "iban" and valor:
            try:
                valor = iban_mod.validar(valor)
            except iban_mod.IbanNoValido as e:
                raise ErrorDocumento(str(e)) from e
        limpios[f["clave"]] = valor
    return limpios


def _valores(tenant_id: int, cliente, datos: dict, lugar: str, hoy: date) -> dict:
    d = _despacho(tenant_id)
    v = {"cliente.nombre": cliente["nombre"] or "", "cliente.nif": cliente["nif"] or "", "cliente.direccion": cliente["direccion"] or "", "cliente.email": cliente["email"] or "",
         "cliente.telefono": cliente["telefono"] or "", "despacho.nombre": d["nombre"], "despacho.cif": d["cif"], "despacho.direccion": d["direccion"], "fecha": _fecha_larga(hoy), "lugar": lugar}
    v.update(datos)
    return v


def _rellenar(texto: str, valores: dict) -> str:
    return _VARIABLE.sub(lambda m: str(valores[m.group(1)]) if m.group(1) in valores else "________", texto)


def componer(tenant_id: int, cliente_id: int, clave: str, datos: dict, *, lugar: str = "", hoy: date | None = None) -> dict:
    """El texto final del documento con los datos del cliente y los campos rellenados. Lanza `ErrorDocumento` si falta algo imprescindible; no guarda nada."""
    hoy = hoy or date.today()
    p = _plantilla(clave)
    c = _cliente(tenant_id, cliente_id)
    faltan = datos_que_faltan(tenant_id, c, clave)
    if faltan:
        raise ErrorDocumento("Antes de generarlo, completa: " + ", ".join(faltan) + ".")
    datos = dict(datos)
    if clave == "mandato_sepa":
        datos["referencia"] = re.sub(r"[^A-Za-z0-9]", "", str(datos.get("referencia") or ""))[:35] or f"GW{cliente_id}{hoy.strftime('%Y%m%d')}"
    limpios = _datos_validados(tenant_id, clave, datos)
    if clave == "mandato_sepa":
        limpios["texto_esquema"] = TEXTO_ESQUEMA_B2B if limpios["esquema"] == "B2B" else TEXTO_ESQUEMA_CORE
    if clave == "autorizacion_aeat":
        rep = limpios.get("representante_cliente", "")
        limpios["representante_cliente"] = f", representado por {rep}" if rep else ""
    lugar = _limpiar(lugar, 100) or "________"
    texto = _rellenar(texto_de(tenant_id, clave)[0], _valores(tenant_id, c, limpios, lugar, hoy)).strip()
    return {"titulo": f"{p['titulo']} — {c['nombre']}", "texto": texto, "datos": limpios, "lugar": lugar}


# --- PDF -------------------------------------------------------------------------------------------------------------------

def pdf_de(titulo: str, texto: str, despacho: str = "") -> tuple[bytes, int]:
    """(PDF, número de páginas). Deja libre, al pie de la última página, el hueco donde Documenso coloca el campo de firma. Es determinista: el mismo texto da siempre el mismo PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    base = getSampleStyleSheet()["Normal"]
    cuerpo = ParagraphStyle("cuerpo", parent=base, fontName="Helvetica", fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=6)
    epigrafe = ParagraphStyle("epigrafe", parent=cuerpo, fontName="Helvetica-Bold", fontSize=11, leading=15, alignment=0, spaceBefore=8, spaceAfter=4)
    principal = ParagraphStyle("principal", parent=epigrafe, fontSize=15, leading=19, spaceBefore=0, spaceAfter=8)
    vineta = ParagraphStyle("vineta", parent=cuerpo, leftIndent=14, bulletIndent=2)

    def armar() -> list:
        """Las piezas del documento; se crean de nuevo en cada pasada porque reportlab las consume al maquetar."""
        historia = []
        primero = True
        for bloque in re.split(r"\n\s*\n", texto.strip()):
            lineas = [l for l in bloque.split("\n") if l.strip()]
            i = 0
            while i < len(lineas):
                l = lineas[i]
                if l.startswith("# "):
                    historia.append(Paragraph(escape(l[2:].strip()), principal if primero else epigrafe))
                    primero = False
                    i += 1
                elif l.startswith("- "):
                    historia.append(Paragraph(escape(l[2:].strip()), vineta, bulletText="•"))
                    i += 1
                else:
                    fin = i
                    while fin < len(lineas) and not lineas[fin].startswith(("# ", "- ")):
                        fin += 1
                    historia.append(Paragraph("<br/>".join(escape(x.strip()) for x in lineas[i:fin]), cuerpo))
                    i = fin
            historia.append(Spacer(1, 2))
        return historia

    ancho, alto = A4

    def construir(total: int) -> tuple[bytes, int]:
        salida = io.BytesIO()
        paginas = {"n": 0}

        def pie(c, doc):
            paginas["n"] = doc.page
            c.saveState()
            c.setFont("Helvetica", 7.5)
            c.setFillColor(colors.HexColor("#666666"))
            c.drawString(2 * cm, 1.1 * cm, f"{despacho} · {titulo}"[:110])
            c.drawRightString(ancho - 2 * cm, 1.1 * cm, f"Página {doc.page} de {total or '?'}")
            if total and doc.page == total:
                x, y, w, h = (FIRMA[0] / 100 * ancho, alto * (1 - (FIRMA[1] + FIRMA[3]) / 100), FIRMA[2] / 100 * ancho, FIRMA[3] / 100 * alto)
                c.setStrokeColor(colors.HexColor("#999999"))
                c.setDash(3, 2)
                c.rect(x, y, w, h)
                c.setDash()
                c.drawString(x, y - 9, "Firma")
            c.restoreState()

        doc = SimpleDocTemplate(salida, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=4 * cm, title=titulo, author=despacho or "Guilda Work",
                                invariant=1)
        doc.build(armar(), onFirstPage=pie, onLaterPages=pie)
        return salida.getvalue(), paginas["n"]

    _, n = construir(0)
    return construir(n)


# --- Ciclo de vida ----------------------------------------------------------------------------------------------------------

def _fila(f) -> dict:
    d = dict(f)
    try:
        d["datos"] = json.loads(d["datos"])
    except ValueError:
        d["datos"] = {}
    d["nombre_plantilla"] = PLANTILLAS.get(d["plantilla"], {}).get("titulo", d["plantilla"])
    return d


def obtener(tenant_id: int, cliente_id: int, documento_id: int) -> dict | None:
    _cliente(tenant_id, cliente_id)
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM documentos_firma WHERE id = ? AND tenant_id = ? AND cliente_id = ?", (documento_id, tenant_id, cliente_id)).fetchone()
    finally:
        conn.close()
    return _fila(f) if f else None


def listar_de_cliente(tenant_id: int, cliente_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM documentos_firma WHERE tenant_id = ? AND cliente_id = ? ORDER BY creado_en DESC, id DESC", (tenant_id, cliente_id)).fetchall()
    finally:
        conn.close()
    return [_fila(f) for f in filas]


def crear_borrador(tenant_id: int, usuario_id: int, cliente_id: int, clave: str, datos: dict, *, lugar: str = "", firmante_email: str = "", firmante_nombre: str = "",
                   hoy: date | None = None) -> int:
    _exigir_escritura(tenant_id, usuario_id)
    c = _cliente(tenant_id, cliente_id)
    compuesto = componer(tenant_id, cliente_id, clave, datos, lugar=lugar, hoy=hoy)
    por_defecto_email, por_defecto_nombre = _firmante_por_defecto(c)
    email = (firmante_email or por_defecto_email).strip()
    nombre = _limpiar(firmante_nombre or por_defecto_nombre, 100)
    if "@" not in email or len(email) > 200:
        raise ErrorDocumento("Indica el correo electrónico de quien firma.")
    pdf, _n = pdf_de(compuesto["titulo"], compuesto["texto"], _despacho(tenant_id)["nombre"])
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO documentos_firma (tenant_id, cliente_id, plantilla, titulo, datos, texto, firmante_email, firmante_nombre, pdf_sha256, creado_por, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, cliente_id, clave, compuesto["titulo"], json.dumps(compuesto["datos"], ensure_ascii=False), compuesto["texto"], email, nombre, hashlib.sha256(pdf).hexdigest(), usuario_id, _ahora()))
        documento_id = cur.lastrowid
        _recordar(conn, tenant_id, usuario_id, {**compuesto["datos"], "lugar": lugar})
        auditoria.registrar(tenant_id, usuario_id, "documento_firma.creado", "documentos_firma", documento_id, {"plantilla": clave, "cliente_id": cliente_id}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return documento_id


def pdf_del_documento(tenant_id: int, cliente_id: int, documento_id: int) -> tuple[str, bytes]:
    d = obtener(tenant_id, cliente_id, documento_id)
    if d is None:
        raise ErrorDocumento("Documento no encontrado.")
    pdf, _n = pdf_de(d["titulo"], d["texto"], _despacho(tenant_id)["nombre"])
    return d["titulo"], pdf


def _clave_documenso(tenant_id: int) -> str:
    t = db.obtener_tenant(tenant_id)
    return (t["documenso_api_key"] if t and "documenso_api_key" in t.keys() else "") or ""


def puede_enviar(tenant_id: int) -> bool:
    return bool(_clave_documenso(tenant_id))


def enviar(tenant_id: int, usuario_id: int, cliente_id: int, documento_id: int) -> str:
    """Manda el borrador a firmar con Documenso. Devuelve el id del documento allí. Solo se envía un borrador; uno ya enviado no se reenvía (se cancela y se crea otro)."""
    _exigir_escritura(tenant_id, usuario_id)
    d = obtener(tenant_id, cliente_id, documento_id)
    if d is None:
        raise ErrorDocumento("Documento no encontrado.")
    if d["estado"] != "borrador":
        raise ErrorDocumento("Este documento ya se envió: para volver a enviarlo, cancélalo y crea otro.")
    clave = _clave_documenso(tenant_id)
    if not clave:
        raise ErrorDocumento("El despacho no tiene configurado Documenso: descarga el PDF para firmarlo por otro medio.")
    pdf, paginas = pdf_de(d["titulo"], d["texto"], _despacho(tenant_id)["nombre"])
    huella = hashlib.sha256(pdf).hexdigest()
    try:
        doc = documenso.crear_documento(clave, d["titulo"], pdf, [{"email": d["firmante_email"], "nombre": d["firmante_nombre"]}], pagina=paginas, campo=FIRMA)
        ident = str(doc.get("id") or doc.get("envelopeId") or "")
        if not ident:
            raise ErrorDocumento("Documenso no devolvió el identificador del documento.")
        documenso.enviar_a_firma(clave, ident)
    except documenso.ErrorDocumenso as e:
        raise ErrorDocumento(str(e)) from e
    conn = db.get_connection()
    try:
        conn.execute("UPDATE documentos_firma SET estado = 'enviado', documenso_id = ?, pdf_sha256 = ?, enviado_en = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                     (ident, huella, _ahora(), _ahora(), documento_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "documento_firma.enviado", "documentos_firma", documento_id, {"plantilla": d["plantilla"], "documenso_id": ident}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return ident


def cancelar(tenant_id: int, usuario_id: int, cliente_id: int, documento_id: int) -> None:
    """Retira un borrador o un envío pendiente. No toca lo ya firmado."""
    _exigir_escritura(tenant_id, usuario_id)
    d = obtener(tenant_id, cliente_id, documento_id)
    if d is None:
        raise ErrorDocumento("Documento no encontrado.")
    if d["estado"] not in ("borrador", "enviado", "rechazado"):
        raise ErrorDocumento("Un documento firmado no se cancela.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE documentos_firma SET estado = 'cancelado', actualizado_en = ? WHERE id = ? AND tenant_id = ?", (_ahora(), documento_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "documento_firma.cancelado", "documentos_firma", documento_id, {"estado_anterior": d["estado"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def refrescar(tenant_id: int, usuario_id: int, cliente_id: int, documento_id: int) -> str:
    """Pregunta a Documenso por el estado de un envío pendiente. Si ya está firmado, guarda el PDF firmado en los documentos del cliente y aplica el efecto del documento. Devuelve el estado."""
    d = obtener(tenant_id, cliente_id, documento_id)
    if d is None:
        raise ErrorDocumento("Documento no encontrado.")
    if d["estado"] != "enviado" or not d["documenso_id"]:
        return d["estado"]
    clave = _clave_documenso(tenant_id)
    try:
        remoto = documenso.estado_documento(clave, d["documenso_id"])
        firmado_pdf = documenso.descargar_firmado(clave, d["documenso_id"]) if remoto == "COMPLETED" else None
    except documenso.ErrorDocumenso as e:
        raise ErrorDocumento(str(e)) from e
    if remoto == "REJECTED":
        nuevo = "rechazado"
    elif remoto == "COMPLETED":
        nuevo = "firmado"
    else:
        return "enviado"
    guardado = None
    if nuevo == "firmado" and firmado_pdf:
        resultado, guardado = almacen_documentos.guardar(usuario_id, f"{d['titulo']} (firmado).pdf", "application/pdf", firmado_pdf, cliente_id=cliente_id, categoria="Firmados")
        if resultado == "duplicado":
            pass
        elif resultado != "ok":
            guardado = None
    conn = db.get_connection()
    try:
        conn.execute("UPDATE documentos_firma SET estado = ?, firmado_en = ?, documento_firmado_id = ?, actualizado_en = ? WHERE id = ? AND tenant_id = ?",
                     (nuevo, _ahora() if nuevo == "firmado" else None, guardado, _ahora(), documento_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, f"documento_firma.{nuevo}", "documentos_firma", documento_id, {"plantilla": d["plantilla"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    if nuevo == "firmado" and d["plantilla"] in AL_FIRMAR:
        AL_FIRMAR[d["plantilla"]](tenant_id, usuario_id, {**d, "estado": "firmado", "documento_firmado_id": guardado})
    return nuevo


def pendientes_del_despacho(tenant_id: int, usuario_id: int, *, ahora: datetime | None = None, limite: int = 300) -> list[dict]:
    """Todos los envíos aún sin firmar del despacho (de los clientes que la persona ve), del más antiguo al más reciente, con los días que llevan esperando y si se les puede recordar."""
    ahora = ahora or datetime.now()
    cond, params = acceso.condicion_nucleo(tenant_id, usuario_id, "c.id")
    sql = ("SELECT d.*, c.nombre AS cliente_nombre FROM documentos_firma d JOIN clientes c ON c.id = d.cliente_id AND c.tenant_id = d.tenant_id "
           "WHERE d.tenant_id = ? AND d.estado = 'enviado'" + (f" AND {cond}" if cond else "") + " ORDER BY d.enviado_en, d.id LIMIT ?")
    conn = db.get_connection()
    try:
        filas = conn.execute(sql, [tenant_id, *params, limite]).fetchall()
    finally:
        conn.close()
    salida = []
    for f in filas:
        d = _fila(f)
        try:
            d["dias"] = max(0, (ahora - datetime.fromisoformat(d["enviado_en"])).days) if d.get("enviado_en") else 0
        except ValueError:
            d["dias"] = 0
        d["puede_recordar"] = bool(d["documenso_id"]) and (d["recordatorios"] or 0) < MAX_RECORDATORIOS
        salida.append(d)
    return salida


# --- Recordatorios a quien no firma ------------------------------------------------------------------------------------------

def recordatorio_dias(tenant_id: int) -> int:
    """Días sin firmar tras los que el sistema reenvía solo el aviso de Documenso (0 = no lo hace). Lo fija la dirección; hasta `MAX_RECORDATORIOS` veces por documento."""
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT ajustes FROM documentos_plantillas WHERE tenant_id = ? AND clave = ?", (tenant_id, AJUSTES)).fetchone()
    finally:
        conn.close()
    try:
        return max(0, min(int(json.loads(f["ajustes"]).get("recordatorio_dias") or 0), MAX_DIAS_RECORDATORIO)) if f else 0
    except (ValueError, TypeError, AttributeError):
        return 0


def fijar_recordatorio_dias(tenant_id: int, usuario_id: int, dias) -> None:
    _exigir_direccion(usuario_id)
    try:
        dias = int(dias or 0)
    except (TypeError, ValueError):
        raise ErrorDocumento("Los días no son un número.") from None
    if not 0 <= dias <= MAX_DIAS_RECORDATORIO:
        raise ErrorDocumento(f"Elige entre 0 (no recordar) y {MAX_DIAS_RECORDATORIO} días.")
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT ajustes FROM documentos_plantillas WHERE tenant_id = ? AND clave = ?", (tenant_id, AJUSTES)).fetchone()
        try:
            actuales = json.loads(f["ajustes"]) if f else {}
        except ValueError:
            actuales = {}
        actuales["recordatorio_dias"] = dias
        conn.execute(
            "INSERT INTO documentos_plantillas (tenant_id, clave, cuerpo, ajustes, actualizado_en, actualizado_por) VALUES (?, ?, NULL, ?, ?, ?) "
            "ON CONFLICT (tenant_id, clave) DO UPDATE SET ajustes = excluded.ajustes, actualizado_en = excluded.actualizado_en, actualizado_por = excluded.actualizado_por",
            (tenant_id, AJUSTES, json.dumps(actuales, ensure_ascii=False), _ahora(), usuario_id))
        auditoria.registrar(tenant_id, usuario_id, "documento_firma.recordatorio_dias", "documentos_firma", None, {"dias": dias}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def toca_recordar(d: dict, dias: int, ahora: datetime | None = None) -> bool:
    """¿Lleva este envío `dias` o más sin firmar desde el último aviso (o desde el envío) y aún no ha agotado los recordatorios?"""
    if d["estado"] != "enviado" or not d.get("documenso_id") or dias <= 0 or (d.get("recordatorios") or 0) >= MAX_RECORDATORIOS:
        return False
    desde = d.get("recordado_en") or d.get("enviado_en")
    try:
        return bool(desde) and (ahora or datetime.now()) - datetime.fromisoformat(desde) >= timedelta(days=dias)
    except ValueError:
        return False


def recordar(tenant_id: int, usuario_id: int, cliente_id: int, documento_id: int) -> str:
    """Reenvía el aviso de firma a quien aún no ha firmado. Antes pregunta a Documenso: si ya estaba firmado, lo anota y no molesta. Devuelve el estado final."""
    _exigir_escritura(tenant_id, usuario_id)
    d = obtener(tenant_id, cliente_id, documento_id)
    if d is None:
        raise ErrorDocumento("Documento no encontrado.")
    if d["estado"] != "enviado" or not d["documenso_id"]:
        raise ErrorDocumento("Solo se puede recordar un documento que está pendiente de firma.")
    if (d["recordatorios"] or 0) >= MAX_RECORDATORIOS:
        raise ErrorDocumento(f"Ya se ha recordado {MAX_RECORDATORIOS} veces: habla con la persona por otro medio.")
    nuevo = refrescar(tenant_id, usuario_id, cliente_id, documento_id)
    if nuevo != "enviado":
        return nuevo
    try:
        avisados = documenso.reenviar_a_firma(_clave_documenso(tenant_id), d["documenso_id"])
    except documenso.ErrorDocumenso as e:
        raise ErrorDocumento(str(e)) from e
    if not avisados:
        return "enviado"
    conn = db.get_connection()
    try:
        conn.execute("UPDATE documentos_firma SET recordado_en = ?, recordatorios = recordatorios + 1, actualizado_en = ? WHERE id = ? AND tenant_id = ?", (_ahora(), _ahora(), documento_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, "documento_firma.recordar", "documentos_firma", documento_id, {"plantilla": d["plantilla"], "n": (d["recordatorios"] or 0) + 1}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return "recordado"


def recordar_pendientes(ahora: datetime | None = None) -> dict:
    """Para el temporizador: a los despachos que lo han pedido, reenvía el aviso de los envíos que llevan sus días sin firmar. Devuelve `{recordados, errores}`."""
    from .bd import contexto
    r = {"recordados": 0, "errores": 0}
    dias_de: dict[int, int] = {}
    for d in _pendientes_de_documenso(limite=1000):
        t = d["tenant_id"]
        with contexto.en_despacho(t):
            if t not in dias_de:
                dias_de[t] = recordatorio_dias(t)
            if not toca_recordar(d, dias_de[t], ahora):
                continue
            try:
                if recordar(t, d["creado_por"], d["cliente_id"], d["id"]) == "recordado":
                    r["recordados"] += 1
            except ErrorDocumento:
                r["errores"] += 1
    return r


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM documentos_firma WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM documentos_plantillas WHERE tenant_id = ?", (tenant_id,))


# --- Aviso automático cuando Documenso firma (webhook y barrido de respaldo) --------------------------------------------------

def _avisar_resultado(tenant_id: int, d: dict, nuevo: str) -> None:
    """Avisa a quien creó el documento (en la app y por push) de que se ha firmado o rechazado. Nunca impide el resto."""
    try:
        from . import notificaciones
        titulo = f"{'Firmado' if nuevo == 'firmado' else 'Rechazado'}: {d['nombre_plantilla']}"
        cuerpo = f"{d['firmante_nombre'] or d['firmante_email']} ha {'firmado' if nuevo == 'firmado' else 'rechazado'} «{d['titulo']}»."
        notificaciones.crear_y_enviar(d["creado_por"], "documento_firma", titulo, cuerpo, f"/documentos-firma/clientes/{d['cliente_id']}/{d['id']}", despacho_id=tenant_id)
    except Exception:       # noqa: BLE001 -- el aviso es un extra
        pass


def _pendientes_de_documenso(documenso_id: str | None = None, limite: int = 200) -> list[dict]:
    """Los envíos pendientes de firma de TODOS los despachos (o el de un id de Documenso)."""
    from .bd import contexto
    with contexto.como_plataforma():
        conn = db.get_connection(plataforma=True)
        try:
            if documenso_id:
                filas = conn.execute("SELECT * FROM documentos_firma WHERE estado = 'enviado' AND documenso_id = ?", (str(documenso_id),)).fetchall()
            else:
                filas = conn.execute("SELECT * FROM documentos_firma WHERE estado = 'enviado' AND documenso_id IS NOT NULL ORDER BY id LIMIT ?", (limite,)).fetchall()
        finally:
            conn.close()
    return [_fila(f) for f in filas]


def _refrescar_y_avisar(d: dict) -> str:
    from .bd import contexto
    with contexto.en_despacho(d["tenant_id"]):
        try:
            nuevo = refrescar(d["tenant_id"], d["creado_por"], d["cliente_id"], d["id"])
        except ErrorDocumento:
            return "enviado"
    if nuevo in ("firmado", "rechazado"):
        _avisar_resultado(d["tenant_id"], d, nuevo)
    return nuevo


def refrescar_por_documenso(documenso_id: str) -> list[str]:
    """Lo llama el webhook: consulta a Documenso el estado REAL de ese documento (no se fía de lo que diga el aviso) y, si ya está firmado o rechazado, lo anota y avisa."""
    return [_refrescar_y_avisar(d) for d in _pendientes_de_documenso(documenso_id)]


def sincronizar_pendientes(limite: int = 200) -> dict:
    """Respaldo del webhook (por si Documenso no pudo avisar): repasa los envíos pendientes. Devuelve `{revisados, firmados, rechazados}`."""
    r = {"revisados": 0, "firmados": 0, "rechazados": 0}
    for d in _pendientes_de_documenso(limite=limite):
        r["revisados"] += 1
        nuevo = _refrescar_y_avisar(d)
        if nuevo == "firmado":
            r["firmados"] += 1
        elif nuevo == "rechazado":
            r["rechazados"] += 1
    return r
