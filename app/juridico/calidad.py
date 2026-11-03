"""Panel de calidad del Asistente jurídico: qué pasa de verdad con las consultas del despacho, para ajustar con datos y no a ojo (J7).

Todo sale de lo que ya registra cada consulta (`jur_ejecuciones`, su traza y las afirmaciones evaluadas): no mide la calidad jurídica de las respuestas —eso exige revisión profesional (el piloto)—,
sino su comportamiento: cuántas se contestan, cuántas se frenan por falta de fuentes o porque las citas no superan la verificación del servidor, cuántas necesitan reparación, cuánto tardan y con qué modelo."""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta

from .. import db

LIMITE_CONSULTAS = 5000
ESTADOS = ("answered", "needs_context", "insufficient_evidence", "failed", "cancelada", "en_curso")


def _percentil(valores: list[int], p: float) -> int | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(round(p * (len(ordenados) - 1))))]


def _traza(texto: str | None) -> dict:
    try:
        d = json.loads(texto) if texto else {}
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _motivo_de_rechazo(problema: str) -> str:
    """Agrupa los mensajes de validación por su tipo (sin los números de referencia que cambian de una consulta a otra)."""
    p = problema.strip()
    for separador in (":", "«", "'"):
        if separador in p[:90]:
            p = p.split(separador)[0].strip()
    return p[:110] or "Sin detalle"


def resumen(tenant_id: int, dias: int = 30, hoy: date | None = None) -> dict:
    """Las consultas de los últimos `dias` días del despacho: reparto por resultado, causas de las no respondidas, reparaciones, latencia, modelos y las últimas sin respuesta."""
    hoy = hoy or date.today()
    desde = (hoy - timedelta(days=max(1, dias))).isoformat()
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT id, pregunta, estado, modelo, latencia_ms, traza, creada_en FROM jur_ejecuciones WHERE tenant_id = ? AND creada_en >= ? ORDER BY id DESC LIMIT ?",
            (tenant_id, desde, LIMITE_CONSULTAS)).fetchall()
        afirmaciones = conn.execute(
            "SELECT a.evaluacion, COUNT(*) AS n FROM jur_afirmaciones a JOIN jur_ejecuciones e ON e.id = a.ejecucion_id WHERE e.tenant_id = ? AND e.creada_en >= ? GROUP BY a.evaluacion",
            (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    por_estado: Counter = Counter()
    sin_fuentes = rechazadas = reparadas = 0
    llamadas: list[int] = []
    latencias: list[int] = []
    modelos: Counter = Counter()
    motivos: Counter = Counter()
    sin_respuesta: list[dict] = []
    for f in filas:
        por_estado[f["estado"]] += 1
        t = _traza(f["traza"])
        n_llamadas = t.get("llamadas_llm")
        if isinstance(n_llamadas, int) and n_llamadas > 0:
            llamadas.append(n_llamadas)
            if n_llamadas > 1:
                reparadas += 1
        if f["latencia_ms"] is not None and f["estado"] != "en_curso":
            latencias.append(int(f["latencia_ms"]))
        if f["modelo"]:
            modelos[f["modelo"]] += 1
        causa = None
        if f["estado"] == "insufficient_evidence":
            if t.get("problemas_de_validacion"):
                rechazadas += 1
                causa = "citas_rechazadas"
                for p in t["problemas_de_validacion"]:
                    motivos[_motivo_de_rechazo(str(p))] += 1
            elif not t.get("recuperados"):
                sin_fuentes += 1
                causa = "sin_fuentes"
            else:
                causa = "sin_fundamento"
        elif f["estado"] == "needs_context":
            causa = "falta_contexto"
        elif f["estado"] == "failed":
            causa = "error"
        if causa and len(sin_respuesta) < 10:
            sin_respuesta.append({"id": f["id"], "pregunta": (f["pregunta"] or "")[:140], "causa": causa, "fecha": (f["creada_en"] or "")[:10]})
    total = len(filas)
    terminadas = total - por_estado.get("en_curso", 0)

    def pct(n: int, base: int) -> float | None:
        return round(100 * n / base, 1) if base else None

    return {
        "dias": dias, "desde": desde, "total": total, "terminadas": terminadas,
        "por_estado": {e: por_estado.get(e, 0) for e in ESTADOS if por_estado.get(e, 0)},
        "pct_respondidas": pct(por_estado.get("answered", 0), terminadas),
        "pct_sin_evidencia": pct(por_estado.get("insufficient_evidence", 0), terminadas),
        "sin_fuentes": sin_fuentes, "citas_rechazadas": rechazadas, "reparadas": reparadas,
        "pct_reparadas": pct(reparadas, len(llamadas)),
        "llamadas_medias": round(sum(llamadas) / len(llamadas), 2) if llamadas else None,
        "latencia_mediana_ms": _percentil(latencias, 0.5), "latencia_p95_ms": _percentil(latencias, 0.95),
        "modelos": modelos.most_common(6), "motivos_de_rechazo": motivos.most_common(6),
        "afirmaciones": {f["evaluacion"]: f["n"] for f in afirmaciones},
        "sin_respuesta": sin_respuesta,
        "truncado": total >= LIMITE_CONSULTAS,
    }
