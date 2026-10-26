"""API REST de Guilda Fiscal (área de token `guilda_fiscal`, bajo `/api/v1/guilda-fiscal`): SOLO CONSULTA y simulación (ver app/consultas_fiscal.py). Aprobar apuntes, congelar periodos, revisar, exportar y
anotar presentaciones lo hacen personas desde las pantallas: ni los tokens ni la IA aprueban."""
from __future__ import annotations

from flask import g, request

from . import consultas_fiscal as cf
from .auth import token_required
from .rutas_api import _err, _exigir_tenant_api, _ok, api_bp


def _consulta(funcion, *args, **kw):
    error = _exigir_tenant_api()
    if error:
        return error
    try:
        return _ok(funcion(g.tenant_id, g.usuario_id, *args, **kw))
    except ValueError as e:
        codigo = getattr(e, "codigo", None)
        if codigo == "no_encontrado" or str(e).startswith("No existe"):
            return _err(str(e), 404, "no_encontrado")
        if codigo == "prohibido":
            return _err(str(e), 403, "prohibido")
        return _err(str(e), 400, "peticion_invalida")


@api_bp.route("/guilda-fiscal/titulares", methods=["GET"])
@token_required
def titulares_guilda_fiscal_api():
    """Los titulares que ves en Guilda Fiscal, con su perfil, los apuntes del año y la última declaración."""
    return _consulta(cf.titulares)


@api_bp.route("/guilda-fiscal/titulares/<int:cliente_fiscal_id>/perfil", methods=["GET"])
@token_required
def perfil_guilda_fiscal_api(cliente_fiscal_id: int):
    """El perfil fiscal vigente de un titular (`fecha`, opcional, AAAA-MM-DD) y su historial de vigencias."""
    return _consulta(cf.perfil, cliente_fiscal_id, request.args.get("fecha") or None)


@api_bp.route("/guilda-fiscal/titulares/<int:cliente_fiscal_id>/apuntes", methods=["GET"])
@token_required
def apuntes_guilda_fiscal_api(cliente_fiscal_id: int):
    """Los apuntes aprobados de un titular (`ejercicio`, opcional): los que cuentan para el 303."""
    return _consulta(cf.apuntes, cliente_fiscal_id, request.args.get("ejercicio", type=int))


@api_bp.route("/guilda-fiscal/titulares/<int:cliente_fiscal_id>/comprobacion", methods=["GET"])
@token_required
def comprobacion_guilda_fiscal_api(cliente_fiscal_id: int):
    """Comprueba los apuntes de un ejercicio (`ejercicio`, obligatorio) con las reglas que aplica la AEAT al importar libros."""
    return _consulta(cf.comprobar, cliente_fiscal_id, request.args.get("ejercicio", type=int) or 0)


@api_bp.route("/guilda-fiscal/titulares/<int:cliente_fiscal_id>/simulacion-303", methods=["GET"])
@token_required
def simulacion_guilda_fiscal_api(cliente_fiscal_id: int):
    """Simula el modelo 303 de un periodo (`ejercicio` y `periodo`: 1T…4T o 01…12) con los apuntes aprobados. No guarda nada y no es una declaración."""
    return _consulta(cf.simular_303, cliente_fiscal_id, request.args.get("ejercicio", type=int) or 0, request.args.get("periodo") or "")


@api_bp.route("/guilda-fiscal/titulares/<int:cliente_fiscal_id>/declaraciones", methods=["GET"])
@token_required
def declaraciones_guilda_fiscal_api(cliente_fiscal_id: int):
    """Las declaraciones del 303 de un titular, con su estado y resultado."""
    return _consulta(cf.declaraciones, cliente_fiscal_id)


@api_bp.route("/guilda-fiscal/declaraciones/<int:declaracion_id>", methods=["GET"])
@token_required
def declaracion_guilda_fiscal_api(declaracion_id: int):
    """Una declaración con sus casillas, de qué apuntes sale cada una y sus bloqueos."""
    return _consulta(cf.declaracion, declaracion_id)


@api_bp.route("/guilda-fiscal/facturas/<int:factura_id>/propuesta", methods=["GET"])
@token_required
def propuesta_guilda_fiscal_api(factura_id: int):
    """Cómo se registraría una factura anotada como apuntes fiscales. Solo una propuesta: no guarda nada."""
    return _consulta(cf.proponer, factura_id)
