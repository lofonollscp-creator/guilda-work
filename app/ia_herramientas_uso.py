"""Qué herramientas usa de verdad el asistente en un despacho (AA8): cuántas veces, cuántas fallan y cuántas acciones rechaza la gente al pedirles confirmación. Sale de los
mensajes de herramienta que ya guarda cada conversación (`ia_mensajes`): no hay registro nuevo. Sirve para mejorar las descripciones de las herramientas que el modelo elige mal."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from . import ia_herramientas as h


def resumen(tenant_id: int, dias: int = 30, limite: int = 15, ahora: datetime | None = None) -> dict:
    """{dias, total, errores, rechazadas, mas_usadas: [{herramienta, llamadas, errores, rechazadas, escribe}], conflictivas: [...]} de las personas del despacho."""
    desde = ((ahora or datetime.now()) - timedelta(days=dias)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT m.nombre_herramienta AS herramienta, COUNT(*) AS llamadas, "
            "SUM(CASE WHEN LOWER(m.contenido) LIKE '{\"error\"%' THEN 1 ELSE 0 END) AS errores, "
            "SUM(CASE WHEN LOWER(m.contenido) LIKE '%\"rechazado\": true%' THEN 1 ELSE 0 END) AS rechazadas "
            "FROM ia_mensajes m JOIN usuarios u ON u.id = m.usuario_id "
            "WHERE u.tenant_id = ? AND m.rol = 'tool' AND m.creado_en >= ? AND m.nombre_herramienta IS NOT NULL "
            "GROUP BY m.nombre_herramienta ORDER BY llamadas DESC", (tenant_id, desde)).fetchall()
    finally:
        conn.close()
    todas = [{"herramienta": f["herramienta"], "llamadas": int(f["llamadas"]), "errores": int(f["errores"] or 0), "rechazadas": int(f["rechazadas"] or 0),
              "escribe": f["herramienta"] not in h.LECTURA} for f in filas]
    # Las que más fallan o más se rechazan (con al menos 3 usos para que no sea ruido): ahí hay descripciones o parámetros que mejorar.
    conflictivas = sorted((t for t in todas if t["llamadas"] >= 3 and (t["errores"] + t["rechazadas"]) / t["llamadas"] >= 0.3), key=lambda t: -(t["errores"] + t["rechazadas"]))[:limite]
    return {"dias": dias, "total": sum(t["llamadas"] for t in todas), "errores": sum(t["errores"] for t in todas), "rechazadas": sum(t["rechazadas"] for t in todas),
            "mas_usadas": todas[:limite], "conflictivas": conflictivas, "distintas": len(todas)}
