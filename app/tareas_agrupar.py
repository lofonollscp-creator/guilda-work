"""Agrupar la lista de tareas por cliente, proyecto, responsable, fecha, estado o prioridad (T1). Función pura: recibe las tareas ya filtradas y los nombres que hacen falta, y devuelve los grupos
en el orden en que se enseñan, cada uno con su título y sus tareas. Las tareas sin valor (sin cliente, sin proyecto, sin fecha…) forman su propio grupo, al final."""
from __future__ import annotations

from datetime import date, timedelta

from flask_babel import gettext as _

AGRUPACIONES = ("cliente", "proyecto", "responsable", "fecha", "estado", "prioridad")
ORDEN_ESTADOS = ("no_iniciada", "en_progreso", "esperando", "en_revision", "aplazada", "completada")
ORDEN_PRIORIDADES = ("alta", "normal", "baja")


def _tramo_de_fecha(fecha: str | None, hoy: date) -> tuple[int, str]:
    if not fecha:
        return 9, _("Sin fecha")
    dia = fecha[:10]
    if dia < hoy.isoformat():
        return 0, _("Vencidas")
    if dia == hoy.isoformat():
        return 1, _("Hoy")
    if dia == (hoy + timedelta(days=1)).isoformat():
        return 2, _("Mañana")
    if dia <= (hoy + timedelta(days=7)).isoformat():
        return 3, _("Esta semana")
    if dia <= (hoy + timedelta(days=30)).isoformat():
        return 4, _("Este mes")
    return 5, _("Más adelante")


def agrupar(clave: str, tareas: list, *, clientes: dict[int, str], proyectos: dict[int, str], personas: dict[int, str], estados: dict[str, str], prioridades: dict[str, str],
            hoy: date | None = None) -> list[dict]:
    """`clientes`, `proyectos` y `personas` son {id: nombre}; `estados` y `prioridades`, {valor: etiqueta}. Devuelve [{"clave", "titulo", "tareas"}]."""
    if clave not in AGRUPACIONES:
        return []
    hoy = hoy or date.today()
    sin = {"cliente": _("Sin cliente"), "proyecto": _("Sin proyecto"), "responsable": _("Sin responsable")}
    grupos: dict = {}
    for t in tareas:
        if clave == "cliente":
            k = t["cliente_fiscal_id"]
            orden, titulo = (1, sin["cliente"]) if not k or k not in clientes else (0, clientes[k])
        elif clave == "proyecto":
            k = t["categoria_id"]
            orden, titulo = (1, sin["proyecto"]) if not k or k not in proyectos else (0, proyectos[k])
        elif clave == "responsable":
            k = t["asignada_a"] or t["usuario_id"]
            orden, titulo = (1, sin["responsable"]) if not k or k not in personas else (0, personas[k])
        elif clave == "fecha":
            orden, titulo = _tramo_de_fecha(t["fecha_vencimiento"], hoy)
            k = orden
        elif clave == "estado":
            k = t["estado"]
            orden, titulo = (ORDEN_ESTADOS.index(k) if k in ORDEN_ESTADOS else 99), estados.get(k, k or "")
        else:
            k = t["prioridad"]
            orden, titulo = (ORDEN_PRIORIDADES.index(k) if k in ORDEN_PRIORIDADES else 99), prioridades.get(k, k or "")
        g = grupos.setdefault((orden, titulo.lower() if clave in ("cliente", "proyecto", "responsable") else "", titulo), {"clave": clave, "titulo": titulo, "tareas": []})
        g["tareas"].append(t)
    return [grupos[k] for k in sorted(grupos)]
