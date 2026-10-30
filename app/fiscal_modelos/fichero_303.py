"""Del resultado del motor (casillas) al fichero `.303` importable por la AEAT. Une `motor_303` (qué casillas) con `exportador_303` (cómo se escriben): coloca cada casilla en la página que le corresponde
según el diseño oficial y rellena la identificación y los indicadores del periodo. No presenta nada: el fichero se IMPORTA en el formulario (o el colaborador social lo presenta con su certificado)."""
from __future__ import annotations

import json
from decimal import Decimal

from . import exportador_303 as ex
from . import iban as iban_mod
from .disenos_oficiales import indice_casillas
from .motor_303 import Resultado303


class FicheroNoGenerable(ValueError):
    pass


# Página 4 del 303 (solo el último periodo y solo quien está exonerado del 390): nº de campo de la página -> casilla del 390 de la que sale (mismo concepto, otro número). Se comprueba contra las
# descripciones de los dos diseños oficiales en tests/test_fiscal_390.py.
VOLUMEN_PAGINA_4 = {24: "99", 26: "103", 27: "104", 28: "105", 29: "110", 30: "125", 41: "108"}
TERRITORIO_COMUN = 23                                                      # [107], 100,00 %
# Página 3, bloque «Rectificativa»: nº de campo -> qué lleva. El motivo es siempre «Rectificaciones (excepto discrepancia de criterio administrativo)», el único que se genera.
RECTIFICATIVA_MARCA, RECTIFICATIVA_JUSTIFICANTE, RECTIFICATIVA_MOTIVO = 31, 32, 35
# Página DID («Domiciliación/Devolución»): nº de campo del IBAN y de la marca SEPA (1 España · 2 SEPA)
PAGINA_CUENTA, CUENTA_IBAN, CUENTA_MARCA_SEPA = "DP303DID", 6, 11


# Página 4: pares (clave de actividad, epígrafe IAE) de la principal y de las otras cinco
ACTIVIDADES_PAGINA_4 = ((10, 11), (12, 13), (14, 15), (16, 17), (18, 19), (20, 21))


def pagina_4(volumen, actividades: list[dict] | None = None) -> dict:
    """La información anual del exonerado del 390 a partir del volumen de operaciones del año (`motor_390.volumen_anual`) y de las actividades del perfil (la primera es la principal). Lo que el perfil no tenga queda en blanco: se completa en el formulario."""
    valores = {n: Decimal(volumen.casillas.get(c390, 0)) / 100 for n, c390 in VOLUMEN_PAGINA_4.items() if volumen.casillas.get(c390, 0)}
    valores[TERRITORIO_COMUN] = Decimal(100)
    for (n_codigo, n_epigrafe), act in zip(ACTIVIDADES_PAGINA_4, actividades or []):
        if act.get("codigo"):
            valores[n_codigo] = act["codigo"]
        if act.get("epigrafe"):
            valores[n_epigrafe] = act["epigrafe"]
    return valores


def paginas_desde(diseno: dict, r: Resultado303, *, nif: str, nombre: str, tipo_declaracion: str | None = None, exonerado_390: bool = False, volumen=None, justificante_anterior: str | None = None,
                  criterio_caja: bool = False, iban: str | None = None, actividades: list[dict] | None = None) -> dict[str, dict]:
    """`{hoja: {casilla|nº de campo: valor}}` listo para `exportador_303.construir`. En el último periodo (4T/12): quien NO está exonerado del 390 no lleva nada más; quien lo está necesita el volumen
    de operaciones del año (`volumen`) y lleva la página 4. Con `justificante_anterior` (13 cifras) es una autoliquidación rectificativa y lleva el bloque «Rectificativa» de la página 3. Con `iban`, la página DID lleva la cuenta (devolución, o rectificativa con casilla 111)."""
    if not r.calculable:
        raise FicheroNoGenerable("El cálculo está bloqueado: " + " · ".join(r.bloqueos[:3]))
    ultimo = r.periodo in ex.ULTIMOS
    if ultimo and exonerado_390 and volumen is None:
        raise FicheroNoGenerable("El titular está exonerado del 390: el último periodo lleva el volumen de operaciones del año y no se ha calculado.")
    if ultimo and exonerado_390 and r.prorrata_pct is not None:
        raise FicheroNoGenerable("El titular está exonerado del 390 y aplica prorrata: el último periodo lleva la página de prorrata (CNAE, importe y porcentaje por actividad) y todavía no se genera.")
    if ultimo and exonerado_390 and not volumen.calculable:
        raise FicheroNoGenerable("El volumen de operaciones del año está bloqueado: " + " · ".join(volumen.bloqueos[:3]))
    indice = indice_casillas(diseno)
    distinto_de_cero = bool(volumen and volumen.casillas.get("108", 0))
    paginas: dict[str, dict] = {"DP30301": {6: tipo_declaracion or r.tipo_declaracion, 7: nif, 8: nombre, 9: str(r.ejercicio), 10: r.periodo,
                                            **ex.indicadores_pagina1(r.periodo, exonerado_390=exonerado_390, volumen_distinto_de_cero=distinto_de_cero, criterio_caja=criterio_caja,
                                                                                      destinatario_caja=bool(r.casillas.get("74") or r.casillas.get("75")))}}
    if ultimo and exonerado_390:
        paginas["DP30304"] = pagina_4(volumen, actividades)
    if justificante_anterior is not None and not (len(justificante_anterior) == 13 and justificante_anterior.isdigit()):
        raise FicheroNoGenerable("El número de justificante de la autoliquidación rectificada debe tener 13 cifras.")
    for casilla, valor in r.casillas.items():
        if casilla not in indice:
            raise FicheroNoGenerable(f"La casilla {casilla} no existe en el diseño oficial.")
        campo = indice[casilla][0]
        if campo["lon"] == 5:                                                 # porcentaje: centésimas -> «100.00»
            paginas.setdefault(campo["hoja"], {})[casilla] = Decimal(valor) / 100
        else:
            paginas.setdefault(campo["hoja"], {})[casilla] = Decimal(valor) / 100
    if iban:
        try:
            limpio = iban_mod.validar(iban)
        except iban_mod.IbanNoValido as e:
            raise FicheroNoGenerable(f"IBAN no válido: {e}") from None
        paginas[PAGINA_CUENTA] = {CUENTA_IBAN: limpio, CUENTA_MARCA_SEPA: iban_mod.marca_sepa(limpio)}
    if justificante_anterior is not None:
        paginas.setdefault(indice["71"][0]["hoja"], {}).update({RECTIFICATIVA_MARCA: "X", RECTIFICATIVA_JUSTIFICANTE: justificante_anterior, RECTIFICATIVA_MOTIVO: "X"})
    return paginas


def generar(r: Resultado303, *, nif: str, nombre: str, tipo_declaracion: str | None = None, diseno: dict | None = None, exonerado_390: bool = False, volumen=None,
            justificante_anterior: str | None = None, criterio_caja: bool = False, iban: str | None = None, actividades: list[dict] | None = None) -> bytes:
    diseno = diseno or json.loads(ex.DISENO_303_2026.read_text(encoding="utf-8"))
    return ex.construir(diseno, ejercicio=r.ejercicio, periodo=r.periodo, paginas=paginas_desde(diseno, r, nif=nif, nombre=nombre, tipo_declaracion=tipo_declaracion, exonerado_390=exonerado_390, volumen=volumen,
                                                                                  justificante_anterior=justificante_anterior,
                                                                                  criterio_caja=criterio_caja, iban=iban, actividades=actividades))
