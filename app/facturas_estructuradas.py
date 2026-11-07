"""Facturas electrónicas estructuradas: Facturae (el XML oficial español, 3.2.x), UBL 2.1 (Peppol BIS, la factura electrónica europea) y CII (Factur-X / ZUGFeRD, el XML que viaja DENTRO de algunos PDF).

Es lectura exacta: no hay IA ni probabilidad, solo el dato tal como lo escribió quien emitió la factura. Por eso es lo primero que se intenta, y lo que sale de aquí no necesita revisión de lectura
(sí las comprobaciones de siempre: NIF, cuadre, duplicados).

`extraer(contenido, tipo_mime, nombre)` devuelve `{"formato", "datos"}` con los datos en la misma forma que pide el prompt de la IA (emisor, receptor, número, fechas, líneas por tipo de IVA, total…),
de modo que el resto de la lectura no distingue de dónde vienen, o None si el archivo no es una factura electrónica que sepamos leer. El XML se interpreta sin resolver entidades ni abrir la red
(un XML hostil no puede leer ficheros ni hacer peticiones)."""
from __future__ import annotations

import io
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation

logger = logging.getLogger("guilda")

MAX_XML_BYTES = 5 * 1024 * 1024
NOMBRES_XML_INCRUSTADO = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "factur-x", "invoice.xml", "ubl.xml")
TIPOS_ABONO_UBL = {"381", "383", "384"}            # nota de crédito, nota de débito corregida, factura rectificada
TIPOS_ABONO_CII = {"381", "383", "384", "261", "262"}


def _analizar(xml: bytes):
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False, remove_comments=True, remove_pis=True)
    return etree.fromstring(xml, parser)


def _local(el) -> str:
    t = el.tag
    return t.rsplit("}", 1)[-1] if isinstance(t, str) else ""


def _hijos(el, *camino):
    """Los elementos que cuelgan de `el` siguiendo ese camino de nombres locales (sin espacio de nombres)."""
    actuales = [el]
    for nombre in camino:
        actuales = [h for a in actuales for h in a if _local(h) == nombre]
    return actuales


def _primero(el, *camino) -> str:
    for h in _hijos(el, *camino):
        t = (h.text or "").strip()
        if t:
            return t
    return ""


def _desc(el, nombre: str):
    return [e for e in el.iter() if _local(e) == nombre]


def _dec(texto) -> Decimal | None:
    try:
        d = Decimal(str(texto).strip().replace(",", "."))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _num(valor: Decimal | None, absoluto: bool = True) -> str:
    if valor is None:
        return ""
    return f"{abs(valor) if absoluto else valor:.2f}"


def _fecha(texto: str) -> str:
    """AAAA-MM-DD a partir de «2026-10-15», «20261015» o «2026-10-15T10:00:00»; «» si no se entiende."""
    t = (texto or "").strip()
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", t)
    if not m:
        return ""
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return ""


def _nif(texto: str) -> str:
    """El NIF sin prefijo de país («ESB12345678» → «B12345678»), en mayúsculas y sin espacios ni guiones."""
    t = re.sub(r"[\s\-.]", "", (texto or "")).upper()
    return t[2:] if re.match(r"^ES[A-Z0-9]\d{7}[A-Z0-9]$", t) else t


def _resultado(formato: str, d: dict) -> dict | None:
    if not (d.get("numero") and d.get("fecha") and (d.get("lineas") or d.get("total"))):
        return None                                        # un XML sin lo esencial no se da por leído: que lo lea la IA o una persona
    d["evidencias"] = {}
    return {"formato": formato, "datos": d}


# --- Facturae ------------------------------------------------------------------------------------------------------------------------------------------------

def _facturae(raiz) -> dict | None:
    facturas = _hijos(raiz, "Invoices", "Invoice")
    if not facturas:
        return None
    f = facturas[0]

    def parte(nombre: str) -> tuple[str, str]:
        p = _hijos(raiz, "Parties", nombre)
        if not p:
            return "", ""
        nif = _primero(p[0], "TaxIdentification", "TaxIdentificationNumber")
        legal = _primero(p[0], "LegalEntity", "CorporateName") or _primero(p[0], "LegalEntity", "TradeName")
        if not legal:
            ind = _hijos(p[0], "Individual")
            legal = " ".join(x for x in (_primero(ind[0], "Name"), _primero(ind[0], "FirstSurname"), _primero(ind[0], "SecondSurname")) if x) if ind else ""
        return legal, _nif(nif)

    emisor, emisor_nif = parte("SellerParty")
    receptor, receptor_nif = parte("BuyerParty")
    serie, numero = _primero(f, "InvoiceHeader", "InvoiceSeriesCode"), _primero(f, "InvoiceHeader", "InvoiceNumber")
    clase = _primero(f, "InvoiceHeader", "InvoiceClass")
    corrige = _hijos(f, "InvoiceHeader", "Corrective")
    totales = _hijos(f, "InvoiceTotals")
    total = _dec(_primero(totales[0], "InvoiceTotal")) if totales else None
    lineas = []
    for t in _hijos(f, "TaxesOutputs", "Tax"):
        if _primero(t, "TaxTypeCode") not in ("01", "03", "02"):               # IVA, IGIC (Canarias), IPSI (Ceuta y Melilla)
            continue
        base = _dec(_primero(t, "TaxableBase", "TotalAmount"))
        if base is None:
            continue
        linea = {"base": _num(base), "pct_iva": _num(_dec(_primero(t, "TaxRate")) or Decimal(0)), "cuota_iva": _num(_dec(_primero(t, "TaxAmount", "TotalAmount")) or Decimal(0))}
        rec = _dec(_primero(t, "EquivalenceSurcharge"))
        if rec:
            linea["pct_recargo"] = _num(rec)
        lineas.append(linea)
    retenciones = [(_dec(_primero(t, "TaxRate")), _dec(_primero(t, "TaxableBase", "TotalAmount"))) for t in _hijos(f, "TaxesWithheld", "Tax") if _primero(t, "TaxTypeCode") == "04"]
    tipos_retencion = {r for r, _b in retenciones if r}
    if len(tipos_retencion) == 1 and lineas:                                    # una sola retención de IRPF: se aplica a las líneas (como las leería una persona)
        for linea in lineas:
            linea["pct_retencion"] = _num(next(iter(tipos_retencion)))
    suplidos = sum((_dec(_primero(g, "ReimbursableExpensesAmount")) or Decimal(0) for g in _hijos(f, "ReimbursableExpenses", "ReimbursableExpenses")), Decimal(0))
    concepto = _primero(f, "Items", "InvoiceLine", "ItemDescription")
    return _resultado("facturae", {
        "emisor_nombre": emisor, "emisor_nif": emisor_nif, "receptor_nombre": receptor, "receptor_nif": receptor_nif, "numero": f"{serie}{numero}" if serie and not numero.startswith(serie) else numero,
        "fecha": _fecha(_primero(f, "InvoiceIssueData", "IssueDate")), "fecha_operacion": _fecha(_primero(f, "InvoiceIssueData", "OperationDate")),
        "es_abono": clase in ("OR", "CR", "OC", "CC") or bool(corrige) or (total is not None and total < 0),
        "rectifica_numero": _primero(corrige[0], "InvoiceNumber") if corrige else "", "rectifica_fecha": "", "concepto": concepto[:60],
        "lineas": lineas, "suplidos": _num(suplidos) if suplidos else "", "total": _num(total)})


# --- UBL 2.1 (Peppol BIS) ------------------------------------------------------------------------------------------------------------------------------------

def _ubl(raiz) -> dict | None:
    abono = _local(raiz) == "CreditNote"

    def parte(nombre: str) -> tuple[str, str]:
        p = _hijos(raiz, nombre, "Party")
        if not p:
            return "", ""
        nombre_legal = _primero(p[0], "PartyLegalEntity", "RegistrationName") or _primero(p[0], "PartyName", "Name")
        nif = _primero(p[0], "PartyTaxScheme", "CompanyID") or _primero(p[0], "PartyLegalEntity", "CompanyID") or _primero(p[0], "PartyIdentification", "ID")
        return nombre_legal, _nif(nif)

    emisor, emisor_nif = parte("AccountingSupplierParty")
    receptor, receptor_nif = parte("AccountingCustomerParty")
    tipo = _primero(raiz, "InvoiceTypeCode") or _primero(raiz, "CreditNoteTypeCode")
    lineas = []
    for sub in _hijos(raiz, "TaxTotal", "TaxSubtotal"):
        base = _dec(_primero(sub, "TaxableAmount"))
        if base is None:
            continue
        pct = _dec(_primero(sub, "TaxCategory", "Percent")) or Decimal(0)
        lineas.append({"base": _num(base), "pct_iva": _num(pct), "cuota_iva": _num(_dec(_primero(sub, "TaxAmount")) or Decimal(0))})
    total = _dec(_primero(raiz, "LegalMonetaryTotal", "PayableAmount")) or _dec(_primero(raiz, "LegalMonetaryTotal", "TaxInclusiveAmount"))
    ref = _hijos(raiz, "BillingReference", "InvoiceDocumentReference")
    return _resultado("ubl", {
        "emisor_nombre": emisor, "emisor_nif": emisor_nif, "receptor_nombre": receptor, "receptor_nif": receptor_nif, "numero": _primero(raiz, "ID"), "fecha": _fecha(_primero(raiz, "IssueDate")),
        "fecha_operacion": _fecha(_primero(raiz, "TaxPointDate")) or _fecha(_primero(raiz, "ActualDeliveryDate")) or _fecha(_primero(raiz, "Delivery", "ActualDeliveryDate")),
        "es_abono": abono or tipo in TIPOS_ABONO_UBL, "rectifica_numero": _primero(ref[0], "ID") if ref else "", "rectifica_fecha": _fecha(_primero(ref[0], "IssueDate")) if ref else "",
        "concepto": (_primero(raiz, "InvoiceLine", "Item", "Name") or _primero(raiz, "CreditNoteLine", "Item", "Name") or _primero(raiz, "Note"))[:60], "lineas": lineas, "suplidos": "", "total": _num(total)})


# --- CII (Factur-X, ZUGFeRD, XRechnung CII) -----------------------------------------------------------------------------------------------------------------

def _cii(raiz) -> dict | None:
    doc = _hijos(raiz, "ExchangedDocument")
    transaccion = _hijos(raiz, "SupplyChainTradeTransaction")
    if not doc or not transaccion:
        return None
    t = transaccion[0]
    acuerdo = _hijos(t, "ApplicableHeaderTradeAgreement")
    liquidacion = _hijos(t, "ApplicableHeaderTradeSettlement")

    def parte(nombre: str) -> tuple[str, str]:
        p = _hijos(acuerdo[0], nombre) if acuerdo else []
        if not p:
            return "", ""
        registros = _hijos(p[0], "SpecifiedTaxRegistration", "ID")
        va = next((r.text for r in registros if (r.get("schemeID") or "").upper() == "VA" and r.text), None) or next((r.text for r in registros if r.text), "")
        return _primero(p[0], "Name"), _nif(va or _primero(p[0], "SpecifiedLegalOrganization", "ID"))

    emisor, emisor_nif = parte("SellerTradeParty")
    receptor, receptor_nif = parte("BuyerTradeParty")
    lineas = []
    for imp in _hijos(liquidacion[0], "ApplicableTradeTax") if liquidacion else []:
        if _primero(imp, "TypeCode").upper() not in ("VAT", ""):
            continue
        base = _dec(_primero(imp, "BasisAmount"))
        if base is None:
            continue
        lineas.append({"base": _num(base), "pct_iva": _num(_dec(_primero(imp, "RateApplicablePercent")) or Decimal(0)), "cuota_iva": _num(_dec(_primero(imp, "CalculatedAmount")) or Decimal(0))})
    resumen = _hijos(liquidacion[0], "SpecifiedTradeSettlementHeaderMonetarySummation") if liquidacion else []
    total = (_dec(_primero(resumen[0], "GrandTotalAmount")) or _dec(_primero(resumen[0], "DuePayableAmount"))) if resumen else None
    referencia = _hijos(liquidacion[0], "InvoiceReferencedDocument") if liquidacion else []
    return _resultado("cii", {
        "emisor_nombre": emisor, "emisor_nif": emisor_nif, "receptor_nombre": receptor, "receptor_nif": receptor_nif, "numero": _primero(doc[0], "ID"),
        "fecha": _fecha(_primero(doc[0], "IssueDateTime", "DateTimeString")), "fecha_operacion": _fecha(_primero(t, "ApplicableHeaderTradeDelivery", "ActualDeliverySupplyChainEvent", "OccurrenceDateTime", "DateTimeString")),
        "es_abono": _primero(doc[0], "TypeCode") in TIPOS_ABONO_CII, "rectifica_numero": _primero(referencia[0], "IssuerAssignedID") if referencia else "",
        "rectifica_fecha": _fecha(_primero(referencia[0], "FormattedIssueDateTime", "DateTimeString")) if referencia else "",
        "concepto": (_primero(t, "IncludedSupplyChainTradeLineItem", "SpecifiedTradeProduct", "Name"))[:60], "lineas": lineas, "suplidos": "", "total": _num(total)})


def _desde_xml(xml: bytes) -> dict | None:
    if not xml or len(xml) > MAX_XML_BYTES:
        return None
    try:
        raiz = _analizar(xml)
    except Exception:  # noqa: BLE001 -- XML mal formado
        return None
    nombre = _local(raiz)
    try:
        if nombre == "Facturae":
            return _facturae(raiz)
        if nombre in ("Invoice", "CreditNote"):
            return _ubl(raiz)
        if nombre == "CrossIndustryInvoice":
            return _cii(raiz)
    except Exception:  # noqa: BLE001 -- una factura rara no debe romper la lectura: la leerá la IA
        logger.warning("No se pudo interpretar una factura electrónica", exc_info=True)
    return None


def xml_incrustado(pdf: bytes) -> bytes | None:
    """El XML de factura electrónica adjunto a un PDF (Factur-X / ZUGFeRD / XRechnung), o None."""
    try:
        from pypdf import PdfReader
        lector = PdfReader(io.BytesIO(pdf))
        if lector.is_encrypted:
            return None
        adjuntos = lector.attachments
        for nombre in sorted(adjuntos, key=lambda n: (not any(k in n.lower() for k in NOMBRES_XML_INCRUSTADO), n)):
            if nombre.lower().endswith(".xml"):
                for contenido in adjuntos[nombre]:
                    if contenido and len(contenido) <= MAX_XML_BYTES:
                        return bytes(contenido)
    except Exception:  # noqa: BLE001
        return None
    return None


def extraer(contenido: bytes, tipo_mime: str = "", nombre: str = "") -> dict | None:
    """Los datos de una factura electrónica (XML suelto o PDF con XML incrustado), o None si no lo es."""
    mime = (tipo_mime or "").lower().split(";")[0]
    if mime == "application/pdf" or contenido[:5] == b"%PDF-":
        xml = xml_incrustado(contenido)
        r = _desde_xml(xml) if xml else None
        if r:
            r["origen"] = "pdf_incrustado"
        return r
    if mime in ("text/xml", "application/xml") or (nombre or "").lower().endswith(".xml") or contenido.lstrip()[:5] == b"<?xml":
        r = _desde_xml(contenido)
        if r:
            r["origen"] = "xml"
        return r
    return None
