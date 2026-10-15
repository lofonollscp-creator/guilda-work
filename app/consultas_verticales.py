"""Consultas de solo lectura de Gabinete de abogados e Inmobiliaria que comparten el MCP, el asistente de IA y la API REST (área `abogados` / `inmobiliaria`).
Reciben el despacho, la persona y si supervisa; respetan las mismas reglas de visibilidad que las pantallas (un expediente confidencial al que la persona no tiene acceso no aparece)
y exigen el módulo activo (`ValueError` si no lo está o si el objeto no existe)."""
from __future__ import annotations

from datetime import date, timedelta

from . import abogados, inmobiliaria, mensajes_enlace, nucleo, verticales

_MODULO = {"abogados": "El módulo Gabinete de abogados no está activo en tu despacho.", "inmobiliaria": "El módulo Inmobiliaria no está activo en tu despacho."}


def exigir_modulo(tenant_id: int, vertical_id: str) -> None:
    if not verticales.esta_activo(tenant_id, vertical_id):
        raise ValueError(_MODULO[vertical_id])


def euros(centimos) -> str | None:
    return None if centimos is None else f"{centimos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _campos(fila, claves) -> dict:
    d = dict(fila)
    return {k: d.get(k) for k in claves}


def _asunto(t: int, u: int, sup: bool, expediente_id: int, vertical_id: str) -> dict:
    exigir_modulo(t, vertical_id)
    exp = nucleo.obtener_expediente(t, int(expediente_id), u, sup)
    if exp is None:
        raise ValueError(f"No existe el expediente #{expediente_id} en tu despacho, o no tienes acceso.")
    return exp


# --- Gabinete de abogados ------------------------------------------------------------------------------------------------------------------------------
def provision_asunto(t, u, sup, expediente_id) -> dict:
    exp = _asunto(t, u, sup, expediente_id, "abogados")
    s = abogados.saldo(t, exp["id"])
    minima = abogados.obtener_ajustes(t).get("provision_minima_centimos") or 0
    return {"expediente": exp["titulo"], **{k: euros(v) for k, v in s.items()}, "saldo_centimos": s["saldo"], "provision_minima": euros(minima) if minima else None,
            "por_debajo_de_la_minima": bool(minima and s["saldo"] < minima),
            "ultimos_movimientos": [{"fecha": m["fecha"], "tipo": m["tipo"], "importe": euros(m["importe_centimos"]), "concepto": m["concepto"]} for m in abogados.listar_movimientos(t, u, exp["id"], sup)[:10]]}


def partes_asunto(t, u, sup, expediente_id) -> list[dict]:
    exigir_modulo(t, "abogados")
    return [_campos(p, ("id", "rol", "nombre", "nif", "notas")) for p in abogados.listar_partes(t, u, int(expediente_id), sup)]


def agenda_vistas(t, u, sup, dias=30, expediente_id=None) -> list[dict]:
    exigir_modulo(t, "abogados")
    hoy = date.today()
    filas = abogados.listar_vistas(t, u, sup, expediente_id=expediente_id, desde=hoy.isoformat(), hasta=(hoy + timedelta(days=max(1, min(int(dias), 365)))).isoformat(), estado="prevista", limite=100)
    return [_campos(v, ("id", "expediente_id", "fecha_hora", "tipo", "lugar", "notas")) | {"asunto": v["titulo"] if "titulo" in v.keys() else None} for v in filas]


def comprobar_conflicto(t, u, sup, nombre, nif=None, como="cliente") -> dict:
    exigir_modulo(t, "abogados")
    if como not in ("cliente", "contraparte"):
        raise ValueError('`como` debe ser "cliente" o "contraparte".')
    hallazgos = abogados.revisar_conflictos(t, u, nombre, nif, como, sup)
    return {"hay_conflicto": bool(hallazgos), "hallazgos": hallazgos}


# --- Inmobiliaria ----------------------------------------------------------------------------------------------------------------------------------------
def listar_inmuebles(t, u, sup, operacion=None, estado=None, municipio=None, q=None, solo_activos=True, limite=25) -> list[dict]:
    exigir_modulo(t, "inmobiliaria")
    filas = inmobiliaria.listar_inmuebles(t, u, sup, operacion=operacion, estado=estado, municipio=municipio, q=q, solo_activos=bool(solo_activos), limite=max(1, min(int(limite), 100)))
    return [_campos(i, ("id", "expediente_id", "direccion", "municipio", "referencia", "tipo", "estado", "superficie_m2", "habitaciones", "propietario_nombre", "visitas_realizadas"))
            | {"precio": euros(i["precio_centimos"])} for i in filas]


def cruces_de_demanda(t, u, sup, demanda_id, minimo=50) -> list[dict]:
    exigir_modulo(t, "inmobiliaria")
    cruces = inmobiliaria.cruces_para_demanda(t, u, int(demanda_id), sup, minimo=max(0, min(int(minimo), 100)))
    return [{"puntos": c["puntos"], "motivos": [f"{r['criterio']}: {r['puntos']}/{r['maximo']} — {r['detalle']}" for r in c["razones"]], "faltan": c["faltan"],
             "inmueble": _campos(c["inmueble"], ("id", "direccion", "municipio", "tipo", "estado")) | {"precio": euros(c["inmueble"]["precio_centimos"])}} for c in cruces[:15]]


def agenda_visitas(t, u, sup, dias=7) -> list[dict]:
    exigir_modulo(t, "inmobiliaria")
    hoy = date.today()
    filas = inmobiliaria.listar_visitas(t, u, sup, desde=hoy.isoformat(), hasta=(hoy + timedelta(days=max(1, min(int(dias), 60)))).isoformat(), estado="prevista", limite=100)
    return [_campos(v, ("id", "inmueble_id", "fecha_hora", "direccion", "municipio", "visitante_nombre", "agente_nombre")) for v in filas]


def resumen_agencia(t, u, sup) -> dict:
    exigir_modulo(t, "inmobiliaria")
    r = inmobiliaria.resumen(t, u, sup)
    return {"inmuebles_activos": r["n_activos"], "por_fase": r["por_estado"], "demandas_activas": r["demandas"],
            "visitas_hoy": [_campos(v, ("fecha_hora", "direccion", "visitante_nombre", "agente_nombre")) for v in r["visitas_hoy"]],
            "visitas_semana": len(r["visitas_semana"]), "ofertas_abiertas": [_campos(o, ("id", "inmueble_id", "importe_centimos", "estado", "oferente")) for o in r["ofertas"]],
            "sin_movimiento_14_dias": [_campos(i, ("id", "direccion", "municipio", "estado")) for i in r["sin_movimiento"]]}


# --- Mensajes del enlace público (cliente del gabinete / propietario) -----------------------------------------------------------------------------------
def mensajes_del_asunto(t, u, sup, vertical_id, expediente_id) -> dict:
    exp = _asunto(t, u, sup, expediente_id, vertical_id)
    hilo = mensajes_enlace.hilo(vertical_id, t, exp["id"])
    sin_leer = mensajes_enlace.no_leidos(vertical_id, t, exp["id"])
    return {"expediente": exp["titulo"], "admite_respuesta": mensajes_enlace.enlace_vivo_con_mensajes(vertical_id, t, exp["id"]), "sin_leer": sin_leer,
            "mensajes": [{k: m.get(k) for k in ("id", "autor", "nombre", "texto", "creado_en", "leido_en")} for m in hilo]}


def responder_mensaje(t, u, sup, vertical_id, expediente_id, texto) -> dict:
    exp = _asunto(t, u, sup, expediente_id, vertical_id)
    return {"id": mensajes_enlace.responder(vertical_id, t, u, exp["id"], texto, sup)}
