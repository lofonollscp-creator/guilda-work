"""Página de proyecto: resumen, lista, tablero, calendario, notas compartidas, actividad y plantillas.
Un proyecto es una categoría de siempre; aquí se ve y se trabaja en equipo. El registro cronológico
de notas y eventos de cada persona sigue en /menu/<id>?registro=1 (pestaña «Registro»)."""
from datetime import date, datetime

from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, url_for
from flask_babel import format_date
from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l

from . import db, proyecto_plantillas, quickadd
from .auth import login_required
from .rutas_tareas import ESTADOS, _mover_ancla, _rango_para_vista, _titulo_rango

proyectos_bp = Blueprint("proyectos", __name__, url_prefix="/proyecto")

ETIQUETAS_ESTADO = {"activo": _l("Activo"), "en_pausa": _l("En pausa"), "completado": _l("Completado"), "archivado": _l("Archivado")}


def _proyecto_o_404(proyecto_id: int) -> dict:
    proyecto = db.obtener_proyecto(g.usuario_id, proyecto_id)
    if proyecto is None:
        abort(404)
    return proyecto


def _organiza(proyecto: dict) -> bool:
    return proyecto["rol"] in ("dueno", "colabora")


def _iniciales(nombre: str) -> str:
    partes = [p for p in (nombre or "?").replace("@", " ").replace(".", " ").split() if p]
    return ("".join(p[0] for p in partes[:2]) or "?").upper()


def _contexto(proyecto: dict, activa: str) -> dict:
    """Lo que necesita la cabecera común (y las pestañas)."""
    proyecto_id = proyecto["id"]
    miembros = db.miembros_de_proyecto(proyecto_id)
    equipo = [{"usuario_id": proyecto["usuario_id"], "nombre": proyecto["dueno_nombre"], "rol": "dueno", "es_dueno": True}] + miembros
    asignables = [m for m in equipo if m["rol"] in ("dueno", "colabora")]
    resumen = db.resumen_proyecto(g.usuario_id, proyecto_id)
    return {
        "p": proyecto, "pestana": activa, "equipo": equipo, "asignables": asignables, "resumen": resumen,
        "organiza": _organiza(proyecto), "es_dueno": proyecto["rol"] == "dueno",
        "estados": list(db.ESTADOS_PROYECTO), "etiquetas_estado": ETIQUETAS_ESTADO, "iniciales": _iniciales,
        "secciones": db.listar_secciones(proyecto_id),
    }


@proyectos_bp.route("/<int:proyecto_id>")
@login_required
def resumen(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    contexto = _contexto(proyecto, "resumen")
    abiertas = [t for t in db.tareas_de_proyecto(g.usuario_id, proyecto_id, incluir_completadas=False)]
    abiertas.sort(key=lambda t: (t["fecha_vencimiento"] is None, t["fecha_vencimiento"] or "", t["id"]))
    hoy = datetime.now().strftime("%Y-%m-%d")
    contexto.update({"proximas": abiertas[:8], "hoy": hoy, "plantillas": proyecto_plantillas.catalogo(g.usuario_id) if contexto["organiza"] else []})
    if proyecto["cliente_fiscal_id"]:
        contexto.update({
            "vencimientos_cliente": db.listar_vencimientos_fiscales(g.tenant_id, estado="pendiente", cliente_fiscal_id=proyecto["cliente_fiscal_id"])[:5] if g.tenant_id is not None else [],
            "correos_cliente": db.correos_de_cliente_para(g.usuario_id, proyecto["cliente_fiscal_id"]),
        })
    if contexto["es_dueno"]:
        contexto.update({
            "clientes": db.listar_clientes_fiscales(g.tenant_id) if g.tenant_id is not None else [],
            "companeros": [c for c in db.listar_companeros_tenant(g.usuario_id) if c["id"] not in {m["usuario_id"] for m in contexto["equipo"]}],
        })
    return render_template("proyecto_resumen.html", **contexto)


@proyectos_bp.route("/<int:proyecto_id>/lista")
@login_required
def lista(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    contexto = _contexto(proyecto, "lista")
    tareas = db.tareas_de_proyecto(g.usuario_id, proyecto_id)
    por_seccion: dict = {None: []}
    for s in contexto["secciones"]:
        por_seccion[s["id"]] = []
    for t in tareas:
        por_seccion.setdefault(t["seccion_id"] if t["seccion_id"] in por_seccion else None, []).append(t)
    contexto.update({"por_seccion": por_seccion, "hoy": datetime.now().strftime("%Y-%m-%d"), "error": (request.args.get("error") or "")[:200] or None})
    return render_template("proyecto_lista.html", **contexto)


def _volver(proyecto_id: int, destino: str = "proyectos.lista", **kw):
    return redirect(url_for(destino, proyecto_id=proyecto_id, **kw))


# --- ajustes y miembros (solo el dueño) ---

def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


@proyectos_bp.route("/<int:proyecto_id>/ajustes", methods=["POST"])
@login_required
def ajustes(proyecto_id: int):
    _proyecto_o_404(proyecto_id)
    f = request.form
    ok = db.actualizar_proyecto(
        g.usuario_id, proyecto_id, estado=f.get("estado") or None, descripcion=f.get("descripcion", ""),
        fecha_objetivo=f.get("fecha_objetivo", ""), responsable_id=_entero(f.get("responsable_id")), cambiar_responsable=True,
        cliente_fiscal_id=_entero(f.get("cliente_fiscal_id")), cambiar_cliente=True,
    )
    if not ok:
        abort(400 if db.rol_en_proyecto(g.usuario_id, proyecto_id) == "dueno" else 403)
    return _volver(proyecto_id, "proyectos.resumen")


@proyectos_bp.route("/<int:proyecto_id>/miembros", methods=["POST"])
@login_required
def compartir(proyecto_id: int):
    _proyecto_o_404(proyecto_id)
    otro = _entero(request.form.get("usuario_id"))
    if otro is None or not db.compartir_proyecto(g.usuario_id, proyecto_id, otro, request.form.get("rol", "colabora")):
        abort(400)
    return _volver(proyecto_id, "proyectos.resumen")


@proyectos_bp.route("/<int:proyecto_id>/miembros/<int:otro_id>/quitar", methods=["POST"])
@login_required
def quitar_miembro(proyecto_id: int, otro_id: int):
    _proyecto_o_404(proyecto_id)
    if not db.quitar_miembro_proyecto(g.usuario_id, proyecto_id, otro_id):
        abort(403)
    if otro_id == g.usuario_id:
        return redirect(url_for("inicio"))
    return _volver(proyecto_id, "proyectos.resumen")


# --- secciones y tareas ---

@proyectos_bp.route("/<int:proyecto_id>/secciones", methods=["POST"])
@login_required
def crear_seccion(proyecto_id: int):
    _proyecto_o_404(proyecto_id)
    if db.crear_seccion(g.usuario_id, proyecto_id, request.form.get("nombre", "")) is None:
        abort(400)
    return _volver(proyecto_id)


def _seccion_del_proyecto(proyecto_id: int, seccion_id: int):
    _proyecto_o_404(proyecto_id)
    if seccion_id not in {s["id"] for s in db.listar_secciones(proyecto_id)}:
        abort(404)


@proyectos_bp.route("/<int:proyecto_id>/secciones/<int:seccion_id>/renombrar", methods=["POST"])
@login_required
def renombrar_seccion(proyecto_id: int, seccion_id: int):
    _seccion_del_proyecto(proyecto_id, seccion_id)
    if not db.renombrar_seccion(g.usuario_id, seccion_id, request.form.get("nombre", "")):
        abort(400)
    return _volver(proyecto_id)


@proyectos_bp.route("/<int:proyecto_id>/secciones/<int:seccion_id>/eliminar", methods=["POST"])
@login_required
def eliminar_seccion(proyecto_id: int, seccion_id: int):
    _seccion_del_proyecto(proyecto_id, seccion_id)
    if not db.eliminar_seccion(g.usuario_id, seccion_id):
        abort(403)
    return _volver(proyecto_id)


@proyectos_bp.route("/<int:proyecto_id>/secciones/<int:seccion_id>/mover", methods=["POST"])
@login_required
def mover_seccion(proyecto_id: int, seccion_id: int):
    _seccion_del_proyecto(proyecto_id, seccion_id)
    db.mover_seccion(g.usuario_id, seccion_id, request.form.get("direccion", ""))
    return _volver(proyecto_id)


@proyectos_bp.route("/<int:proyecto_id>/tareas", methods=["POST"])
@login_required
def crear_tarea(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    if not _organiza(proyecto):
        abort(403)
    texto = (request.form.get("asunto") or "").strip()
    if not texto:
        return _volver(proyecto_id, error=_("Escribe qué hay que hacer."))
    # El texto libre («viernes 10h pedir extractos @luis !alta #sección») rellena lo que el formulario no trae.
    entendido = _interpretar(proyecto_id, texto)
    fecha = (request.form.get("fecha_vencimiento") or "").strip() or entendido.vencimiento
    if request.form.get("fecha_vencimiento") and entendido.hora and not (request.form.get("fecha_vencimiento") or "").count("T"):
        fecha = f"{fecha}T{entendido.hora}"
    prioridad = request.form.get("prioridad") if request.form.get("prioridad") in ("baja", "normal", "alta") else (entendido.prioridad or "normal")
    db.crear_tarea_en_proyecto(
        g.usuario_id, proyecto_id, entendido.asunto[:300], seccion_id=_entero(request.form.get("seccion_id")) or entendido.etiqueta_id,
        prioridad=prioridad, fecha_vencimiento=fecha, asignada_a=_entero(request.form.get("asignada_a")) or entendido.persona_id,
        estimacion_min=quickadd.duracion_a_minutos(request.form.get("estimacion")) or entendido.estimacion_min,
    )
    return _volver(proyecto_id)


def _interpretar(proyecto_id: int, texto: str) -> quickadd.Interpretacion:
    """Qué entiende el alta rápida: las personas son las que pueden recibir tareas del proyecto y las #etiquetas, sus secciones."""
    proyecto = db.obtener_proyecto(g.usuario_id, proyecto_id)
    equipo = [(proyecto["usuario_id"], proyecto["dueno_nombre"], "")] + [
        (m["usuario_id"], m["nombre"], m["email"]) for m in db.miembros_de_proyecto(proyecto_id) if m["rol"] == "colabora"
    ]
    secciones = [(s["id"], s["nombre"]) for s in db.listar_secciones(proyecto_id)]
    return quickadd.interpretar(texto, date.today(), equipo, secciones)


@proyectos_bp.route("/<int:proyecto_id>/interpretar")
@login_required
def interpretar(proyecto_id: int):
    """Vista previa en vivo del alta rápida: lo que se ha entendido del texto (no crea nada)."""
    proyecto = _proyecto_o_404(proyecto_id)
    e = _interpretar(proyecto_id, (request.args.get("texto") or "")[:400])
    nombres = {proyecto["usuario_id"]: proyecto["dueno_nombre"], **{m["usuario_id"]: m["nombre"] for m in db.miembros_de_proyecto(proyecto_id)}}
    secciones = {s["id"]: s["nombre"] for s in db.listar_secciones(proyecto_id)}
    return jsonify({
        "asunto": e.asunto, "vencimiento": e.vencimiento,
        "fecha_texto": format_date(e.fecha, "EEE d MMM") if e.fecha else None, "hora": e.hora, "prioridad": e.prioridad,
        "persona": nombres.get(e.persona_id), "seccion": secciones.get(e.etiqueta_id), "sin_resolver": e.sin_resolver,
        "estimacion": quickadd.formatear_minutos(e.estimacion_min) or None,
    })


@proyectos_bp.route("/<int:proyecto_id>/tareas/<int:tarea_id>/seccion", methods=["POST"])
@login_required
def mover_tarea(proyecto_id: int, tarea_id: int):
    _proyecto_o_404(proyecto_id)
    tarea = db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)
    if tarea is None or tarea["categoria_id"] != proyecto_id:
        abort(404)
    if not db.asignar_seccion_tarea(g.usuario_id, tarea_id, _entero(request.form.get("seccion_id"))):
        abort(403)
    return _volver(proyecto_id)


# --- Tablero y calendario del proyecto, y los cambios que hacen arrastrar y soltar ---

LIMITE_COLUMNA = 25


@proyectos_bp.route("/<int:proyecto_id>/tablero")
@login_required
def tablero(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    contexto = _contexto(proyecto, "tablero")
    columnas = {valor: [] for valor, _etiqueta in ESTADOS}
    for t in db.tareas_de_proyecto(g.usuario_id, proyecto_id):
        columnas.setdefault(t["estado"], []).append(t)
    columnas["completada"] = sorted(columnas.get("completada", []), key=lambda t: t["fecha_completada"] or "", reverse=True)[:15]
    totales = {v: len(l) for v, l in columnas.items()}
    ampliada = request.args.get("mas")
    columnas = {v: (l if ampliada in (v, "*") else l[:LIMITE_COLUMNA]) for v, l in columnas.items()}
    contexto.update({"estados_tablero": ESTADOS, "columnas": columnas, "totales_columna": totales, "hoy": datetime.now().strftime("%Y-%m-%d")})
    return render_template("proyecto_tablero.html", **contexto)


@proyectos_bp.route("/<int:proyecto_id>/calendario")
@login_required
def calendario(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    contexto = _contexto(proyecto, "calendario")
    try:
        ancla = date.fromisoformat(request.args.get("fecha", ""))
    except ValueError:
        ancla = date.today()
    inicio, fin = _rango_para_vista("mes", ancla)
    por_dia: dict[str, list] = {}
    sin_fecha = []
    for t in db.tareas_de_proyecto(g.usuario_id, proyecto_id):
        dia = (t["fecha_vencimiento"] or "")[:10]
        if dia:
            por_dia.setdefault(dia, []).append(t)
        elif t["estado"] != "completada":
            sin_fecha.append(t)
    dias, cursor = [], inicio
    while cursor <= fin:
        iso = cursor.isoformat()
        dias.append({"fecha": cursor, "iso": iso, "es_hoy": cursor == date.today(), "es_mes_actual": cursor.month == ancla.month, "tareas": por_dia.get(iso, [])})
        cursor = date.fromordinal(cursor.toordinal() + 1)
    contexto.update({
        "semanas": [dias[i:i + 7] for i in range(0, len(dias), 7)], "titulo_rango": _titulo_rango("mes", ancla, inicio, fin),
        "anterior": _mover_ancla("mes", ancla, -1).isoformat(), "siguiente": _mover_ancla("mes", ancla, 1).isoformat(),
        "sin_fecha": sin_fecha, "hoy": date.today().isoformat(),
    })
    return render_template("proyecto_calendario.html", **contexto)


def _quiere_json() -> bool:
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


def _responder(ok: bool, mensaje: str | None, destino: str, proyecto_id: int, codigo_error: int = 400, **datos):
    """Los gestos de arrastrar piden JSON; sin JavaScript el mismo formulario vuelve a la página."""
    if _quiere_json():
        respuesta = jsonify({"ok": ok, "mensaje": mensaje, **datos})
        respuesta.status_code = 200 if ok else codigo_error
        return respuesta
    if not ok:
        abort(codigo_error)
    return _volver(proyecto_id, destino)


def _tarea_del_proyecto(proyecto_id: int, tarea_id: int):
    _proyecto_o_404(proyecto_id)
    tarea = db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)
    if tarea is None or tarea["categoria_id"] != proyecto_id:
        abort(404)
    return tarea


@proyectos_bp.route("/<int:proyecto_id>/tareas/<int:tarea_id>/estado", methods=["POST"])
@login_required
def cambiar_estado(proyecto_id: int, tarea_id: int):
    tarea = _tarea_del_proyecto(proyecto_id, tarea_id)
    estado = request.form.get("estado", "")
    if estado not in {v for v, _e in ESTADOS}:
        return _responder(False, _("Estado no válido."), "proyectos.tablero", proyecto_id)
    if not db.puede_trabajar_tarea(g.usuario_id, tarea_id):
        return _responder(False, _("No tienes permiso para cambiar esta tarea."), "proyectos.tablero", proyecto_id, 403)
    if estado in ("en_progreso", "completada") and db.tarea_bloqueada(tarea_id):
        return _responder(False, _("Esta tarea espera a otras que aún no están completadas."), "proyectos.tablero", proyecto_id, 409)
    anterior = tarea["estado"]
    db.cambiar_estado_tarea_outlook(g.usuario_id, tarea_id, estado)
    return _responder(True, None, "proyectos.tablero", proyecto_id, estado=estado, anterior=anterior)


@proyectos_bp.route("/<int:proyecto_id>/tareas/<int:tarea_id>/fecha", methods=["POST"])
@login_required
def cambiar_fecha(proyecto_id: int, tarea_id: int):
    tarea = _tarea_del_proyecto(proyecto_id, tarea_id)
    anterior = (tarea["fecha_vencimiento"] or "")[:10]
    if not db.cambiar_fecha_tarea_proyecto(g.usuario_id, tarea_id, (request.form.get("fecha") or "").strip() or None):
        return _responder(False, _("No se ha podido cambiar la fecha."), "proyectos.calendario", proyecto_id, 403)
    return _responder(True, None, "proyectos.calendario", proyecto_id, fecha=(request.form.get("fecha") or "")[:10], anterior=anterior)


@proyectos_bp.route("/<int:proyecto_id>/tareas/<int:tarea_id>/orden", methods=["POST"])
@login_required
def reordenar_tarea(proyecto_id: int, tarea_id: int):
    tarea = _tarea_del_proyecto(proyecto_id, tarea_id)
    anterior = {"seccion_id": tarea["seccion_id"]}
    if not db.mover_tarea_en_proyecto(g.usuario_id, tarea_id, _entero(request.form.get("seccion_id")), _entero(request.form.get("antes_de"))):
        return _responder(False, _("No se ha podido mover la tarea."), "proyectos.lista", proyecto_id, 403)
    return _responder(True, None, "proyectos.lista", proyecto_id, **anterior)


# --- Fase 3: notas compartidas, actividad, plantillas y datos del cliente ---------------------------------


@proyectos_bp.route("/<int:proyecto_id>/notas")
@login_required
def notas(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    contexto = _contexto(proyecto, "notas")
    contexto.update({"notas": db.listar_notas_proyecto(g.usuario_id, proyecto_id), "error": (request.args.get("error") or "")[:200] or None})
    return render_template("proyecto_notas.html", **contexto)


@proyectos_bp.route("/<int:proyecto_id>/notas", methods=["POST"])
@login_required
def crear_nota(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    if not _organiza(proyecto):
        abort(403)
    if db.crear_nota_proyecto(g.usuario_id, proyecto_id, request.form.get("texto", "")) is None:
        return _volver(proyecto_id, "proyectos.notas", error=_("No se ha podido guardar la nota."))
    return _volver(proyecto_id, "proyectos.notas")


@proyectos_bp.route("/<int:proyecto_id>/notas/<int:nota_id>/fijar", methods=["POST"])
@login_required
def fijar_nota(proyecto_id: int, nota_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    if not _organiza(proyecto):
        abort(403)
    db.fijar_nota_proyecto(g.usuario_id, proyecto_id, nota_id, request.form.get("fijada") == "1")
    return _volver(proyecto_id, "proyectos.notas")


@proyectos_bp.route("/<int:proyecto_id>/notas/<int:nota_id>/eliminar", methods=["POST"])
@login_required
def eliminar_nota(proyecto_id: int, nota_id: int):
    _proyecto_o_404(proyecto_id)
    if not db.eliminar_nota_proyecto(g.usuario_id, proyecto_id, nota_id):
        abort(403)
    return _volver(proyecto_id, "proyectos.notas")


@proyectos_bp.route("/<int:proyecto_id>/actividad")
@login_required
def actividad(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    contexto = _contexto(proyecto, "actividad")
    contexto.update({"entradas": db.actividad_proyecto(g.usuario_id, proyecto_id)})
    return render_template("proyecto_actividad.html", **contexto)


@proyectos_bp.route("/<int:proyecto_id>/plantilla", methods=["POST"])
@login_required
def aplicar_plantilla(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    if not _organiza(proyecto):
        abort(403)
    estructura = proyecto_plantillas.estructura_de(g.usuario_id, request.form.get("plantilla", ""))
    if not estructura or db.aplicar_plantilla_proyecto(g.usuario_id, proyecto_id, estructura) is None:
        return _volver(proyecto_id, error=_("No se ha podido aplicar la plantilla."))
    return _volver(proyecto_id)


@proyectos_bp.route("/<int:proyecto_id>/plantilla/guardar", methods=["POST"])
@login_required
def guardar_plantilla(proyecto_id: int):
    proyecto = _proyecto_o_404(proyecto_id)
    if proyecto["rol"] != "dueno":
        abort(403)
    db.guardar_plantilla_desde_proyecto(g.usuario_id, proyecto_id, request.form.get("nombre", ""))
    return _volver(proyecto_id, "proyectos.resumen", _anchor="plantillas")


@proyectos_bp.route("/plantillas/<int:plantilla_id>/eliminar", methods=["POST"])
@login_required
def eliminar_plantilla(plantilla_id: int):
    if not db.eliminar_plantilla_proyecto(g.usuario_id, plantilla_id):
        abort(404)
    return redirect(request.referrer or url_for("inicio"))
