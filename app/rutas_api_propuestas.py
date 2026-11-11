"""API: la bandeja de propuestas (W15). `GET /propuestas` lista lo pendiente del despacho activo y `POST /propuestas/<id>/aprobar|rechazar` lo resuelve como la persona del token: aprobar ejecuta la propuesta (crear la tarea,
pedir la documentación, escribir al cliente por el portal…), igual que en la web, y rechazar la silencia durante 30 días. Un token de solo lectura solo puede listar.

Se registra importándola desde `rutas_api_extras.py` (que `main.py` ya carga). Pertenece al área `ia`."""
from flask import g

from . import ia_propuestas
from .auth import token_required
from .rutas_api import _err, _ok, api_bp


def _publica(p: dict) -> dict:
    return {"id": p["id"], "tipo": p["tipo"], "origen": p["origen"], "titulo": p["titulo"], "detalle": p["detalle"], "cliente_id": p["cliente_fiscal_id"], "prioridad": p["prioridad"], "estado": p["estado"], "creada_en": p["creada_en"]}


def _despacho_o_error():
    return None if g.tenant_id is not None else _err("No hay un despacho activo.", 404)


@api_bp.route("/propuestas", methods=["GET"])
@token_required
def listar_propuestas():
    """Las propuestas pendientes del despacho (la IA y las reglas del sistema proponen; una persona aprueba o rechaza), las urgentes primero. Cada una lleva `tipo` (`tarea`, `peticion_portal`, `mensaje_portal`,
    `cuenta_tercero`), `origen`, `titulo`, `detalle`, `cliente_id`, `prioridad` y `creada_en`."""
    if (error := _despacho_o_error()) is not None:
        return error
    return _ok({"propuestas": [_publica(p) for p in ia_propuestas.pendientes(g.tenant_id)]})


def _resolver(propuesta_id: int, aprobar: bool):
    if (error := _despacho_o_error()) is not None:
        return error
    try:
        if aprobar:
            resultado = ia_propuestas.aprobar(g.tenant_id, g.usuario_id, propuesta_id)
        else:
            ia_propuestas.rechazar(g.tenant_id, g.usuario_id, propuesta_id)
            resultado = ""
    except ia_propuestas.ErrorPropuesta as e:
        return _err(str(e), 409 if "resuelta" in str(e) else 404)
    return _ok({"id": propuesta_id, "estado": "aprobada" if aprobar else "rechazada", "resultado": resultado})


@api_bp.route("/propuestas/<int:propuesta_id>/aprobar", methods=["POST"])
@token_required
def aprobar_propuesta(propuesta_id: int):
    """Ejecuta la propuesta como la persona del token y la cierra (409 si ya estaba resuelta). Devuelve `resultado` (p. ej. `tarea:12`)."""
    return _resolver(propuesta_id, True)


@api_bp.route("/propuestas/<int:propuesta_id>/rechazar", methods=["POST"])
@token_required
def rechazar_propuesta(propuesta_id: int):
    """Rechaza la propuesta: no vuelve a salir en 30 días (409 si ya estaba resuelta)."""
    return _resolver(propuesta_id, False)
