"""«Hoy»: la bandeja única de lo que necesita a la persona (ver app/bandeja_hoy.py)."""
from __future__ import annotations

from flask import Blueprint, Response, g, redirect, render_template, request, url_for

from . import bandeja_hoy, db, nucleo, tareas_trabajo
from .auth import login_required

hoy_bp = Blueprint("hoy", __name__, url_prefix="/hoy")


@hoy_bp.route("/")
@login_required
def bandeja():
    supervisor = bool(g.get("supervisor_tenant") or g.get("es_admin"))
    return render_template("hoy.html", bandeja=bandeja_hoy.reunir(g.usuario_id, supervisor), hechos=request.args.get("hechos", type=int), fallos=request.args.get("fallos", type=int))


@hoy_bp.route("/destacados")
@login_required
def destacados():
    """El panel «Necesita tu atención» del inicio (sin las tareas, que ya salen en «Mi día»): un fragmento que el inicio pide después de cargar. 204 si no hay nada."""
    supervisor = bool(g.get("supervisor_tenant") or g.get("es_admin"))
    b = bandeja_hoy.reunir(g.usuario_id, supervisor)
    elegidos = [i for i in b["destacados"] if i["clave"] != "tareas"][:5]
    if not elegidos:
        return Response(status=204)
    return render_template("_hoy_destacados.html", destacados=elegidos, total=b["total"])


HECHO_POSIBLE = ("tarea", "plazo")      # lo que se puede dar por hecho desde aquí; el resto (correos, facturas, vencimientos…) se resuelve en su módulo


def _dar_por_hecho(clave: str) -> bool:
    """Marca como hecho un elemento `tipo:id` con las mismas reglas que su pantalla (permisos, tareas bloqueadas, subtareas o revisión pendientes). False si no se pudo."""
    tipo, _sep, texto_id = clave.partition(":")
    if tipo not in HECHO_POSIBLE or not texto_id.isdigit():
        return False
    id_ = int(texto_id)
    if tipo == "plazo":
        if g.get("tenant_id") is None:
            return False
        try:
            nucleo.marcar_cumplido(g.tenant_id, g.usuario_id, id_)
        except (ValueError, LookupError, PermissionError):
            return False
        return True
    previa = db.obtener_tarea_outlook_visible(g.usuario_id, id_)
    if previa is None or not db.puede_trabajar_tarea(g.usuario_id, id_) or db.tarea_bloqueada(id_) or tareas_trabajo.impedimento_de_cierre(id_):
        return False
    if previa["estado"] == "completada":
        return True
    if not db.cambiar_estado_tarea_outlook(g.usuario_id, id_, "completada"):
        return False
    from .rutas_tareas import _avisar_desbloqueos
    _avisar_desbloqueos(g.usuario_id, id_, False)
    return True


@hoy_bp.route("/hecho", methods=["POST"])
@login_required
def hecho():
    """Marca como hecho uno o varios elementos (`elemento=tarea:12`, repetido). Los que no se pueden (bloqueados, sin permiso…) se quedan en la bandeja y la pantalla lo cuenta."""
    claves = list(dict.fromkeys(c for c in request.form.getlist("elemento") if c))[:200]
    hechos = sum(1 for c in claves if _dar_por_hecho(c))
    return redirect(url_for("hoy.bandeja", hechos=hechos, fallos=len(claves) - hechos))
