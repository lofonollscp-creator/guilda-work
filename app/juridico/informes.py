"""Informes del asistente jurídico guardados en el expediente: instantánea de una consulta con sus citas, revisión por un profesional autorizado y estados.

- **Instantánea inmutable**: se guarda la consulta, la respuesta, y por cada cita su extracto, localizador, versión, documento, URL, fecha de captura y la versión de la política aplicada. Una actualización posterior de la biblioteca NO cambia un informe guardado; si una fuente se retira después, el informe se marca con un aviso (`aviso_fuente`) y se pide revisión.
- **No se guarda el texto íntegro de las fuentes**, solo los extractos citados (la política `citar` basta; no hace falta `exportar`).
- **Estados**: borrador → revisado → archivado. Solo la dirección o quien puede autorizar marca «revisado», y queda quién y cuándo. Un informe revisado no se edita: se archiva o se crea otro.
- **Permisos**: por cliente/expediente (quien no ve al cliente no ve el informe) y solo en el despacho de origen."""
from __future__ import annotations

import json
import re

from .. import acceso, db
from . import asistente, corpus


class ErrorInforme(ValueError):
    def __init__(self, mensaje: str, codigo: str = "peticion_invalida"):
        super().__init__(mensaje)
        self.codigo = codigo


def _puede_revisar(tenant_id: int, usuario_id: int) -> bool:
    return acceso.es_directivo(usuario_id) or acceso.puede_autorizar(tenant_id, usuario_id)


def guardar(tenant_id: int, usuario_id: int, ejecucion_id: int, *, titulo: str | None = None) -> dict:
    """Guarda en el expediente (o en el cliente) de la conversación una instantánea de una consulta respondida. Quien no está autorizado a escribir (auditor) no puede."""
    if acceso.es_solo_auditor(tenant_id, usuario_id):
        raise ErrorInforme("Tu rol solo permite consultar.", "permiso")
    e = asistente.ejecucion(tenant_id, usuario_id, ejecucion_id)
    if e is None:
        raise ErrorInforme("No encuentras esa consulta.", "no_encontrado")
    r = e["respuesta"]
    if not r or r.get("status") != "answered":
        raise ErrorInforme("Solo se guarda una consulta respondida y fundamentada: esta no lo está.", "peticion_invalida")
    conn = db.get_connection()
    try:
        citas = []
        for c in r["citations"]:
            fila = None
            if c["kind"] == "legal_source":
                fila = conn.execute("SELECT v.capturada_en, v.hash_texto, v.politica_version, d.titulo, d.id_externo, d.fuente_id, d.fecha_publicacion, d.fecha_resolucion, d.ecli, d.eli FROM jur_versiones v "
                                    "JOIN jur_documentos d ON d.id = v.documento_id WHERE v.id = ?", (c["versionId"],)).fetchone()
            citas.append({**c, "captura": dict(fila) if fila else None})
        instantanea = {"pregunta": e["pregunta"], "fecha_juridica": e["fecha_juridica"], "objetivo": e["objetivo"], "filtros": e["filtros"], "respuesta": {**r, "citations": citas},
                       "modelo": e["modelo"], "prompt_version": e["prompt_version"], "ejecucion_id": ejecucion_id, "guardada_en": corpus.ahora(), "aviso": "Borrador del asistente: pendiente de revisión profesional."}
        conv = conn.execute("SELECT cliente_id, expediente_id, titulo FROM jur_conversaciones WHERE id = ? AND tenant_id = ?", (e["conversacion_id"], tenant_id)).fetchone()
        nombre = (titulo or "").strip()[:200] or (e["pregunta"][:80])
        iid = conn.execute("INSERT INTO jur_informes (tenant_id, ejecucion_id, cliente_id, expediente_id, titulo, instantanea, estado, creado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, 'borrador', ?, ?)",
                           (tenant_id, ejecucion_id, conv["cliente_id"], conv["expediente_id"], nombre, json.dumps(instantanea, ensure_ascii=False), usuario_id, corpus.ahora())).lastrowid
        corpus.auditar(tenant_id, usuario_id, "informe.guardar", f"informe:{iid}", {"expediente": conv["expediente_id"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener(tenant_id, usuario_id, iid)


def _visible(tenant_id: int, usuario_id: int, f) -> bool:
    return f["tenant_id"] == tenant_id and acceso.puede_ver_cliente_nucleo(tenant_id, usuario_id, f["cliente_id"])


def obtener(tenant_id: int, usuario_id: int, informe_id: int) -> dict | None:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM jur_informes WHERE id = ? AND tenant_id = ?", (informe_id, tenant_id)).fetchone()
        if f is None or not _visible(tenant_id, usuario_id, f):
            return None
        d = dict(f)
        d["instantanea"] = json.loads(d["instantanea"])
        return d
    finally:
        conn.close()


def listar(tenant_id: int, usuario_id: int, *, expediente_id: int | None = None, cliente_id: int | None = None, limite: int = 100) -> list[dict]:
    conn = db.get_connection()
    try:
        donde, p = ["tenant_id = ?"], [tenant_id]
        if expediente_id is not None:
            donde.append("expediente_id = ?"); p.append(expediente_id)
        if cliente_id is not None:
            donde.append("cliente_id = ?"); p.append(cliente_id)
        filas = conn.execute(f"SELECT id, tenant_id, cliente_id, expediente_id, titulo, estado, creado_por, revisado_por, revisado_en, creado_en, aviso_fuente FROM jur_informes WHERE {' AND '.join(donde)} ORDER BY id DESC LIMIT ?", (*p, limite)).fetchall()
        return [dict(f) for f in filas if _visible(tenant_id, usuario_id, f)]
    finally:
        conn.close()


def revisar(tenant_id: int, usuario_id: int, informe_id: int, decision: str = "revisado", nota: str | None = None) -> dict:
    """Marca «revisado» (solo un profesional autorizado, con quién y cuándo) o «archivado» (quien lo creó o un profesional autorizado)."""
    inf = obtener(tenant_id, usuario_id, informe_id)
    if inf is None:
        raise ErrorInforme("No encuentras ese informe.", "no_encontrado")
    if decision not in ("revisado", "archivado"):
        raise ErrorInforme("La decisión no es válida.")
    if decision == "revisado":
        if not _puede_revisar(tenant_id, usuario_id):
            raise ErrorInforme("Solo la dirección o una persona autorizada puede marcar un informe como revisado.", "permiso")
        if inf["estado"] != "borrador":
            raise ErrorInforme("Solo un borrador se puede marcar como revisado.")
        if inf["aviso_fuente"]:
            raise ErrorInforme("Una fuente citada se ha retirado o corregido: vuelve a lanzar la consulta antes de revisarla.")
    else:
        if inf["estado"] == "archivado":
            raise ErrorInforme("Ya está archivado.")
        if usuario_id != inf["creado_por"] and not _puede_revisar(tenant_id, usuario_id):
            raise ErrorInforme("Solo quien lo creó o una persona autorizada puede archivarlo.", "permiso")
    conn = db.get_connection()
    try:
        if decision == "revisado":
            conn.execute("UPDATE jur_informes SET estado = 'revisado', revisado_por = ?, revisado_en = ? WHERE id = ? AND tenant_id = ?", (usuario_id, corpus.ahora(), informe_id, tenant_id))
        else:
            conn.execute("UPDATE jur_informes SET estado = 'archivado' WHERE id = ? AND tenant_id = ?", (informe_id, tenant_id))
        corpus.auditar(tenant_id, usuario_id, f"informe.{decision}", f"informe:{informe_id}", {"nota": bool(nota)}, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return obtener(tenant_id, usuario_id, informe_id)


def texto_para_copiar(inf: dict) -> str:
    """El informe como texto con las referencias junto a cada afirmación (para copiar o exportar)."""
    r = inf["instantanea"]["respuesta"]
    citas = {c["id"]: c for c in r["citations"]}
    n = {cid: i for i, cid in enumerate(citas, 1)}
    lineas = [inf["titulo"], f"Estado: {inf['estado']}" + (f" (revisado el {inf['revisado_en']})" if inf["revisado_en"] else " — borrador pendiente de revisión profesional"),
              f"Fecha jurídica: {inf['instantanea']['fecha_juridica']}", "", "Pregunta: " + inf["instantanea"]["pregunta"], ""]
    if r.get("conclusion"):
        lineas += ["Conclusión: " + r["conclusion"], ""]
    for a in r["claims"]:
        lineas.append("- " + a["text"] + " " + "".join(f"[{n[c]}]" for c in a["citationIds"]))
    lineas += ["", "Fuentes:"]
    for c in citas.values():
        lineas.append(f"[{n[c['id']]}] {c.get('title') or ''} · {c['locator']}" + (f" · {c['canonicalUrl']}" if c.get("canonicalUrl") else "") + f"\n    «{c['quote']}»")
    if r.get("limitations"):
        lineas += ["", "Límites:"] + [f"- {x}" for x in r["limitations"]]
    return "\n".join(lineas)
