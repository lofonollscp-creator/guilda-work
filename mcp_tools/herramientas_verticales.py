"""Herramientas MCP (y del asistente de IA) de los módulos de negocio: Gabinete de abogados e Inmobiliaria. **Solo lectura**, con las mismas reglas de visibilidad que las pantallas
(un expediente confidencial al que la persona no tiene acceso no aparece) y solo si el módulo está activo en el despacho. Las dos primeras familias de herramientas del núcleo
(`listar_expedientes_despacho`, `resumen_expediente_despacho`…) ya sirven para listar asuntos y operaciones; estas añaden lo propio de cada módulo."""
from __future__ import annotations

from datetime import date, timedelta

import mcp_tools as _mt


def _exigir_modulo(vertical_id: str) -> int:
    from app import verticales
    t = _mt._tenant_id_actual()
    if not verticales.esta_activo(t, vertical_id):
        raise ValueError({"abogados": "El módulo Gabinete de abogados no está activo en tu despacho.", "inmobiliaria": "El módulo Inmobiliaria no está activo en tu despacho."}[vertical_id])
    return t


def _euros(centimos) -> str | None:
    return None if centimos is None else f"{centimos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


# --- Gabinete de abogados ------------------------------------------------------------------------------------------------------------------------------

def abogados_provision_asunto(expediente_id: int) -> dict:
    """La cuenta del cliente en un asunto: provisiones recibidas, suplidos, honorarios cargados, devoluciones y saldo (negativo = el despacho ha adelantado dinero), con los últimos movimientos."""
    from app import abogados, nucleo
    t = _mt._exigir_modulo("abogados")
    u, sup = _mt._uid(), _mt._supervisor_actual()
    exp = nucleo.obtener_expediente(t, expediente_id, u, sup)
    if exp is None:
        raise ValueError(f"No existe el asunto #{expediente_id} en tu despacho, o no tienes acceso.")
    s = abogados.saldo(t, expediente_id)
    minima = abogados.obtener_ajustes(t).get("provision_minima_centimos") or 0
    return {"expediente": exp["titulo"], **{k: _mt._euros(v) for k, v in s.items()}, "saldo_centimos": s["saldo"], "provision_minima": _mt._euros(minima) if minima else None,
            "por_debajo_de_la_minima": bool(minima and s["saldo"] < minima),
            "ultimos_movimientos": [{"fecha": m["fecha"], "tipo": m["tipo"], "importe": _mt._euros(m["importe_centimos"]), "concepto": m["concepto"]} for m in abogados.listar_movimientos(t, u, expediente_id, sup)[:10]]}


def abogados_partes_asunto(expediente_id: int) -> list[dict]:
    """Las partes de un asunto (cliente, contraparte, letrados, procuradores…) con su rol y NIF."""
    from app import abogados
    t = _mt._exigir_modulo("abogados")
    partes = abogados.listar_partes(t, _mt._uid(), expediente_id, _mt._supervisor_actual())
    return [_mt._campos(p, ("id", "rol", "nombre", "nif", "notas")) for p in partes]


def abogados_agenda_vistas(dias: int = 30, expediente_id: int | None = None) -> list[dict]:
    """Los señalamientos (vistas, juicios, comparecencias) previstos en los próximos `dias` días, por fecha."""
    from app import abogados
    t = _mt._exigir_modulo("abogados")
    hoy = date.today()
    filas = abogados.listar_vistas(t, _mt._uid(), _mt._supervisor_actual(), expediente_id=expediente_id, desde=hoy.isoformat(), hasta=(hoy + timedelta(days=max(1, min(int(dias), 365)))).isoformat(), estado="prevista", limite=100)
    return [_mt._campos(v, ("id", "expediente_id", "fecha_hora", "tipo", "lugar", "notas")) | {"asunto": v["titulo"] if "titulo" in v.keys() else None} for v in filas]


def abogados_comprobar_conflicto(nombre: str, nif: str | None = None, como: str = "cliente") -> dict:
    """¿Hay conflicto de intereses? `como="cliente"`: ¿esta persona o empresa fue contraparte (o su letrado o procurador) en algún asunto del despacho? `como="contraparte"`: ¿ya es cliente?
    Coincide por NIF o por nombre. De un asunto confidencial que no puedes ver solo se avisa de que existe."""
    from app import abogados
    t = _mt._exigir_modulo("abogados")
    if como not in ("cliente", "contraparte"):
        raise ValueError('`como` debe ser "cliente" o "contraparte".')
    hallazgos = abogados.revisar_conflictos(t, _mt._uid(), nombre, nif, como, _mt._supervisor_actual())
    return {"hay_conflicto": bool(hallazgos), "hallazgos": hallazgos}


# --- Inmobiliaria ----------------------------------------------------------------------------------------------------------------------------------------

def inmobiliaria_listar_inmuebles(operacion: str | None = None, estado: str | None = None, municipio: str | None = None, q: str | None = None, solo_activos: bool = True, limite: int = 25) -> list[dict]:
    """Los inmuebles de la agencia (cada uno es una operación de venta o alquiler), con su fase, precio, propietario y visitas realizadas. `operacion`: venta o alquiler."""
    from app import inmobiliaria
    t = _mt._exigir_modulo("inmobiliaria")
    filas = inmobiliaria.listar_inmuebles(t, _mt._uid(), _mt._supervisor_actual(), operacion=operacion, estado=estado, municipio=municipio, q=q, solo_activos=bool(solo_activos), limite=max(1, min(int(limite), 100)))
    return [_mt._campos(i, ("id", "expediente_id", "direccion", "municipio", "referencia", "tipo", "estado", "superficie_m2", "habitaciones", "propietario_nombre", "visitas_realizadas"))
            | {"precio": _mt._euros(i["precio_centimos"])} for i in filas]


def inmobiliaria_cruces_de_demanda(demanda_id: int, minimo: int = 50) -> list[dict]:
    """Los inmuebles en comercialización que mejor encajan con una demanda (comprador o inquilino), de 0 a 100 puntos, con el porqué de cada puntuación."""
    from app import inmobiliaria
    t = _mt._exigir_modulo("inmobiliaria")
    cruces = inmobiliaria.cruces_para_demanda(t, _mt._uid(), demanda_id, _mt._supervisor_actual(), minimo=max(0, min(int(minimo), 100)))
    return [{"puntos": c["puntos"], "motivos": [f"{r['criterio']}: {r['puntos']}/{r['maximo']} — {r['detalle']}" for r in c["razones"]], "faltan": c["faltan"], "inmueble": _mt._campos(c["inmueble"], ("id", "direccion", "municipio", "tipo", "estado")) | {"precio": _mt._euros(c["inmueble"]["precio_centimos"])}}
            for c in cruces[:15]]


def inmobiliaria_agenda_visitas(dias: int = 7) -> list[dict]:
    """Las visitas previstas desde hoy en los próximos `dias` días, con el inmueble, quién visita y qué agente va."""
    from app import inmobiliaria
    t = _mt._exigir_modulo("inmobiliaria")
    hoy = date.today()
    filas = inmobiliaria.listar_visitas(t, _mt._uid(), _mt._supervisor_actual(), desde=hoy.isoformat(), hasta=(hoy + timedelta(days=max(1, min(int(dias), 60)))).isoformat(), estado="prevista", limite=100)
    return [_mt._campos(v, ("id", "inmueble_id", "fecha_hora", "direccion", "municipio", "visitante_nombre", "agente_nombre")) for v in filas]


def inmobiliaria_resumen() -> dict:
    """El panel de la agencia de un vistazo: inmuebles activos por fase, visitas de hoy y de la semana, ofertas por responder, demandas activas e inmuebles sin movimiento en 14 días."""
    from app import inmobiliaria
    t = _mt._exigir_modulo("inmobiliaria")
    r = inmobiliaria.resumen(t, _mt._uid(), _mt._supervisor_actual())
    return {"inmuebles_activos": r["n_activos"], "por_fase": r["por_estado"], "demandas_activas": r["demandas"],
            "visitas_hoy": [_mt._campos(v, ("fecha_hora", "direccion", "visitante_nombre", "agente_nombre")) for v in r["visitas_hoy"]],
            "visitas_semana": len(r["visitas_semana"]), "ofertas_abiertas": [_mt._campos(o, ("id", "inmueble_id", "importe_centimos", "estado", "oferente")) for o in r["ofertas"]],
            "sin_movimiento_14_dias": [_mt._campos(i, ("id", "direccion", "municipio", "estado")) for i in r["sin_movimiento"]]}
