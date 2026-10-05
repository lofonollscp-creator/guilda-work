"""Atajos de prompts del chat del asistente: 6 de serie (traducidos) más los
propios de cada usuario (tabla `ia_atajos`, máximo 20)."""
from flask_babel import lazy_gettext as _l

from . import db

DE_SERIE = [
    (_l("Resumen de mi día"), _l("Hazme un resumen de mi día: tareas para hoy y atrasadas, vencimientos fiscales próximos y correos importantes sin leer.")),
    (_l("¿Qué vence esta semana?"), _l("¿Qué vencimientos fiscales y tareas vencen esta semana?")),
    (_l("Correos importantes sin leer"), _l("Muéstrame los correos sin leer que parezcan importantes y resúmelos.")),
    (_l("Tareas atrasadas"), _l("Lista mis tareas atrasadas ordenadas por prioridad.")),
    (_l("Notas de hoy"), _l("Resume las notas que he escrito hoy.")),
    (_l("Clientes con vencimientos"), _l("¿Qué clientes tienen vencimientos fiscales pendientes esta semana?")),
]


def atajos_para(usuario_id: int) -> list[dict]:
    """De serie primero, luego los del usuario. Los de serie no llevan id."""
    atajos = [{"id": None, "titulo": str(t), "prompt": str(p), "propio": False} for t, p in DE_SERIE]
    atajos += [
        {"id": a["id"], "titulo": a["titulo"], "prompt": a["prompt"], "propio": True}
        for a in db.listar_atajos_ia(usuario_id)
    ]
    return atajos
