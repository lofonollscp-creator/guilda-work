"""«Cómo va lo mío»: para cada trabajo en curso con la gestoría, en qué fase está, quién lo lleva y cuándo se movió por última vez, sin que el cliente tenga que preguntarlo.

Se calcula con lo que ya tiene la tarea (estado, porcentaje, fechas y responsable); la revisión interna no se le cuenta (para él sigue «en curso»). Sin tablas nuevas."""
from __future__ import annotations

from . import db

FASES = ("no_iniciada", "en_progreso", "completada")           # las tres etapas visibles; «en espera» y «aplazada» son pausas dentro de la etapa en que están


def _etapa(estado: str) -> int:
    return {"no_iniciada": 0, "esperando": 1, "aplazada": 1, "en_progreso": 1, "en_revision": 1, "completada": 2}.get(estado, 0)


def enriquecer(trabajo: list[dict], tenant_id: int) -> list[dict]:
    """Las mismas tareas con `fases` (lista de {texto, estado: hecha|actual|pendiente}), `pausa` (texto si está en espera o aplazada), `responsable`, `actualizada_en` y `porcentaje`. Requiere contexto de petición (traduce)."""
    if not trabajo:
        return []
    from flask_babel import gettext as _
    ids = [t["id"] for t in trabajo]
    conn = db.get_connection()
    try:
        extra = {f["id"]: f for f in conn.execute(f"SELECT id, usuario_id, porcentaje_completado, actualizada_en, creada_en, fecha_completada FROM tareas_outlook WHERE id IN ({','.join('?' * len(ids))})", ids)}
    finally:
        conn.close()
    nombres: dict[int, str | None] = {}
    salida = []
    textos = (_("Recibido"), _("En curso"), _("Terminado"))
    for t in trabajo:
        e = extra.get(t["id"])
        etapa = _etapa(t["estado"])
        uid = e["usuario_id"] if e else None
        if uid and uid not in nombres:
            nombres[uid] = (db.nombre_mostrado_usuario(uid) or "").strip() or None
        salida.append({**t, "fases": [{"texto": textos[i], "estado": "hecha" if i < etapa or (i == etapa == 2) else "actual" if i == etapa else "pendiente"} for i in range(3)],
                       "pausa": {"esperando": _("En espera"), "aplazada": _("Aplazada")}.get(t["estado"]), "responsable": nombres.get(uid) if uid else None,
                       "actualizada_en": ((e["fecha_completada"] if t["estado"] == "completada" and e["fecha_completada"] else e["actualizada_en"] or e["creada_en"]) or "")[:10] if e else "",
                       "porcentaje": min(100, max(0, e["porcentaje_completado"] or 0)) if e else 0})
    return salida
