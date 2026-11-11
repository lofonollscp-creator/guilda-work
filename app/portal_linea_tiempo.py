"""La línea de tiempo de un modelo en «Impuestos» (V9): Recibido → En preparación → Presentado, con lo que falta de la persona en el paso en que está. Se calcula con lo que ya tiene el vencimiento; sin tablas nuevas.

Mismo aspecto que «Cómo va este trabajo» del inicio (`portal-fases`): cada paso es `hecha`, `actual` o `pendiente`."""
from __future__ import annotations


def de_vencimiento(v) -> list[dict]:
    """`[{clave, estado}]`: Recibido siempre hecho; En preparación es el actual mientras no se presente; Presentado se completa al presentarlo. Fuera de plazo deja «Presentado» como paso actual (hay que moverlo)."""
    presentado = v["estado"] == "presentado"
    fuera = v["estado"] == "fuera_plazo"
    return [
        {"clave": "recibido", "estado": "hecha"},
        {"clave": "preparacion", "estado": "hecha" if presentado else ("hecha" if fuera else "actual")},
        {"clave": "presentado", "estado": "hecha" if presentado else ("actual" if fuera else "pendiente")},
    ]


def falta_de_ti(v) -> str:
    """Lo que la gestoría espera de la persona para poder seguir (vacío si no espera nada o ya está presentado)."""
    if v["estado"] == "presentado":
        return ""
    return (v["documento_solicitado"] or "").strip()
