"""Import/export de tareas en los dos formatos de archivo que Microsoft
Outlook Classic sabe leer y escribir para su carpeta de Tareas:

- iCalendar (.ics), un VTODO por tarea (RFC 5545) — vía "Archivo > Abrir y
  exportar > Importar o exportar > Exportar a un archivo" (o arrastrando el
  .ics sobre la carpeta de Tareas para importarlo).
- CSV, con las columnas que usa el asistente de Importar/Exportar de Outlook
  para Tareas (Subject, Start Date, Due Date, Status, % Complete, Priority,
  Categories, Body, Date Completed).

No requiere que Outlook esté instalado ni corriendo — solo trabaja con el
archivo. La sincronización en vivo (COM) es una pieza aparte (Fase D).

Cada tarea/fila se valida por separado: si falta el asunto se omite y se
cuenta en "omitidas" en vez de abortar toda la importación.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from icalendar import Calendar, Todo

from . import db


class ErrorSincronizacionOutlook(Exception):
    """Error legible para mostrar en la interfaz cuando el archivo no se puede leer."""


# --- Mapeos de vocabulario: nuestro esquema <-> el de Outlook/iCalendar -------

ESTADO_A_ICS = {
    "no_iniciada": "NEEDS-ACTION",
    "en_progreso": "IN-PROCESS",
    "completada": "COMPLETED",
    "esperando": "NEEDS-ACTION",
    "aplazada": "NEEDS-ACTION",
}
ICS_A_ESTADO = {
    "NEEDS-ACTION": "no_iniciada",
    "IN-PROCESS": "en_progreso",
    "COMPLETED": "completada",
    "CANCELLED": "no_iniciada",
}
PRIORIDAD_A_ICS = {"alta": 1, "normal": 5, "baja": 9}

ESTADO_A_CSV = {
    "no_iniciada": "Not Started",
    "en_progreso": "In Progress",
    "completada": "Completed",
    "esperando": "Waiting on someone else",
    "aplazada": "Deferred",
}
CSV_A_ESTADO = {v.lower(): k for k, v in ESTADO_A_CSV.items()}
PRIORIDAD_A_CSV = {"baja": "Low", "normal": "Normal", "alta": "High"}
CSV_A_PRIORIDAD = {v.lower(): k for k, v in PRIORIDAD_A_CSV.items()}

COLUMNAS_CSV = ["Subject", "Start Date", "Due Date", "Status", "% Complete", "Priority", "Categories", "Body", "Date Completed"]

# Encabezados alternativos que se aceptan al importar un CSV (de Outlook o de
# otra herramienta), normalizados a minúsculas y sin espacios/símbolos.
ALIAS_COLUMNAS_CSV = {
    "subject": "asunto",
    "startdate": "fecha_inicio",
    "duedate": "fecha_vencimiento",
    "status": "estado",
    "complete": "porcentaje_completado",
    "percentcomplete": "porcentaje_completado",
    "priority": "prioridad",
    "categories": "categoria_outlook",
    "category": "categoria_outlook",
    "body": "cuerpo",
    "description": "cuerpo",
    "datecompleted": "fecha_completada",
}


def _normalizar_encabezado(nombre: str) -> str:
    return "".join(c for c in nombre.lower() if c.isalnum())


def _ics_a_prioridad(valor) -> str:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return "normal"
    if 1 <= n <= 4:
        return "alta"
    if 6 <= n <= 9:
        return "baja"
    return "normal"


def _fecha_iso(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor[:10])
    except ValueError:
        return None


def _parsear_fecha_csv(valor: str | None) -> str | None:
    """Acepta ISO (2026-07-13) y los formatos más comunes que usa Outlook
    según la configuración regional (7/13/2026, 13/07/2026, con hora...)."""
    if not valor:
        return None
    valor = valor.strip()
    if not valor:
        return None
    for fmt in (
        "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y",
        "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(valor, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# --- iCalendar (.ics) ----------------------------------------------------------

def exportar_ics(tareas) -> str:
    """`tareas`: filas de tareas_outlook (p.ej. de db.listar_tareas_outlook())."""
    cal = Calendar()
    cal.add("prodid", "-//Guilda Work//Tareas//ES")
    cal.add("version", "2.0")
    for t in tareas:
        todo = Todo()
        uid = t["outlook_entry_id"] or f"guilda-work-tarea-{t['id']}@guilda-work.local"
        todo.add("uid", uid)
        todo.add("summary", t["asunto"])
        if t["cuerpo"]:
            todo.add("description", t["cuerpo"])
        todo.add("status", ESTADO_A_ICS.get(t["estado"], "NEEDS-ACTION"))
        todo.add("percent-complete", t["porcentaje_completado"])
        todo.add("priority", PRIORIDAD_A_ICS.get(t["prioridad"], 5))
        fecha_inicio = _fecha_iso(t["fecha_inicio"])
        if fecha_inicio:
            todo.add("dtstart", fecha_inicio)
        fecha_vencimiento = _fecha_iso(t["fecha_vencimiento"])
        if fecha_vencimiento:
            todo.add("due", fecha_vencimiento)
        if t["fecha_completada"]:
            try:
                todo.add("completed", datetime.fromisoformat(t["fecha_completada"]))
            except ValueError:
                pass
        if t["categoria_outlook"]:
            todo.add("categories", [t["categoria_outlook"]])
        cal.add_component(todo)
    return cal.to_ical().decode("utf-8")


def importar_ics(contenido: str) -> dict:
    """Devuelve {"creadas": N, "actualizadas": N, "omitidas": N}."""
    resumen = {"creadas": 0, "actualizadas": 0, "omitidas": 0}
    try:
        cal = Calendar.from_ical(contenido)
    except ValueError as e:
        raise ErrorSincronizacionOutlook(f"El archivo no es un .ics válido: {e}") from e

    for componente in cal.walk("VTODO"):
        asunto = str(componente.get("summary") or "").strip()
        if not asunto:
            resumen["omitidas"] += 1
            continue

        uid = str(componente.get("uid")) if componente.get("uid") else None
        cuerpo = str(componente.get("description")) if componente.get("description") else None
        estado_ics = str(componente.get("status") or "NEEDS-ACTION").upper()
        estado = ICS_A_ESTADO.get(estado_ics, "no_iniciada")
        percent = componente.get("percent-complete")
        porcentaje = int(percent) if percent is not None else (100 if estado == "completada" else 0)
        prioridad = _ics_a_prioridad(componente.get("priority"))

        dtstart = componente.get("dtstart")
        fecha_inicio = dtstart.dt.isoformat()[:10] if dtstart else None
        due = componente.get("due")
        fecha_vencimiento = due.dt.isoformat()[:10] if due else None
        completed = componente.get("completed")
        fecha_completada = completed.dt.isoformat()[:19] if completed else None

        categoria = None
        categorias = componente.get("categories")
        if categorias is not None:
            valores = list(categorias.cats) if hasattr(categorias, "cats") else [categorias]
            if valores:
                categoria = str(valores[0])

        _, creada = db.upsert_tarea_outlook_por_entry_id(
            uid,
            asunto=asunto, cuerpo=cuerpo, estado=estado,
            porcentaje_completado=porcentaje, prioridad=prioridad,
            fecha_inicio=fecha_inicio, fecha_vencimiento=fecha_vencimiento,
            fecha_completada=fecha_completada, categoria_outlook=categoria,
        )
        resumen["creadas" if creada else "actualizadas"] += 1
    return resumen


# --- CSV -------------------------------------------------------------------

def exportar_csv_outlook(tareas) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(COLUMNAS_CSV)
    for t in tareas:
        escritor.writerow([
            t["asunto"],
            (t["fecha_inicio"] or "")[:10],
            (t["fecha_vencimiento"] or "")[:10],
            ESTADO_A_CSV.get(t["estado"], "Not Started"),
            t["porcentaje_completado"],
            PRIORIDAD_A_CSV.get(t["prioridad"], "Normal"),
            t["categoria_outlook"] or "",
            t["cuerpo"] or "",
            (t["fecha_completada"] or "")[:10],
        ])
    return salida.getvalue()


def importar_csv_outlook(contenido: str) -> dict:
    """Devuelve {"creadas": N, "actualizadas": N, "omitidas": N}."""
    resumen = {"creadas": 0, "actualizadas": 0, "omitidas": 0}
    lector = csv.DictReader(io.StringIO(contenido))
    if not lector.fieldnames:
        raise ErrorSincronizacionOutlook("El CSV está vacío o no tiene cabecera.")

    mapa_columnas = {}
    for encabezado in lector.fieldnames:
        campo = ALIAS_COLUMNAS_CSV.get(_normalizar_encabezado(encabezado))
        if campo:
            mapa_columnas[encabezado] = campo
    if "asunto" not in mapa_columnas.values():
        raise ErrorSincronizacionOutlook(
            "El CSV no tiene una columna de asunto reconocible (se esperaba \"Subject\")."
        )

    for fila in lector:
        datos = {mapa_columnas[enc]: valor for enc, valor in fila.items() if enc in mapa_columnas}
        asunto = (datos.get("asunto") or "").strip()
        if not asunto:
            resumen["omitidas"] += 1
            continue

        estado_txt = (datos.get("estado") or "").strip().lower()
        prioridad_txt = (datos.get("prioridad") or "").strip().lower()
        try:
            porcentaje = int(float(datos.get("porcentaje_completado") or 0))
        except ValueError:
            porcentaje = 0

        tid = db.crear_tarea_outlook(
            asunto=asunto,
            cuerpo=(datos.get("cuerpo") or "").strip() or None,
            estado=CSV_A_ESTADO.get(estado_txt, "no_iniciada"),
            porcentaje_completado=max(0, min(100, porcentaje)),
            prioridad=CSV_A_PRIORIDAD.get(prioridad_txt, "normal"),
            fecha_inicio=_parsear_fecha_csv(datos.get("fecha_inicio")),
            fecha_vencimiento=_parsear_fecha_csv(datos.get("fecha_vencimiento")),
            categoria_outlook=(datos.get("categoria_outlook") or "").strip() or None,
        )
        # crear_tarea_outlook no admite fecha_completada al crear; se aplica
        # en un segundo paso si el CSV trae una tarea ya cerrada.
        fecha_completada = _parsear_fecha_csv(datos.get("fecha_completada"))
        if fecha_completada:
            db.editar_tarea_outlook(tid, fecha_completada=fecha_completada)
        resumen["creadas"] += 1
    return resumen
