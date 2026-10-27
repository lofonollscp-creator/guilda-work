"""API REST de Gabinete de abogados e Inmobiliaria (áreas `abogados` e `inmobiliaria`) y comprobación de certificados. Consultas de solo lectura más los mensajes del enlace público
(leer y responder). Mismas reglas que la web: despacho propio, módulo activo y expedientes confidenciales solo para quien participa o supervisa (si no, 404)."""
from __future__ import annotations

from flask import g, request
from flask_babel import gettext

from . import consultas_verticales as cv
from . import db
from .auth import token_required
from .rutas_api import _body, _err, _exigir_tenant_api, _ok, api_bp


def _supervisor() -> bool:
    return bool(db.es_admin(g.usuario_id) or db.es_supervisor_tenant(g.usuario_id))


def _consulta(funcion, *args, **kw):
    """Ejecuta una consulta de `consultas_verticales`: despacho propio, y los `ValueError` (módulo inactivo, objeto inexistente o sin acceso, parámetro no válido) como 404/400."""
    error = _exigir_tenant_api()
    if error:
        return error
    try:
        return _ok(funcion(g.tenant_id, g.usuario_id, _supervisor(), *args, **kw))
    except ValueError as e:
        texto = str(e)
        if texto.startswith("No existe") or "no está activo" in texto or "no encontrado" in texto.lower():
            return _err(texto, 404, "no_encontrado")
        return _err(texto, 400, "peticion_invalida")


# --- Gabinete de abogados ------------------------------------------------------------------------------------------------------------------------------
@api_bp.route("/abogados/expedientes/<int:expediente_id>/provision", methods=["GET"])
@token_required
def provision_asunto_api(expediente_id: int):
    """La cuenta del cliente en un asunto: provisiones, suplidos, honorarios, devoluciones y saldo (en céntimos y con formato), si está por debajo de la provisión mínima y los últimos movimientos."""
    return _consulta(cv.provision_asunto, expediente_id)


@api_bp.route("/abogados/expedientes/<int:expediente_id>/partes", methods=["GET"])
@token_required
def partes_asunto_api(expediente_id: int):
    """Partes del asunto (cliente, contraparte, letrados, procuradores…) con rol y NIF."""
    return _consulta(cv.partes_asunto, expediente_id)


@api_bp.route("/abogados/vistas", methods=["GET"])
@token_required
def agenda_vistas_api():
    """Señalamientos previstos (vistas, juicios, comparecencias) en los próximos `dias` días (30 por defecto, máximo 365); `expediente_id` limita a un asunto."""
    return _consulta(cv.agenda_vistas, request.args.get("dias", 30, type=int), request.args.get("expediente_id", type=int))


@api_bp.route("/abogados/conflictos", methods=["GET"])
@token_required
def comprobar_conflicto_api():
    """Conflicto de intereses de una persona o empresa (`nombre`, `nif` opcional). `como=cliente` (por defecto): ¿fue contraparte, letrado o procurador en algún asunto? `como=contraparte`: ¿ya es cliente?
    De un asunto confidencial que no puedes ver solo se avisa de que existe."""
    if not (request.args.get("nombre") or "").strip():
        return _err(gettext("Indica el nombre."), 400, "peticion_invalida", "nombre")
    return _consulta(cv.comprobar_conflicto, request.args["nombre"], request.args.get("nif") or None, request.args.get("como") or "cliente")


# --- Inmobiliaria ----------------------------------------------------------------------------------------------------------------------------------------
@api_bp.route("/inmobiliaria/inmuebles", methods=["GET"])
@token_required
def listar_inmuebles_api():
    """Inmuebles de la agencia (cada uno es una operación de venta o alquiler). Filtros: `operacion` (`venta`, `alquiler`), `estado` (fase), `municipio`, `q`, `solo_activos` (por defecto `true`) y `limite` (100 como máximo)."""
    return _consulta(cv.listar_inmuebles, request.args.get("operacion") or None, request.args.get("estado") or None, request.args.get("municipio") or None, request.args.get("q") or None,
                     request.args.get("solo_activos", "true").lower() not in ("0", "false", "no"), request.args.get("limite", 25, type=int))


@api_bp.route("/inmobiliaria/demandas/<int:demanda_id>/cruces", methods=["GET"])
@token_required
def cruces_demanda_api(demanda_id: int):
    """Inmuebles en comercialización que encajan con la demanda, de 0 a 100 puntos (`minimo`, 50 por defecto), con el motivo de cada puntuación."""
    return _consulta(cv.cruces_de_demanda, demanda_id, request.args.get("minimo", 50, type=int))


@api_bp.route("/inmobiliaria/visitas", methods=["GET"])
@token_required
def agenda_visitas_api():
    """Visitas previstas desde hoy en los próximos `dias` días (7 por defecto, máximo 60)."""
    return _consulta(cv.agenda_visitas, request.args.get("dias", 7, type=int))


@api_bp.route("/inmobiliaria/resumen", methods=["GET"])
@token_required
def resumen_agencia_api():
    """Panel de la agencia: inmuebles activos por fase, visitas de hoy y de la semana, ofertas abiertas, demandas activas e inmuebles sin movimiento en 14 días."""
    return _consulta(cv.resumen_agencia)


# --- Mensajes del enlace público ------------------------------------------------------------------------------------------------------------------------
@api_bp.route("/abogados/expedientes/<int:expediente_id>/mensajes", methods=["GET"])
@token_required
def mensajes_asunto_api(expediente_id: int):
    """Mensajes que el cliente ha escrito desde su enlace público y las respuestas del despacho (sin marcarlos como leídos)."""
    return _consulta(cv.mensajes_del_asunto, "abogados", expediente_id)


@api_bp.route("/inmobiliaria/inmuebles/<int:expediente_id>/mensajes", methods=["GET"])
@token_required
def mensajes_inmueble_api(expediente_id: int):
    """Mensajes que el propietario ha escrito desde su enlace público y las respuestas de la agencia (sin marcarlos como leídos). `expediente_id` es el de la operación del inmueble."""
    return _consulta(cv.mensajes_del_asunto, "inmobiliaria", expediente_id)


@api_bp.route("/abogados/expedientes/<int:expediente_id>/mensajes", methods=["POST"])
@token_required
def responder_asunto_api(expediente_id: int):
    """Contesta al cliente en el hilo de su enlace público (`texto`, hasta 2000 caracteres). 400 si no hay un enlace activo que admita mensajes."""
    d = _body()
    return _consulta(cv.responder_mensaje, "abogados", expediente_id, d.get("texto") or "")


@api_bp.route("/inmobiliaria/inmuebles/<int:expediente_id>/mensajes", methods=["POST"])
@token_required
def responder_inmueble_api(expediente_id: int):
    """Contesta al propietario en el hilo de su enlace público (`texto`, hasta 2000 caracteres). 400 si no hay un enlace activo que admita mensajes."""
    d = _body()
    return _consulta(cv.responder_mensaje, "inmobiliaria", expediente_id, d.get("texto") or "")
