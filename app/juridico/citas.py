"""Estado actual de las fuentes que cita una respuesta (J3): ¿el texto citado sigue siendo el de hoy, o la fuente lo ha actualizado desde la consulta? ¿Estaba vigente en la fecha jurídica?

Las citas guardan la versión exacta (`versionId`) y el fragmento (`chunkId`) con los que se respondió; la biblioteca puede haber capturado después una versión nueva del mismo documento. Aquí se compara lo
citado con lo activo ahora, solo con lo que el despacho puede usar, y se devuelve para cada cita un resumen listo para mostrar. No interpreta jurídicamente nada: solo dice que ha cambiado y cuándo."""
from __future__ import annotations

from datetime import date

from .. import db
from . import busqueda


def estado_de_citas(tenant_id: int, citas: list[dict], fecha_juridica: str | None = None, hoy: date | None = None) -> dict[str, dict]:
    """`{id_de_cita: {...}}` solo para las citas de fuentes legales (`kind == 'legal_source'`). Claves: `disponible` (la fuente sigue usable en el despacho), `modificada` (hay una versión activa distinta
    de la citada), `actual` ({version_id, capturada_en, fecha_publicacion} de la activa), `vigente_desde`, `vigente_hasta`, `derogada` (el fragmento tiene fin de vigencia ya pasado) y `fuera_de_fecha`
    (no estaba vigente en la fecha jurídica de la consulta)."""
    hoy_iso = (hoy or date.today()).isoformat()
    legales = [c for c in citas if c.get("kind") == "legal_source" and c.get("documentId")]
    if not legales:
        return {}
    conn = db.get_connection()
    try:
        usables = set(busqueda._fuentes_del_despacho(conn, tenant_id))
        salida: dict[str, dict] = {}
        for c in legales:
            d = conn.execute("SELECT id, fuente_id FROM jur_documentos WHERE id = ?", (c["documentId"],)).fetchone()
            if d is None or d["fuente_id"] not in usables:
                salida[c["id"]] = {"disponible": False}
                continue
            activa = conn.execute("SELECT id, capturada_en, fecha_publicacion FROM jur_versiones WHERE documento_id = ? AND activa = 1 AND bloqueada = 0", (d["id"],)).fetchone()
            info: dict = {"disponible": True, "modificada": bool(activa and c.get("versionId") and activa["id"] != c["versionId"]),
                          "actual": {"version_id": activa["id"], "capturada_en": (activa["capturada_en"] or "")[:10], "fecha_publicacion": activa["fecha_publicacion"]} if activa else None,
                          "vigente_desde": None, "vigente_hasta": None, "derogada": False, "fuera_de_fecha": False}
            if c.get("chunkId"):
                f = conn.execute("SELECT vigente_desde, vigente_hasta FROM jur_fragmentos WHERE id = ?", (c["chunkId"],)).fetchone()
                if f is not None:
                    info["vigente_desde"], info["vigente_hasta"] = f["vigente_desde"], f["vigente_hasta"]
                    info["derogada"] = bool(f["vigente_hasta"] and f["vigente_hasta"][:10] < hoy_iso)
                    if fecha_juridica:
                        info["fuera_de_fecha"] = bool((f["vigente_desde"] and f["vigente_desde"][:10] > fecha_juridica[:10]) or (f["vigente_hasta"] and f["vigente_hasta"][:10] < fecha_juridica[:10]))
            salida[c["id"]] = info
        return salida
    finally:
        conn.close()


def resumen_de_avisos(estados: dict[str, dict]) -> dict:
    """Los totales que se enseñan arriba de la respuesta: cuántas citas cambiaron, cuántas ya no están disponibles y cuántas tienen el texto derogado."""
    return {"modificadas": sum(1 for e in estados.values() if e.get("modificada")), "no_disponibles": sum(1 for e in estados.values() if not e.get("disponible", True)),
            "derogadas": sum(1 for e in estados.values() if e.get("derogada")), "fuera_de_fecha": sum(1 for e in estados.values() if e.get("fuera_de_fecha"))}
