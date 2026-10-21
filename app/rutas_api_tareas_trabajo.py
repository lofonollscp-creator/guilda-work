"""API del trabajo con tareas (Fase 1 del plan, docs/guilda-work-implementation-plan.md): transiciones con motivo y versión, clientes vinculados a una tarea y tareas de un
cliente con contadores. Capa fina sobre `app/tareas_trabajo.py`; mismo token, mismo formato de error y mismos permisos que el resto de la API de tareas. Todo aditivo."""
from __future__ import annotations

from flask import Response, abort, g, jsonify, request

from . import db, tareas_trabajo as tt
from .auth import token_required
from .rutas_api import _body, _dict, _err, _exigir_tenant_api, _ok, _ok_paginado, api_bp

_STATUS = {"no_encontrada": 404, "sin_permiso": 403, "tarea_bloqueada": 409, "subtareas_abiertas": 409, "revision_pendiente": 409, "tarea_completada": 409, "nota_obligatoria": 400, "ya_has_votado": 409, "demasiados_revisores": 400, "sin_cliente": 409, "subtarea_de_subtarea": 409, "padre_completada": 409, "duplicado": 409, "limite": 409,
           "tipo_no_admitido": 415, "archivo_grande": 413}


def _tarea_o_404(tarea_id: int):
    tarea = db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id)
    if tarea is None:
        abort(404, "Tarea no encontrada.")
    return tarea


def _version_del_cuerpo(datos: dict):
    """Versión de la petición: cuerpo `version` o cabecera `If-Match`. (valor, error)."""
    bruto = datos.get("version", request.headers.get("If-Match"))
    try:
        return tt.version_pedida(str(bruto).strip('"') if bruto not in (None, "") else None), None
    except ValueError:
        return None, _err("version debe ser un número entero.", 400, "version_invalida", "version")


def _conflicto(e: tt.ConflictoDeVersion):
    cuerpo = {"ok": False, "error": str(e), "codigo": "version_obsoleta", "version_actual": e.actual}
    return jsonify(cuerpo), 409


def _con_extras(tarea_id: int) -> dict:
    fila = _dict(db.obtener_tarea_outlook_visible(g.usuario_id, tarea_id))
    fila["vencida"] = tt.esta_vencida(fila.get("fecha_vencimiento"), fila.get("estado"))
    fila["clientes"] = tt.clientes_de_tarea(tarea_id)
    return fila


@api_bp.route("/tareas-outlook/<int:tarea_id>/transiciones", methods=["POST"])
@token_required
def transicionar_tarea(tarea_id: int):
    """Cuerpo: `{"estado": "esperando", "motivo": "Falta el certificado", "version": 4}`. `esperando` exige `motivo`; con `version` (o cabecera `If-Match`) solo
    vale si nadie ha tocado la tarea (409 `version_obsoleta` con `version_actual`)."""
    _tarea_o_404(tarea_id)
    datos = _body()
    version, error = _version_del_cuerpo(datos)
    if error:
        return error
    try:
        tt.transicionar(g.usuario_id, tarea_id, (datos.get("estado") or "").strip(), datos.get("motivo"), version)
    except tt.ConflictoDeVersion as e:
        return _conflicto(e)
    except tt.TransicionInvalida as e:
        return _err(str(e), _STATUS.get(e.codigo, 400), e.codigo, e.campo)
    from .rutas_tareas import _avisar_desbloqueos
    _avisar_desbloqueos(g.usuario_id, tarea_id, False)
    return _ok(_con_extras(tarea_id))


@api_bp.route("/tareas-outlook/<int:tarea_id>/clientes", methods=["GET"])
@token_required
def clientes_de_la_tarea(tarea_id: int):
    _tarea_o_404(tarea_id)
    return _ok({"clientes": tt.clientes_de_tarea(tarea_id)})


@api_bp.route("/tareas-outlook/<int:tarea_id>/clientes", methods=["PUT"])
@token_required
def fijar_clientes_de_la_tarea(tarea_id: int):
    """Cuerpo: `{"cliente_ids": [3, 8], "principal_id": 3, "version": 4}`. Sustituye los vinculados; lista vacía = tarea interna sin cliente. Solo clientes del propio
    despacho. Un único principal (el indicado o el primero)."""
    _tarea_o_404(tarea_id)
    datos = _body()
    if not isinstance(datos.get("cliente_ids"), list):
        return _err("cliente_ids debe ser una lista.", 400, "cliente_ids_invalido", "cliente_ids")
    version, error = _version_del_cuerpo(datos)
    if error:
        return error
    try:
        clientes = tt.fijar_clientes(g.usuario_id, tarea_id, datos["cliente_ids"], datos.get("principal_id"), version)
    except tt.ConflictoDeVersion as e:
        return _conflicto(e)
    except tt.TransicionInvalida as e:
        return _err(str(e), _STATUS.get(e.codigo, 400 if e.codigo != "cliente_invalido" else 422), e.codigo, e.campo)
    return _ok({"clientes": clientes, "version": tt.version_de(tarea_id)})


@api_bp.route("/fiscal/clientes/<int:cliente_id>/tareas", methods=["GET"])
@token_required
def tareas_del_cliente(cliente_id: int):
    """Las tareas del cliente que la persona puede ver (principal o vinculado), con contadores abiertas/vencidas/completadas calculados sobre esa misma lista.
    Filtros: `estado`, `vencidas=1`. Paginación opcional `limit`/`offset`."""
    error = _exigir_tenant_api()
    if error:
        return error
    if db.obtener_cliente_fiscal(g.tenant_id, cliente_id) is None:
        abort(404, "Cliente fiscal no encontrado.")
    todas = [dict(t) for t in db.listar_tareas_outlook(g.usuario_id, incluir_asignadas=True, cliente_fiscal_id=cliente_id)]
    contadores = tt.contadores_de_cliente(todas)
    estado = request.args.get("estado") or None
    solo_vencidas = request.args.get("vencidas") in ("1", "true", "si")
    filas = []
    for t in todas:
        t["vencida"] = tt.esta_vencida(t["fecha_vencimiento"], t["estado"])
        if (estado and t["estado"] != estado) or (solo_vencidas and not t["vencida"]):
            continue
        filas.append(t)
    filas.sort(key=lambda t: (t["estado"] == "completada", t["fecha_vencimiento"] or "9999", t["id"]))
    respuesta, status = _ok_paginado(filas)
    cuerpo = respuesta.get_json()
    cuerpo["contadores"] = contadores
    nueva = jsonify(cuerpo)
    nueva.headers.update(respuesta.headers)
    return nueva, status


# --- Subtareas ------------------------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>/subtareas", methods=["GET"])
@token_required
def subtareas_de_la_tarea(tarea_id: int):
    """Las subtareas (un nivel) con su progreso. La tarea padre no se puede completar mientras tenga subtareas abiertas (409 `subtareas_abiertas`)."""
    _tarea_o_404(tarea_id)
    subtareas = tt.subtareas_de(tarea_id)
    return _ok({"subtareas": subtareas, "progreso": tt.progreso_subtareas(subtareas)})


@api_bp.route("/tareas-outlook/<int:tarea_id>/subtareas", methods=["POST"])
@token_required
def crear_subtarea_de_la_tarea(tarea_id: int):
    """Cuerpo: `{"asunto": "Pedir el certificado", "fecha_vencimiento": "2026-10-30", "asignada_a": 7}`. Hereda el cliente y el proyecto del padre."""
    _tarea_o_404(tarea_id)
    datos = _body()
    try:
        nueva = tt.crear_subtarea(g.usuario_id, tarea_id, datos.get("asunto"), datos.get("fecha_vencimiento"), _int(datos.get("asignada_a")))
    except tt.TransicionInvalida as e:
        return _err(str(e), _STATUS.get(e.codigo, 400), e.codigo, e.campo)
    return _ok(_dict(db.obtener_tarea_outlook_visible(g.usuario_id, nueva)), 201)


def _int(valor):
    try:
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


# --- Adjuntos -------------------------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>/adjuntos", methods=["GET"])
@token_required
def adjuntos_de_la_tarea(tarea_id: int):
    """Metadatos de los archivos adjuntos (sin el contenido)."""
    _tarea_o_404(tarea_id)
    return _ok(tt.listar_adjuntos(tarea_id))


@api_bp.route("/tareas-outlook/<int:tarea_id>/adjuntos", methods=["POST"])
@token_required
def subir_adjuntos_de_la_tarea(tarea_id: int):
    """Multipart, uno o varios `adjunto`. PDF, imágenes, texto, CSV y documentos de Office o LibreOffice; 15 MB cada uno y 20 por tarea. Devuelve el resultado por archivo
    (los válidos quedan adjuntos aunque otro falle). Nunca se guardan claves privadas ni .p12/.pfx."""
    _tarea_o_404(tarea_id)
    archivos = [f for f in request.files.getlist("adjunto") if f and f.filename]
    if not archivos:
        return _err("Adjunta al menos un archivo en el campo «adjunto» (multipart).", 400, "sin_archivos", "adjunto")
    resultados = []
    for f in archivos:
        try:
            resultados.append({"archivo": f.filename, "ok": True, "id": tt.subir_adjunto(g.usuario_id, tarea_id, f.filename, f.read(tt.MAX_ADJUNTO_BYTES + 1))})
        except tt.TransicionInvalida as e:
            resultados.append({"archivo": f.filename, "ok": False, "codigo": e.codigo, "error": str(e)})
    return _ok(resultados, 201 if any(r["ok"] for r in resultados) else 400)


@api_bp.route("/tareas-outlook/adjuntos/<int:adjunto_id>", methods=["GET"])
@token_required
def descargar_adjunto_de_tarea(adjunto_id: int):
    """Descarga el archivo (`?ver=1` lo muestra en línea solo si es una imagen)."""
    return respuesta_de_adjunto(tt.leer_adjunto(g.usuario_id, adjunto_id), request.args.get("ver") == "1")


@api_bp.route("/tareas-outlook/adjuntos/<int:adjunto_id>", methods=["DELETE"])
@token_required
def eliminar_adjunto_de_tarea(adjunto_id: int):
    if not tt.eliminar_adjunto(g.usuario_id, adjunto_id):
        abort(404, "Adjunto no encontrado.")
    return _ok()


def respuesta_de_adjunto(adjunto, en_linea: bool = False):
    """La respuesta de descarga, igual para la web y la API: el tipo lo fija el servidor, `nosniff` y una CSP que impide ejecutar nada del archivo."""
    if adjunto is None:
        abort(404, "Adjunto no encontrado.")
    en_linea = en_linea and adjunto["imagen"]
    r = Response(adjunto["contenido"], mimetype=adjunto["tipo_mime"])
    nombre = adjunto["nombre_archivo"].replace('"', "").replace("\r", "").replace("\n", "")
    r.headers["Content-Disposition"] = f'{"inline" if en_linea else "attachment"}; filename="{nombre}"'
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    r.headers["Cache-Control"] = "private, no-store"
    return r


# --- Informe ----------------------------------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/informe", methods=["GET"])
@token_required
def informe_de_tareas():
    """Abiertas, vencidas y completadas por persona y por cliente, tasa en plazo, tiempo medio de cierre, bloqueos y lo que se acerca. Solo las tareas que puedes ver.
    `desde`/`hasta` (AAAA-MM-DD, por defecto los últimos 30 días, máximo 366) acotan lo histórico; `dias_proximos` (1-90) lo que se acerca. Lo de «ahora» no depende de la ventana."""
    from . import informes_tareas
    try:
        return _ok(informes_tareas.informe(g.tenant_id, g.usuario_id, request.args.get("desde"), request.args.get("hasta"), request.args.get("dias_proximos", type=int) or 14))
    except ValueError as e:
        return _err(str(e), 400, "ventana_invalida")


# --- Revisión (aprobación) ------------------------------------------------------------------------------------------------

def _revision_json(tarea_id: int) -> dict:
    return {"pendiente": tt.revision_pendiente(tarea_id), "historial": tt.historial_de_revisiones(tarea_id)}


@api_bp.route("/tareas-outlook/<int:tarea_id>/revision", methods=["GET"])
@token_required
def revision_de_la_tarea(tarea_id: int):
    """La revisión pendiente (si la hay) y las últimas resueltas."""
    _tarea_o_404(tarea_id)
    return _ok(_revision_json(tarea_id))


@api_bp.route("/tareas-outlook/<int:tarea_id>/revision", methods=["POST"])
@token_required
def pedir_revision_de_la_tarea(tarea_id: int):
    """Cuerpo: `{"revisor_id": 7, "nota": "Mira el cálculo del IVA"}` o, con varias personas, `{"revisor_ids": [7, 9], "modo": "todos", "nota": "…"}` (hasta cinco). Tiene que revisarla otra
    persona del despacho. `modo`: `todos` (por defecto, aprueban todos) o `cualquiera` (basta uno); una petición de cambios, de quien sea, detiene la revisión. Mientras esté pendiente la tarea
    no se puede completar (409 `revision_pendiente`)."""
    _tarea_o_404(tarea_id)
    datos = _body()
    try:
        tt.solicitar_revision(g.usuario_id, tarea_id, datos.get("revisor_ids") if datos.get("revisor_ids") is not None else datos.get("revisor_id"), datos.get("nota"), datos.get("modo") or "todos")
    except tt.TransicionInvalida as e:
        return _err(str(e), _STATUS.get(e.codigo, 400), e.codigo, e.campo)
    return _ok(_revision_json(tarea_id), 201)


@api_bp.route("/tareas-outlook/<int:tarea_id>/revision/resolver", methods=["POST"])
@token_required
def resolver_revision_de_la_tarea(tarea_id: int):
    """El voto de un revisor designado (cada uno vota una vez). Cuerpo: `{"decision": "aprobar" | "cambios", "nota": "…"}`; pedir cambios exige nota, detiene la revisión y devuelve la tarea a
    «en progreso». Aprobar no la completa; con varios revisores en modo `todos`, la revisión sigue pendiente hasta que aprueben todos."""
    _tarea_o_404(tarea_id)
    datos = _body()
    try:
        tt.resolver_revision(g.usuario_id, tarea_id, (datos.get("decision") or "").strip(), datos.get("nota"))
    except tt.TransicionInvalida as e:
        return _err(str(e), _STATUS.get(e.codigo, 400), e.codigo, e.campo)
    return _ok(_revision_json(tarea_id))


@api_bp.route("/tareas-outlook/<int:tarea_id>/revision/cancelar", methods=["POST"])
@token_required
def cancelar_revision_de_la_tarea(tarea_id: int):
    _tarea_o_404(tarea_id)
    if not tt.cancelar_revision(g.usuario_id, tarea_id):
        return _err("No hay una revisión pendiente que puedas cancelar.", 404, "no_encontrada")
    return _ok(_revision_json(tarea_id))


# --- Visibilidad para el cliente (portal) ---------------------------------------------------------------------------------

@api_bp.route("/tareas-outlook/<int:tarea_id>/visible-cliente", methods=["PUT"])
@token_required
def fijar_visible_cliente_de_la_tarea(tarea_id: int):
    """Cuerpo: `{"visible": true}`. Enseña (o deja de enseñar) la tarea al cliente al que está vinculada, en su portal, solo de lectura: asunto, estado y fecha límite.
    Por defecto ninguna tarea es visible. Hace falta que la tarea tenga cliente (409 `sin_cliente`)."""
    _tarea_o_404(tarea_id)
    datos = _body()
    if not isinstance(datos.get("visible"), bool):
        return _err("visible tiene que ser true o false.", 400, "visible_invalido", "visible")
    try:
        tt.fijar_visible_cliente(g.usuario_id, tarea_id, datos["visible"])
    except tt.TransicionInvalida as e:
        return _err(str(e), _STATUS.get(e.codigo, 400), e.codigo, e.campo)
    return _ok({"visible_cliente": datos["visible"]})
