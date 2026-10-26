"""API de tareas, completa: lo que la web hace con una tarea de lista y no estaba en la API (estado, cronómetro, comentarios,
dependencias, recordatorios, compartir, acciones en lote, vistas guardadas, plantillas, recurrentes, reglas por vencimiento,
plan de carga y papelera). Capa fina sobre las mismas funciones de `db.py` y las mismas notificaciones que la web; registra
sus rutas en `api_bp` (mismo token, áreas, formato de error y OpenAPI). Todo aditivo."""
from datetime import date, timedelta

from flask import abort, g, request

from . import db, quickadd, tareas_trabajo
from .auth import token_required
from .rutas_api import _body, _dict, _dicts, _err, _ok, _ok_paginado, api_bp
from .rutas_tareas import (
    MENSAJE_BLOQUEADA, _avisar_desbloqueos, _notificar_asignacion, _notificar_comentario, _notificar_compartida,
)

ESTADOS = ("no_iniciada", "en_progreso", "completada", "esperando", "aplazada")


def _visible_o_404(tarea_id: int):
    tarea = db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)
    if tarea is None:
        abort(404, "Tarea no encontrada.")
    return tarea


def _int(valor):
    try:
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _sin_permiso(mensaje="No tienes permiso para hacer esto con esta tarea."):
    return _err(mensaje, 403, "sin_permiso")


# --- Estado, cronómetro, tiempo y actividad -------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>/estado", methods=["POST"])
@token_required
def cambiar_estado_tarea(tarea_id: int):
    """Cuerpo: `{"estado": "no_iniciada|en_progreso|completada|esperando|aplazada"}`. 409 si la tarea espera a otras."""
    previa = _visible_o_404(tarea_id)
    estado = (_body().get("estado") or "").strip()
    if estado == "en_revision" and previa["estado"] != "en_revision":
        return _err(tareas_trabajo.MENSAJE_SOLO_POR_REVISION, 409, "solo_por_revision", "estado")
    if previa["estado"] == "en_revision" and estado != "en_revision":
        return _err(tareas_trabajo.MENSAJE_EN_REVISION, 409, "revision_pendiente", "estado")
    if estado not in ESTADOS:
        return _err(f"estado debe ser uno de: {', '.join(ESTADOS)}.", 400, "estado_invalido", "estado")
    if estado in ("en_progreso", "completada") and db.tarea_bloqueada(tarea_id):
        return _err(MENSAJE_BLOQUEADA, 409, "tarea_bloqueada")
    impedimento = tareas_trabajo.impedimento_de_cierre(tarea_id) if estado == "completada" else None
    if impedimento:
        return _err(impedimento[1], 409, impedimento[0])
    if not db.cambiar_estado_tarea_outlook(g.usuario_id, tarea_id, estado):
        return _sin_permiso()
    _avisar_desbloqueos(g.usuario_id, tarea_id, previa["estado"] == "completada")
    return _ok(_dict(db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)))


@api_bp.route("/tareas-outlook/<int:tarea_id>/cronometro/iniciar", methods=["POST"])
@token_required
def iniciar_cronometro_tarea(tarea_id: int):
    """Empieza a contar tiempo sobre esta tarea (crea la tarea con duración enlazada). `proyecto_id` solo si la tarea no tiene."""
    _visible_o_404(tarea_id)
    try:
        cronometro_id = db.iniciar_cronometro_tarea_outlook(g.usuario_id, tarea_id, _int(_body().get("proyecto_id")))
    except ValueError as e:
        return _err(str(e), 400, "cronometro_no_iniciado")
    return _ok({"tarea_cronometro_id": cronometro_id}, 201)


@api_bp.route("/tareas-outlook/<int:tarea_id>/tiempo", methods=["GET"])
@token_required
def tiempo_de_tarea(tarea_id: int):
    """Tiempo registrado en la tarea (tuyo y del equipo)."""
    _visible_o_404(tarea_id)
    return _ok(db.tiempo_equipo_tarea(g.usuario_id, tarea_id))


@api_bp.route("/tareas-outlook/<int:tarea_id>/actividad", methods=["GET"])
@token_required
def actividad_de_tarea(tarea_id: int):
    _visible_o_404(tarea_id)
    return _ok(db.actividad_de_tarea(g.usuario_id, tarea_id))


@api_bp.route("/tareas-outlook/<int:tarea_id>/restaurar", methods=["POST"])
@token_required
def restaurar_tarea_outlook(tarea_id: int):
    """Saca una tarea de la papelera."""
    db.restaurar_tarea_outlook(g.usuario_id, tarea_id)
    return _ok(_dict(db.obtener_tarea_outlook(g.usuario_id, tarea_id)))


@api_bp.route("/checklist/<int:item_id>", methods=["DELETE"])
@token_required
def eliminar_item_checklist(item_id: int):
    if not db.eliminar_item_checklist(g.usuario_id, item_id):
        abort(404, "Subtarea no encontrada.")
    return _ok()


# --- Comentarios ----------------------------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>/comentarios", methods=["GET"])
@token_required
def listar_comentarios(tarea_id: int):
    _visible_o_404(tarea_id)
    return _ok_paginado(db.listar_comentarios_tarea(g.usuario_id, tarea_id))


@api_bp.route("/tareas-outlook/<int:tarea_id>/comentarios", methods=["POST"])
@token_required
def comentar_tarea(tarea_id: int):
    """Cuerpo: `{"texto": "..."}` (@menciones a compañeros del despacho las notifican). Lo puede hacer cualquiera que vea la tarea."""
    _visible_o_404(tarea_id)
    resultado = db.comentar_tarea_outlook(g.usuario_id, tarea_id, _body().get("texto") or "")
    if resultado is None:
        return _err("El comentario no puede estar vacío.", 400, "comentario_vacio", "texto")
    _notificar_comentario(g.usuario_id, tarea_id, resultado)
    comentarios = db.listar_comentarios_tarea(g.usuario_id, tarea_id)
    return _ok(next((c for c in comentarios if c["id"] == resultado["id"]), {"id": resultado["id"]}), 201)


@api_bp.route("/tareas-outlook/<int:tarea_id>/comentarios/<int:comentario_id>", methods=["DELETE"])
@token_required
def eliminar_comentario(tarea_id: int, comentario_id: int):
    if not db.eliminar_comentario_tarea(g.usuario_id, tarea_id, comentario_id):
        abort(404, "Comentario no encontrado.")
    return _ok()


# --- Dependencias ---------------------------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>/dependencias", methods=["GET"])
@token_required
def listar_dependencias(tarea_id: int):
    """Tareas de las que depende esta y si está bloqueada (no se puede empezar ni completar hasta que acaben)."""
    _visible_o_404(tarea_id)
    return _ok({"bloqueada": db.tarea_bloqueada(tarea_id), "depende_de": db.dependencias_de_tarea(tarea_id)})


@api_bp.route("/tareas-outlook/<int:tarea_id>/dependencias", methods=["POST"])
@token_required
def anadir_dependencia(tarea_id: int):
    """Cuerpo: `{"depende_de_id": n}`. 409 si crearía un ciclo."""
    _visible_o_404(tarea_id)
    espera_a = _int(_body().get("depende_de_id"))
    if espera_a is None:
        return _err("Indica depende_de_id.", 400, "peticion_invalida", "depende_de_id")
    if not db.puede_editar_tarea(g.usuario_id, tarea_id):
        return _sin_permiso()
    if not db.anadir_dependencia_tarea(g.usuario_id, tarea_id, espera_a):
        return _err("No se puede enlazar: crearía un ciclo o no tienes acceso a esa tarea.", 409, "dependencia_invalida", "depende_de_id")
    return _ok({"bloqueada": db.tarea_bloqueada(tarea_id), "depende_de": db.dependencias_de_tarea(tarea_id)}, 201)


@api_bp.route("/tareas-outlook/<int:tarea_id>/dependencias/<int:depende_de_id>", methods=["DELETE"])
@token_required
def quitar_dependencia(tarea_id: int, depende_de_id: int):
    if not db.quitar_dependencia_tarea(g.usuario_id, tarea_id, depende_de_id):
        abort(404, "Dependencia no encontrada.")
    return _ok()


# --- Recordatorios --------------------------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>/recordatorios", methods=["GET"])
@token_required
def listar_recordatorios(tarea_id: int):
    _visible_o_404(tarea_id)
    return _ok(db.listar_recordatorios_tarea(g.usuario_id, tarea_id))


@api_bp.route("/tareas-outlook/<int:tarea_id>/recordatorios", methods=["POST"])
@token_required
def anadir_recordatorio(tarea_id: int):
    """Cuerpo: `{"avisar_en": "2026-11-01T09:00"}` o `{"atajo": "<clave relativa al vencimiento>"}`; `canales` opcional (por defecto `["app"]`)."""
    _visible_o_404(tarea_id)
    datos = _body()
    canales = datos.get("canales") or ["app"]
    if datos.get("atajo"):
        nuevo = db.recordatorio_relativo(g.usuario_id, tarea_id, str(datos["atajo"]), canales)
    else:
        nuevo = db.anadir_recordatorio_tarea(g.usuario_id, tarea_id, str(datos.get("avisar_en") or ""), canales)
    if nuevo is None:
        return _err("No se pudo crear el recordatorio: indica una fecha y hora válidas (o pon antes un vencimiento a la tarea).", 400, "recordatorio_invalido", "avisar_en")
    return _ok(db.listar_recordatorios_tarea(g.usuario_id, tarea_id), 201)


@api_bp.route("/tareas-outlook/recordatorios/<int:recordatorio_id>", methods=["DELETE"])
@token_required
def eliminar_recordatorio(recordatorio_id: int):
    if not db.eliminar_recordatorio_tarea(g.usuario_id, recordatorio_id):
        abort(404, "Recordatorio no encontrado.")
    return _ok()


@api_bp.route("/tareas-outlook/recordatorios/<int:recordatorio_id>/posponer", methods=["POST"])
@token_required
def posponer_recordatorio(recordatorio_id: int):
    """Cuerpo: `{"opcion": "..."}` (las mismas que ofrece la web al posponer)."""
    if not db.posponer_recordatorio_tarea(g.usuario_id, recordatorio_id, str(_body().get("opcion") or "")):
        abort(404, "Recordatorio no encontrado o la opción no es válida.")
    return _ok()


# --- Compartir ------------------------------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>/compartir", methods=["GET"])
@token_required
def listar_participantes(tarea_id: int):
    _visible_o_404(tarea_id)
    return _ok(_dicts(db.participantes_de_tarea(tarea_id)))


@api_bp.route("/tareas-outlook/<int:tarea_id>/compartir", methods=["POST"])
@token_required
def compartir_tarea(tarea_id: int):
    """Solo el dueño. Cuerpo: `{"usuario_id": n, "rol": "colabora"|"observa"}` (compañeros del mismo despacho)."""
    otro, rol = _int(_body().get("usuario_id")), _body().get("rol") or "colabora"
    if otro is None or not db.compartir_tarea_outlook(g.usuario_id, tarea_id, otro, rol):
        return _err("No se puede compartir: la tarea no es tuya, el compañero no es de tu despacho o el rol no es válido.", 403, "sin_permiso")
    _notificar_compartida(g.usuario_id, tarea_id, otro, rol)
    return _ok(_dicts(db.participantes_de_tarea(tarea_id)), 201)


@api_bp.route("/tareas-outlook/<int:tarea_id>/compartir/<int:usuario_id>", methods=["DELETE"])
@token_required
def dejar_de_compartir(tarea_id: int, usuario_id: int):
    """El dueño quita a un participante; un participante puede salirse él mismo."""
    if not db.dejar_de_compartir_tarea_outlook(g.usuario_id, tarea_id, usuario_id):
        abort(404, "Participante no encontrado.")
    return _ok()


# --- Lote, tablero, carga y mover -----------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/lote", methods=["POST"])
@token_required
def accion_en_lote():
    """Una acción sobre varias tareas (máx. 200), cada una con sus permisos. Cuerpo: `{"ids": [..], "accion": "completar|estado|prioridad|fecha|asignar|proyecto|seccion", "valor": ".."}`.
    Devuelve `{"ok": n, "fallos": m}`."""
    datos = _body()
    if not isinstance(datos.get("ids"), list) or not datos["ids"]:
        return _err("ids debe ser una lista no vacía.", 400, "peticion_invalida", "ids")
    try:
        resultado = db.accion_en_lote(g.usuario_id, datos["ids"], str(datos.get("accion") or ""), None if datos.get("valor") is None else str(datos["valor"]))
    except ValueError as e:
        return _err(str(e), 400, "accion_invalida", "accion")
    if datos.get("accion") == "asignar" and datos.get("valor") not in (None, ""):
        for tarea_id in {_int(i) for i in datos["ids"]} - {None}:
            _notificar_asignacion(g.usuario_id, tarea_id, _int(datos["valor"]))
    return _ok(resultado)


@api_bp.route("/tareas-outlook/categorias-outlook", methods=["GET"])
@token_required
def categorias_outlook():
    """Las categorías (estilo Outlook) que ya usan tus tareas: los valores que admite el filtro `categoria` de `GET /tareas-outlook`."""
    return _ok(db.listar_categorias_outlook(g.usuario_id))


@api_bp.route("/tareas-outlook/tablero", methods=["GET"])
@token_required
def tablero():
    """Tareas pendientes y recientes agrupadas por estado (propias y asignadas)."""
    filas = db.listar_tareas_outlook(g.usuario_id, incluir_asignadas=True, limite=500)
    columnas = {e: [] for e in ESTADOS}
    for f in filas:
        columnas.setdefault(f["estado"], []).append(dict(f))
    return _ok(columnas)


@api_bp.route("/tareas-outlook/carga", methods=["GET"])
@token_required
def carga_semanal():
    """Plan de la semana por persona del despacho (horas estimadas por día frente a su capacidad). `semana`: cualquier fecha YYYY-MM-DD de esa semana."""
    try:
        base = date.fromisoformat(request.args.get("semana") or date.today().isoformat())
    except ValueError:
        return _err("semana debe ser una fecha YYYY-MM-DD.", 400, "peticion_invalida", "semana")
    lunes = base - timedelta(days=base.weekday())
    datos = db.carga_semanal(g.usuario_id, lunes)
    return _ok({"lunes": lunes.isoformat(), "dias": datos["dias"], "personas": datos["personas"]})


@api_bp.route("/tareas-outlook/<int:tarea_id>/mover", methods=["POST"])
@token_required
def mover_tarea(tarea_id: int):
    """Reasigna y/o cambia el día. Cuerpo: `{"persona_id": n|null, "fecha": "YYYY-MM-DD"|null}` (cualquiera de los dos)."""
    _visible_o_404(tarea_id)
    datos = _body()
    if "persona_id" not in datos and "fecha" not in datos:
        return _err("Indica persona_id y/o fecha.", 400, "peticion_invalida")
    if "persona_id" in datos:
        destino = _int(datos["persona_id"])
        if not db.reasignar_tarea_outlook(g.usuario_id, tarea_id, destino):
            return _sin_permiso("No tienes permiso para reasignar esta tarea a esa persona.")
        _notificar_asignacion(g.usuario_id, tarea_id, destino)
    if "fecha" in datos and not db.cambiar_fecha_tarea_proyecto(g.usuario_id, tarea_id, (datos["fecha"] or "").strip() or None):
        return _sin_permiso("No se ha podido cambiar la fecha.")
    return _ok(_dict(db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)))


# --- Vistas guardadas -----------------------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/vistas", methods=["GET"])
@token_required
def listar_vistas():
    """Vistas (filtros con nombre) propias y las compartidas por tu despacho."""
    return _ok(db.listar_vistas_tareas(g.usuario_id))


@api_bp.route("/tareas-outlook/vistas", methods=["POST"])
@token_required
def guardar_vista():
    """Cuerpo: `{"nombre": "...", "filtros": {"estado": "en_progreso", ...}, "compartida": false}`. Mismo nombre = actualiza."""
    datos = _body()
    filtros = datos.get("filtros") if isinstance(datos.get("filtros"), dict) else {}
    vista_id = db.crear_vista_tareas(g.usuario_id, datos.get("nombre") or "", filtros, bool(datos.get("compartida")))
    if vista_id is None:
        return _err("Para guardar una vista pon un nombre y al menos un filtro válido (y no superes el máximo de vistas).", 400, "vista_invalida")
    return _ok(next(v for v in db.listar_vistas_tareas(g.usuario_id) if v["id"] == vista_id), 201)


@api_bp.route("/tareas-outlook/vistas/<int:vista_id>", methods=["DELETE"])
@token_required
def eliminar_vista(vista_id: int):
    if not db.eliminar_vista_tareas(g.usuario_id, vista_id):
        abort(404, "Vista no encontrada.")
    return _ok()


# --- Plantillas de tareas -------------------------------------------------------------------------------------------------

def _items_texto(valor) -> str:
    return "\n".join(str(x) for x in valor) if isinstance(valor, list) else str(valor or "")


@api_bp.route("/tareas-plantillas", methods=["GET"])
@token_required
def listar_plantillas_tareas():
    return _ok(db.listar_plantillas_tareas(g.usuario_id))


@api_bp.route("/tareas-plantillas", methods=["POST"])
@token_required
def crear_plantilla_tareas():
    """Cuerpo: `{"nombre", "descripcion", "items": ["tarea 1", ...] (o texto con una por línea), "compartida"}`."""
    d = _body()
    plantilla_id = db.crear_plantilla_tareas(g.usuario_id, d.get("nombre") or "", d.get("descripcion"), _items_texto(d.get("items")), compartida=bool(d.get("compartida")))
    if plantilla_id is None:
        return _err("Pon un nombre y al menos una tarea.", 400, "plantilla_invalida")
    return _ok(db.obtener_plantilla_tareas(g.usuario_id, plantilla_id), 201)


@api_bp.route("/tareas-plantillas/<int:plantilla_id>", methods=["PUT"])
@token_required
def editar_plantilla_tareas(plantilla_id: int):
    p = db.obtener_plantilla_tareas(g.usuario_id, plantilla_id)
    if p is None or p["usuario_id"] != g.usuario_id:
        abort(404, "Plantilla no encontrada.")
    d = _body()
    ok = db.editar_plantilla_tareas(
        g.usuario_id, plantilla_id, d.get("nombre", p["nombre"]), d.get("descripcion", p.get("descripcion")),
        _items_texto(d["items"]) if "items" in d else db.items_a_texto(p["items"]), bool(d.get("compartida", p.get("compartida"))),
    )
    if not ok:
        return _err("Pon un nombre y al menos una tarea.", 400, "plantilla_invalida")
    return _ok(db.obtener_plantilla_tareas(g.usuario_id, plantilla_id))


@api_bp.route("/tareas-plantillas/<int:plantilla_id>", methods=["DELETE"])
@token_required
def eliminar_plantilla_tareas(plantilla_id: int):
    if not db.eliminar_plantilla_tareas(g.usuario_id, plantilla_id):
        abort(404, "Plantilla no encontrada.")
    return _ok()


@api_bp.route("/tareas-plantillas/<int:plantilla_id>/aplicar", methods=["POST"])
@token_required
def aplicar_plantilla_tareas(plantilla_id: int):
    """Crea las tareas de la plantilla. Cuerpo: `fecha_inicio`, `proyecto_id` | `nuevo_proyecto`, `cliente_fiscal_id`, `asignada_a`, `encadenar` (cada una depende de la anterior)."""
    d = _body()
    ids = db.aplicar_plantilla_tareas(
        g.usuario_id, plantilla_id, d.get("fecha_inicio") or date.today().isoformat(), categoria_id=_int(d.get("proyecto_id")),
        nuevo_proyecto=d.get("nuevo_proyecto"), cliente_fiscal_id=_int(d.get("cliente_fiscal_id")), asignada_a=_int(d.get("asignada_a")),
        encadenar=bool(d.get("encadenar")),
    )
    if not ids:
        abort(404, "Plantilla no encontrada.")
    if _int(d.get("asignada_a")):
        for tarea_id in ids:
            _notificar_asignacion(g.usuario_id, tarea_id, _int(d["asignada_a"]))
    return _ok({"tareas_creadas": ids}, 201)


# --- Tareas recurrentes y reglas por vencimiento --------------------------------------------------------------------------

@api_bp.route("/tareas-recurrentes", methods=["GET"])
@token_required
def listar_recurrentes():
    return _ok(_dicts(db.listar_tareas_recurrentes(g.usuario_id)))


@api_bp.route("/tareas-recurrentes", methods=["POST"])
@token_required
def crear_recurrente():
    """Cuerpo: `asunto`, `periodicidad` (diaria|laborables|semanal|mensual|trimestral|anual), `dia` (semanal 0-6; mensual/trimestral/anual 1-31), `mes` (solo anual), `proyecto_id`."""
    d = _body()
    asunto, periodicidad = (d.get("asunto") or "").strip(), d.get("periodicidad")
    if not asunto:
        return _err("El asunto es obligatorio.", 400, "peticion_invalida", "asunto")
    if periodicidad not in db.PERIODICIDADES_RECURRENTES:
        return _err(f"periodicidad debe ser una de: {', '.join(db.PERIODICIDADES_RECURRENTES)}.", 400, "peticion_invalida", "periodicidad")
    dia, mes = (0 if periodicidad in ("diaria", "laborables") else _int(d.get("dia"))), _int(d.get("mes"))
    if dia is None or (periodicidad == "semanal" and not 0 <= dia <= 6) or (periodicidad in ("mensual", "trimestral", "anual") and not 1 <= dia <= 31):
        return _err("dia no válido para esa periodicidad.", 400, "peticion_invalida", "dia")
    if periodicidad == "anual" and not (mes and 1 <= mes <= 12):
        return _err("Las anuales necesitan mes (1-12).", 400, "peticion_invalida", "mes")
    regla_id = db.crear_tarea_recurrente(g.usuario_id, asunto, periodicidad, dia, categoria_id=_int(d.get("proyecto_id")), mes=mes if periodicidad == "anual" else None)
    return _ok(next(dict(r) for r in db.listar_tareas_recurrentes(g.usuario_id) if r["id"] == regla_id), 201)


@api_bp.route("/tareas-recurrentes/<int:regla_id>/alternar", methods=["POST"])
@token_required
def alternar_recurrente(regla_id: int):
    if not any(r["id"] == regla_id for r in db.listar_tareas_recurrentes(g.usuario_id)):
        abort(404, "Regla no encontrada.")
    db.alternar_activa_tarea_recurrente(g.usuario_id, regla_id)
    return _ok(next(dict(r) for r in db.listar_tareas_recurrentes(g.usuario_id) if r["id"] == regla_id))


@api_bp.route("/tareas-recurrentes/<int:regla_id>", methods=["DELETE"])
@token_required
def eliminar_recurrente(regla_id: int):
    if not any(r["id"] == regla_id for r in db.listar_tareas_recurrentes(g.usuario_id)):
        abort(404, "Regla no encontrada.")
    db.eliminar_tarea_recurrente(g.usuario_id, regla_id)
    return _ok()


@api_bp.route("/tareas-reglas-vencimiento", methods=["GET"])
@token_required
def listar_reglas_vencimiento():
    """Reglas «una tarea por cada vencimiento del modelo X»."""
    return _ok(db.listar_reglas_por_vencimiento(g.usuario_id))


@api_bp.route("/tareas-reglas-vencimiento", methods=["POST"])
@token_required
def crear_regla_vencimiento():
    """Cuerpo: `modelo` (p. ej. 303), `asunto` (admite {cliente}, {modelo}, {periodo}), `crear_dias_antes` (14), `vence_dias_antes` (2), `proyecto_id`, `asignar_responsable`, `estimacion` ("2h"), `prioridad`. Se aplica al momento a los vencimientos existentes."""
    d = _body()
    try:
        regla_id = db.crear_regla_por_vencimiento(
            g.usuario_id, d.get("modelo") or "", d.get("asunto") or "", crear_dias_antes=_int(d.get("crear_dias_antes")) if d.get("crear_dias_antes") is not None else 14,
            vence_dias_antes=_int(d.get("vence_dias_antes")) if d.get("vence_dias_antes") is not None else 2, categoria_id=_int(d.get("proyecto_id")),
            asignar_responsable=bool(d.get("asignar_responsable", True)), estimacion_min=quickadd.duracion_a_minutos(d.get("estimacion")) if d.get("estimacion") else None,
            prioridad=d.get("prioridad") or "normal",
        )
    except ValueError as e:
        return _err(str(e), 400, "regla_invalida")
    generadas = db.generar_tareas_por_vencimiento(regla_id=regla_id)
    regla = next(r for r in db.listar_reglas_por_vencimiento(g.usuario_id) if r["id"] == regla_id)
    return _ok({**regla, "generadas_ahora": generadas if isinstance(generadas, int) else None}, 201)


@api_bp.route("/tareas-reglas-vencimiento/<int:regla_id>/alternar", methods=["POST"])
@token_required
def alternar_regla_vencimiento(regla_id: int):
    if not any(r["id"] == regla_id for r in db.listar_reglas_por_vencimiento(g.usuario_id)):
        abort(404, "Regla no encontrada.")
    db.alternar_regla_por_vencimiento(g.usuario_id, regla_id)
    return _ok(next(r for r in db.listar_reglas_por_vencimiento(g.usuario_id) if r["id"] == regla_id))


@api_bp.route("/tareas-reglas-vencimiento/<int:regla_id>", methods=["DELETE"])
@token_required
def eliminar_regla_vencimiento(regla_id: int):
    if not any(r["id"] == regla_id for r in db.listar_reglas_por_vencimiento(g.usuario_id)):
        abort(404, "Regla no encontrada.")
    db.eliminar_regla_por_vencimiento(g.usuario_id, regla_id)
    return _ok()


from . import rutas_api_tareas_trabajo  # noqa: E402,F401 -- transiciones con versión, clientes de una tarea y tareas de un cliente
