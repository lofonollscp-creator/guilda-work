"""Informe mensual al cliente de la gestoría: qué se ha presentado en el mes, qué sigue pendiente y qué vence en los próximos 30 días.
`datos_informe` es una función pura (recibe los vencimientos ya leídos); `a_pdf` los maqueta con la capa común de informes."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from . import informes

DIAS_PROXIMOS = 30


def _fecha(v: dict) -> date:
    return date.fromisoformat(str(v["fecha_limite"])[:10])


def datos_informe(vencimientos: Iterable[dict], anio: int, mes: int, hoy: date) -> dict:
    """`presentados`: los marcados como presentados cuya fecha límite cae en el mes. `atrasados`: pendientes con fecha pasada.
    `proximos`: pendientes que vencen en los 30 días siguientes a `hoy`. Cada lista va ordenada por fecha."""
    venc = list(vencimientos)
    presentados = [v for v in venc if v.get("estado") == "presentado" and (_fecha(v).year, _fecha(v).month) == (anio, mes)]
    pendientes = [v for v in venc if v.get("estado") == "pendiente"]
    atrasados = [v for v in pendientes if _fecha(v) < hoy]
    limite = hoy + timedelta(days=DIAS_PROXIMOS)
    proximos = [v for v in pendientes if hoy <= _fecha(v) <= limite]
    clave = lambda v: (_fecha(v), v.get("modelo", ""))
    return {"anio": anio, "mes": mes, "presentados": sorted(presentados, key=clave), "atrasados": sorted(atrasados, key=clave),
            "proximos": sorted(proximos, key=clave)}


def a_pdf(cliente_nombre: str, nif: str | None, despacho: str | None, datos: dict) -> bytes:
    def filas(lista):
        return [[v["modelo"], v["periodo"], str(v["fecha_limite"])[:10]] for v in lista]

    cols = ["Modelo", "Periodo", "Fecha límite"]
    bloques: list[tuple] = [("claves", [("Cliente", cliente_nombre), ("NIF", nif or "—"), ("Periodo del informe", f"{datos['mes']:02d}/{datos['anio']}")])]
    for titulo, clave, vacio in (("Presentado este mes", "presentados", "No se ha presentado ningún modelo este mes."),
                                  ("Pendiente y fuera de plazo", "atrasados", "No hay nada atrasado."),
                                  ("Próximos 30 días", "proximos", "No vence nada en los próximos 30 días.")):
        bloques.append(("seccion", titulo))
        bloques.append(("tabla", cols, filas(datos[clave])) if datos[clave] else ("parrafo", vacio))
    bloques += [("espacio",), ("parrafo", "Documento informativo elaborado por la gestoría. No sustituye a los justificantes oficiales de presentación.")]
    return informes.construir_pdf(f"Informe mensual — {cliente_nombre}", bloques, despacho=despacho)
