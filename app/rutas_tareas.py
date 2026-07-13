"""Rutas de la pestaña "Tareas" (estilo Microsoft Outlook): lista, calendario
e import/export con Outlook. Vive en su propio Blueprint para no seguir
haciendo crecer app/main.py — es, en la práctica, una sección independiente
dentro de la app (sin relación con los menús ni con las tareas con duración).
"""
import calendar as calendario_std
from datetime import date, timedelta

from flask import Blueprint, Response, abort, redirect, render_template, request, url_for

from . import db, outlook_ics

tareas_bp = Blueprint("tareas", __name__, url_prefix="/tareas")

ESTADOS = [
    ("no_iniciada", "No iniciada"),
    ("en_progreso", "En progreso"),
    ("completada", "Completada"),
    ("esperando", "Esperando a otros"),
    ("aplazada", "Aplazada"),
]
PRIORIDADES = [
    ("baja", "Baja"),
    ("normal", "Normal"),
    ("alta", "Alta"),
]
VISTAS_CALENDARIO = ["mes", "semana", "semana_laboral", "dia"]
HORAS_DIA = [f"{h:02d}:00" for h in range(6, 22)]
NOMBRES_MES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


PALETA_CATEGORIAS = ["#4a6cf7", "#e0555a", "#2fa66a", "#d98c1f", "#8a5cf5", "#1f9fd9", "#c94f8a", "#0f9b8e"]


@tareas_bp.app_template_filter("color_categoria")
def color_categoria(nombre: str | None) -> str:
    """Color estable por nombre de categoría (misma idea que el color por menú)."""
    if not nombre:
        return "#7c8ba1"
    indice = sum(ord(c) for c in nombre) % len(PALETA_CATEGORIAS)
    return PALETA_CATEGORIAS[indice]


def _lunes_de_semana(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _rango_para_vista(vista: str, ancla: date) -> tuple[date, date]:
    """(inicio, fin) inclusive de los días a mostrar en la parrilla de la vista dada."""
    if vista == "dia":
        return ancla, ancla
    if vista == "semana_laboral":
        lunes = _lunes_de_semana(ancla)
        return lunes, lunes + timedelta(days=4)
    if vista == "semana":
        lunes = _lunes_de_semana(ancla)
        return lunes, lunes + timedelta(days=6)
    # "mes": semanas completas (lunes a domingo) que cubren el mes, como Outlook
    primer_dia_mes = ancla.replace(day=1)
    ultimo_dia_mes = date(ancla.year, ancla.month, calendario_std.monthrange(ancla.year, ancla.month)[1])
    inicio = _lunes_de_semana(primer_dia_mes)
    fin = _lunes_de_semana(ultimo_dia_mes) + timedelta(days=6)
    return inicio, fin


def _mover_ancla(vista: str, ancla: date, direccion: int) -> date:
    """direccion: -1 (anterior) o +1 (siguiente). Desplaza la fecha ancla un "paso" de la vista."""
    if vista == "dia":
        return ancla + timedelta(days=direccion)
    if vista in ("semana", "semana_laboral"):
        return ancla + timedelta(days=7 * direccion)
    mes = ancla.month - 1 + direccion
    anio = ancla.year + mes // 12
    mes = mes % 12 + 1
    ultimo_dia = calendario_std.monthrange(anio, mes)[1]
    return date(anio, mes, min(ancla.day, ultimo_dia))


@tareas_bp.route("/")
def listar():
    estado = request.args.get("estado") or None
    prioridad = request.args.get("prioridad") or None
    categoria = request.args.get("categoria") or None
    q = request.args.get("q") or None
    incluir_completadas = request.args.get("completadas") == "1"

    if estado is None and not incluir_completadas:
        # Vista por defecto: como el "To-Do List" de Outlook, oculta lo ya
        # completado para que la lista no se llene de tareas resueltas.
        tareas = [
            t for t in db.listar_tareas_outlook(prioridad=prioridad, categoria_outlook=categoria, texto=q)
            if t["estado"] != "completada"
        ]
    else:
        tareas = db.listar_tareas_outlook(
            estado=estado, prioridad=prioridad, categoria_outlook=categoria, texto=q
        )

    return render_template(
        "tareas_lista.html",
        tareas=tareas,
        estados=ESTADOS,
        prioridades=PRIORIDADES,
        categorias_outlook=db.listar_categorias_outlook(),
        estado=estado or "",
        prioridad=prioridad or "",
        categoria=categoria or "",
        q=q or "",
        incluir_completadas=incluir_completadas,
    )


@tareas_bp.route("/calendario")
def calendario():
    vista = request.args.get("vista", "mes")
    if vista not in VISTAS_CALENDARIO:
        vista = "mes"
    try:
        ancla = date.fromisoformat(request.args.get("fecha", ""))
    except ValueError:
        ancla = date.today()

    inicio, fin = _rango_para_vista(vista, ancla)

    # Se traen todas las tareas activas (sin filtrar por fecha en SQL) porque
    # cada tarea se ubica en el día de su vencimiento o, si no tiene, en el de
    # inicio — ese cálculo se hace aquí, no es un filtro directo de columna.
    tareas_por_dia: dict[str, list] = {}
    for t in db.listar_tareas_outlook():
        fecha_efectiva = (t["fecha_vencimiento"] or t["fecha_inicio"] or "")[:10]
        if fecha_efectiva:
            tareas_por_dia.setdefault(fecha_efectiva, []).append(t)

    dias = []
    cursor = inicio
    while cursor <= fin:
        iso = cursor.isoformat()
        dias.append({
            "fecha": cursor,
            "iso": iso,
            "es_hoy": cursor == date.today(),
            "es_mes_actual": cursor.month == ancla.month,
            "tareas": tareas_por_dia.get(iso, []),
        })
        cursor += timedelta(days=1)
    semanas = [dias[i:i + 7] for i in range(0, len(dias), 7)] if vista == "mes" else None

    return render_template(
        "tareas_calendario.html",
        vista=vista,
        ancla=ancla,
        titulo_rango=_titulo_rango(vista, ancla, inicio, fin),
        dias=dias,
        semanas=semanas,
        anterior=_mover_ancla(vista, ancla, -1).isoformat(),
        siguiente=_mover_ancla(vista, ancla, 1).isoformat(),
        hoy=date.today().isoformat(),
        horas=HORAS_DIA,
        prioridades=PRIORIDADES,
        categorias_outlook=db.listar_categorias_outlook(),
        volver_a=url_for("tareas.calendario", vista=vista, fecha=ancla.isoformat()),
    )


def _titulo_rango(vista: str, ancla: date, inicio: date, fin: date) -> str:
    if vista == "dia":
        return f"{ancla.day} de {NOMBRES_MES[ancla.month]} de {ancla.year}"
    if vista == "mes":
        return f"{NOMBRES_MES[ancla.month].capitalize()} de {ancla.year}"
    if inicio.month == fin.month:
        return f"{inicio.day}–{fin.day} de {NOMBRES_MES[inicio.month]} de {inicio.year}"
    return f"{inicio.day} de {NOMBRES_MES[inicio.month]} – {fin.day} de {NOMBRES_MES[fin.month]} de {fin.year}"


@tareas_bp.route("/", methods=["POST"])
def crear():
    asunto = request.form.get("asunto", "").strip()
    if asunto:
        db.crear_tarea_outlook(
            asunto=asunto,
            prioridad=request.form.get("prioridad", "normal"),
            fecha_inicio=request.form.get("fecha_inicio") or None,
            fecha_vencimiento=request.form.get("fecha_vencimiento") or None,
            categoria_outlook=request.form.get("categoria_outlook") or None,
        )
    return redirect(request.form.get("volver_a") or url_for("tareas.listar"))


@tareas_bp.route("/<int:tarea_id>/editar", methods=["GET", "POST"])
def editar(tarea_id: int):
    tarea = db.obtener_tarea_outlook(tarea_id)
    if tarea is None:
        abort(404)

    if request.method == "POST":
        asunto = request.form.get("asunto", "").strip()
        if not asunto:
            return render_template(
                "tarea_outlook_editar.html", tarea=tarea, estados=ESTADOS, prioridades=PRIORIDADES,
                error="El asunto no puede estar vacío.",
            )
        campos = {
            "asunto": asunto,
            "cuerpo": request.form.get("cuerpo", "").strip() or None,
            "estado": request.form.get("estado", "no_iniciada"),
            "prioridad": request.form.get("prioridad", "normal"),
            "porcentaje_completado": int(request.form.get("porcentaje_completado") or 0),
            "fecha_inicio": request.form.get("fecha_inicio") or None,
            "fecha_vencimiento": request.form.get("fecha_vencimiento") or None,
            "categoria_outlook": request.form.get("categoria_outlook", "").strip() or None,
        }
        if campos["estado"] == "completada" and tarea["estado"] != "completada":
            db.completar_tarea_outlook(tarea_id)
            campos.pop("estado")
            campos.pop("porcentaje_completado")
        db.editar_tarea_outlook(tarea_id, **campos)
        return redirect(url_for("tareas.listar"))

    return render_template("tarea_outlook_editar.html", tarea=tarea, estados=ESTADOS, prioridades=PRIORIDADES, error=None)


@tareas_bp.route("/<int:tarea_id>/completar", methods=["POST"])
def completar(tarea_id: int):
    db.completar_tarea_outlook(tarea_id)
    return redirect(request.referrer or url_for("tareas.listar"))


@tareas_bp.route("/<int:tarea_id>/eliminar", methods=["POST"])
def eliminar(tarea_id: int):
    if db.obtener_tarea_outlook(tarea_id) is None:
        abort(404)
    db.eliminar_tarea_outlook(tarea_id)
    return redirect(url_for("tareas.listar"))


@tareas_bp.route("/<int:tarea_id>/restaurar", methods=["POST"])
def restaurar(tarea_id: int):
    db.restaurar_tarea_outlook(tarea_id)
    return redirect(request.form.get("volver_a") or url_for("papelera"))


@tareas_bp.route("/<int:tarea_id>/eliminar-definitivamente", methods=["POST"])
def eliminar_definitivamente(tarea_id: int):
    db.eliminar_tarea_outlook_definitivamente(tarea_id)
    return redirect(request.form.get("volver_a") or url_for("papelera"))


@tareas_bp.route("/sincronizar")
def sincronizar():
    return render_template("tareas_outlook_sync.html", resumen=None, error=None)


@tareas_bp.route("/exportar.ics")
def exportar_ics():
    contenido = outlook_ics.exportar_ics(db.listar_tareas_outlook())
    return Response(
        contenido,
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=guilda_work_tareas.ics"},
    )


@tareas_bp.route("/exportar.csv")
def exportar_csv():
    contenido = outlook_ics.exportar_csv_outlook(db.listar_tareas_outlook())
    return Response(
        contenido,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=guilda_work_tareas.csv"},
    )


@tareas_bp.route("/importar", methods=["POST"])
def importar_archivo():
    archivo = request.files.get("archivo")
    if archivo is None or not archivo.filename:
        return render_template(
            "tareas_outlook_sync.html", resumen=None,
            error="Elige un archivo .ics o .csv exportado desde Outlook (o desde Guilda Work).",
        )

    contenido = archivo.read().decode("utf-8", errors="replace")
    try:
        if archivo.filename.lower().endswith(".csv"):
            resumen = outlook_ics.importar_csv_outlook(contenido)
        else:
            resumen = outlook_ics.importar_ics(contenido)
    except outlook_ics.ErrorSincronizacionOutlook as e:
        return render_template("tareas_outlook_sync.html", resumen=None, error=str(e))

    return render_template("tareas_outlook_sync.html", resumen=resumen, error=None)
