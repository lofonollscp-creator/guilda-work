"""Conjunto de evaluación del asistente jurídico (hito 5, piloto con profesionales). Lo ANOTA un profesional; este módulo solo lo ejecuta y mide, sin inventar resultados.

Formato del conjunto (JSON): lista de casos
  {"id": "c01", "pregunta": "...", "fecha_juridica": "AAAA-MM-DD", "colecciones": ["legislacion"],
   "esperadas": [{"id_externo": "BOE-A-1992-28740", "localizador": "Artículo 91"}],   # fuentes que hacen falta (vacía = el caso debe quedar sin base suficiente)
   "debe_ser_insuficiente": false, "sintetico": true|false}

Mide, sobre el corpus real autorizado y con el tamaño del corpus informado: **recuperación** (¿está entre los 10 primeros alguna fuente necesaria?) y, para los casos «insuficientes», que no se
recupere nada de aplicación. La **corrección** de las respuestas, que las citas sostengan lo afirmado y la aplicabilidad temporal los puntúa una persona con `respuestas_para_revision`.
Los objetivos del piloto (cero filtraciones entre organizaciones, cero citas inventadas aceptadas, ≥90 % de citas que sostienen su afirmación, ≥85 % de consultas con una fuente necesaria entre los 10
primeros) son objetivos de producto a validar, NO resultados conseguidos. Los casos `sintetico: true` prueban el software, no acreditan calidad jurídica."""
from __future__ import annotations

import json

from .. import db
from . import busqueda, corpus


def cargar(ruta: str) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        casos = json.load(f)
    if not isinstance(casos, list):
        raise ValueError("El conjunto de evaluación debe ser una lista de casos.")
    ids = set()
    for c in casos:
        if not c.get("id") or c["id"] in ids or not (c.get("pregunta") or "").strip():
            raise ValueError(f"Caso inválido o con id repetido: {c.get('id')!r}")
        ids.add(c["id"])
    return casos


def recuperacion(tenant_id: int, casos: list[dict], embedder=None, k: int = 10) -> dict:
    """Recuperación por caso y agregada. Un caso con `esperadas` acierta si alguno de los k primeros documentos es una fuente esperada (y, si se indica localizador, el fragmento coincide)."""
    resultados, aciertos, evaluables, insuficientes_ok, insuficientes = [], 0, 0, 0, 0
    for c in casos:
        r = busqueda.buscar(tenant_id, c["pregunta"], colecciones=c.get("colecciones"), fecha_juridica=c.get("fecha_juridica"), limite=k, embedder=embedder)
        conn = db.get_connection()
        try:
            hallados = [(conn.execute("SELECT id_externo FROM jur_documentos WHERE id = ?", (x["documento_id"],)).fetchone()["id_externo"], x["localizador"]) for x in r["resultados"][:k]]
        finally:
            conn.close()
        esperadas = c.get("esperadas") or []
        if c.get("debe_ser_insuficiente"):
            insuficientes += 1
            ok = not hallados
            insuficientes_ok += ok
        else:
            evaluables += 1
            ok = any(e["id_externo"] == h[0] and (not e.get("localizador") or e["localizador"] == h[1]) for e in esperadas for h in hallados)
            aciertos += ok
        resultados.append({"id": c["id"], "acierto": bool(ok), "hallados": hallados, "sintetico": bool(c.get("sintetico"))})
    cob = corpus.cobertura()
    return {"casos": len(casos), "evaluables": evaluables, "recuperan_fuente_necesaria": aciertos, "porcentaje_recuperacion": round(100 * aciertos / evaluables, 1) if evaluables else None,
            "insuficientes": insuficientes, "insuficientes_correctos": insuficientes_ok, "k": k, "modo": r["modo"] if casos else None,
            "corpus": {c["fuente_id"]: {"documentos": c["documentos"], "fragmentos": c["fragmentos"]} for c in cob if c["documentos"]}, "detalle": resultados,
            "aviso": "Medición de recuperación sobre ESTE corpus; no mide la corrección jurídica de las respuestas. Los casos sintéticos no acreditan calidad."}


def respuestas_para_revision(tenant_id: int, usuario_id: int, casos: list[dict], generador=None, embedder=None) -> list[dict]:
    """Lanza cada caso y devuelve la respuesta con sus citas y una hoja en blanco para que un profesional puntúe: corrección, citas que sostienen la afirmación, aplicabilidad temporal, tiempo de revisión."""
    from . import asistente
    conv = asistente.crear_conversacion(tenant_id, usuario_id, titulo="Evaluación")
    salida = []
    for c in casos:
        r = asistente.consultar(tenant_id, usuario_id, conv, c["pregunta"], colecciones=c.get("colecciones"), fecha_juridica=c.get("fecha_juridica"), generador=generador, embedder=embedder)
        salida.append({"id": c["id"], "pregunta": c["pregunta"], "respuesta": r, "puntuacion_profesional": {"correcta": None, "citas_que_sostienen": None, "citas_inventadas": None, "aplicabilidad_temporal_correcta": None,
                                                                                                         "util": None, "minutos_de_revision": None, "comentario": ""}})
    return salida
