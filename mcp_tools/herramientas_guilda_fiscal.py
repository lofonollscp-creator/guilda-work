"""Herramientas MCP (y del asistente de IA) de Guilda Fiscal: SOLO CONSULTA y simulación del modelo 303. La lógica está en app/consultas_fiscal.py, que comparte con la API REST. Nada de aquí aprueba un apunte,
congela un periodo, revisa, exporta ni da una declaración por presentada: eso lo hace una persona (dirección o revisor fiscal) desde las pantallas. Los importes van en euros."""
from __future__ import annotations

import mcp_tools as _mt


def _ctx_gfiscal() -> tuple[int, int]:
    return _mt._tenant_id_actual(), _mt._uid()


def _gfiscal():
    from app import consultas_fiscal
    return consultas_fiscal


def fiscal_listar_titulares() -> list[dict]:
    """Los titulares que ves en Guilda Fiscal, con su perfil fiscal, los apuntes aprobados del año y su última declaración del 303."""
    return _mt._gfiscal().titulares(*_mt._ctx_gfiscal())


def fiscal_ver_perfil(cliente_fiscal_id: int, fecha: str | None = None) -> dict:
    """El perfil fiscal vigente de un titular (en `fecha` AAAA-MM-DD, por defecto hoy) y su historial de vigencias: régimen de IVA, periodicidad, criterio de caja, prorrata…"""
    return _mt._gfiscal().perfil(*_mt._ctx_gfiscal(), cliente_fiscal_id, fecha)


def fiscal_listar_apuntes(cliente_fiscal_id: int, ejercicio: int | None = None) -> list[dict]:
    """Los apuntes APROBADOS de un titular (los únicos que cuentan para el 303): libro, tipo de factura, clave, base, tipo de IVA y cuota."""
    return _mt._gfiscal().apuntes(*_mt._ctx_gfiscal(), cliente_fiscal_id, ejercicio)


def fiscal_comprobar_apuntes(cliente_fiscal_id: int, ejercicio: int) -> dict:
    """Pasa los apuntes aprobados de un ejercicio por las mismas reglas que aplica la AEAT al importar libros registro: errores (la AEAT los rechazaría) y avisos. No cambia nada."""
    return _mt._gfiscal().comprobar(*_mt._ctx_gfiscal(), cliente_fiscal_id, ejercicio)


def fiscal_proponer_apuntes_de_factura(factura_id: int) -> list[dict]:
    """Cómo se registraría como apuntes fiscales una factura ya anotada en Facturas para contabilizar. Es solo una propuesta que no se guarda: la aprobación la hace una persona en la pantalla."""
    return _mt._gfiscal().proponer(*_mt._ctx_gfiscal(), factura_id)


def fiscal_simular_303(cliente_fiscal_id: int, ejercicio: int, periodo: str) -> dict:
    """SIMULA el modelo 303 de un periodo (`1T`…`4T` o `01`…`12`) con los apuntes aprobados y el perfil vigente: casillas y resultado, o los motivos del bloqueo si el caso no está soportado. No guarda nada
    y no es una declaración: para declarar, la dirección o el revisor fiscal congela el periodo desde la pantalla."""
    return _mt._gfiscal().simular_303(*_mt._ctx_gfiscal(), cliente_fiscal_id, ejercicio, periodo)


def fiscal_listar_declaraciones(cliente_fiscal_id: int) -> list[dict]:
    """Las declaraciones del modelo 303 de un titular con su estado (borrador, revisada, exportada, presentada, anulada) y resultado."""
    return _mt._gfiscal().declaraciones(*_mt._ctx_gfiscal(), cliente_fiscal_id)


def fiscal_ver_declaracion(declaracion_id: int) -> dict:
    """Una declaración del 303: casillas, de qué apuntes sale cada una, bloqueos del cálculo, versiones del motor y del diseño, y qué ficheros se generaron."""
    return _mt._gfiscal().declaracion(*_mt._ctx_gfiscal(), declaracion_id)
