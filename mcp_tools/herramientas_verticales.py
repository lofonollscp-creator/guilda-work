"""Herramientas MCP (y del asistente de IA) de los módulos de negocio: Gabinete de abogados e Inmobiliaria. Las consultas son de **solo lectura**, con las mismas reglas de visibilidad que las pantallas
(un expediente confidencial al que la persona no tiene acceso no aparece) y solo si el módulo está activo en el despacho; la lógica está en app/consultas_verticales.py, que comparte con la API REST.
Las dos primeras familias de herramientas del núcleo (`listar_expedientes_despacho`, `resumen_expediente_despacho`…) ya sirven para listar asuntos y operaciones; estas añaden lo propio de cada módulo."""
from __future__ import annotations

import mcp_tools as _mt


def _ctx() -> tuple[int, int, bool]:
    return _mt._tenant_id_actual(), _mt._uid(), _mt._supervisor_actual()


def _consultas():
    from app import consultas_verticales
    return consultas_verticales


def abogados_provision_asunto(expediente_id: int) -> dict:
    """La cuenta del cliente en un asunto: provisiones recibidas, suplidos, honorarios cargados, devoluciones y saldo (negativo = el despacho ha adelantado dinero), con los últimos movimientos."""
    return _mt._consultas().provision_asunto(*_mt._ctx(), expediente_id)


def abogados_partes_asunto(expediente_id: int) -> list[dict]:
    """Las partes de un asunto (cliente, contraparte, letrados, procuradores…) con su rol y NIF."""
    return _mt._consultas().partes_asunto(*_mt._ctx(), expediente_id)


def abogados_agenda_vistas(dias: int = 30, expediente_id: int | None = None) -> list[dict]:
    """Los señalamientos (vistas, juicios, comparecencias) previstos en los próximos `dias` días, por fecha."""
    return _mt._consultas().agenda_vistas(*_mt._ctx(), dias, expediente_id)


def abogados_comprobar_conflicto(nombre: str, nif: str | None = None, como: str = "cliente") -> dict:
    """¿Hay conflicto de intereses? `como="cliente"`: ¿esta persona o empresa fue contraparte (o su letrado o procurador) en algún asunto del despacho? `como="contraparte"`: ¿ya es cliente?
    Coincide por NIF o por nombre. De un asunto confidencial que no puedes ver solo se avisa de que existe."""
    return _mt._consultas().comprobar_conflicto(*_mt._ctx(), nombre, nif, como)


def inmobiliaria_listar_inmuebles(operacion: str | None = None, estado: str | None = None, municipio: str | None = None, q: str | None = None, solo_activos: bool = True, limite: int = 25) -> list[dict]:
    """Los inmuebles de la agencia (cada uno es una operación de venta o alquiler), con su fase, precio, propietario y visitas realizadas. `operacion`: venta o alquiler."""
    return _mt._consultas().listar_inmuebles(*_mt._ctx(), operacion, estado, municipio, q, solo_activos, limite)


def inmobiliaria_cruces_de_demanda(demanda_id: int, minimo: int = 50) -> list[dict]:
    """Los inmuebles en comercialización que mejor encajan con una demanda (comprador o inquilino), de 0 a 100 puntos, con el porqué de cada puntuación."""
    return _mt._consultas().cruces_de_demanda(*_mt._ctx(), demanda_id, minimo)


def inmobiliaria_agenda_visitas(dias: int = 7) -> list[dict]:
    """Las visitas previstas desde hoy en los próximos `dias` días, con el inmueble, quién visita y qué agente va."""
    return _mt._consultas().agenda_visitas(*_mt._ctx(), dias)


def inmobiliaria_resumen() -> dict:
    """El panel de la agencia de un vistazo: inmuebles activos por fase, visitas de hoy y de la semana, ofertas por responder, demandas activas e inmuebles sin movimiento en 14 días."""
    return _mt._consultas().resumen_agencia(*_mt._ctx())


def mensajes_de_enlace(vertical: str, expediente_id: int) -> dict:
    """Los mensajes que el cliente (gabinete, `vertical="abogados"`) o el propietario (inmobiliaria, `vertical="inmobiliaria"`) han escrito desde su enlace público y las respuestas del despacho.
    No los marca como leídos (eso se hace al abrir el panel). `admite_respuesta` dice si hay un enlace vivo que permita mensajes."""
    if vertical not in ("abogados", "inmobiliaria"):
        raise ValueError('`vertical` debe ser "abogados" o "inmobiliaria".')
    return _mt._consultas().mensajes_del_asunto(*_mt._ctx(), vertical, expediente_id)


def responder_mensaje_de_enlace(vertical: str, expediente_id: int, texto: str) -> dict:
    """Contesta al cliente o propietario en el hilo de su enlace público (hasta 2000 caracteres). Falla si no hay un enlace activo que admita mensajes. Lo verá la persona que tenga el enlace."""
    if vertical not in ("abogados", "inmobiliaria"):
        raise ValueError('`vertical` debe ser "abogados" o "inmobiliaria".')
    return _mt._consultas().responder_mensaje(*_mt._ctx(), vertical, expediente_id, texto)
