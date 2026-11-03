"""Exportación de un informe jurídico a PDF y a Word (J5), con las citas, el estado de revisión y la atribución de cada fuente.

La política de uso de cada fuente manda: si no permite exportar, el informe sale igual pero sin el extracto de esa fuente (queda su título, su localizador y su enlace original). Un borrador sale marcado
como pendiente de revisión profesional; uno revisado, con quién lo revisó y cuándo. Si desde que se guardó el informe una fuente se ha actualizado o ya no está en vigor, el documento lo avisa arriba."""
from __future__ import annotations

import io
import re

from .. import db, informes as informes_pdf
from . import citas as citas_estado
from . import corpus

AVISO_BORRADOR = "Borrador del asistente: pendiente de revisión por un profesional. No es un informe revisado."
SIN_EXTRACTO = "(Extracto no exportable: la política de uso de la fuente no permite exportarlo. Consúltalo en la fuente original.)"


def _nombre(usuario_id: int | None) -> str:
    return (db.nombre_mostrado_usuario(usuario_id) if usuario_id else None) or "—"


def _cliente(tenant_id: int, cliente_id: int | None) -> str | None:
    if not cliente_id:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT nombre FROM clientes WHERE id = ? AND tenant_id = ?", (cliente_id, tenant_id)).fetchone()
        return f["nombre"] if f else None
    finally:
        conn.close()


def preparar(tenant_id: int, inf: dict) -> dict:
    """Todo lo que lleva el documento, ya resuelto y en texto plano: igual para PDF y Word."""
    inst = inf["instantanea"]
    r = inst["respuesta"]
    exportables = set(corpus.fuentes_para_despacho(tenant_id, "exportar"))
    estados = citas_estado.estado_de_citas(tenant_id, r.get("citations", []), inst.get("fecha_juridica"))
    avisos = citas_estado.resumen_de_avisos(estados)
    numero = {c["id"]: i for i, c in enumerate(r.get("citations", []), 1)}
    fuentes, atribuciones = [], {}
    for c in r.get("citations", []):
        captura = c.get("captura") or {}
        fuente_id = captura.get("fuente_id")
        legal = c.get("kind") == "legal_source"
        puede = (not legal) or (fuente_id in exportables)
        if legal and fuente_id and puede and fuente_id not in atribuciones:
            p = corpus.politica_vigente(fuente_id)
            if p and p["atribucion"]:
                atribuciones[fuente_id] = p["atribucion"]
        fuentes.append({
            "n": numero[c["id"]], "titulo": c.get("title") or "", "localizador": c.get("locator") or "", "extracto": c.get("quote") if puede else None,
            "url": c.get("canonicalUrl") if legal else None, "captura": (captura.get("capturada_en") or "")[:10] or None, "privada": not legal,
        })
    revisado = inf["estado"] == "revisado"
    sello = (f"Revisado por {_nombre(inf.get('revisado_por'))} el {(inf.get('revisado_en') or '')[:10]}." if revisado else AVISO_BORRADOR)
    alertas = []
    if avisos["modificadas"]:
        alertas.append(f"{avisos['modificadas']} fuente(s) citada(s) se han actualizado desde que se guardó el informe: revisa las versiones actuales.")
    if avisos["derogadas"]:
        alertas.append(f"{avisos['derogadas']} cita(s) corresponden a textos que ya no están en vigor.")
    if avisos["fuera_de_fecha"]:
        alertas.append(f"{avisos['fuera_de_fecha']} cita(s) no estaban vigentes en la fecha jurídica de la consulta.")
    if avisos["no_disponibles"]:
        alertas.append(f"{avisos['no_disponibles']} fuente(s) citada(s) ya no están disponibles en el despacho.")
    return {
        "titulo": inf["titulo"], "estado": inf["estado"], "sello": sello, "cliente": _cliente(tenant_id, inf.get("cliente_id")), "pregunta": inst.get("pregunta") or "",
        "fecha_juridica": inst.get("fecha_juridica") or "", "guardado": (inf.get("creado_en") or "")[:10], "creado_por": _nombre(inf.get("creado_por")), "alertas": alertas,
        "conclusion": r.get("conclusion"), "hechos": r.get("facts") or [],
        "fundamento": [{"texto": a["text"], "refs": [numero[c] for c in a["citationIds"] if c in numero]} for a in r.get("claims", [])],
        "limites": r.get("limitations") or [], "pasos": r.get("suggestedNextSteps") or [], "fuentes": fuentes, "atribuciones": sorted(set(atribuciones.values())),
        "referencia": f"Informe jurídico nº {inf['id']} · consulta {inst.get('ejecucion_id')} · modelo {inst.get('modelo') or '—'}",
    }


def _refs(refs: list[int]) -> str:
    return " " + "".join(f"[{n}]" for n in refs) if refs else ""


def pdf(tenant_id: int, inf: dict) -> bytes:
    d = preparar(tenant_id, inf)
    bloques: list[tuple] = [("claves", [(k, v) for k, v in (("Cliente", d["cliente"]), ("Estado", d["sello"]), ("Fecha jurídica", d["fecha_juridica"]), ("Guardado", f"{d['guardado']} por {d['creado_por']}")) if v])]
    for a in d["alertas"]:
        bloques.append(("parrafo", "Atención: " + a))
    bloques += [("seccion", "Pregunta"), ("parrafo", d["pregunta"])]
    if d["conclusion"]:
        bloques += [("seccion", "Conclusión"), ("parrafo", d["conclusion"])]
    if d["hechos"]:
        bloques += [("seccion", "Hechos considerados"), ("parrafo", "\n".join("• " + h for h in d["hechos"]))]
    if d["fundamento"]:
        bloques += [("seccion", "Fundamento"), ("parrafo", "\n".join("• " + a["texto"] + _refs(a["refs"]) for a in d["fundamento"]))]
    if d["limites"]:
        bloques += [("seccion", "Límites de aplicabilidad"), ("parrafo", "\n".join("• " + x for x in d["limites"]))]
    if d["pasos"]:
        bloques += [("seccion", "Próximos pasos"), ("parrafo", "\n".join("• " + x for x in d["pasos"]))]
    bloques.append(("seccion", "Fuentes"))
    for f in d["fuentes"]:
        linea = f"[{f['n']}] {f['titulo']} · {f['localizador']}" + (" (adjunto privado)" if f["privada"] else "")
        if f["captura"]:
            linea += f" · versión capturada el {f['captura']}"
        if f["url"]:
            linea += f"\n{f['url']}"
        linea += f"\n«{f['extracto']}»" if f["extracto"] else "\n" + SIN_EXTRACTO
        bloques.append(("parrafo", linea))
        bloques.append(("espacio",))
    if d["atribuciones"]:
        bloques += [("seccion", "Atribución de las fuentes"), ("parrafo", "\n".join(d["atribuciones"]))]
    bloques += [("espacio",), ("parrafo", d["sello"]), ("parrafo", d["referencia"])]
    return informes_pdf.construir_pdf(d["titulo"], bloques, subtitulo="Asistente jurídico · Guilda Work")


def docx(tenant_id: int, inf: dict) -> bytes:
    from docx import Document
    from docx.shared import Pt
    d = preparar(tenant_id, inf)
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.add_heading(d["titulo"], 0)
    for k, v in (("Cliente", d["cliente"]), ("Estado", d["sello"]), ("Fecha jurídica", d["fecha_juridica"]), ("Guardado", f"{d['guardado']} por {d['creado_por']}")):
        if v:
            p = doc.add_paragraph()
            p.add_run(k + ": ").bold = True
            p.add_run(str(v))
    for a in d["alertas"]:
        p = doc.add_paragraph()
        p.add_run("Atención: ").bold = True
        p.add_run(a)

    def lista(titulo, items):
        if items:
            doc.add_heading(titulo, 1)
            for it in items:
                doc.add_paragraph(it, style="List Bullet")

    doc.add_heading("Pregunta", 1)
    doc.add_paragraph(d["pregunta"])
    if d["conclusion"]:
        doc.add_heading("Conclusión", 1)
        doc.add_paragraph(d["conclusion"])
    lista("Hechos considerados", d["hechos"])
    lista("Fundamento", [a["texto"] + _refs(a["refs"]) for a in d["fundamento"]])
    lista("Límites de aplicabilidad", d["limites"])
    lista("Próximos pasos", d["pasos"])
    doc.add_heading("Fuentes", 1)
    for f in d["fuentes"]:
        p = doc.add_paragraph()
        p.add_run(f"[{f['n']}] {f['titulo']} · {f['localizador']}").bold = True
        if f["privada"]:
            p.add_run(" (adjunto privado)")
        if f["captura"]:
            p.add_run(f" · versión capturada el {f['captura']}")
        if f["url"]:
            p.add_run("\n" + f["url"])
        p.add_run("\n«" + f["extracto"] + "»" if f["extracto"] else "\n" + SIN_EXTRACTO).italic = True
    if d["atribuciones"]:
        doc.add_heading("Atribución de las fuentes", 1)
        for a in d["atribuciones"]:
            doc.add_paragraph(a)
    doc.add_paragraph()
    doc.add_paragraph(d["sello"]).runs[0].bold = True
    doc.add_paragraph(d["referencia"])
    salida = io.BytesIO()
    doc.save(salida)
    return salida.getvalue()


def nombre_de_archivo(titulo: str, extension: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", re.sub(r"[áàä]", "a", re.sub(r"[éèë]", "e", re.sub(r"[íìï]", "i", re.sub(r"[óòö]", "o", re.sub(r"[úùü]", "u", (titulo or "informe").lower()))))).replace("ñ", "n")).strip("-")
    return f"informe-juridico-{base[:60] or 'informe'}.{extension}"
