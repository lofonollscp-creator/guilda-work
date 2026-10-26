"""Ampliación de la API REST (`/api/v1`): lo que ya existía en la web y en el MCP pero no en la API (proyectos,
listados de notas y tareas, checklist, asignación, «mi día», conversaciones y acciones de correo, notificaciones,
búsqueda, consumo de IA y comunicados). Capa fina sobre las mismas funciones de `db.py`; registra sus rutas en el
mismo blueprint `api_bp`, así que comparten autenticación por token, formato de respuesta y OpenAPI. Todo aditivo."""
import json

from flask import abort, g, jsonify, request

from . import aviso_destino, busqueda, comunicados, correo, db, eventos, ia_consumo
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

def _notas_enriquecidas(filas, usuario_id: int) -> list[dict]:
    """Las notas como las pinta la lista de la web: con `rol` (dueno, colabora u observa), cuántas personas la comparten y cuántos adjuntos lleva."""
    filas = _dicts(filas)
    ids = [f["id"] for f in filas]
    participantes, adjuntos = db.contar_participantes_notas(ids), db.contar_adjuntos_notas(ids)
    for f in filas:
        f["rol"] = "dueno" if f["usuario_id"] == usuario_id else (db.rol_en_nota(usuario_id, f["id"]) or "observa")
        f["n_participantes"], f["n_adjuntos"] = participantes.get(f["id"], 0), adjuntos.get(f["id"], 0)
    return filas


@api_bp.route("/notas", methods=["GET"])
@token_required
def listar_notas():
    """Notas propias, fijadas primero. Filtros: `proyecto_id`, `q` y `compartidas` (`incluir`: también las que te han compartido; `solo`: solo esas). Paginación
    `limit`/`offset` hecha en la base de datos (sin `limit` devuelve hasta 1000); total en `X-Total-Count`. `campos=id,titulo` limita los campos devueltos.
    Cada nota lleva `rol`, `n_participantes` y `n_adjuntos`."""
    ref = request.args.get("referencia_externa")
    if ref:
        encontrado = db.id_por_referencia_externa("notas", g.usuario_id, ref)
        return _ok_paginado(_notas_enriquecidas([db.obtener_nota(g.usuario_id, encontrado)] if encontrado else [], g.usuario_id))
    proyecto, q = request.args.get("proyecto_id", type=int), request.args.get("q") or None
    modo = request.args.get("compartidas")
    incluir, solo = modo in ("incluir", "solo"), modo == "solo"
    limit = request.args.get("limit", type=int)
    offset = max(0, request.args.get("offset", default=0, type=int) or 0)
    limite = 1000 if limit is None else max(1, min(limit, 1000))
    filas = db.listar_notas(g.usuario_id, categoria_id=proyecto, texto=q, limite=limite, offset=offset, incluir_compartidas=incluir, solo_compartidas=solo)
    respuesta, status = _ok(_notas_enriquecidas(filas, g.usuario_id))
    respuesta.headers["X-Total-Count"] = str(db.contar_notas(g.usuario_id, proyecto, q, incluir_compartidas=incluir, solo_compartidas=solo))
    return respuesta, status


def _nota_visible_o_404(nota_id: int, roles=("dueno", "colabora", "observa")):
    rol = db.rol_en_nota(g.usuario_id, nota_id)
    if rol not in roles:
        abort(404, "Nota no encontrada.")
    return db.obtener_nota_visible(g.usuario_id, nota_id), rol


def _nota_completa(nota_id: int) -> dict:
    """Una nota con su `rol`, sus `participantes` y los nombres de lo que tiene vinculado (la tarea y el correo, solo para su dueño)."""
    nota, rol = _nota_visible_o_404(nota_id)
    d = _dict(nota)
    d["rol"] = rol
    d["participantes"] = _dicts(db.participantes_de_nota(nota_id))
    d["n_participantes"] = len(d["participantes"])
    d["tarea_outlook_asunto"] = d["mensaje_correo_asunto"] = None
    if rol == "dueno":
        if d.get("tarea_outlook_id"):
            tarea = db.obtener_tarea_outlook(g.usuario_id, d["tarea_outlook_id"])
            d["tarea_outlook_asunto"] = tarea["asunto"] if tarea else None
        if d.get("mensaje_correo_id") and db.mensaje_correo_pertenece_a_usuario(g.usuario_id, d["mensaje_correo_id"]):
            mensaje = db.obtener_mensaje_correo(d["mensaje_correo_id"])
            d["mensaje_correo_asunto"] = mensaje["asunto"] if mensaje else None
    return d


@api_bp.route("/notas/<int:nota_id>", methods=["GET"])
@token_required
def obtener_nota(nota_id: int):
    """Una nota, también si te la han compartido. Lleva `rol` (dueno, colabora u observa), `participantes` y, para su dueño, el asunto de la tarea y del correo vinculados."""
    return _ok(_nota_completa(nota_id))


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


@api_bp.route("/notas/<int:nota_id>/participantes", methods=["GET"])
@token_required
def listar_participantes_nota(nota_id: int):
    """Con quién está compartida la nota (`usuario_id`, `nombre`, `rol`: colabora u observa)."""
    _nota_visible_o_404(nota_id)
    return _ok(_dicts(db.participantes_de_nota(nota_id)))


@api_bp.route("/notas/<int:nota_id>/compartir", methods=["POST"])
@token_required
def compartir_nota_con(nota_id: int):
    """Solo su dueño. Cuerpo: `{"usuario_id": N, "rol": "colabora"|"observa"}` (por defecto colabora; si ya la tenía, cambia el rol). Solo con compañeros del despacho."""
    datos = _body()
    try:
        otro = int(datos.get("usuario_id"))
    except (TypeError, ValueError):
        return _err("Indica con quién compartirla (`usuario_id`).", 400, "usuario_invalido", "usuario_id")
    rol = datos.get("rol") or "colabora"
    if rol not in db.ROLES_PARTICIPANTE:
        return _err("El rol debe ser «colabora» u «observa».", 400, "rol_invalido", "rol")
    if not db.compartir_nota(g.usuario_id, nota_id, otro, rol):
        abort(404, "No se puede compartir esa nota con esa persona.")
    try:
        if db.notificacion_tipo_activa(otro, "tarea_asignada"):
            nota = db.obtener_nota_visible(otro, nota_id)
            quien = db.nombre_mostrado_usuario(g.usuario_id) or db.obtener_usuario(g.usuario_id)["email"]
            titulo = (nota["titulo"] or nota["texto"].split("\n")[0])[:60]
            from . import notificaciones
            notificaciones.crear_y_enviar(
                otro, "tarea_asignada", "Nota compartida", f"{quien} ha compartido contigo la nota: {titulo}",
                url=f"/notas?nota={nota_id}&compartidas=1", datos={"tipo": "nota_compartida", "nota_id": nota_id},
            )
    except Exception:  # noqa: BLE001 -- el aviso es un extra: compartir ya está hecho
        pass
    return _ok(_dicts(db.participantes_de_nota(nota_id)))


@api_bp.route("/notas/<int:nota_id>/compartir/<int:otro_id>", methods=["DELETE"])
@token_required
def dejar_de_compartir_nota(nota_id: int, otro_id: int):
    """El dueño quita a una persona; cualquiera puede salirse de una nota que le han compartido (`otro_id` = su propio id)."""
    if not db.dejar_de_compartir_nota(g.usuario_id, nota_id, otro_id):
        abort(404, "Esa persona no tiene la nota compartida.")
    return _ok()


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
    """«Mi día», las mismas cinco secciones que la web: `vencidas`, `hoy`, `en_progreso`, `asignadas` y `compartidas`. Cada tarea trae los mismos indicadores que la lista de `GET /tareas-outlook`."""
    return _ok({seccion: _api._filas_de_tarea(filas, con_rol=True) for seccion, filas in db.tareas_para_hoy(g.usuario_id).items()})


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
    """Últimas notificaciones (`limit`, máx. 100, por defecto 30) y cuántas hay sin leer (cabecera y campo). Filtros opcionales: `tipo` (uno o varios separados por
    comas), `desde` (fecha/hora ISO: solo las posteriores) y `no_leidas=1`. Cada una lleva `destino` (`{tipo, id, ...}`: a dónde lleva) y `canal` (familia del aviso)."""
    limite = max(1, min(request.args.get("limit", default=30, type=int) or 30, 100))
    tipos = {t.strip() for t in (request.args.get("tipo") or "").split(",") if t.strip()}
    desde = (request.args.get("desde") or "").strip()
    solo_no_leidas = request.args.get("no_leidas") in ("1", "true")
    filas = _dicts(db.listar_notificaciones(g.usuario_id, 500 if (tipos or desde or solo_no_leidas) else limite))
    filas = [f for f in filas if (not tipos or f["tipo"] in tipos) and (not desde or f["creado_en"] > desde) and (not solo_no_leidas or not f["leido_en"])][:limite]
    for f in filas:
        f["destino"] = aviso_destino.destino_de(f["tipo"], None, f.get("url"))
        f["canal"] = aviso_destino.canal_de(f["tipo"])
    respuesta, status = _ok({"no_leidas": db.contar_notificaciones_no_leidas(g.usuario_id), "notificaciones": filas})
    return respuesta, status


@api_bp.route("/notificaciones/leidas", methods=["POST"])
@token_required
def marcar_notificaciones_leidas():
    db.marcar_notificaciones_leidas(g.usuario_id)
    return _ok()


@api_bp.route("/notificaciones/<int:notificacion_id>/leida", methods=["POST"])
@token_required
def marcar_notificacion_leida(notificacion_id: int):
    """Marca como leída una sola notificación (la `POST /notificaciones/leidas` marca todas)."""
    db.marcar_notificacion_leida(g.usuario_id, notificacion_id)
    return _ok()


@api_bp.route("/notificaciones/<int:notificacion_id>", methods=["DELETE"])
@token_required
def eliminar_notificacion(notificacion_id: int):
    db.eliminar_notificacion(g.usuario_id, notificacion_id)
    return _ok()


@api_bp.route("/buscar", methods=["GET"])
@token_required
def buscar():
    """Búsqueda en notas, tareas, correo y calendario fiscal. Parámetros: `q` (obligatorio), `limit` (1-40, por defecto 8) y `tipo` (uno o varios separados por comas:
    `nota`, `tarea`, `mensaje`, `vencimiento_fiscal`, `cliente_fiscal`). Sin el servicio de vectores busca solo por palabra clave en vez de no devolver nada.
    Cada resultado lleva `titulo`, `fragmento` y `fecha` listos para pintar."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return _err("Indica qué buscar con ?q=.")
    limite = max(1, min(request.args.get("limit", default=8, type=int) or 8, 40))
    tipos = {t.strip() for t in (request.args.get("tipo") or "").split(",") if t.strip()} & set(aviso_destino._DESTINO_DE_RESULTADO)
    resultados = busqueda.buscar_hibrido(g.usuario_id, q, limite, tenant_id=g.get("tenant_id"), tipos=tipos or None, con_respaldo=True)
    # `destino`: a dónde lleva cada resultado en la app móvil (el `id` del índice es «tipo-N»); fuera los vectores, que no sirven a quien consulta.
    return _ok([{**{k: v for k, v in r.items() if not k.startswith("_")}, **busqueda.presentar_resultado(r), "destino": aviso_destino.destino_de_resultado(r)} for r in resultados])


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


# --- Ausencias, vacaciones y permisos (área «fichaje») ----------------------------------------------------------------------------------------

def _ausencia_propia_publica(a) -> dict:
    return {k: v for k, v in dict(a).items() if k not in ("tenant_id", "creada_por", "resuelta_por")}


@api_bp.route("/fichaje/ausencias", methods=["GET"])
@token_required
def listar_ausencias():
    """Tus ausencias, las más recientes primero. Filtros: `anio` y `estado` (`pendiente`, `aprobada`, `rechazada`, `cancelada`)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from . import ausencias
    return _ok_paginado(_ausencia_propia_publica(a) for a in ausencias.listar(g.tenant_id, usuario_id=g.usuario_id, anio=request.args.get("anio", type=int), estado=request.args.get("estado")))


@api_bp.route("/fichaje/ausencias/saldo", methods=["GET"])
@token_required
def saldo_ausencias():
    """Tus días de vacaciones del año (`anio`, por defecto el actual): los que te corresponden, los aprobados, los pendientes y los disponibles."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from . import ausencias
    return _ok(ausencias.saldo(g.tenant_id, g.usuario_id, request.args.get("anio", type=int)))


@api_bp.route("/fichaje/ausencias", methods=["POST"])
@token_required
def pedir_ausencia():
    """Pide una ausencia. Cuerpo: `{"tipo": "vacaciones", "desde": "2026-08-03", "hasta": "2026-08-14", "motivo": "...", "medio_dia": false}`.
    `tipo`: `vacaciones`, `asuntos_propios`, `permiso`, `baja` u `otro`. `hasta` es opcional (un solo día). Solo cuentan los días laborables;
    solo las vacaciones gastan saldo. Quien gestiona el fichaje puede pasar además `usuario_id` para registrar la de otra persona (queda aprobada)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from . import ausencias
    datos = _body()
    para = datos.get("usuario_id") or g.usuario_id
    try:
        aid = ausencias.solicitar(g.tenant_id, int(para), datos.get("tipo", ""), datos.get("desde"), datos.get("hasta"), motivo=datos.get("motivo"),
                                  medio_dia=bool(datos.get("medio_dia")), por=g.usuario_id)
    except (ValueError, TypeError) as e:
        return _err(str(e), 400, "ausencia_invalida")
    return _ok(_ausencia_propia_publica(ausencias.obtener(g.tenant_id, aid)), 201)


@api_bp.route("/fichaje/ausencias/<int:ausencia_id>/cancelar", methods=["POST"])
@token_required
def cancelar_ausencia_api(ausencia_id: int):
    """Cancela una ausencia tuya (pendiente o aprobada que no haya terminado). Quien gestiona el fichaje puede cancelar cualquiera del despacho."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from . import ausencias
    try:
        ausencias.cancelar(g.tenant_id, g.usuario_id, ausencia_id)
    except ValueError as e:
        return _err(str(e), 404 if "No existe" in str(e) else 400, "ausencia_no_cancelable")
    return _ok(_ausencia_propia_publica(ausencias.obtener(g.tenant_id, ausencia_id)))


@api_bp.route("/fichaje/ausencias/equipo", methods=["GET"])
@token_required
def ausencias_del_equipo():
    """Solo para quien gestiona el fichaje del despacho: las solicitudes pendientes de aprobar (o las de otro `estado`)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from . import ausencias
    if not ausencias.puede_gestionar(g.usuario_id, g.tenant_id):
        abort(403, "Solo quien gestiona el fichaje del despacho puede ver las ausencias del equipo.")
    return _ok_paginado(_ausencia_propia_publica(a) | {"persona": a["persona"]} for a in ausencias.listar(g.tenant_id, estado=request.args.get("estado") or "pendiente"))


@api_bp.route("/fichaje/ausencias/<int:ausencia_id>/resolver", methods=["POST"])
@token_required
def resolver_ausencia_api(ausencia_id: int):
    """Solo para quien gestiona el fichaje: cuerpo `{"decision": "aprobar" | "rechazar", "comentario": "..."}`. Avisa a la persona."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from . import ausencias
    if not ausencias.puede_gestionar(g.usuario_id, g.tenant_id):
        abort(403, "Solo quien gestiona el fichaje del despacho puede aprobar o rechazar ausencias.")
    datos = _body()
    if datos.get("decision") not in ("aprobar", "rechazar"):
        return _err("`decision` debe ser «aprobar» o «rechazar».", 400, "decision_invalida", "decision")
    try:
        ausencias.resolver(g.tenant_id, g.usuario_id, ausencia_id, datos["decision"] == "aprobar", datos.get("comentario"))
    except ValueError as e:
        return _err(str(e), 404 if "No existe" in str(e) else 409, "ausencia_no_resoluble")
    return _ok(_ausencia_propia_publica(ausencias.obtener(g.tenant_id, ausencia_id)))


# --- Cuadrante de turnos y bolsa de horas (área «fichaje») ----------------------------------------------------------------------------------

def _exigir_gestion_fichaje() -> None:
    from . import ausencias
    if not ausencias.puede_gestionar(g.usuario_id, g.tenant_id):
        abort(403, "Solo quien gestiona el fichaje del despacho puede hacer esto.")


@api_bp.route("/fichaje/turnos", methods=["GET"])
@token_required
def mis_turnos_api():
    """Tus turnos entre `desde` y `hasta` (AAAA-MM-DD; por defecto, las próximas dos semanas)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from datetime import date, timedelta
    from . import turnos
    hoy = date.today()
    try:
        return _ok_paginado(turnos.mis_turnos(g.tenant_id, g.usuario_id, request.args.get("desde") or hoy.isoformat(), request.args.get("hasta") or (hoy + timedelta(days=14)).isoformat()))
    except ValueError as e:
        return _err(str(e), 400, "rango_invalido")


@api_bp.route("/fichaje/turnos/cuadrante", methods=["GET"])
@token_required
def cuadrante_api():
    """El cuadrante de todo el despacho entre `desde` y `hasta` (como mucho 62 días; por defecto, la semana en curso)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from datetime import date, timedelta
    from . import turnos
    lunes = turnos.lunes_de(date.today())
    try:
        return _ok(turnos.cuadrante(g.tenant_id, request.args.get("desde") or lunes.isoformat(), request.args.get("hasta") or (lunes + timedelta(days=6)).isoformat()))
    except ValueError as e:
        return _err(str(e), 400, "rango_invalido")


@api_bp.route("/fichaje/turnos/tipos", methods=["GET"])
@token_required
def tipos_de_turno_api():
    """Los turnos que existen en el despacho (nombre, horario, color y horas)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from . import turnos
    return _ok_paginado(turnos.listar_tipos(g.tenant_id))


@api_bp.route("/fichaje/turnos/tipos", methods=["POST"])
@token_required
def crear_tipo_de_turno_api():
    """Solo quien gestiona el fichaje. Cuerpo: `{"nombre": "Mañana", "inicio": "08:00", "fin": "15:00", "color": "#6c8cff"}`."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_gestion_fichaje()
    from . import turnos
    d = _body()
    try:
        tid = turnos.crear_tipo(g.tenant_id, g.usuario_id, d.get("nombre", ""), d.get("inicio", ""), d.get("fin", ""), d.get("color"))
    except ValueError as e:
        return _err(str(e), 400, "turno_invalido")
    return _ok(next(t for t in turnos.listar_tipos(g.tenant_id) if t["id"] == tid), 201)


@api_bp.route("/fichaje/turnos/asignar", methods=["POST"])
@token_required
def asignar_turno_api():
    """Solo quien gestiona el fichaje. Cuerpo: `{"usuario_id": 7, "fecha": "2026-11-02", "turno_id": 3}`; con `turno_id: null` se quita el turno de ese día.
    Falla si la persona tiene una ausencia aprobada ese día. Avisa a la persona."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_gestion_fichaje()
    from . import turnos
    d = _body()
    try:
        cambio = turnos.asignar(g.tenant_id, g.usuario_id, int(d.get("usuario_id") or 0), d.get("fecha"), d.get("turno_id"))
    except (ValueError, TypeError) as e:
        return _err(str(e), 400, "turno_invalido")
    return _ok({"cambiado": cambio})


@api_bp.route("/fichaje/bolsa-horas", methods=["GET"])
@token_required
def bolsa_de_horas_api():
    """Tu bolsa de horas: lo trabajado frente a lo que tocaba según tu jornada (las ausencias aprobadas no se esperan), más los ajustes manuales. Periodo `desde`/`hasta`
    (por defecto, del 1 de enero (o tu alta o tu primer fichaje) hasta ayer). Todas las cifras van en segundos; `saldo_seg` es `null` si no tienes jornada semanal indicada."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    from . import bolsa_horas
    try:
        return _ok(bolsa_horas.calcular(g.tenant_id, g.usuario_id, request.args.get("desde"), request.args.get("hasta")))
    except ValueError as e:
        return _err(str(e), 400, "rango_invalido")


@api_bp.route("/fichaje/bolsa-horas/equipo", methods=["GET"])
@token_required
def bolsa_de_horas_equipo_api():
    """Solo quien gestiona el fichaje: la bolsa de cada persona del despacho, de quien más debe a quien más tiene a favor."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_gestion_fichaje()
    from . import bolsa_horas
    try:
        return _ok_paginado(bolsa_horas.resumen_equipo(g.tenant_id, request.args.get("desde"), request.args.get("hasta")))
    except ValueError as e:
        return _err(str(e), 400, "rango_invalido")


@api_bp.route("/fichaje/bolsa-horas/ajustes", methods=["POST"])
@token_required
def ajustar_bolsa_api():
    """Solo quien gestiona el fichaje. Cuerpo: `{"usuario_id": 7, "minutos": 90, "motivo": "Horas extra del cierre", "fecha": "2026-11-02"}` (minutos negativos restan). Avisa a la persona."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_gestion_fichaje()
    from . import bolsa_horas
    d = _body()
    try:
        aid = bolsa_horas.anadir_ajuste(g.tenant_id, g.usuario_id, int(d.get("usuario_id") or 0), d.get("minutos"), d.get("motivo", ""), d.get("fecha"))
    except (ValueError, TypeError) as e:
        return _err(str(e), 400, "ajuste_invalido")
    return _ok({"id": aid}, 201)


# --- Certificados digitales (área «certificados»; solo custodios y supervisores del despacho) --------------------------------------------------

def _exigir_certificados() -> None:
    from . import certificados
    if not certificados.puede_gestionar(g.usuario_id, g.tenant_id):
        abort(403, "Solo los custodios de certificados y los supervisores del despacho pueden usar esto.")


def _certificado_publico(c: dict) -> dict:
    return {k: v for k, v in c.items() if k not in ("tenant_id", "der", "cliente_email")}


@api_bp.route("/certificados", methods=["GET"])
@token_required
def listar_certificados_api():
    """Inventario de certificados del despacho (los más próximos a caducar primero). Filtros: `q` (titular, emisor, NIF o serie), `temporal` (`vigente`, `caducado`,
    `todavia_no_vigente`) y `operativo` (`inventariado`, `autorizado`, `suspendido`, `sustituido`, `archivado`; sin él, los que están en uso).
    Cada certificado trae sus dimensiones por separado (`temporal`, `cadena`, `revocacion`, `clave`, `estado_operativo`, `renovacion`): lo no comprobado figura como tal."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    return _ok_paginado(_certificado_publico(c) for c in certificados.listar(g.tenant_id, q=request.args.get("q") or None, temporal=request.args.get("temporal") or None, operativo=request.args.get("operativo") or None))


@api_bp.route("/certificados/riesgos", methods=["GET"])
@token_required
def riesgos_certificados_api():
    """Obligaciones pendientes (próximos `dias`, 90 por defecto) cuya cobertura con certificado no está asegurada: caduca antes del vencimiento, sin alternativa autorizada o
    cobertura desconocida (no hay certificado registrado para ese cliente)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    return _ok_paginado(certificados.riesgos(g.tenant_id, horizonte_dias=max(1, min(request.args.get("dias", 90, type=int), 365))))


@api_bp.route("/certificados/<int:certificado_id>", methods=["GET"])
@token_required
def obtener_certificado_api(certificado_id: int):
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    c = certificados.obtener(g.tenant_id, certificado_id)
    if c is None:
        abort(404, "Certificado no encontrado.")
    return _ok(_certificado_publico(c))


@api_bp.route("/certificados/<int:certificado_id>/comprobar", methods=["POST"])
@token_required
def comprobar_certificado_api(certificado_id: int):
    """Comprueba ahora la cadena de confianza y la revocación (OCSP y CRL) del certificado y anota los resultados como evaluaciones automáticas. Hace consultas a las direcciones que declara el propio
    certificado (descarga segura, sin llegar a redes internas). Ante un fallo de red o una CA desconocida el resultado es `indeterminada`, nunca `valida`. 400 si el certificado se apuntó a mano (sin archivo)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    if certificados.obtener(g.tenant_id, certificado_id) is None:
        abort(404, "Certificado no encontrado.")
    try:
        certificados.comprobar_ahora(g.tenant_id, g.usuario_id, certificado_id)
    except ValueError as e:
        return _err(str(e), 400, "certificado_no_valido")
    return _ok(_certificado_publico(certificados.obtener(g.tenant_id, certificado_id)))


@api_bp.route("/certificados/importar", methods=["POST"])
@token_required
def importar_certificado_api():
    """Importa un certificado **público** (PEM o DER) en `contenido_base64`. Nunca se aceptan claves privadas ni contenedores .p12/.pfx: se rechazan (400 `certificado_no_valido`)
    sin guardar nada. Si el archivo trae varios certificados finales responde 409 `eleccion_requerida` con los `candidatos`; vuelve a enviarlo con la `huella` elegida.
    Importar de nuevo el mismo certificado no lo duplica (`nuevo: false`)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    import base64
    from . import certificados
    d = _body()
    try:
        datos = base64.b64decode(d.get("contenido_base64") or "", validate=True)
    except ValueError:
        return _err("`contenido_base64` no es base64 válido.", 400, "certificado_no_valido", "contenido_base64")
    try:
        r = certificados.importar(g.tenant_id, g.usuario_id, datos, huella=d.get("huella") or None, ubicacion_externa=d.get("ubicacion"), notas=d.get("notas"), custodio_id=d.get("custodio_id"))
    except certificados.EleccionRequerida as e:
        respuesta, _estado = _err(str(e), 409, "eleccion_requerida")
        return jsonify({**respuesta.get_json(), "candidatos": e.candidatos}), 409
    except ValueError as e:
        return _err(str(e), 400, "certificado_no_valido")
    return _ok(r, 201 if r["nuevo"] else 200)


@api_bp.route("/certificados/<int:certificado_id>/renovaciones", methods=["POST"])
@token_required
def abrir_renovacion_api(certificado_id: int):
    """Abre la renovación del certificado (solo puede haber una en curso; 409 si ya la hay). Cuerpo opcional: `{"titular": "...", "notas": "..."}`."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    d = _body()
    try:
        rid = certificados.abrir_renovacion(g.tenant_id, g.usuario_id, certificado_id, titular=d.get("titular"), notas=d.get("notas"))
    except ValueError as e:
        return _err(str(e), 404 if "No existe" in str(e) else 409, "renovacion_no_abrible")
    return _ok({"id": rid}, 201)


@api_bp.route("/certificados", methods=["POST"])
@token_required
def apuntar_certificado_api():
    """Apunta un certificado **sin archivo**: `{"cliente_fiscal_id": 12, "tipo": "fnmt_persona_fisica", "caduca": "2027-03-31"}`. `tipo`: `fnmt_persona_fisica`, `fnmt_representante`, `fnmt_representante_sin_personalidad`, `dnie`,
    `accv`, `izenpe`, `camerfirma`, `firmaprofesional` u `otro`. Con `emitido` en vez de `caduca`, se propone la caducidad habitual del tipo (FNMT: 4 años persona física, 2 representante). Opcionales: `titular`
    y `nif` (por defecto los del cliente), `serie`, `custodio_id`, `ubicacion` (sin contraseñas), `notas` y `avisar_cliente` (`true` siempre, `false` nunca, omitido = según el ajuste del despacho). Si ya estaba apuntado
    responde 200 con `nuevo: false`."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    d = _body()
    try:
        r = certificados.alta_rapida(g.tenant_id, g.usuario_id, tipo=d.get("tipo", "otro"), caduca=d.get("caduca"), emitido=d.get("emitido"), cliente_fiscal_id=d.get("cliente_fiscal_id"), titular=d.get("titular"), nif=d.get("nif"),
                                     serie=d.get("serie"), custodio_id=d.get("custodio_id"), ubicacion=d.get("ubicacion"), notas=d.get("notas"), avisar_cliente=d.get("avisar_cliente"))
    except (ValueError, TypeError) as e:
        return _err(str(e), 400, "certificado_no_valido")
    return _ok(r, 201 if r["nuevo"] else 200)


@api_bp.route("/certificados/<int:certificado_id>", methods=["PUT"])
@token_required
def editar_certificado_api(certificado_id: int):
    """Corrige un certificado (los campos que no envíes no cambian): `cliente_fiscal_id`, `custodio_id`, `nif`, `ubicacion`, `notas` y `avisar_cliente` siempre; y, solo si se apuntó a mano, `titular`, `tipo`,
    `caduca`, `emitido` y `serie`. Cambiar la caducidad reinicia los avisos de esa fecha."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    d = _body()
    campos = {k: d[k] for k in ("titular", "tipo", "caduca", "emitido", "serie", "nif", "cliente_fiscal_id", "custodio_id", "ubicacion", "notas", "avisar_cliente") if k in d}
    if certificados.obtener(g.tenant_id, certificado_id) is None:
        abort(404, "Certificado no encontrado.")
    try:
        certificados.editar(g.tenant_id, g.usuario_id, certificado_id, **campos)
    except ValueError as e:
        return _err(str(e), 400, "certificado_no_valido")
    return _ok(_certificado_publico(certificados.obtener(g.tenant_id, certificado_id)))


@api_bp.route("/certificados/<int:certificado_id>/renovado", methods=["POST"])
@token_required
def renovado_certificado_api(certificado_id: int):
    """«Ya está renovado»: `{"nueva_caducidad": "2031-03-31", "emitido": "2027-03-31", "serie": "...", "funciona": true}`. El certificado nuevo hereda cliente, tipo, custodio y servicios y el
    anterior pasa a «sustituido» con su historial. Si el anterior daba servicio a algún cliente, `funciona: true` confirma que el nuevo funciona (si no, 400)."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    d = _body()
    try:
        r = certificados.renovado(g.tenant_id, g.usuario_id, certificado_id, d.get("nueva_caducidad"), emitido=d.get("emitido"), serie=d.get("serie"), funciona=bool(d.get("funciona")))
    except ValueError as e:
        return _err(str(e), 404 if "No existe" in str(e) else 400, "renovacion_no_valida")
    return _ok(r, 201)


@api_bp.route("/certificados/avisos-cliente", methods=["GET"])
@token_required
def configuracion_avisos_cliente_api():
    """Cómo informa el despacho a sus clientes de la caducidad de su certificado: `avisar_cliente`, `mostrar_en_portal`, `dias_antes`, `dias_despues`, `asunto`, `cuerpo` e `instrucciones`."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    return _ok(certificados.config(g.tenant_id))


@api_bp.route("/certificados/avisos-cliente", methods=["PUT"])
@token_required
def guardar_avisos_cliente_api():
    """Solo la dirección del despacho. Cuerpo: `{"avisar_cliente": true, "mostrar_en_portal": true, "dias_antes": [60, 30, 15, 7], "dias_despues": [3], "instrucciones": "...", "asunto": "...", "cuerpo": "..."}`
    (lo que no envíes se mantiene). Marcas del texto propio: `{cliente}`, `{tipo}`, `{caduca}`, `{dias}`, `{cuando}`, `{despacho}`, `{instrucciones}` y `{enlace}`."""
    error = _api._exigir_tenant_api()
    if error:
        return error
    _exigir_certificados()
    from . import certificados
    actual = certificados.config(g.tenant_id)
    d = _body()
    try:
        c = certificados.guardar_config(g.tenant_id, g.usuario_id, avisar_cliente=bool(d.get("avisar_cliente", actual["avisar_cliente"])), mostrar_en_portal=bool(d.get("mostrar_en_portal", actual["mostrar_en_portal"])),
                                        dias_antes=d.get("dias_antes", actual["dias_antes"]), dias_despues=d.get("dias_despues", actual["dias_despues"]), asunto=d.get("asunto", actual["asunto"]),
                                        cuerpo=d.get("cuerpo", actual["cuerpo"]), instrucciones=d.get("instrucciones", actual["instrucciones"]))
    except ValueError as e:
        return _err(str(e), 403 if "Solo la dirección" in str(e) else 400, "configuracion_no_valida")
    return _ok(c)
