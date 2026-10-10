"""Ampliación de la API REST (`/api/v1`): lo que ya existía en la web y en el MCP pero no en la API (proyectos,
listados de notas y tareas, checklist, asignación, «mi día», conversaciones y acciones de correo, notificaciones,
búsqueda, consumo de IA y comunicados). Capa fina sobre las mismas funciones de `db.py`; registra sus rutas en el
mismo blueprint `api_bp`, así que comparten autenticación por token, formato de respuesta y OpenAPI. Todo aditivo."""
from flask import abort, g, request

from . import busqueda, comunicados, correo, db, ia_consumo
from .rutas_api import _body, _dict, _dicts, _err, _ok, _ok_paginado, api_bp
from .auth import token_required
from .rutas_correo import _mensaje_de_usuario_o_404


def _tarea_visible_o_404(tarea_id: int):
    tarea = db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)
    if tarea is None:
        abort(404, "Tarea no encontrada.")
    return tarea


# --- Notas y tareas con cronómetro: listados ----------------------------------------------------------

@api_bp.route("/notas", methods=["GET"])
@token_required
def listar_notas():
    """Notas propias, fijadas primero. Filtros: `proyecto_id`, `q`; paginación `limit`/`offset`."""
    filas = db.listar_notas(g.usuario_id, categoria_id=request.args.get("proyecto_id", type=int), texto=request.args.get("q") or None, limite=1000)
    return _ok_paginado(filas)


@api_bp.route("/notas/<int:nota_id>", methods=["GET"])
@token_required
def obtener_nota(nota_id: int):
    nota = db.obtener_nota(g.usuario_id, nota_id)
    if nota is None:
        abort(404, "Nota no encontrada.")
    return _ok(_dict(nota))


@api_bp.route("/notas/<int:nota_id>/fijar", methods=["POST"])
@token_required
def fijar_nota(nota_id: int):
    """Cuerpo: `{"fijada": true|false}` (por defecto true)."""
    nota = db.obtener_nota(g.usuario_id, nota_id)
    if nota is None:
        abort(404, "Nota no encontrada.")
    fijada = bool(_body().get("fijada", True))
    if bool(nota["fijada"]) != fijada:
        db.alternar_fijada_nota(g.usuario_id, nota_id)
    return _ok(_dict(db.obtener_nota(g.usuario_id, nota_id)))


@api_bp.route("/tareas", methods=["GET"])
@token_required
def listar_tareas_cronometro():
    """Tareas con cronómetro. Filtros: `desde`, `hasta` (YYYY-MM-DD), `proyecto_id`; paginación `limit`/`offset`."""
    filas = db.historial(g.usuario_id, desde=request.args.get("desde"), hasta=request.args.get("hasta"), categoria_id=request.args.get("proyecto_id", type=int))
    return _ok_paginado(f for f in filas if f["origen"] == "tarea")


# --- Proyectos -------------------------------------------------------------------------------------------

@api_bp.route("/proyectos", methods=["GET"])
@token_required
def listar_proyectos():
    return _ok_paginado(db.listar_categorias(g.usuario_id))


@api_bp.route("/proyectos", methods=["POST"])
@token_required
def crear_proyecto():
    datos = _body()
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        return _err("El proyecto necesita un nombre.")
    proyecto_id = db.crear_categoria(g.usuario_id, nombre, datos.get("color"))
    return _ok(_dict(db.obtener_categoria(g.usuario_id, proyecto_id)), 201)


@api_bp.route("/proyectos/<int:proyecto_id>", methods=["PUT"])
@token_required
def renombrar_proyecto(proyecto_id: int):
    if db.obtener_categoria(g.usuario_id, proyecto_id) is None:
        abort(404, "Proyecto no encontrado.")
    datos = _body()
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        return _err("El proyecto necesita un nombre.")
    db.renombrar_categoria(g.usuario_id, proyecto_id, nombre, datos.get("color"))
    return _ok(_dict(db.obtener_categoria(g.usuario_id, proyecto_id)))


@api_bp.route("/proyectos/<int:proyecto_id>", methods=["DELETE"])
@token_required
def eliminar_proyecto(proyecto_id: int):
    """Lo manda a la papelera (recuperable), no lo borra."""
    if db.obtener_categoria(g.usuario_id, proyecto_id) is None:
        abort(404, "Proyecto no encontrado.")
    db.eliminar_categoria(g.usuario_id, proyecto_id)
    return _ok()


# --- Tareas de lista: detalle, checklist, asignación, «mi día» --------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>", methods=["GET"])
@token_required
def obtener_tarea_outlook(tarea_id: int):
    """Detalle de una tarea (propia o asignada) con su checklist."""
    tarea = _dict(_tarea_visible_o_404(tarea_id))
    tarea["checklist"] = _dicts(db.listar_checklist(tarea_id))
    return _ok(tarea)


@api_bp.route("/tareas-outlook/<int:tarea_id>/checklist", methods=["GET"])
@token_required
def listar_checklist(tarea_id: int):
    _tarea_visible_o_404(tarea_id)
    return _ok(_dicts(db.listar_checklist(tarea_id)))


@api_bp.route("/tareas-outlook/<int:tarea_id>/checklist", methods=["POST"])
@token_required
def agregar_item_checklist(tarea_id: int):
    item_id = db.agregar_item_checklist(g.usuario_id, tarea_id, (_body().get("texto") or "").strip())
    if item_id is None:
        return _err("No se ha podido añadir: la tarea no es tuya, el texto está vacío o el checklist está lleno (máx. 50).")
    return _ok({"id": item_id, "checklist": _dicts(db.listar_checklist(tarea_id))}, 201)


@api_bp.route("/checklist/<int:item_id>/alternar", methods=["POST"])
@token_required
def alternar_item_checklist(item_id: int):
    if not db.alternar_item_checklist(g.usuario_id, item_id):
        abort(404, "Subtarea no encontrada.")
    return _ok()


@api_bp.route("/tareas-outlook/<int:tarea_id>/asignar", methods=["POST"])
@token_required
def asignar_tarea_outlook(tarea_id: int):
    """Cuerpo: `{"companero_id": 5}`; sin él (o `null`) la desasigna. Solo compañeros del mismo despacho."""
    if not db.asignar_tarea_outlook(g.usuario_id, tarea_id, _body().get("companero_id")):
        return _err("No se puede asignar: la tarea no es tuya o el compañero no es de tu despacho.", 403)
    return _ok(_dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id)))


@api_bp.route("/companeros", methods=["GET"])
@token_required
def listar_companeros():
    """Compañeros del despacho a quienes se puede asignar una tarea."""
    return _ok(_dicts(db.listar_companeros_tenant(g.usuario_id)))


@api_bp.route("/mi-dia", methods=["GET"])
@token_required
def mi_dia():
    """«Mi día»: tareas vencidas, de hoy, en curso y asignadas."""
    return _ok({seccion: _dicts(filas) for seccion, filas in db.tareas_para_hoy(g.usuario_id).items()})


# --- Correo: conversaciones y paso a tarea/nota -----------------------------------------------------------

@api_bp.route("/correo/mensajes/<int:mensaje_id>/conversacion", methods=["GET"])
@token_required
def conversacion_correo(mensaje_id: int):
    m = _mensaje_de_usuario_o_404(mensaje_id)
    return _ok(_dicts(db.mensajes_del_hilo_correo(m["cuenta_id"], m["hilo_clave"])))


@api_bp.route("/correo/mensajes/<int:mensaje_id>/tarea", methods=["POST"])
@token_required
def tarea_desde_correo(mensaje_id: int):
    """Crea una tarea vinculada al correo (y a su cliente fiscal). Cuerpo opcional: `fecha_vencimiento`."""
    m = _mensaje_de_usuario_o_404(mensaje_id)
    tarea_id = db.crear_tarea_outlook(
        g.usuario_id, (m["asunto"] or "(sin asunto)").strip()[:200], cuerpo=f"Correo de {m['remitente'] or ''}",
        fecha_vencimiento=_body().get("fecha_vencimiento") or None, cliente_fiscal_id=m["cliente_fiscal_id"], mensaje_correo_id=mensaje_id,
    )
    return _ok(_dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id)), 201)


@api_bp.route("/correo/mensajes/<int:mensaje_id>/nota", methods=["POST"])
@token_required
def nota_desde_correo(mensaje_id: int):
    m = _mensaje_de_usuario_o_404(mensaje_id)
    texto = f"De: {m['remitente'] or ''}\n\n{(m['cuerpo_texto'] or '').strip()[:2000]}"
    nota_id = db.crear_nota(g.usuario_id, texto, titulo=(m["asunto"] or "(sin asunto)").strip()[:120], cliente_fiscal_id=m["cliente_fiscal_id"], mensaje_correo_id=mensaje_id)
    return _ok(_dict(db.obtener_nota(g.usuario_id, nota_id)), 201)


@api_bp.route("/correo/programados", methods=["GET"])
@token_required
def listar_programados():
    return _ok_paginado(db.listar_envios_programados(g.usuario_id))


@api_bp.route("/correo/programados/<int:envio_id>", methods=["DELETE"])
@token_required
def cancelar_programado(envio_id: int):
    if not db.cancelar_envio_correo(g.usuario_id, envio_id):
        abort(404, "Envío no encontrado o ya enviado.")
    return _ok()


@api_bp.route("/correo/seguimientos", methods=["GET"])
@token_required
def listar_seguimientos():
    """Correos con «avísame si no responde». `todos=1` incluye los ya cerrados."""
    return _ok_paginado(db.listar_seguimientos_correo(g.usuario_id, solo_esperando=request.args.get("todos") != "1"))


@api_bp.route("/correo/seguimientos/<int:seguimiento_id>", methods=["DELETE"])
@token_required
def cancelar_seguimiento(seguimiento_id: int):
    if not db.cancelar_seguimiento_correo(g.usuario_id, seguimiento_id):
        abort(404, "Seguimiento no encontrado.")
    return _ok()


@api_bp.route("/correo/plantillas", methods=["GET"])
@token_required
def listar_plantillas():
    return _ok_paginado(db.listar_plantillas_correo(g.usuario_id))


# --- Notificaciones, búsqueda, IA y comunicados ------------------------------------------------------------

@api_bp.route("/notificaciones", methods=["GET"])
@token_required
def listar_notificaciones():
    """Últimas notificaciones (`limit`, máx. 100, por defecto 30) y cuántas hay sin leer (cabecera y campo)."""
    limite = max(1, min(request.args.get("limit", default=30, type=int) or 30, 100))
    respuesta, status = _ok({"no_leidas": db.contar_notificaciones_no_leidas(g.usuario_id), "notificaciones": _dicts(db.listar_notificaciones(g.usuario_id, limite))})
    return respuesta, status


@api_bp.route("/notificaciones/leidas", methods=["POST"])
@token_required
def marcar_notificaciones_leidas():
    db.marcar_notificaciones_leidas(g.usuario_id)
    return _ok()


@api_bp.route("/notificaciones/<int:notificacion_id>", methods=["DELETE"])
@token_required
def eliminar_notificacion(notificacion_id: int):
    db.eliminar_notificacion(g.usuario_id, notificacion_id)
    return _ok()


@api_bp.route("/buscar", methods=["GET"])
@token_required
def buscar():
    """Búsqueda en notas, tareas y correo. Parámetros: `q` (obligatorio), `limit` (1-20, por defecto 8)."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return _err("Indica qué buscar con ?q=.")
    limite = max(1, min(request.args.get("limit", default=8, type=int) or 8, 20))
    return _ok(busqueda.buscar_hibrido(g.usuario_id, q, limite, tenant_id=g.get("tenant_id")))


@api_bp.route("/ia/consumo", methods=["GET"])
@token_required
def consumo_ia():
    """Consultas de IA usadas este mes por el despacho y su tope (`ilimitado` si no hay). Sin despacho: ilimitado."""
    tenant_id = getattr(g, "tenant_id", None)
    return _ok(ia_consumo.estado(tenant_id) if tenant_id else {"ilimitado": True, "limite": None, "usadas": 0})


@api_bp.route("/comunicados", methods=["GET"])
@token_required
def listar_comunicados():
    """Avisos vigentes publicados por Guilda para este usuario (los críticos no se pueden cerrar)."""
    return _ok(comunicados.activos_para(g.usuario_id, getattr(g, "tenant_id", None)))


@api_bp.route("/comunicados/<int:comunicado_id>/cerrar", methods=["POST"])
@token_required
def cerrar_comunicado(comunicado_id: int):
    if not comunicados.cerrar(g.usuario_id, comunicado_id):
        return _err("Este comunicado no se puede cerrar.", 403)
    return _ok()
