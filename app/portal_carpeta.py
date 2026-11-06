"""La carpeta del año del cliente: todo lo que su gestoría le ha dejado de un ejercicio en un solo sitio y descargable — justificantes oficiales y constancias de presentación, informes de los trimestres y resúmenes de los
modelos 303 presentados —, con un ZIP del año entero.

Solo se enseña lo que ya existe y es del cliente: nada de borradores ni de documentos internos. Los informes y resúmenes se generan al pedirlos con los datos de ese momento (los mismos PDF que usa el despacho)."""
from __future__ import annotations

import io
import re
import zipfile

from . import cierre_trimestre, db, facturas_contables as fc, facturas_portal, portal_pagos, verticales
from .vencimientos_fiscales import MODELOS_INTERNOS

MAX_ZIP_BYTES = 60 * 1024 * 1024
ORIGENES = ("justificante", "constancia")


def _anio(texto) -> int | None:
    return int(texto[:4]) if texto and re.match(r"\d{4}", texto) else None


def _vencimientos_del_anio(cliente: dict, anio: int) -> list:
    return [v for v in db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"], sin_internos=True) if _anio(v["fecha_limite"]) == anio and v["modelo"] not in MODELOS_INTERNOS]


def anios_disponibles(cliente: dict) -> list[int]:
    anios = {_anio(v["fecha_limite"]) for v in db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"], sin_internos=True)}
    anios |= {_anio(f["fecha"]) for f in fc.listar_del_cliente(cliente["id"], 500)}
    return sorted((a for a in anios if a), reverse=True)


def _resumenes(cliente: dict, anio: int) -> list[dict]:
    if not verticales.esta_activo(cliente["tenant_id"], "fiscal"):
        return []
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, periodo, presentada_en FROM fiscal_declaraciones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' AND ejercicio = ? AND estado = 'presentada' "
                                              "ORDER BY periodo, id", (cliente["tenant_id"], cliente["id"], anio))]
    finally:
        conn.close()


def _trimestres_con_datos(cliente: dict, anio: int, resumenes: list[dict]) -> list[str]:
    if not verticales.esta_activo(cliente["tenant_id"], "fiscal"):
        return []
    trimestres = {f["trimestre"] for f in facturas_portal.facturas_del_cliente(cliente["id"]) if f["trimestre"].startswith(f"{anio}-")}
    trimestres |= {f"{anio}-T{r['periodo'][0]}" for r in resumenes if r["periodo"] in ("1T", "2T", "3T", "4T")}
    return sorted(trimestres)


def contenido(cliente: dict, anio: int) -> dict:
    documentos = []
    for v in _vencimientos_del_anio(cliente, anio):
        for d in db.listar_documentos_vencimiento(v["id"], excluir_origenes=db.ORIGENES_INTERNOS_DOCUMENTO_VENCIMIENTO):
            if d["origen"] in ORIGENES:
                documentos.append({"vencimiento_id": v["id"], "modelo": v["modelo"], "periodo": v["periodo"], "id": d["id"], "nombre": d["nombre_archivo"], "origen": d["origen"], "tamano": d["tamano_bytes"], "fecha": (d["creado_en"] or "")[:10]})
    resumenes = _resumenes(cliente, anio)
    return {"anio": anio, "documentos": documentos, "resumenes": resumenes, "trimestres": _trimestres_con_datos(cliente, anio, resumenes), "honorarios": portal_pagos.del_anio(cliente, anio)}


def pdf_resumen(cliente: dict, declaracion_id: int) -> bytes | None:
    """El resumen del modelo 303 de una declaración PRESENTADA del cliente, o None."""
    from . import fiscal_nucleo as fn, fiscal_resumen_pdf
    from flask_babel import gettext as _
    conn = db.get_connection()
    try:
        d = conn.execute("SELECT id, ejercicio, periodo, estado, tipo_declaracion FROM fiscal_declaraciones WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'presentada'",
                         (declaracion_id, cliente["tenant_id"], cliente["id"])).fetchone()
        if d is None or not verticales.esta_activo(cliente["tenant_id"], "fiscal"):
            return None
        casillas = {c["casilla"]: c["valor"] for c in conn.execute("SELECT casilla, valor FROM fiscal_casillas WHERE declaracion_id = ? AND tenant_id = ?", (declaracion_id, cliente["tenant_id"]))}
        v = conn.execute("SELECT fecha_limite FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND modelo = '303' AND periodo = ? AND papelera_en IS NULL ORDER BY id DESC LIMIT 1",
                         (cliente["tenant_id"], cliente["id"], f"{d['periodo']} {d['ejercicio']}")).fetchone()
    finally:
        conn.close()
    despacho = db.obtener_tenant(cliente["tenant_id"])
    return fiscal_resumen_pdf.generar(titular=cliente["nombre"], nif=cliente["nif"], ejercicio=d["ejercicio"], periodo=d["periodo"], estado=_("presentada"), casillas=casillas, etiqueta=fn.etiqueta_casilla,
                                      tipo_declaracion=d["tipo_declaracion"], fecha_limite=v["fecha_limite"][:10] if v and v["fecha_limite"] else None, gestoria=despacho["nombre"] if despacho else "")


def _nombre_seguro(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", texto or "archivo").strip("._")[:80] or "archivo"


def zip_del_anio(cliente: dict, anio: int) -> bytes:
    """Todo lo de la carpeta del año en un ZIP (con un tope de tamaño: lo que no quepa se indica en LEEME.txt)."""
    c = contenido(cliente, anio)
    buf = io.BytesIO()
    total, omitidos = 0, []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def añadir(ruta: str, datos: bytes) -> None:
            nonlocal total
            if total + len(datos) > MAX_ZIP_BYTES:
                omitidos.append(ruta)
                return
            total += len(datos)
            z.writestr(ruta, datos)
        for d in c["documentos"]:
            doc = db.obtener_documento_vencimiento(d["id"])
            try:
                añadir(f"justificantes/{d['modelo']}-{_nombre_seguro(d['periodo'])}-{_nombre_seguro(d['nombre'])}", db.contenido_documento_vencimiento(doc))
            except Exception:  # noqa: BLE001 -- almacenamiento externo caído: se anota como omitido
                omitidos.append(d["nombre"])
        for t in c["trimestres"]:
            pdf = cierre_trimestre.informe_pdf(cliente["tenant_id"], cliente["id"], t)
            if pdf:
                añadir(f"informes/informe-{t}.pdf", pdf)
        for r in c["resumenes"]:
            pdf = pdf_resumen(cliente, r["id"])
            if pdf:
                añadir(f"resumenes/303-{anio}-{r['periodo']}.pdf", pdf)
        if omitidos:
            z.writestr("LEEME.txt", "No han cabido en este ZIP (descárgalos uno a uno desde tu portal):\n" + "\n".join(omitidos) + "\n")
    return buf.getvalue()
