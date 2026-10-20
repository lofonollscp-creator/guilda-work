"""API del trabajo con tareas (Fase 1 del plan, docs/guilda-work-implementation-plan.md): transiciones con motivo y versión, clientes vinculados a una tarea y tareas de un
cliente con contadores. Capa fina sobre `app/tareas_trabajo.py`; mismo token, mismo formato de error y mismos permisos que el resto de la API de tareas. Todo aditivo."""
from __future__ import annotations

from flask import abort, g, jsonify, request

from . import db, tareas_trabajo as tt
from .auth import token_required
from .rutas_api import _body, _dict, _err, _exigir_tenant_api, _ok, _ok_paginado, api_bp

_STATUS = {"no_encontrada": 404, "sin_permiso": 403, "tarea_bloqueada": 409}


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
