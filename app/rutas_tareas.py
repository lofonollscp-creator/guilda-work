"""Rutas de la pestaña "Tareas" (estilo Microsoft Outlook): lista, calendario
e import/export con Outlook. Vive en su propio Blueprint para no seguir
haciendo crecer app/main.py — es, en la práctica, una sección independiente
dentro de la app (sin relación con los proyectos ni con las tareas con duración).
"""
import calendar as calendario_std
from datetime import date, timedelta

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from flask_babel import lazy_gettext as _l

from . import db, notificaciones, outlook_ics
from .auth import login_required

tareas_bp = Blueprint("tareas", __name__, url_prefix="/tareas")

ESTADOS = [
    ("no_iniciada", _l("No iniciada")),
    ("en_progreso", _l("En progreso")),
    ("completada", _l("Completada")),
    ("esperando", _l("Esperando a otros")),
    ("aplazada", _l("Aplazada")),
]
PRIORIDADES = [
    ("baja", _l("Baja")),
    ("normal", _l("Normal")),
    ("alta", _l("Alta")),
]
VISTAS_CALENDARIO = ["mes", "semana", "semana_laboral", "dia"]
HORAS_DIA = [f"{h:02d}:00" for h in range(6, 22)]
NOMBRES_MES = [
    "", _l("enero"), _l("febrero"), _l("marzo"), _l("abril"), _l("mayo"), _l("junio"), _l("julio"),
    _l("agosto"), _l("septiembre"), _l("octubre"), _l("noviembre"), _l("diciembre"),
]


PALETA_CATEGORIAS = ["#4a6cf7", "#e0555a", "#2fa66a", "#d98c1f", "#8a5cf5", "#1f9fd9", "#c94f8a", "#0f9b8e"]

TAREAS_POR_PAGINA = 50


@tareas_bp.app_template_filter("duracion_hm")
def duracion_hm(segundos: int | None) -> str:
    """Tiempo registrado en formato corto: "2 h 05 min", "35 min" o "<1 min"."""
    segundos = int(segundos or 0)
    horas, resto = divmod(segundos, 3600)
    minutos = resto // 60
    if horas:
        return f"{horas} h {minutos:02d} min"
    return f"{minutos} min" if minutos else "<1 min"


@tareas_bp.app_template_filter("color_categoria")
def color_categoria(nombre: str | None) -> str:
    """Color estable por nombre de categoría (misma idea que el color por proyecto)."""
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
@login_required
def listar():
    estado = request.args.get("estado") or None
    prioridad = request.args.get("prioridad") or None
    categoria = request.args.get("categoria") or None
    q = request.args.get("q") or None
    incluir_completadas = request.args.get("completadas") == "1"
    pagina = max(request.args.get("pagina", 1, type=int) or 1, 1)
    offset = (pagina - 1) * TAREAS_POR_PAGINA

    # Vista por defecto: como el "To-Do List" de Outlook, oculta lo ya
    # completado para que la lista no se llene de tareas resueltas. Antes
    # ese filtro se aplicaba en Python DESPUÉS de traer las filas de la
    # BD; se ha movido a SQL (excluir_completadas=...) para que la
    # paginación de abajo (LIMIT/OFFSET) cuente sobre el conjunto ya
    # filtrado, igual que hace db.listar_mensajes_correo.
    excluir_completadas = estado is None and not incluir_completadas
    # Se pide una fila de más para saber si hay página siguiente sin un
    # COUNT(*) aparte.
    vista = request.args.get("vista") or ""
    if vista not in ("mias", "asignadas", "compartidas"):
        vista = ""
    tareas = db.listar_tareas_outlook(
        g.usuario_id, estado=estado, prioridad=prioridad, categoria_outlook=categoria, texto=q,
        excluir_completadas=excluir_completadas, limite=TAREAS_POR_PAGINA + 1, offset=offset,
        incluir_asignadas=vista == "", solo_asignadas=vista == "asignadas",
        solo_compartidas=vista == "compartidas",
    )
    hay_pagina_siguiente = len(tareas) > TAREAS_POR_PAGINA
    tareas = tareas[:TAREAS_POR_PAGINA]

    return render_template(
        "tareas_lista.html",
        **_contexto_filas(tareas),
        vista=vista,
        error=(request.args.get("error") or "")[:200] or None,
        tareas=tareas,
        estados=ESTADOS,
        prioridades=PRIORIDADES,
        categorias_outlook=db.listar_categorias_outlook(g.usuario_id),
        estado=estado or "",
        prioridad=prioridad or "",
        categoria=categoria or "",
        q=q or "",
        incluir_completadas=incluir_completadas,
        pagina=pagina,
        hay_pagina_anterior=pagina > 1,
        hay_pagina_siguiente=hay_pagina_siguiente,
    )


def _contexto_filas(tareas) -> dict:
    """Lo que necesita cada fila de tarea (lista, "Mi día", tablero): el
    cronómetro y el checklist de cada una, y los selectores de proyecto,
    compañero y cliente."""
    ids = [t["id"] for t in tareas]
    return {
        "cronometros": db.cronometros_de_tareas_outlook(g.usuario_id, ids),
        "checklists": db.resumen_checklist(ids),
        "participantes": db.participantes_de_tareas(ids),
        "n_comentarios": db.contar_comentarios_tareas(ids),
        "menus": db.listar_categorias(g.usuario_id),
        "companeros": db.listar_companeros_tenant(g.usuario_id),
        "clientes_fiscales": db.listar_clientes_fiscales(g.tenant_id) if g.tenant_id else [],
    }


def _int_o_none(valor):
    try:
        return int(valor) if valor not in (None, "") else None
    except ValueError:
        return None


def _notificar_asignacion(origen_id: int, tarea_id: int, destino_id: int | None) -> None:
    """Avisa al compañero (en la app y por push) de que le han asignado una
    tarea. Un fallo al avisar nunca debe romper la asignación."""
    if destino_id is None or destino_id == origen_id:
        return
    try:
        if not db.notificacion_tipo_activa(destino_id, "tarea_asignada"):
            return
        tarea = db.obtener_tarea_outlook_visible(destino_id, tarea_id)
        if tarea is None:
            return
        quien = db.nombre_mostrado_usuario(origen_id) or (db.obtener_usuario(origen_id)["email"])
        notificaciones.crear_y_enviar(
            destino_id, "tarea_asignada", "Tarea asignada", f"{quien} te ha asignado: {tarea['asunto']}",
            url=url_for("tareas.listar", vista="asignadas"),
            datos={"tipo": "tarea_asignada", "tarea_id": tarea_id},
        )
    except Exception:  # noqa: BLE001
        pass


def _notificar_compartida(origen_id: int, tarea_id: int, destino_id: int, rol: str) -> None:
    """Avisa al compañero de que le han compartido una tarea (nunca rompe la acción)."""
    try:
        if not db.notificacion_tipo_activa(destino_id, "tarea_asignada"):
            return
        tarea = db.obtener_tarea_outlook_visible(destino_id, tarea_id)
        if tarea is None:
            return
        quien = db.nombre_mostrado_usuario(origen_id) or (db.obtener_usuario(origen_id)["email"])
        que = "para colaborar" if rol == "colabora" else "en solo lectura"
        notificaciones.crear_y_enviar(
            destino_id, "tarea_asignada", "Tarea compartida", f"{quien} ha compartido contigo ({que}): {tarea['asunto']}",
            url=url_for("tareas.listar", vista="compartidas"),
            datos={"tipo": "tarea_compartida", "tarea_id": tarea_id},
        )
    except Exception:  # noqa: BLE001
        pass


def _volver_con_error(mensaje: str):
    return redirect(url_for("tareas.listar", error=mensaje))


@tareas_bp.route("/calendario")
@login_required
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
    for t in db.listar_tareas_outlook(g.usuario_id):
        fecha_efectiva = (t["fecha_vencimiento"] or t["fecha_inicio"] or "")[:10]
        if fecha_efectiva:
            tareas_por_dia.setdefault(fecha_efectiva, []).append(t)

    # Vencimientos fiscales del tenant (no del usuario) -- solo si hay tenant
    # asignado; g.tenant_id es None en modo escritorio o para un admin sin
    # tenant, y ahí simplemente no hay nada que mostrar en este bucket, sin
    # caso especial en la plantilla.
    vencimientos_por_dia: dict[str, list] = {}
    if g.tenant_id is not None:
        for v in db.listar_vencimientos_fiscales(g.tenant_id, desde=inicio.isoformat(), hasta=fin.isoformat()):
            fecha_efectiva = (v["fecha_limite"] or "")[:10]
            if fecha_efectiva:
                vencimientos_por_dia.setdefault(fecha_efectiva, []).append(v)

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
            "vencimientos": vencimientos_por_dia.get(iso, []),
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
        categorias_outlook=db.listar_categorias_outlook(g.usuario_id),
        menus=db.listar_categorias(g.usuario_id),
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
@login_required
def crear():
    asunto = request.form.get("asunto", "").strip()
    if asunto:
        categoria_id = request.form.get("categoria_id") or None
        asignada_a = _int_o_none(request.form.get("asignada_a"))
        tarea_id = db.crear_tarea_outlook(
            g.usuario_id,
            asunto=asunto,
            prioridad=request.form.get("prioridad", "normal"),
            fecha_inicio=request.form.get("fecha_inicio") or None,
            fecha_vencimiento=request.form.get("fecha_vencimiento") or None,
            categoria_outlook=request.form.get("categoria_outlook") or None,
            categoria_id=int(categoria_id) if categoria_id else None,
            cliente_fiscal_id=_int_o_none(request.form.get("cliente_fiscal_id")),
            asignada_a=asignada_a,
        )
        _notificar_asignacion(g.usuario_id, tarea_id, asignada_a)
        if request.form.get("con_cronometro"):
            try:
                db.iniciar_cronometro_tarea_outlook(g.usuario_id, tarea_id)
            except ValueError as e:
                return _volver_con_error(str(e))
    return redirect(request.form.get("volver_a") or url_for("tareas.listar"))


@tareas_bp.route("/<int:tarea_id>/editar", methods=["GET", "POST"])
@login_required
def editar(tarea_id: int):
    # Dueño o colaborador (los demás ni la editan ni llegan aquí).
    if not db.puede_editar_tarea(g.usuario_id, tarea_id):
        abort(404)
    tarea = db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)
    if tarea is None:
        abort(404)
    es_dueno = tarea["usuario_id"] == g.usuario_id

    menus = db.listar_categorias(g.usuario_id)

    def _contexto_edicion(tarea, error=None):
        return dict(
            **_contexto_comentarios(tarea["id"]),
            es_dueno=es_dueno, dueno_nombre=db.nombre_mostrado_usuario(tarea["usuario_id"]),
            participantes=db.participantes_de_tarea(tarea["id"]),
            tarea=tarea, estados=ESTADOS, prioridades=PRIORIDADES, menus=menus, error=error,
            checklist=db.listar_checklist(tarea["id"]),
            companeros=db.listar_companeros_tenant(g.usuario_id),
            clientes_fiscales=db.listar_clientes_fiscales(g.tenant_id) if g.tenant_id else [],
            cronometro=db.cronometros_de_tareas_outlook(g.usuario_id, [tarea["id"]]).get(tarea["id"]),
        )

    if request.method == "POST":
        asunto = request.form.get("asunto", "").strip()
        if not asunto:
            return render_template("tarea_outlook_editar.html", **_contexto_edicion(tarea, "El asunto no puede estar vacío."))
        categoria_id = request.form.get("categoria_id") or None
        campos = {
            "asunto": asunto,
            "cuerpo": request.form.get("cuerpo", "").strip() or None,
            "estado": request.form.get("estado", "no_iniciada"),
            "prioridad": request.form.get("prioridad", "normal"),
            "porcentaje_completado": int(request.form.get("porcentaje_completado") or 0),
            "fecha_inicio": request.form.get("fecha_inicio") or None,
            "fecha_vencimiento": request.form.get("fecha_vencimiento") or None,
            "categoria_outlook": request.form.get("categoria_outlook", "").strip() or None,
            "categoria_id": int(categoria_id) if categoria_id else None,
            "cliente_fiscal_id": _int_o_none(request.form.get("cliente_fiscal_id")),
        }
        if not es_dueno:
            campos.pop("categoria_id")
        if campos["estado"] == "completada" and tarea["estado"] != "completada":
            db.completar_tarea_outlook(g.usuario_id, tarea_id)
            campos.pop("estado")
            campos.pop("porcentaje_completado")
        db.editar_tarea_outlook(g.usuario_id, tarea_id, **campos)
        nueva_asignacion = _int_o_none(request.form.get("asignada_a"))
        if es_dueno and nueva_asignacion != tarea["asignada_a"] and db.asignar_tarea_outlook(g.usuario_id, tarea_id, nueva_asignacion):
            _notificar_asignacion(g.usuario_id, tarea_id, nueva_asignacion)
        return redirect(url_for("tareas.listar"))

    return render_template("tarea_outlook_editar.html", **_contexto_edicion(tarea))


@tareas_bp.route("/hoy")
@login_required
def hoy():
    """"Mi día": vencidas, de hoy, en progreso y asignadas a mí."""
    secciones = db.tareas_para_hoy(g.usuario_id)
    todas = [t for lista in secciones.values() for t in lista]
    return render_template(
        "tareas_hoy.html", secciones=secciones, estados=ESTADOS, vista="hoy",
        error=(request.args.get("error") or "")[:200] or None, **_contexto_filas(todas),
    )


@tareas_bp.route("/tablero")
@login_required
def tablero():
    """Tablero por estado. Sin arrastrar: cada tarjeta tiene botones para moverla."""
    tareas = db.listar_tareas_outlook(g.usuario_id, incluir_asignadas=True)
    columnas = {valor: [] for valor, _etiqueta in ESTADOS}
    for t in tareas:
        columnas[t["estado"]].append(t)
    # Las completadas son muchas con el tiempo: solo las más recientes.
    columnas["completada"] = sorted(columnas["completada"], key=lambda t: t["fecha_completada"] or "", reverse=True)[:15]
    visibles = [t for lista in columnas.values() for t in lista]
    return render_template(
        "tareas_tablero.html", estados=ESTADOS, columnas=columnas, vista="tablero", **_contexto_filas(visibles)
    )


@tareas_bp.route("/<int:tarea_id>/estado", methods=["POST"])
@login_required
def cambiar_estado(tarea_id: int):
    if not db.cambiar_estado_tarea_outlook(g.usuario_id, tarea_id, request.form.get("estado", "")):
        abort(404)
    return redirect(request.referrer or url_for("tareas.tablero"))


@tareas_bp.route("/<int:tarea_id>/cronometro/iniciar", methods=["POST"])
@login_required
def iniciar_cronometro(tarea_id: int):
    try:
        db.iniciar_cronometro_tarea_outlook(g.usuario_id, tarea_id, _int_o_none(request.form.get("categoria_id")))
    except ValueError as e:
        return _volver_con_error(str(e))
    return redirect(request.referrer or url_for("tareas.listar"))


@tareas_bp.route("/<int:tarea_id>/checklist", methods=["POST"])
@login_required
def agregar_checklist(tarea_id: int):
    db.agregar_item_checklist(g.usuario_id, tarea_id, request.form.get("texto", ""))
    return redirect(url_for("tareas.editar", tarea_id=tarea_id) + "#checklist")


@tareas_bp.route("/checklist/<int:item_id>/alternar", methods=["POST"])
@login_required
def alternar_checklist(item_id: int):
    if not db.alternar_item_checklist(g.usuario_id, item_id):
        abort(404)
    return redirect(request.referrer or url_for("tareas.listar"))


@tareas_bp.route("/checklist/<int:item_id>/eliminar", methods=["POST"])
@login_required
def eliminar_checklist(item_id: int):
    if not db.eliminar_item_checklist(g.usuario_id, item_id):
        abort(404)
    return redirect(request.referrer or url_for("tareas.listar"))


@tareas_bp.route("/<int:tarea_id>/asignar", methods=["POST"])
@login_required
def asignar(tarea_id: int):
    destino = _int_o_none(request.form.get("asignada_a"))
    if not db.asignar_tarea_outlook(g.usuario_id, tarea_id, destino):
        abort(404)
    _notificar_asignacion(g.usuario_id, tarea_id, destino)
    return redirect(request.referrer or url_for("tareas.listar"))


def _notificar_comentario(autor_id: int, tarea_id: int, resultado: dict) -> None:
    """Avisa a los mencionados ("te ha mencionado") y al resto de implicados
    ("ha comentado"). Un fallo al avisar nunca rompe el comentario."""
    try:
        tarea = db.obtener_tarea_outlook_visible(autor_id, tarea_id)
        quien = db.nombre_mostrado_usuario(autor_id) or db.obtener_usuario(autor_id)["email"]
        for destino, titulo, cuerpo in (
            [(u, "Te han mencionado", f"{quien} te ha mencionado en: {tarea['asunto']}") for u in resultado["menciones"]]
            + [(u, "Nuevo comentario", f"{quien} ha comentado en: {tarea['asunto']}") for u in resultado["otros"]]
        ):
            if not db.notificacion_tipo_activa(destino, "tarea_asignada"):
                continue
            notificaciones.crear_y_enviar(
                destino, "tarea_asignada", titulo, cuerpo,
                url=url_for("tareas.ver", tarea_id=tarea_id) + "#comentarios",
                datos={"tipo": "tarea_comentario", "tarea_id": tarea_id},
            )
    except Exception:  # noqa: BLE001
        pass


@tareas_bp.route("/<int:tarea_id>")
@login_required
def ver(tarea_id: int):
    """Ficha de solo lectura de una tarea para quien la ve (también observadores y
    asignados): datos, subtareas, participantes y comentarios."""
    tarea = db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)
    if tarea is None:
        abort(404)
    return render_template(
        "tarea_ver.html", tarea=tarea, estados=ESTADOS,
        checklist=db.listar_checklist(tarea_id), participantes=db.participantes_de_tarea(tarea_id),
        dueno_nombre=db.nombre_mostrado_usuario(tarea["usuario_id"]),
        puede_editar=db.puede_editar_tarea(g.usuario_id, tarea_id),
        **_contexto_comentarios(tarea_id),
    )


def _contexto_comentarios(tarea_id: int) -> dict:
    return {
        "comentarios": db.listar_comentarios_tarea(g.usuario_id, tarea_id),
        "personas_mencionables": [p for p in db.personas_de_tarea(g.usuario_id, tarea_id) if p["id"] != g.usuario_id],
    }


@tareas_bp.route("/<int:tarea_id>/comentarios", methods=["POST"])
@login_required
def comentar(tarea_id: int):
    resultado = db.comentar_tarea_outlook(g.usuario_id, tarea_id, request.form.get("texto", ""))
    if resultado is None:
        if db.rol_en_tarea(g.usuario_id, tarea_id) is None:
            abort(404)
        return redirect(url_for("tareas.ver", tarea_id=tarea_id) + "#comentarios")
    _notificar_comentario(g.usuario_id, tarea_id, resultado)
    return redirect(url_for("tareas.ver", tarea_id=tarea_id) + "#comentarios")


@tareas_bp.route("/<int:tarea_id>/comentarios/<int:comentario_id>/eliminar", methods=["POST"])
@login_required
def eliminar_comentario(tarea_id: int, comentario_id: int):
    if not db.eliminar_comentario_tarea(g.usuario_id, tarea_id, comentario_id):
        abort(404)
    return redirect(url_for("tareas.ver", tarea_id=tarea_id) + "#comentarios")


@tareas_bp.route("/<int:tarea_id>/compartir", methods=["POST"])
@login_required
def compartir(tarea_id: int):
    """Solo el dueño: comparte la tarea con un compañero del tenant."""
    otro = _int_o_none(request.form.get("usuario_id"))
    rol = request.form.get("rol", "colabora")
    if otro is None or not db.compartir_tarea_outlook(g.usuario_id, tarea_id, otro, rol):
        abort(404)
    _notificar_compartida(g.usuario_id, tarea_id, otro, rol)
    return redirect(url_for("tareas.editar", tarea_id=tarea_id) + "#compartir")


@tareas_bp.route("/<int:tarea_id>/compartir/quitar", methods=["POST"])
@login_required
def dejar_de_compartir(tarea_id: int):
    """El dueño quita a un participante; un participante puede salirse él mismo."""
    otro = _int_o_none(request.form.get("usuario_id"))
    if otro is None or not db.dejar_de_compartir_tarea_outlook(g.usuario_id, tarea_id, otro):
        abort(404)
    if otro == g.usuario_id:
        return redirect(url_for("tareas.listar"))
    return redirect(url_for("tareas.editar", tarea_id=tarea_id) + "#compartir")


@tareas_bp.route("/<int:tarea_id>/completar", methods=["POST"])
@login_required
def completar(tarea_id: int):
    db.completar_tarea_outlook(g.usuario_id, tarea_id)
    return redirect(request.referrer or url_for("tareas.listar"))


@tareas_bp.route("/<int:tarea_id>/eliminar", methods=["POST"])
@login_required
def eliminar(tarea_id: int):
    if db.obtener_tarea_outlook(g.usuario_id, tarea_id) is None:
        abort(404)
    db.eliminar_tarea_outlook(g.usuario_id, tarea_id)
    return redirect(url_for("tareas.listar"))


@tareas_bp.route("/<int:tarea_id>/restaurar", methods=["POST"])
@login_required
def restaurar(tarea_id: int):
    db.restaurar_tarea_outlook(g.usuario_id, tarea_id)
    return redirect(request.form.get("volver_a") or url_for("papelera"))


@tareas_bp.route("/<int:tarea_id>/eliminar-definitivamente", methods=["POST"])
@login_required
def eliminar_definitivamente(tarea_id: int):
    db.eliminar_tarea_outlook_definitivamente(g.usuario_id, tarea_id)
    return redirect(request.form.get("volver_a") or url_for("papelera"))


@tareas_bp.route("/sincronizar")
@login_required
def sincronizar():
    return render_template("tareas_outlook_sync.html", resumen=None, error=None)


@tareas_bp.route("/exportar.ics")
@login_required
def exportar_ics():
    contenido = outlook_ics.exportar_ics(db.listar_tareas_outlook(g.usuario_id))
    return Response(
        contenido,
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=guilda_work_tareas.ics"},
    )


@tareas_bp.route("/exportar.csv")
@login_required
def exportar_csv():
    contenido = outlook_ics.exportar_csv_outlook(db.listar_tareas_outlook(g.usuario_id))
    return Response(
        contenido,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=guilda_work_tareas.csv"},
    )


DIAS_SEMANA = [
    (0, _l("Lunes")), (1, _l("Martes")), (2, _l("Miércoles")), (3, _l("Jueves")),
    (4, _l("Viernes")), (5, _l("Sábado")), (6, _l("Domingo")),
]


PERIODICIDADES = [
    ("diaria", _l("Cada día")),
    ("laborables", _l("Cada día laborable (lunes a viernes)")),
    ("semanal", _l("Cada semana")),
    ("mensual", _l("Cada mes")),
    ("trimestral", _l("Cada trimestre (enero, abril, julio, octubre)")),
    ("anual", _l("Cada año")),
]
NOMBRES_MES_SELECT = [(i, NOMBRES_MES[i]) for i in range(1, 13)]


@tareas_bp.route("/recurrentes")
@login_required
def recurrentes():
    return render_template(
        "tareas_recurrentes.html",
        reglas=db.listar_tareas_recurrentes(g.usuario_id),
        menus=db.listar_categorias(g.usuario_id),
        dias_semana=DIAS_SEMANA,
        periodicidades=PERIODICIDADES,
        meses=NOMBRES_MES_SELECT,
        etiquetas_periodicidad=dict(PERIODICIDADES),
    )


@tareas_bp.route("/recurrentes", methods=["POST"])
@login_required
def crear_recurrente():
    asunto = request.form.get("asunto", "").strip()
    periodicidad = request.form.get("periodicidad")
    dia = request.form.get("dia", type=int)  # formulario antiguo: un solo selector de día
    if dia is None:
        dia = request.form.get("dia_semana" if periodicidad == "semanal" else "dia_mes", type=int)
    mes = request.form.get("mes", type=int)
    if periodicidad in ("diaria", "laborables"):
        dia = 0
    if asunto and periodicidad in db.PERIODICIDADES_RECURRENTES and dia is not None:
        if periodicidad == "semanal" and not 0 <= dia <= 6:
            return redirect(url_for("tareas.recurrentes"))
        if periodicidad in ("mensual", "trimestral", "anual") and not 1 <= dia <= 31:
            return redirect(url_for("tareas.recurrentes"))
        if periodicidad == "anual" and not (mes and 1 <= mes <= 12):
            return redirect(url_for("tareas.recurrentes"))
        categoria_id = request.form.get("categoria_id") or None
        db.crear_tarea_recurrente(
            g.usuario_id, asunto, periodicidad, dia, categoria_id=int(categoria_id) if categoria_id else None,
            mes=mes if periodicidad == "anual" else None,
        )
    return redirect(url_for("tareas.recurrentes"))


@tareas_bp.route("/recurrentes/<int:regla_id>/alternar", methods=["POST"])
@login_required
def alternar_recurrente(regla_id: int):
    db.alternar_activa_tarea_recurrente(g.usuario_id, regla_id)
    return redirect(url_for("tareas.recurrentes"))


@tareas_bp.route("/recurrentes/<int:regla_id>/eliminar", methods=["POST"])
@login_required
def eliminar_recurrente(regla_id: int):
    db.eliminar_tarea_recurrente(g.usuario_id, regla_id)
    return redirect(url_for("tareas.recurrentes"))


@tareas_bp.route("/importar", methods=["POST"])
@login_required
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
            resumen = outlook_ics.importar_csv_outlook(g.usuario_id, contenido)
        else:
            resumen = outlook_ics.importar_ics(g.usuario_id, contenido)
    except outlook_ics.ErrorSincronizacionOutlook as e:
        return render_template("tareas_outlook_sync.html", resumen=None, error=str(e))

    return render_template("tareas_outlook_sync.html", resumen=resumen, error=None)
