"""Perfil fiscal de un cliente de la gestoría: de qué es (autónomo, sociedad...) y qué hace (IVA, retenciones, alquiler de local) se deducen los
modelos que le tocan, con el motivo de cada uno para que la persona lo revise. Todo son funciones puras (sin base de datos ni Flask).

Las reglas son un **punto de partida sin validar**: no sustituyen al criterio de quien lleva al cliente. Por eso el resultado siempre se muestra
como propuesta editable y nunca se guarda sin confirmación."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from flask_babel import lazy_gettext as _l

from . import calendario_plazos as cp

TIPOS = ("autonomo", "sociedad", "particular")
ATRIBUTOS = ("iva", "estimacion_directa", "retenciones", "alquiler_local")
SEMAFOROS = ("al_dia", "proximo", "atrasado", "sin_obligaciones")
DIAS_PROXIMO = 7


def perfil_limpio(tipo: str | None, atributos: Iterable[str] = ()) -> dict:
    """Normaliza lo que llega de un formulario o de la API: tipo desconocido -> `particular`, atributos desconocidos se descartan."""
    tipo = tipo if tipo in TIPOS else "particular"
    marcados = {a for a in atributos if a in ATRIBUTOS}
    return {"tipo": tipo, "atributos": [a for a in ATRIBUTOS if a in marcados]}


def modelos_para_perfil(perfil: dict | None) -> list[dict]:
    """`[{modelo, motivo}]` en orden estable. Un perfil vacío o de particular sin atributos no propone nada."""
    if not perfil:
        return []
    tipo, attrs = perfil.get("tipo"), set(perfil.get("atributos") or ())
    res: list[dict] = []

    def poner(modelo: str, motivo: str) -> None:
        if all(r["modelo"] != modelo for r in res):
            res.append({"modelo": modelo, "motivo": motivo})

    if "iva" in attrs:
        poner("303", _l("Repercute o soporta IVA: declaración trimestral"))
        poner("390", _l("Si presenta el 303, resumen anual de IVA"))
    if tipo == "autonomo" and "estimacion_directa" in attrs:
        poner("130", _l("Autónomo en estimación directa: pago fraccionado de IRPF"))
    if "retenciones" in attrs:
        poner("111", _l("Practica retenciones a trabajadores o profesionales"))
    if "alquiler_local" in attrs:
        poner("115", _l("Paga un alquiler de local con retención"))
    if tipo == "sociedad":
        poner("200", _l("Sociedad: Impuesto sobre Sociedades anual"))
    return res


def ajustar_a_calendario(propuestas: list[dict], cal: cp.Calendario) -> list[dict]:
    """Si la fecha límite cae en inhábil (fin de semana o festivo), pasa al siguiente hábil. Devuelve copias; las desplazadas llevan
    `fecha_original` para poder explicarlo en pantalla."""
    res = []
    for p in propuestas:
        nueva = dict(p)
        orig = date.fromisoformat(p["fecha_limite"])
        ajustada = cp.siguiente_habil(orig, cal)
        if ajustada != orig:
            nueva["fecha_original"] = p["fecha_limite"]
            nueva["fecha_limite"] = ajustada.isoformat()
        res.append(nueva)
    return res


def semaforo(vencimientos: Iterable[dict], hoy: date) -> dict:
    """Estado de un cliente de un vistazo. `atrasado` si hay algo pendiente con fecha pasada; `proximo` si vence en menos de `DIAS_PROXIMO` días;
    `al_dia` si todo está presentado o lejos; `sin_obligaciones` si no tiene ningún vencimiento pendiente ni presentado."""
    pendientes = [v for v in vencimientos if v.get("estado") == "pendiente"]
    atrasados = [v for v in pendientes if date.fromisoformat(v["fecha_limite"][:10]) < hoy]
    limite = hoy + timedelta(days=DIAS_PROXIMO)
    proximos = [v for v in pendientes if hoy <= date.fromisoformat(v["fecha_limite"][:10]) <= limite]
    total = sum(1 for v in vencimientos)
    if atrasados:
        estado = "atrasado"
    elif proximos:
        estado = "proximo"
    elif total == 0:
        estado = "sin_obligaciones"
    else:
        estado = "al_dia"
    return {"estado": estado, "atrasados": len(atrasados), "proximos": len(proximos), "pendientes": len(pendientes)}
