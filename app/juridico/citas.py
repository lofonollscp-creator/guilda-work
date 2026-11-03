"""Estado actual de las fuentes que cita una respuesta (J3): ¿el texto citado sigue siendo el de hoy, o la fuente lo ha actualizado desde la consulta? ¿Estaba vigente en la fecha jurídica?

Las citas guardan la versión exacta (`versionId`) y el fragmento (`chunkId`) con los que se respondió; la biblioteca puede haber capturado después una versión nueva del mismo documento. Aquí se compara lo
citado con lo activo ahora, solo con lo que el despacho puede usar, y se devuelve para cada cita un resumen listo para mostrar. No interpreta jurídicamente nada: solo dice que ha cambiado y cuándo."""
from __future__ import annotations

import json
import logging
from datetime import date

from .. import db
from . import busqueda, corpus

logger = logging.getLogger(__name__)


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


# --- Avisos de cambio normativo en los informes guardados (J6) -----------------------------------------------------------------------------------------

def revisar_cambios(tenant_id: int | None = None, enviar: bool = True) -> dict:
    """Mira los informes vivos (borrador o revisado) y, por cada documento que citan cuya versión activa en la biblioteca ya no es la citada, deja UNA alerta (por informe, documento y versión nueva) y avisa
    a quien creó el informe y a quien lo revisó. Un informe guardado no cambia nunca: la alerta solo dice que su fuente cambió después y que conviene volver a consultar. Devuelve {informes, alertas, avisos}."""
    conn = db.get_connection()
    nuevas: list[dict] = []
    try:
        donde, params = ("estado != 'archivado'", [])
        if tenant_id is not None:
            donde, params = donde + " AND tenant_id = ?", [tenant_id]
        informes = conn.execute(f"SELECT id, tenant_id, titulo, instantanea, creado_por, revisado_por FROM jur_informes WHERE {donde} ORDER BY id", params).fetchall()
        for inf in informes:
            try:
                citas = json.loads(inf["instantanea"])["respuesta"].get("citations", [])
            except (ValueError, KeyError, TypeError):
                continue
            vistos = set()
            for c in citas:
                if c.get("kind") != "legal_source" or not c.get("documentId") or not c.get("versionId") or (c["documentId"], c["versionId"]) in vistos:
                    continue
                vistos.add((c["documentId"], c["versionId"]))
                activa = conn.execute("SELECT id FROM jur_versiones WHERE documento_id = ? AND activa = 1 AND bloqueada = 0", (c["documentId"],)).fetchone()
                if activa is None or activa["id"] == c["versionId"]:
                    continue
                ya = conn.execute("SELECT 1 FROM jur_alertas_cambio WHERE informe_id = ? AND documento_id = ? AND version_nueva_id = ?", (inf["id"], c["documentId"], activa["id"])).fetchone()
                if ya:
                    continue
                conn.execute("INSERT INTO jur_alertas_cambio (tenant_id, informe_id, documento_id, version_citada_id, version_nueva_id, creada_en) VALUES (?, ?, ?, ?, ?, ?)",
                             (inf["tenant_id"], inf["id"], c["documentId"], c["versionId"], activa["id"], corpus.ahora()))
                titulo = conn.execute("SELECT titulo FROM jur_documentos WHERE id = ?", (c["documentId"],)).fetchone()
                nuevas.append({"informe_id": inf["id"], "tenant_id": inf["tenant_id"], "informe": inf["titulo"], "documento": titulo["titulo"] if titulo else "", "destinatarios": {inf["creado_por"], inf["revisado_por"]} - {None}})
        conn.commit()
    finally:
        conn.close()
    avisos = 0
    if enviar:
        for a in nuevas:
            for usuario_id in a["destinatarios"]:
                try:
                    from .. import notificaciones
                    notificaciones.crear_y_enviar(usuario_id, "juridico_cambio", "Una fuente de un informe jurídico ha cambiado",
                                                  f"«{a['documento'][:120]}» se ha actualizado en la biblioteca desde que guardaste el informe «{a['informe'][:100]}». Conviene volver a consultar antes de usarlo.",
                                                  url=f"/juridico/informes/{a['informe_id']}", datos={"tipo": "juridico_cambio"})
                    avisos += 1
                except Exception:  # noqa: BLE001 -- un aviso que falla no debe parar la revisión ni perder la alerta
                    logger.warning("No se ha podido avisar del cambio normativo del informe %s", a["informe_id"], exc_info=True)
        if nuevas:
            conn = db.get_connection()
            try:
                for a in nuevas:
                    conn.execute("UPDATE jur_alertas_cambio SET notificada_en = ? WHERE informe_id = ? AND notificada_en IS NULL", (corpus.ahora(), a["informe_id"]))
                conn.commit()
            finally:
                conn.close()
    return {"informes": len(informes), "alertas": len(nuevas), "avisos": avisos}


def informes_con_cambios(tenant_id: int, ids: list[int]) -> set[int]:
    """Cuáles de esos informes tienen alguna alerta de cambio de fuente (para marcarlos en la lista)."""
    if not ids:
        return set()
    conn = db.get_connection()
    try:
        marcas = ",".join("?" for _ in ids)
        return {f["informe_id"] for f in conn.execute(f"SELECT DISTINCT informe_id FROM jur_alertas_cambio WHERE tenant_id = ? AND informe_id IN ({marcas})", [tenant_id, *ids])}
    finally:
        conn.close()
