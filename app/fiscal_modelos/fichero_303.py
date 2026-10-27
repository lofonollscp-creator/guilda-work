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


# Página 4 del 303 (solo el último periodo y solo quien está exonerado del 390): nº de campo de la página -> casilla del 390 de la que sale (mismo concepto, otro número). Se comprueba contra las
# descripciones de los dos diseños oficiales en tests/test_fiscal_390.py.
VOLUMEN_PAGINA_4 = {24: "99", 26: "103", 27: "104", 28: "105", 29: "110", 30: "125", 41: "108"}
TERRITORIO_COMUN = 23                                                      # [107], 100,00 %


def pagina_4(volumen) -> dict:
    """La información anual del exonerado del 390 a partir del volumen de operaciones del año (`motor_390.volumen_anual`). Epígrafes y códigos de actividad quedan en blanco: se completan en el formulario."""
    valores = {n: Decimal(volumen.casillas.get(c390, 0)) / 100 for n, c390 in VOLUMEN_PAGINA_4.items() if volumen.casillas.get(c390, 0)}
    valores[TERRITORIO_COMUN] = Decimal(100)
    return valores


def paginas_desde(diseno: dict, r: Resultado303, *, nif: str, nombre: str, tipo_declaracion: str | None = None, exonerado_390: bool = False, volumen=None) -> dict[str, dict]:
    """`{hoja: {casilla|nº de campo: valor}}` listo para `exportador_303.construir`. En el último periodo (4T/12): quien NO está exonerado del 390 no lleva nada más; quien lo está necesita el volumen
    de operaciones del año (`volumen`) y lleva la página 4."""
    if not r.calculable:
        raise FicheroNoGenerable("El cálculo está bloqueado: " + " · ".join(r.bloqueos[:3]))
    ultimo = r.periodo in ex.ULTIMOS
    if ultimo and exonerado_390 and volumen is None:
        raise FicheroNoGenerable("El titular está exonerado del 390: el último periodo lleva el volumen de operaciones del año y no se ha calculado.")
    if ultimo and exonerado_390 and not volumen.calculable:
        raise FicheroNoGenerable("El volumen de operaciones del año está bloqueado: " + " · ".join(volumen.bloqueos[:3]))
    indice = indice_casillas(diseno)
    distinto_de_cero = bool(volumen and volumen.casillas.get("108", 0))
    paginas: dict[str, dict] = {"DP30301": {6: tipo_declaracion or r.tipo_declaracion, 7: nif, 8: nombre, 9: str(r.ejercicio), 10: r.periodo,
                                            **ex.indicadores_pagina1(r.periodo, exonerado_390=exonerado_390, volumen_distinto_de_cero=distinto_de_cero)}}
    if ultimo and exonerado_390:
        paginas["DP30304"] = pagina_4(volumen)
    for casilla, valor in r.casillas.items():
        if casilla not in indice:
            raise FicheroNoGenerable(f"La casilla {casilla} no existe en el diseño oficial.")
        campo = indice[casilla][0]
        if campo["lon"] == 5:                                                 # porcentaje: centésimas -> «100.00»
            paginas.setdefault(campo["hoja"], {})[casilla] = Decimal(valor) / 100
        else:
            paginas.setdefault(campo["hoja"], {})[casilla] = Decimal(valor) / 100
    return paginas


def generar(r: Resultado303, *, nif: str, nombre: str, tipo_declaracion: str | None = None, diseno: dict | None = None, exonerado_390: bool = False, volumen=None) -> bytes:
    diseno = diseno or json.loads(ex.DISENO_303_2026.read_text(encoding="utf-8"))
    return ex.construir(diseno, ejercicio=r.ejercicio, periodo=r.periodo, paginas=paginas_desde(diseno, r, nif=nif, nombre=nombre, tipo_declaracion=tipo_declaracion, exonerado_390=exonerado_390, volumen=volumen))
