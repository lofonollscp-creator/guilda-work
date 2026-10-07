"""Página de proyecto (fase 1): resumen, lista con secciones y compartir con el despacho.
Un proyecto es una categoría de siempre; aquí se ve y se trabaja en equipo. El registro cronológico
de notas y eventos de cada persona sigue en /menu/<id>?registro=1 (pestaña «Registro»)."""
from datetime import datetime

from flask import Blueprint, abort, g, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l

from . import db
from .auth import login_required

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
    contexto.update({"proximas": abiertas[:8], "hoy": hoy})
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
    asunto = (request.form.get("asunto") or "").strip()
    if not asunto:
        return _volver(proyecto_id, error=_("Escribe qué hay que hacer."))
    fecha = (request.form.get("fecha_vencimiento") or "").strip() or None
    db.crear_tarea_en_proyecto(
        g.usuario_id, proyecto_id, asunto[:300], seccion_id=_entero(request.form.get("seccion_id")),
        prioridad=request.form.get("prioridad") if request.form.get("prioridad") in ("baja", "normal", "alta") else "normal",
        fecha_vencimiento=fecha, asignada_a=_entero(request.form.get("asignada_a")),
    )
    return _volver(proyecto_id)


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
