"""Del resultado del motor (casillas) al fichero `.303` importable por la AEAT. Une `motor_303` (qué casillas) con `exportador_303` (cómo se escriben): coloca cada casilla en la página que le corresponde
según el diseño oficial y rellena la identificación y los indicadores del periodo. No presenta nada: el fichero se IMPORTA en el formulario (o el colaborador social lo presenta con su certificado)."""
from __future__ import annotations

import json
from decimal import Decimal

from . import exportador_303 as ex
from .disenos_oficiales import indice_casillas
from .motor_303 import Resultado303


class FicheroNoGenerable(ValueError):
    pass


def paginas_desde(diseno: dict, r: Resultado303, *, nif: str, nombre: str, tipo_declaracion: str | None = None) -> dict[str, dict]:
    """`{hoja: {casilla|nº de campo: valor}}` listo para `exportador_303.construir`."""
    if not r.calculable:
        raise FicheroNoGenerable("El cálculo está bloqueado: " + " · ".join(r.bloqueos[:3]))
    if r.periodo in ex.ULTIMOS:
        raise FicheroNoGenerable("El último periodo (4T/12) lleva además la información anual (casillas 79-99): todavía no está soportado generar ese fichero.")
    indice = indice_casillas(diseno)
    paginas: dict[str, dict] = {"DP30301": {6: tipo_declaracion or r.tipo_declaracion, 7: nif, 8: nombre, 9: str(r.ejercicio), 10: r.periodo, **ex.indicadores_pagina1(r.periodo)}}
    for casilla, valor in r.casillas.items():
        if casilla not in indice:
            raise FicheroNoGenerable(f"La casilla {casilla} no existe en el diseño oficial.")
        campo = indice[casilla][0]
        if campo["lon"] == 5:                                                 # porcentaje: centésimas -> «100.00»
            paginas.setdefault(campo["hoja"], {})[casilla] = Decimal(valor) / 100
        else:
            paginas.setdefault(campo["hoja"], {})[casilla] = Decimal(valor) / 100
    return paginas


def generar(r: Resultado303, *, nif: str, nombre: str, tipo_declaracion: str | None = None, diseno: dict | None = None) -> bytes:
    diseno = diseno or json.loads(ex.DISENO_303_2026.read_text(encoding="utf-8"))
    return ex.construir(diseno, ejercicio=r.ejercicio, periodo=r.periodo, paginas=paginas_desde(diseno, r, nif=nif, nombre=nombre, tipo_declaracion=tipo_declaracion))
