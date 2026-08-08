"""Rutas de "Tiquets" (Fase soporte interno): errores y sugerencias sobre
la propia Guilda Work. Vive en su propio Blueprint, mismo patrón que
app/rutas_tareas.py.

A diferencia de notas/tareas/correo, es un tablero COMPARTIDO entre todos
los usuarios (ver db.listar_tiquets/db.obtener_tiquet, que no filtran por
usuario_id) -- cualquiera ve todos los tiquets, pero solo puede editar/
borrar los suyos propios (o cualquiera, si es admin), y solo un admin
puede moverlos de estado en el Kanban.
"""
from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for

from . import db
from .auth import admin_required, login_required

tiquets_bp = Blueprint("tiquets", __name__, url_prefix="/tiquets")

TIPOS = [
    ("error", "Error"),
    ("sugerencia", "Sugerencia"),
]
ESTADOS = [
    ("sin_revisar", "Sin revisar"),
    ("en_revision", "En revisión"),
    ("finalizado", "Finalizado"),
]

# Capturas de pantalla + PDF, nada más -- es lo que se pidió, no un
# adjuntador de archivos genérico. 8MB por archivo: de sobra para una
# captura o un PDF de unas pocas páginas, sin dejar que alguien suba un
# vídeo entero a la base de datos (los adjuntos se guardan como BLOB,
# igual que correo_adjuntos, ver db.py).
MIME_ADJUNTOS_PERMITIDOS = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
TAMANO_MAXIMO_ADJUNTO = 8 * 1024 * 1024


def _puede_borrar(tiquet) -> bool:
    return tiquet["usuario_id"] == g.usuario_id or g.es_admin


def _puede_editar(tiquet) -> bool:
    return tiquet["usuario_id"] == g.usuario_id and tiquet["estado"] == "sin_revisar"


@tiquets_bp.app_template_global("puede_borrar_tiquet")
def _tg_puede_borrar(tiquet):
    return _puede_borrar(tiquet)


@tiquets_bp.app_template_global("puede_editar_tiquet")
def _tg_puede_editar(tiquet):
    return _puede_editar(tiquet)


def _guardar_adjuntos(tiquet_id: int, campo: str = "adjuntos") -> None:
    """Guarda los archivos válidos de `campo` (multipart) para ese tiquet.
    Los que no sean imagen/PDF o pesen de más se descartan en silencio --
    mismo criterio permisivo que el resto de formularios de esta app
    (ver rutas_tareas.py:crear, que tampoco avisa de un asunto vacío,
    solo no crea nada)."""
    for f in request.files.getlist(campo):
        if not f.filename:
            continue
        contenido = f.read()
        if f.mimetype not in MIME_ADJUNTOS_PERMITIDOS or len(contenido) > TAMANO_MAXIMO_ADJUNTO:
            continue
        db.guardar_adjunto_tiquet(tiquet_id, f.filename, f.mimetype, contenido)


@tiquets_bp.route("/")
@login_required
def tarjetas():
    tiquets = db.listar_tiquets()
    por_tipo = {clave: [t for t in tiquets if t["tipo"] == clave] for clave, _ in TIPOS}
    adjuntos_por_tiquet = {t["id"]: db.listar_adjuntos_tiquet(t["id"]) for t in tiquets}
    return render_template(
        "tiquets_tarjetas.html", por_tipo=por_tipo, tipos=TIPOS, estados=ESTADOS,
        adjuntos_por_tiquet=adjuntos_por_tiquet,
    )


@tiquets_bp.route("/kanban")
@login_required
def kanban():
    tiquets = db.listar_tiquets()
    por_estado = {clave: [t for t in tiquets if t["estado"] == clave] for clave, _ in ESTADOS}
    adjuntos_por_tiquet = {t["id"]: db.listar_adjuntos_tiquet(t["id"]) for t in tiquets}
    return render_template(
        "tiquets_kanban.html", por_estado=por_estado, estados=ESTADOS, tipos=TIPOS,
        adjuntos_por_tiquet=adjuntos_por_tiquet,
    )


@tiquets_bp.route("/", methods=["POST"])
@login_required
def crear():
    titulo = request.form.get("titulo", "").strip()
    tipo = request.form.get("tipo", "")
    if titulo and tipo in dict(TIPOS):
        tiquet_id = db.crear_tiquet(
            g.usuario_id, tipo=tipo, titulo=titulo, descripcion=request.form.get("descripcion") or None,
        )
        _guardar_adjuntos(tiquet_id)
    return redirect(request.form.get("volver_a") or url_for("tiquets.tarjetas"))


@tiquets_bp.route("/<int:tiquet_id>/editar", methods=["GET", "POST"])
@login_required
def editar(tiquet_id: int):
    tiquet = db.obtener_tiquet(tiquet_id)
    if tiquet is None:
        abort(404)
    if not _puede_editar(tiquet):
        abort(403)

    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        tipo = request.form.get("tipo", "")
        if not titulo or tipo not in dict(TIPOS):
            return render_template(
                "tiquet_editar.html", tiquet=tiquet, tipos=TIPOS, adjuntos=db.listar_adjuntos_tiquet(tiquet_id),
                error="Faltan datos: título y tipo son obligatorios.",
            )
        db.editar_tiquet(
            g.usuario_id, tiquet_id, titulo=titulo, descripcion=request.form.get("descripcion") or None, tipo=tipo,
        )
        _guardar_adjuntos(tiquet_id)
        return redirect(url_for("tiquets.tarjetas"))

    return render_template(
        "tiquet_editar.html", tiquet=tiquet, tipos=TIPOS, adjuntos=db.listar_adjuntos_tiquet(tiquet_id), error=None,
    )


@tiquets_bp.route("/<int:tiquet_id>/eliminar", methods=["POST"])
@login_required
def eliminar(tiquet_id: int):
    tiquet = db.obtener_tiquet(tiquet_id)
    if tiquet is None:
        abort(404)
    if not _puede_borrar(tiquet):
        abort(403)
    db.eliminar_tiquet(tiquet_id)
    return redirect(request.form.get("volver_a") or url_for("tiquets.tarjetas"))


@tiquets_bp.route("/<int:tiquet_id>/estado", methods=["POST"])
@login_required
@admin_required
def cambiar_estado(tiquet_id: int):
    if db.obtener_tiquet(tiquet_id) is None:
        abort(404)
    estado = request.form.get("estado", "")
    if estado in dict(ESTADOS):
        db.cambiar_estado_tiquet(tiquet_id, estado)
    return redirect(request.form.get("volver_a") or url_for("tiquets.kanban"))


TIPOS_PREVISUALIZABLES = ("application/pdf",)


@tiquets_bp.route("/<int:tiquet_id>/adjunto/<int:adjunto_id>")
@login_required
def descargar_adjunto(tiquet_id: int, adjunto_id: int):
    # Sin restringir a dueño/admin -- es un tablero compartido, cualquiera
    # que vea el tiquet (todo el mundo) puede ver también sus adjuntos.
    if db.obtener_tiquet(tiquet_id) is None:
        abort(404)
    adjunto = db.obtener_adjunto_tiquet(adjunto_id)
    if adjunto is None or adjunto["tiquet_id"] != tiquet_id:
        abort(404)
    previsualizable = adjunto["tipo_mime"].startswith("image/") or adjunto["tipo_mime"] in TIPOS_PREVISUALIZABLES
    disposicion = "inline" if previsualizable else "attachment"
    return Response(
        adjunto["contenido"],
        mimetype=adjunto["tipo_mime"],
        headers={"Content-Disposition": f'{disposicion}; filename="{adjunto["nombre_archivo"]}"'},
    )


@tiquets_bp.route("/<int:tiquet_id>/adjunto/<int:adjunto_id>/eliminar", methods=["POST"])
@login_required
def eliminar_adjunto(tiquet_id: int, adjunto_id: int):
    tiquet = db.obtener_tiquet(tiquet_id)
    if tiquet is None:
        abort(404)
    if not _puede_editar(tiquet):
        abort(403)
    adjunto = db.obtener_adjunto_tiquet(adjunto_id)
    if adjunto is None or adjunto["tiquet_id"] != tiquet_id:
        abort(404)
    db.eliminar_adjunto_tiquet(adjunto_id)
    return redirect(url_for("tiquets.editar", tiquet_id=tiquet_id))
