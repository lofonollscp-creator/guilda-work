"""Ampliación de la API REST (`/api/v1`): lo que ya existía en la web y en el MCP pero no en la API (proyectos,
listados de notas y tareas, checklist, asignación, «mi día», conversaciones y acciones de correo, notificaciones,
búsqueda, consumo de IA y comunicados). Capa fina sobre las mismas funciones de `db.py`; registra sus rutas en el
mismo blueprint `api_bp`, así que comparten autenticación por token, formato de respuesta y OpenAPI. Todo aditivo."""
import json

from flask import abort, g, request

from . import busqueda, comunicados, correo, db, eventos, ia_consumo
from . import rutas_api as _api
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
    """Notas propias, fijadas primero. Filtros: `proyecto_id`, `q`. Paginación `limit`/`offset` hecha en la base de datos
    (sin `limit` devuelve hasta 1000); total en `X-Total-Count`. `campos=id,titulo` limita los campos devueltos."""
    ref = request.args.get("referencia_externa")
    if ref:
        encontrado = db.id_por_referencia_externa("notas", g.usuario_id, ref)
        return _ok_paginado([db.obtener_nota(g.usuario_id, encontrado)] if encontrado else [])
    proyecto, q = request.args.get("proyecto_id", type=int), request.args.get("q") or None
    limit = request.args.get("limit", type=int)
    offset = max(0, request.args.get("offset", default=0, type=int) or 0)
    limite = 1000 if limit is None else max(1, min(limit, 1000))
    filas = db.listar_notas(g.usuario_id, categoria_id=proyecto, texto=q, limite=limite, offset=offset)
    respuesta, status = _ok(_dicts(filas))
    respuesta.headers["X-Total-Count"] = str(db.contar_notas(g.usuario_id, proyecto, q))
    return respuesta, status


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
    from .rutas_tareas import _notificar_asignacion
    _notificar_asignacion(g.usuario_id, tarea_id, _body().get("companero_id"))
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
    """Cancela y descarta un envío programado (con sus adjuntos). Para conservarlo como borrador: `POST /correo/envios/{id}/cancelar`."""
    if db.obtener_envio_correo(g.usuario_id, envio_id) is None or not db.cancelar_envio_correo(g.usuario_id, envio_id):
        abort(404, "Envío no encontrado o ya enviado.")
    db.cerrar_envio_correo(envio_id, "cancelado", borrar_adjuntos=True)
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


# --- Sincronización incremental ------------------------------------------------------------------------------

def _fila_visible(entidad: str, entidad_id: int):
    if entidad == "notas":
        return db.obtener_nota(g.usuario_id, entidad_id)
    if entidad == "tareas_outlook":
        return db.obtener_tarea_outlook_visible(g.usuario_id, entidad_id)
    if entidad == "proyectos":
        return db.obtener_categoria(g.usuario_id, entidad_id)
    return db.obtener_tarea(g.usuario_id, entidad_id)


@api_bp.route("/sync", methods=["GET"])
@token_required
def sincronizar():
    """Cambios desde un cursor, para no volver a descargarlo todo.

    1. `GET /sync` (sin cursor) devuelve el cursor actual: pídelo ANTES de la descarga completa inicial por los listados.
    2. Más tarde, `GET /sync?cursor=N` devuelve `cambios` (filas nuevas o modificadas, por entidad) y `eliminados`
       (ids que ya no existen o están en la papelera), más el `cursor` nuevo. Si `hay_mas` es true, vuelve a llamar con él.
    3. `reiniciar: true` = el cursor es demasiado antiguo (se conservan 30 días): descarga todo de nuevo.
    Entidades: `notas`, `tareas_outlook`, `proyectos`, `tareas`. Solo lo propio (y las tareas que te han asignado)."""
    cursor = request.args.get("cursor", type=int)
    if cursor is None:
        return _ok({"cursor": db.cursor_cambios_actual(), "hay_mas": False, "reiniciar": False, "cambios": {}, "eliminados": {}})
    if cursor < 0:
        return _err("cursor no válido.", 400, "cursor_invalido", "cursor")
    resultado = db.cambios_desde(g.usuario_id, cursor, limite=max(1, min(request.args.get("limit", default=500, type=int) or 500, 1000)))
    cambios: dict[str, list] = {}
    eliminados: dict[str, list] = {}
    for entidad, entidad_id, accion in resultado["cambios"]:
        fila = _fila_visible(entidad, entidad_id) if accion == "upsert" else None
        if fila is not None:
            cambios.setdefault(entidad, []).append(dict(fila))
        else:
            eliminados.setdefault(entidad, []).append(entidad_id)
    return _ok({"cursor": resultado["cursor"], "hay_mas": resultado["hay_mas"], "reiniciar": resultado["reiniciar"], "cambios": cambios, "eliminados": eliminados})


# --- Webhooks del despacho -----------------------------------------------------------------------------------------

MAX_WEBHOOKS_POR_DESPACHO = 20


def _exigir_gestion_webhooks():
    """Un webhook saca datos del despacho hacia fuera: solo lo gestiona quien supervisa el despacho o administra."""
    if getattr(g, "tenant_id", None) is None:
        abort(403, "Los webhooks pertenecen a un despacho y tu usuario no tiene ninguno.")
    if not (g.get("supervisor_tenant") or g.get("es_admin")):
        abort(403, "Solo un supervisor del despacho o un administrador puede gestionar webhooks.")


def _webhook_del_despacho_o_404(webhook_id: int, *, modificar: bool = False) -> dict:
    _exigir_gestion_webhooks()
    w = db.obtener_webhook(webhook_id)
    if w is None or w["tenant_id"] != g.tenant_id:
        abort(404, "Webhook no encontrado.")
    if modificar and w["origen"] == "backoffice":
        abort(403, "Este webhook lo gestiona Guilda Work (backoffice): pide el cambio a soporte.")
    return dict(w)


def _publico(w: dict) -> dict:
    return {**{k: v for k, v in w.items() if k != "secreto"}, "eventos": json.loads(w["eventos"]) if isinstance(w["eventos"], str) else w["eventos"]}


def _validar_cuerpo_webhook(datos: dict, *, parcial: bool):
    """(url, eventos) validados o un `_err` ya construido."""
    url, lista = datos.get("url"), datos.get("eventos")
    if not parcial or "url" in datos:
        ok, motivo = eventos.validar_url_publica(str(url or ""))
        if not ok:
            return _err(motivo, 400, "url_invalida", "url")
    if not parcial or "eventos" in datos:
        if not isinstance(lista, list) or not lista or any(e not in eventos.EVENTOS for e in lista):
            return _err(f"eventos debe ser una lista no vacía de entre: {', '.join(eventos.EVENTOS)}.", 400, "eventos_invalidos", "eventos")
    return None


@api_bp.route("/webhooks", methods=["GET"])
@token_required
def listar_webhooks():
    _exigir_gestion_webhooks()
    return _ok_paginado(_publico(dict(w)) for w in db.listar_webhooks(g.tenant_id))


@api_bp.route("/webhooks/catalogo-eventos", methods=["GET"])
@token_required
def catalogo_eventos():
    """Eventos a los que se puede suscribir un webhook."""
    return _ok(eventos.EVENTOS)


@api_bp.route("/webhooks", methods=["POST"])
@token_required
def crear_webhook():
    """Cuerpo: `{"url": "https://...", "eventos": ["tarea.completada", ...]}`. La URL debe ser https y pública. El
    `secreto` con el que se firman las entregas solo se devuelve aquí (y al rotarlo): guárdalo."""
    _exigir_gestion_webhooks()
    datos = _body()
    error = _validar_cuerpo_webhook(datos, parcial=False)
    if error:
        return error
    if len(db.listar_webhooks(g.tenant_id)) >= MAX_WEBHOOKS_POR_DESPACHO:
        return _err(f"Tu despacho ya tiene {MAX_WEBHOOKS_POR_DESPACHO} webhooks (el máximo).", 409, "limite_de_webhooks")
    w = db.crear_webhook(g.usuario_id, g.tenant_id, datos["url"], list(dict.fromkeys(datos["eventos"])), origen="api")
    return _ok({**_publico(w), "secreto": w["secreto"]}, 201)


@api_bp.route("/webhooks/<int:webhook_id>", methods=["GET"])
@token_required
def obtener_webhook(webhook_id: int):
    return _ok(_publico(_webhook_del_despacho_o_404(webhook_id)))


@api_bp.route("/webhooks/<int:webhook_id>", methods=["PUT"])
@token_required
def editar_webhook(webhook_id: int):
    """Cambia `url`, `eventos` y/o `activo` (cualquier subconjunto)."""
    _webhook_del_despacho_o_404(webhook_id, modificar=True)
    datos = _body()
    error = _validar_cuerpo_webhook(datos, parcial=True)
    if error:
        return error
    db.actualizar_webhook(
        webhook_id, url=datos.get("url") if "url" in datos else None,
        eventos=list(dict.fromkeys(datos["eventos"])) if "eventos" in datos else None,
        activo=bool(datos["activo"]) if "activo" in datos else None,
    )
    return _ok(_publico(dict(db.obtener_webhook(webhook_id))))


@api_bp.route("/webhooks/<int:webhook_id>", methods=["DELETE"])
@token_required
def borrar_webhook(webhook_id: int):
    _webhook_del_despacho_o_404(webhook_id, modificar=True)
    db.borrar_webhook(webhook_id)
    return _ok()


@api_bp.route("/webhooks/<int:webhook_id>/rotar-secreto", methods=["POST"])
@token_required
def rotar_secreto_webhook(webhook_id: int):
    """Secreto nuevo; el anterior deja de valer al instante. Se devuelve solo esta vez."""
    _webhook_del_despacho_o_404(webhook_id, modificar=True)
    return _ok({"secreto": db.rotar_secreto_webhook(webhook_id)})


@api_bp.route("/webhooks/<int:webhook_id>/probar", methods=["POST"])
@token_required
def probar_webhook(webhook_id: int):
    """Encola un evento `ping` firmado como cualquier otro; mira el resultado en `/entregas`."""
    _webhook_del_despacho_o_404(webhook_id, modificar=True)
    eventos.enviar_prueba(webhook_id)
    return _ok({"encolado": True}, 202)


@api_bp.route("/webhooks/<int:webhook_id>/entregas", methods=["GET"])
@token_required
def entregas_webhook(webhook_id: int):
    """Últimos intentos de entrega y lo que sigue en cola (pendiente/fallido) de este webhook."""
    _webhook_del_despacho_o_404(webhook_id)
    return _ok({"intentos": _dicts(db.entregas_de_webhook(webhook_id, 30)), "cola": db.cola_webhook_de(webhook_id, 30)})


@api_bp.route("/webhooks/entregas/<int:cola_id>/reintentar", methods=["POST"])
@token_required
def reintentar_entrega(cola_id: int):
    fila = db.cola_webhook_obtener(cola_id)
    if fila is None:
        abort(404, "Entrega no encontrada.")
    _webhook_del_despacho_o_404(fila["webhook_id"], modificar=True)
    if not db.cola_webhook_reintentar(cola_id):
        return _err("Solo se pueden reintentar entregas fallidas.", 409, "entrega_no_fallida")
    return _ok()


# --- Upsert por referencia externa (sincronizar con un ERP/CRM sin guardar nuestros ids) ----------------------------------

def _upsert(tabla: str, dueno_id: int, referencia: str, vista_crear, vista_editar):
    """Si existe un registro con esa `referencia_externa` lo edita; si no, lo crea. Reutiliza los mismos controladores
    que POST y PUT (mismas validaciones y permisos): solo cambia que la referencia viene en la ruta."""
    try:
        ref = db.validar_referencia_externa(referencia)
    except ValueError as e:
        return _err(str(e), 400, "referencia_invalida", "referencia_externa")
    if not ref:
        return _err("La referencia no puede estar vacía.", 400, "referencia_invalida", "referencia_externa")
    g.referencia_forzada = ref
    existente = db.id_por_referencia_externa(tabla, dueno_id, ref)
    resultado = vista_editar.__wrapped__(existente) if existente else vista_crear.__wrapped__()
    respuesta, status = resultado
    if existente and status == 200:
        respuesta.headers["X-Guilda-Upsert"] = "actualizado"
    elif status == 201:
        respuesta.headers["X-Guilda-Upsert"] = "creado"
    return respuesta, status


@api_bp.route("/notas/por-referencia/<path:referencia>", methods=["GET"])
@token_required
def nota_por_referencia(referencia: str):
    nota_id = db.id_por_referencia_externa("notas", g.usuario_id, referencia)
    if nota_id is None:
        abort(404, "No hay ninguna nota con esa referencia.")
    return _ok(_dict(db.obtener_nota(g.usuario_id, nota_id)))


@api_bp.route("/notas/por-referencia/<path:referencia>", methods=["PUT"])
@token_required
def upsert_nota(referencia: str):
    """Crea o actualiza la nota con esa `referencia_externa` (cuerpo como POST/PUT /notas). 201 si la crea, 200 si la actualiza."""
    return _upsert("notas", g.usuario_id, referencia, _api.crear_nota, _api.editar_nota)


@api_bp.route("/tareas-outlook/por-referencia/<path:referencia>", methods=["GET"])
@token_required
def tarea_por_referencia(referencia: str):
    tarea_id = db.id_por_referencia_externa("tareas_outlook", g.usuario_id, referencia)
    if tarea_id is None:
        abort(404, "No hay ninguna tarea con esa referencia.")
    return _ok(_dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id)))


@api_bp.route("/tareas-outlook/por-referencia/<path:referencia>", methods=["PUT"])
@token_required
def upsert_tarea_outlook(referencia: str):
    """Crea o actualiza la tarea con esa `referencia_externa` (cuerpo como POST/PUT /tareas-outlook)."""
    return _upsert("tareas_outlook", g.usuario_id, referencia, _api.crear_tarea_outlook, _api.editar_tarea_outlook)


@api_bp.route("/fiscal/clientes/por-referencia/<path:referencia>", methods=["GET"])
@token_required
def cliente_fiscal_por_referencia(referencia: str):
    error = _api._exigir_tenant_api()
    if error:
        return error
    cliente_id = db.id_por_referencia_externa("clientes_fiscales", g.tenant_id, referencia)
    if cliente_id is None:
        abort(404, "No hay ningún cliente fiscal con esa referencia.")
    return _ok(_dict(db.obtener_cliente_fiscal(g.tenant_id, cliente_id)))


@api_bp.route("/fiscal/clientes/por-referencia/<path:referencia>", methods=["PUT"])
@token_required
def upsert_cliente_fiscal(referencia: str):
    """Crea o actualiza el cliente fiscal con esa `referencia_externa` (cuerpo como POST/PUT /fiscal/clientes)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    return _upsert("clientes_fiscales", g.tenant_id, referencia, _api.crear_cliente_fiscal, _api.editar_cliente_fiscal)
