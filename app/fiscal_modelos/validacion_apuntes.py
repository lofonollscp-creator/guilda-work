"""Validación de los apuntes ANTES de calcular o de escribir el libro: las reglas que el simulador de la AEAT aplica al importar un libro registro (descubiertas por prueba y error,
docs/fiscal-vias-aeat.md §4e) más las que el motor necesita. Así el error se le dice a quien lo puede arreglar (la persona que revisa la factura) en vez de descubrirlo al importar en la AEAT.

Devuelve `Problema`s: nivel «error» (la AEAT lo rechazaría o el cálculo sería incorrecto) o «aviso» (probablemente mal, pero no bloquea). Es una función pura."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .apuntes import RECIBIDAS, RECTIFICATIVAS, Apunte, periodo_de

# Formato del NIF-IVA intracomunitario por país (con el prefijo del país). Es una comprobación de FORMA; la AEAT además aplica el algoritmo de cada Estado miembro.
FORMATOS_NIF_IVA = {
    "AT": r"ATU\d{8}", "BE": r"BE[01]\d{9}", "BG": r"BG\d{9,10}", "CY": r"CY\d{8}[A-Z]", "CZ": r"CZ\d{8,10}", "DE": r"DE\d{9}", "DK": r"DK\d{8}", "EE": r"EE\d{9}", "EL": r"EL\d{9}",
    "ES": r"ES[A-Z0-9]\d{7}[A-Z0-9]", "FI": r"FI\d{8}", "FR": r"FR[A-HJ-NP-Z0-9]{2}\d{9}", "HR": r"HR\d{11}", "HU": r"HU\d{8}", "IE": r"IE\d[A-Z0-9+*]\d{5}[A-Z]{1,2}",
    "IT": r"IT\d{11}", "LT": r"LT(\d{9}|\d{12})", "LU": r"LU\d{8}", "LV": r"LV\d{11}", "MT": r"MT\d{8}", "NL": r"NL\d{9}B\d{2}", "PL": r"PL\d{10}", "PT": r"PT\d{9}",
    "RO": r"RO\d{2,10}", "SE": r"SE\d{12}", "SI": r"SI\d{8}", "SK": r"SK\d{10}", "XI": r"XI(\d{9}|\d{12}|GD\d{3}|HA\d{3})",
}
DUA_ESPANOL = re.compile(r"^\d{2}ES\w{14}$")
TIPOS_IVA_VIGENTES = {2026: (400, 1000, 2100)}           # los tipos de 0 %, 2 % y 5 % de las medidas temporales ya no se admiten en 2026 (el simulador los rechaza)


@dataclass(frozen=True)
class Problema:
    nivel: str                 # "error" | "aviso"
    codigo: str
    mensaje: str
    indice: int | None = None  # posición del apunte en la lista


def _e(codigo, mensaje, i):
    return Problema("error", codigo, mensaje, i)


def _a(codigo, mensaje, i):
    return Problema("aviso", codigo, mensaje, i)


def validar_apunte(a: Apunte, indice: int | None = None, *, hoy: date | None = None, nif_titular: str = "") -> list[Problema]:
    hoy = hoy or date.today()
    p: list[Problema] = []
    nombre = f"{a.serie}{a.numero}"
    rectifica = a.tipo_factura in RECTIFICATIVAS
    if a.fecha_expedicion > hoy:
        p.append(_e("fecha_futura", f"{nombre}: la fecha de expedición es posterior a hoy.", indice))
    if a.fecha_operacion and a.fecha_operacion > hoy:
        p.append(_e("fecha_futura", f"{nombre}: la fecha de operación es posterior a hoy.", indice))
    if a.libro == RECIBIDAS:
        recepcion = a.fecha_recepcion or a.fecha_expedicion
        if recepcion < a.fecha_expedicion:
            p.append(_e("recepcion_anterior", f"{nombre}: la recepción es anterior a la expedición.", indice))
        if recepcion > hoy:
            p.append(_e("fecha_futura", f"{nombre}: la fecha de recepción es posterior a hoy.", indice))
        if a.deducible_periodo_posterior:
            if not a.periodo_deduccion:
                p.append(_e("sin_periodo_deduccion", f"{nombre}: se difiere la deducción pero no se indica el periodo.", indice))
            else:
                ejercicio, periodo = a.periodo_deduccion
                actual = (recepcion.year, periodo_de(recepcion, periodo[-1] != "T"))
                if (ejercicio, periodo) <= actual:
                    p.append(_e("deduccion_no_posterior", f"{nombre}: el periodo de deducción debe ser posterior al de la factura.", indice))
        elif a.periodo_deduccion:
            p.append(_a("periodo_deduccion_sin_marca", f"{nombre}: hay periodo de deducción pero la deducción no está marcada como diferida.", indice))
        if a.isp or a.clave == "09":
            if a.total_efectivo != a.base:
                p.append(_e("total_distinto_base", f"{nombre}: con inversión del sujeto pasivo o clave 09 el total de la factura es igual a la base.", indice))
        if a.tipo_factura == "F5":
            if nif_titular and a.contraparte_nif != nif_titular:
                p.append(_e("dua_expedidor", f"{nombre}: en un DUA (F5) el expedidor es el propio titular del libro.", indice))
            if not DUA_ESPANOL.match(a.numero.replace(" ", "")):
                p.append(_e("dua_no_espanol", f"{nombre}: el nº de DUA no tiene formato español (AAES + 14): con un DUA no español la cuota deducible debe ser cero.", indice))
        if a.clave == "09" and not a.contraparte_nif_tipo == "02":
            p.append(_e("aib_sin_nif_iva", f"{nombre}: una adquisición intracomunitaria exige NIF-IVA del proveedor (tipo «02»).", indice))
    else:
        if a.calificacion == "S2" and (a.tipo_iva or a.cuota):
            p.append(_e("s2_con_iva", f"{nombre}: con calificación S2 el tipo y la cuota de IVA deben ser cero.", indice))
        if a.exenta == "E5" and not (a.contraparte_nif_tipo == "02" or a.contraparte_nif.startswith(tuple(FORMATOS_NIF_IVA))):
            p.append(_e("e5_sin_nif_iva", f"{nombre}: una entrega intracomunitaria exenta (E5) exige que el cliente tenga NIF-IVA.", indice))
        if a.calificacion == "" and not a.exenta:
            p.append(_e("sin_calificacion", f"{nombre}: falta la calificación de la operación o la causa de exención.", indice))
        if a.calificacion == "S1" and not a.exenta and not rectifica:
            esperada = (1 if a.base >= 0 else -1) * ((abs(a.base) * a.tipo_iva + 5000) // 10000)          # redondeo al céntimo, mitad hacia arriba (en valor absoluto)
            if a.cuota != esperada:
                p.append(_e("cuota_no_cuadra", f"{nombre}: la cuota repercutida debe ser exactamente base × tipo ({esperada / 100:.2f} €), y es {a.cuota / 100:.2f} €.", indice))
            if a.total is not None and a.clave not in ("03", "05", "09") and a.total != a.base + a.cuota:
                p.append(_e("total_no_cuadra", f"{nombre}: el total debe ser base + cuota.", indice))
    if a.contraparte_nif_tipo == "02":
        nif = a.contraparte_nif.replace(" ", "").upper()
        formato = FORMATOS_NIF_IVA.get(a.contraparte_pais or nif[:2])
        if formato is None or not re.fullmatch(formato, nif):
            p.append(_e("nif_iva_invalido", f"{nombre}: el NIF-IVA intracomunitario no tiene un formato válido.", indice))
        elif (a.contraparte_pais or nif[:2]) == "FR" and not _clave_francesa_correcta(nif):
            p.append(_e("nif_iva_invalido", f"{nombre}: el NIF-IVA francés no pasa la comprobación de su clave.", indice))
    elif a.contraparte_nif and not re.fullmatch(r"[A-Z0-9]\d{7}[A-Z0-9]", a.contraparte_nif.replace("-", "").upper()) and a.contraparte_nif_tipo == "":
        p.append(_a("nif_dudoso", f"{nombre}: el NIF de la contraparte no tiene la forma de un NIF español (L99999999 / 99999999L).", indice))
    tipos = TIPOS_IVA_VIGENTES.get(a.fecha_expedicion.year)
    if tipos and a.calificacion == "S1" and a.libro != RECIBIDAS and not rectifica and a.tipo_iva not in tipos:
        p.append(_e("tipo_iva_no_vigente", f"{nombre}: el tipo de IVA del {a.tipo_iva / 100:g} % no está vigente en {a.fecha_expedicion.year} (salvo en rectificativas).", indice))
    return p


def _clave_francesa_correcta(nif: str) -> bool:
    """FR + clave (2 dígitos) + SIREN (9): clave = (12 + 3 × (SIREN mod 97)) mod 97. Las claves alfabéticas (nuevo formato) no se comprueban."""
    cuerpo = nif[2:]
    if not cuerpo[:2].isdigit():
        return True
    return int(cuerpo[:2]) == (12 + 3 * (int(cuerpo[2:]) % 97)) % 97


def validar(apuntes: list[Apunte], *, hoy: date | None = None, nif_titular: str = "") -> list[Problema]:
    salida: list[Problema] = []
    vistos: dict[tuple, int] = {}
    for i, a in enumerate(apuntes):
        salida += validar_apunte(a, i, hoy=hoy, nif_titular=nif_titular)
        clave = (a.libro, a.serie, a.numero, a.contraparte_nif)
        if clave in vistos:
            salida.append(_a("posible_duplicado", f"{a.serie}{a.numero}: parece repetida (mismo número y contraparte que el apunte {vistos[clave] + 1}).", i))
        vistos.setdefault(clave, i)
    return salida


def errores(problemas: list[Problema]) -> list[Problema]:
    return [x for x in problemas if x.nivel == "error"]
