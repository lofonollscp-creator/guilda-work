"""El QR de las facturas y tickets electrónicos (VeriFactu de la AEAT, TicketBAI del País Vasco): lleva el NIF del emisor, el número, la fecha y el importe total tal como los registró el programa
de facturación. Es un dato **exacto** con el que se contrasta lo que lee la IA (y que la corrige si se equivoca en esos cuatro datos).

`leer(contenido, tipo_mime)` devuelve `{"tipo", "nif", "numero", "fecha", "total"}` o None. Usa OpenCV (sin interfaz gráfica) y, para PDF, las dos primeras páginas renderizadas. Un QR que no sea de
factura (un pago, una web) se ignora. Nada de esto sale a la red: el QR se interpreta localmente, no se visita su dirección."""
from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("guilda")

DOMINIOS_VERIFACTU = ("agenciatributaria.gob.es", "agenciatributaria.es")
DOMINIOS_TICKETBAI = ("batuz.eus", "egoitza.gipuzkoa.eus", "ebizkaia.eus", "araba.eus", "euskadi.eus", "bizkaia.eus", "gipuzkoa.eus")


def _importe(texto: str) -> str:
    t = (texto or "").strip().replace(",", ".")
    return f"{float(t):.2f}" if re.fullmatch(r"-?\d+(\.\d+)?", t) else ""


def interpretar(texto: str) -> dict | None:
    """Los datos de factura de un QR de VeriFactu o de TicketBAI, o None si el contenido no es de ninguno de los dos."""
    try:
        u = urlparse((texto or "").strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    q = {k.lower(): v[0] for k, v in parse_qs(u.query).items() if v}
    if u.scheme in ("http", "https") and any(host == d or host.endswith("." + d) for d in DOMINIOS_VERIFACTU) and "validarqr" in u.path.lower():
        m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", q.get("fecha", ""))
        try:
            fecha = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat() if m else ""
        except ValueError:
            fecha = ""
        if q.get("nif") and q.get("numserie"):
            return {"tipo": "verifactu", "nif": q["nif"].strip().upper(), "numero": q["numserie"].strip(), "fecha": fecha, "total": _importe(q.get("importe", ""))}
    if u.scheme in ("http", "https") and any(host == d or host.endswith("." + d) for d in DOMINIOS_TICKETBAI) and q.get("id", "").upper().startswith("TBAI-"):
        trozos = q["id"].split("-")
        fecha = ""
        if len(trozos) > 2 and re.fullmatch(r"\d{6}", trozos[2]):
            try:
                fecha = date(2000 + int(trozos[2][4:6]), int(trozos[2][2:4]), int(trozos[2][0:2])).isoformat()
            except ValueError:
                fecha = ""
        numero = (q.get("s", "") + q.get("nf", "")).strip()
        return {"tipo": "ticketbai", "nif": trozos[1].strip().upper() if len(trozos) > 1 else "", "numero": numero, "fecha": fecha, "total": _importe(q.get("i", ""))}
    return None


def _decodificar(img) -> list[str]:
    import cv2
    textos: list[str] = []
    detector = cv2.QRCodeDetector()
    for variante in _variantes(img):
        try:
            ok, valores, _p, _s = detector.detectAndDecodeMulti(variante)
            textos += [v for v in (valores or []) if v]
            if not textos:
                v, _p2, _s2 = detector.detectAndDecode(variante)
                if v:
                    textos.append(v)
        except cv2.error:
            continue
        if textos:
            break
    return textos


def _variantes(img):
    """La imagen tal cual, en grises y ampliada: los QR de un ticket fotografiado suelen ser pequeños."""
    import cv2
    yield img
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    yield gris
    alto, ancho = gris.shape[:2]
    if max(alto, ancho) < 2400:
        yield cv2.resize(gris, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


def leer(contenido: bytes, tipo_mime: str = "") -> dict | None:
    """El QR de factura de este archivo (imagen o PDF), o None si no tiene o no es de VeriFactu ni TicketBAI."""
    try:
        import cv2
        import numpy as np
        from . import pdf_facturas
        mime = (tipo_mime or "").lower().split(";")[0]
        imagenes = []
        if mime == "application/pdf" or contenido[:5] == b"%PDF-":
            for png in (pdf_facturas.paginas_a_imagenes(contenido, maximo=2, lado=2400) or []):
                imagenes.append(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR))
        else:
            img = cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR)
            imagenes.append(img)
        for img in imagenes:
            if img is None:
                continue
            for texto in _decodificar(img):
                d = interpretar(texto)
                if d:
                    return d
    except Exception:  # noqa: BLE001 -- el QR solo ayuda: sin él se lee igual
        logger.warning("No se pudo buscar el QR de la factura", exc_info=True)
    return None
