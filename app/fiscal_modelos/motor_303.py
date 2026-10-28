"""Motor de cálculo del **modelo 303** (IVA): de los apuntes de los libros registro a las casillas de la autoliquidación. Es una función PURA (sin base de datos, sin red, sin IA): los mismos apuntes dan siempre
las mismas casillas, y cada casilla sabe de qué apuntes sale (`Resultado303.origen`) para poder explicarla.

Las reglas son las de la tabla oficial de la AEAT «Cálculo de casillas del 303 desde los libros registro» (`docs/fuentes-oficiales/aeat/CALCULO_CASILLAS_IVA_PRE303-LSI.xlsx`) y se contrastan con la propia AEAT
(`scripts/fiscal/simulador_libros.py`: el mismo libro se sube al simulador público y se comparan las casillas). **Lo que no está soportado no se calcula: se BLOQUEA** (`bloqueos`) en vez de dar un número que
podría ser falso: criterio de caja, recargo de equivalencia, prorrata, régimen simplificado y agrario, OSS, tributación foral, compensaciones, regularización de inversiones, claves de operación y tipos no contemplados…

Importes en céntimos enteros (con signo), porcentajes en centésimas; el redondeo es al céntimo, mitad hacia arriba."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .apuntes import RECIBIDAS, RECTIFICATIVAS, Apunte, en_periodo, periodo_de

CLAVES_DEVENGO_S1 = {"01", "11", "12", "13", "15", "03", "05", "09"}
TIPOS_EMITIDAS_NORMALES = {"F1", "F2", "F4"}
TIPOS_RECIBIDAS_NORMALES = {"F1", "F3", "F4", "F6"}
# tipo de IVA (centésimas) -> (casilla de base, casilla de cuota) del régimen general
CASILLAS_TIPO = {0: ("150", "152"), 400: ("01", "03"), 500: ("154", "155"), 1000: ("04", "06"), 2100: ("07", "09")}
CUOTAS_DEVENGADAS = ("152", "03", "155", "06", "09", "11", "13", "15", "18", "21", "24", "26", "158", "170")      # casilla 27 (la 167 no se usa)
# recargo de equivalencia repercutido: (tipo de IVA, tipo de recargo) -> (casilla de base, casilla de cuota). Tipos de recargo del art. 161 LIVA: 0,5 % sobre el 4 %, 1,4 % sobre el 10 %, 5,2 % sobre el 21 % y 1,75 % (tabaco) sobre el 21 %
CASILLAS_RECARGO = {(400, 50): ("168", "170"), (1000, 140): ("19", "21"), (2100, 520): ("22", "24"), (2100, 175): ("156", "158")}
CUOTAS_DEDUCIBLES = ("29", "31", "33", "35", "37", "39", "41", "44")                   # casilla 45 (42 y 43 no se calculan; la 44 es la regularización de la prorrata en el último periodo)


class ErrorDeCalculo(ValueError):
    pass


@dataclass
class Resultado303:
    ejercicio: int
    periodo: str
    casillas: dict[str, int] = field(default_factory=dict)             # casilla -> céntimos (o centésimas en las de porcentaje)
    origen: dict[str, list[int]] = field(default_factory=dict)         # casilla -> índices de los apuntes que contribuyen
    bloqueos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    tipo_declaracion: str = "N"
    prorrata_pct: int | None = None                                    # prorrata general provisional aplicada a las cuotas soportadas (porcentaje entero)

    @property
    def calculable(self) -> bool:
        return not self.bloqueos

    def sumar(self, casilla: str, importe: int, indice: int | None = None) -> None:
        self.casillas[casilla] = self.casillas.get(casilla, 0) + importe
        if indice is not None:
            self.origen.setdefault(casilla, []).append(indice)


def _redondear(numerador: int, denominador: int) -> int:
    """División entera con redondeo mitad hacia arriba (en valor absoluto)."""
    signo = -1 if (numerador < 0) != (denominador < 0) else 1
    n, d = abs(numerador), abs(denominador)
    return signo * ((2 * n + d) // (2 * d))


def _fecha_devengo(a: Apunte):
    """Qué fecha manda para el devengo: en las rectificativas la de expedición; en el resto la de la operación si se informó, y si no la de expedición."""
    if a.tipo_factura in RECTIFICATIVAS:
        return a.fecha_expedicion
    return a.fecha_operacion or a.fecha_expedicion


def _limites_periodo(ejercicio: int, periodo: str) -> tuple[date, date]:
    """Primer y último día del periodo («2T» o «05»)."""
    import calendar
    primero, ultimo = (3 * int(periodo[0]) - 2, 3 * int(periodo[0])) if periodo.endswith("T") else (int(periodo), int(periodo))
    return date(ejercicio, primero, 1), date(ejercicio, ultimo, calendar.monthrange(ejercicio, ultimo)[1])


def _cobrado_hasta(a: Apunte, fecha: date, total: int) -> int:
    """Lo cobrado (o pagado) de la factura hasta `fecha`, entre 0 y el total. A partir del 31 de diciembre del año siguiente al de la operación cuenta como cobrado todo: es el límite del régimen (devengo y deducción
    forzosos)."""
    operacion = a.fecha_operacion or a.fecha_expedicion
    if fecha >= date(operacion.year + 1, 12, 31):
        return total
    return min(max(sum(importe for dia, importe in a.cobros if dia <= fecha), 0), total)


def _parte_del_periodo(importe: int, a: Apunte, r: Resultado303, total: int) -> int:
    """La parte de `importe` (base o cuota) que se devenga o se deduce en el periodo por criterio de caja: proporcional a lo cobrado o pagado en él. Se calcula con acumulados redondeados, así que la suma de
    todos los periodos es exactamente el importe."""
    desde, hasta = _limites_periodo(r.ejercicio, r.periodo)
    return _redondear(importe * _cobrado_hasta(a, hasta, total), total) - _redondear(importe * _cobrado_hasta(a, desde - timedelta(days=1), total), total)


def _devengado_caja(a: Apunte, i: int, r: Resultado303) -> None:
    """Expedida con criterio de caja (clave 07): el IVA se devenga al cobrar, en proporción a lo cobrado, o el 31 de diciembre del año siguiente. Las casillas 62 y 63 informan de lo que se habría devengado por la regla
    general en el periodo."""
    nombre = f"Expedida {a.serie}{a.numero}"
    if a.tipo_factura not in TIPOS_EMITIDAS_NORMALES:
        r.bloqueos.append(f"{nombre}: criterio de caja solo con facturas normales (las rectificativas con caja no están soportadas).")
        return
    if a.calificacion != "S1" or a.exenta or a.recargo_cuota or a.recargo_pct or a.base <= 0 or a.cuota < 0:
        r.bloqueos.append(f"{nombre}: criterio de caja solo con operaciones sujetas y no exentas, sin recargo y con importes positivos.")
        return
    if a.tipo_iva not in CASILLAS_TIPO:
        r.bloqueos.append(f"{nombre}: el tipo de IVA {a.tipo_iva / 100:g} % no está soportado (solo 0, 4, 5, 10 y 21).")
        return
    total = a.total_efectivo
    if total <= 0:
        r.bloqueos.append(f"{nombre}: el total de la factura debe ser positivo.")
        return
    if any(importe for dia, importe in a.cobros) and sum(importe for dia, importe in a.cobros) > total:
        r.bloqueos.append(f"{nombre}: los cobros suman más que el total de la factura.")
        return
    base_dev, cuota_dev = _parte_del_periodo(a.base, a, r, total), _parte_del_periodo(a.cuota, a, r, total)
    base, cuota = CASILLAS_TIPO[a.tipo_iva]
    if base_dev or cuota_dev:
        r.sumar(base, base_dev, i)
        r.sumar(cuota, cuota_dev, i)
    if en_periodo(_fecha_devengo(a), r.ejercicio, r.periodo):
        r.sumar("62", a.base, i)
        r.sumar("63", a.cuota, i)


def _devengado_expedidas(a: Apunte, i: int, r: Resultado303) -> None:
    if a.clave == "07":
        _devengado_caja(a, i, r)
        return
    if not en_periodo(_fecha_devengo(a), r.ejercicio, r.periodo):
        return
    if a.tipo_factura not in TIPOS_EMITIDAS_NORMALES | set(RECTIFICATIVAS):
        r.bloqueos.append(f"Expedida {a.serie}{a.numero}: el tipo de factura {a.tipo_factura} no está soportado.")
        return
    if a.clave == "17":
        r.bloqueos.append(f"Expedida {a.serie}{a.numero}: la clave {a.clave} (ventanilla única) no está soportada.")
        return
    rectifica = a.tipo_factura in RECTIFICATIVAS or a.base < 0 or a.cuota < 0
    # --- operaciones no sujetas, exentas e inversión del sujeto pasivo: solo «información adicional» (no entran en la cuota)
    if a.calificacion == "S2":
        r.sumar("122", a.base, i)
        return
    if a.calificacion == "N2":
        r.sumar("120", a.base, i)
        return
    if a.calificacion == "N1":
        return
    if a.exenta:
        if a.exenta == "E5" and a.clave in ("01", "15"):
            r.sumar("59", a.base, i)
        elif a.exenta in ("E2", "E3", "E4") and a.clave in ("01", "02", "05"):
            r.sumar("60", a.base, i)
        elif a.exenta == "E6" and a.clave in ("02", "05"):
            r.sumar("60", a.base, i)
        return
    if a.calificacion != "S1":
        r.bloqueos.append(f"Expedida {a.serie}{a.numero}: la calificación {a.calificacion!r} no está soportada.")
        return
    if a.clave not in CLAVES_DEVENGO_S1:
        r.bloqueos.append(f"Expedida {a.serie}{a.numero}: la clave de operación {a.clave} no está soportada en el devengo.")
        return
    if rectifica:
        r.sumar("14", a.base, i)
        r.sumar("15", a.cuota, i)
        if a.recargo_cuota or a.recargo_pct:                                  # modificación de bases y cuotas del recargo de equivalencia
            r.sumar("25", a.base, i)
            r.sumar("26", a.recargo_cuota, i)
        return
    if a.tipo_iva not in CASILLAS_TIPO:
        r.bloqueos.append(f"Expedida {a.serie}{a.numero}: el tipo de IVA {a.tipo_iva / 100:g} % no está soportado (solo 0, 4, 5, 10 y 21).")
        return
    base, cuota = CASILLAS_TIPO[a.tipo_iva]
    if a.recargo_cuota or a.recargo_pct:
        if (a.tipo_iva, a.recargo_pct) not in CASILLAS_RECARGO:
            r.bloqueos.append(f"Expedida {a.serie}{a.numero}: el recargo de equivalencia del {a.recargo_pct / 100:g} % sobre el IVA del {a.tipo_iva / 100:g} % no tiene casilla en el 303 (solo 0,5 % sobre 4 %, 1,4 % sobre 10 %, "
                              "5,2 % y 1,75 % sobre 21 %).")
            return
        base_re, cuota_re = CASILLAS_RECARGO[(a.tipo_iva, a.recargo_pct)]
        r.sumar(base_re, a.base, i)                                           # la base se repite en el bloque del recargo
        r.sumar(cuota_re, a.recargo_cuota, i)
    r.sumar(base, a.base, i)
    r.sumar(cuota, a.cuota, i)


def _periodo_de_deduccion(a: Apunte, r: Resultado303) -> bool:
    """¿Se deduce esta cuota en la autoliquidación en curso? Por la fecha de recepción (nunca anterior a la de expedición); si se difiere, por el periodo de deducción que indica el libro."""
    if a.deducible_periodo_posterior:
        if not a.periodo_deduccion:
            r.bloqueos.append(f"Recibida {a.serie}{a.numero}: se difiere la deducción pero no se indica el periodo de deducción.")
            return False
        return a.periodo_deduccion == (r.ejercicio, r.periodo)
    recepcion = a.fecha_recepcion or a.fecha_expedicion
    if recepcion < a.fecha_expedicion:
        r.bloqueos.append(f"Recibida {a.serie}{a.numero}: la fecha de recepción es anterior a la de expedición.")
        return False
    return en_periodo(recepcion, r.ejercicio, r.periodo)


def _soportado_caja(a: Apunte, i: int, r: Resultado303) -> None:
    """Recibida con criterio de caja (clave 07): la cuota se deduce al pagar, en proporción a lo pagado, o el 31 de diciembre del año siguiente. Las casillas 74 y 75 informan de la adquisición en el periodo en que
    se habría deducido por la regla general."""
    nombre = f"Recibida {a.serie}{a.numero}"
    if a.tipo_factura not in TIPOS_RECIBIDAS_NORMALES or a.isp or a.deducible_periodo_posterior or a.base <= 0 or a.cuota < 0:
        r.bloqueos.append(f"{nombre}: criterio de caja solo con facturas normales positivas, sin inversión del sujeto pasivo y sin deducción diferida.")
        return
    total = a.total_efectivo
    if total <= 0:
        r.bloqueos.append(f"{nombre}: el total de la factura debe ser positivo.")
        return
    if sum(importe for dia, importe in a.cobros) > total:
        r.bloqueos.append(f"{nombre}: los pagos suman más que el total de la factura.")
        return
    efectiva = _deduccion_efectiva(a, r, nombre)
    if efectiva is None:
        return
    if _periodo_de_deduccion(efectiva, r):
        r.sumar("74", a.base, i)
        r.sumar("75", a.cuota, i)
    if efectiva.deducible == 0:
        return
    base, cuota = ("30", "31") if a.bien_inversion else ("28", "29")
    base_pagada, cuota_deducida = _parte_del_periodo(a.base, a, r, total), _parte_del_periodo(efectiva.deducible, a, r, total)
    if base_pagada or cuota_deducida:
        r.sumar(base, base_pagada, i)
        r.sumar(cuota, cuota_deducida, i)


def _deduccion_efectiva(a: Apunte, r: Resultado303, nombre: str) -> Apunte | None:
    """El apunte con la cuota deducible que corresponde (aplicando la prorrata general si la hay); None si lleva una deducción parcial que no se soporta."""
    if a.cuota_deducible is not None and a.cuota_deducible not in (0, a.cuota):
        r.bloqueos.append(f"{nombre}: deducción parcial (prorrata o afectación) no soportada.")
        return None
    if r.prorrata_pct is not None and r.prorrata_pct < 100 and a.cuota_deducible != 0:                 # una cuota que el apunte ya excluye por completo no se prorratea
        a = a.con(cuota_deducible=_redondear(a.cuota * r.prorrata_pct, 100))
    return a


def _recibidas(a: Apunte, i: int, r: Resultado303) -> None:
    if a.clave == "07":
        _soportado_caja(a, i, r)
        return
    if not _periodo_de_deduccion(a, r):
        return
    nombre = f"Recibida {a.serie}{a.numero}"
    if a.tipo_factura not in TIPOS_RECIBIDAS_NORMALES | set(RECTIFICATIVAS) | {"F5", "LC"}:
        r.bloqueos.append(f"{nombre}: el tipo de factura {a.tipo_factura} no está soportado.")
        return
    if a.clave == "02":
        r.bloqueos.append(f"{nombre}: la clave {a.clave} (régimen agrario) no está soportada.")
        return
    if a.clave not in ("01", "09", "12"):
        r.bloqueos.append(f"{nombre}: la clave de operación {a.clave} no está soportada en las recibidas.")
        return
    a = _deduccion_efectiva(a, r, nombre)
    if a is None:
        return
    rectifica = a.tipo_factura in RECTIFICATIVAS or a.cuota < 0
    if a.clave == "09":                                              # adquisición intracomunitaria: se devenga y se deduce
        if rectifica:
            r.sumar("14", a.base, i)
            r.sumar("15", a.cuota, i)
        else:
            r.sumar("10", a.base, i)
            r.sumar("11", a.cuota, i)
    elif a.isp:                                                      # inversión del sujeto pasivo: se devenga y se deduce
        if rectifica:
            r.sumar("14", a.base, i)
            r.sumar("15", a.cuota, i)
        else:
            r.sumar("12", a.base, i)
            r.sumar("13", a.cuota, i)
    elif a.deducible == 0:
        return
    if a.deducible == 0:
        return
    if rectifica:
        r.sumar("40", a.base, i)
        r.sumar("41", a.deducible, i)
        return
    if a.tipo_factura in ("F5", "LC"):
        base, cuota = ("34", "35") if a.bien_inversion else ("32", "33")
    elif a.clave == "09":
        base, cuota = ("38", "39") if a.bien_inversion else ("36", "37")
    else:
        base, cuota = ("30", "31") if a.bien_inversion else ("28", "29")
    r.sumar(base, a.base, i)
    r.sumar(cuota, a.deducible, i)


def porcentaje_de_prorrata(centesimas: int) -> int:
    """Prorrata general: el porcentaje se redondea a la unidad superior (art. 104.Tres LIVA). 7234 (72,34 %) -> 73."""
    return min(100, -(-int(centesimas) // 100))


def _deducciones_del_ejercicio(apuntes: list[Apunte], ejercicio: int, periodos: tuple[str, ...], pct: int, bloqueos: list[str]) -> int:
    """Suma de las cuotas soportadas deducibles de todos los periodos del ejercicio con una prorrata dada (la misma lógica que en cada autoliquidación)."""
    total = 0
    for p in periodos:
        sub = Resultado303(ejercicio, p, prorrata_pct=pct)
        for i, a in enumerate(apuntes):
            if a.libro == RECIBIDAS:
                _recibidas(a, i, sub)
        total += sum(sub.casillas.get(k, 0) for k in CUOTAS_DEDUCIBLES)
        bloqueos.extend(b for b in sub.bloqueos if b not in bloqueos)
    return total


def _regularizar_prorrata(apuntes: list[Apunte], r: Resultado303) -> None:
    """Casilla 44 (último periodo): deducciones con el porcentaje DEFINITIVO del año menos las practicadas con el provisional. El definitivo sale del volumen de operaciones del año (con derecho a
    deducción sobre el total, redondeado a la unidad superior). No se aplican las exclusiones del art. 104.Tres (operaciones financieras accesorias, entregas de bienes de inversión…)."""
    from .motor_390 import volumen_anual
    v = volumen_anual(apuntes, r.ejercicio)
    r.bloqueos.extend(b for b in v.bloqueos if b not in r.bloqueos)
    total, sin_derecho = v.casillas.get("108", 0), v.casillas.get("105", 0)
    if total <= 0:
        r.bloqueos.append("Prorrata general: sin operaciones en el año no se puede fijar el porcentaje definitivo.")
        return
    definitivo = min(100, -(-100 * (total - sin_derecho) // total))
    periodos = tuple(f"{m:02d}" for m in range(1, 13)) if r.periodo == "12" else ("1T", "2T", "3T", "4T")
    provisional = _deducciones_del_ejercicio(apuntes, r.ejercicio, periodos, r.prorrata_pct, r.bloqueos)
    definitiva = _deducciones_del_ejercicio(apuntes, r.ejercicio, periodos, definitivo, r.bloqueos)
    if definitiva != provisional:
        r.casillas["44"] = definitiva - provisional
    r.avisos.append(f"Prorrata general: provisional {r.prorrata_pct} %, definitiva {definitivo} % según el volumen de operaciones del año. No se aplican las exclusiones del art. 104.Tres ni se regularizan "
                    "los bienes de inversión de años anteriores (casilla 43).")


def calcular(apuntes: list[Apunte], *, ejercicio: int, periodo: str, cuotas_a_compensar_anteriores: int = 0, tributacion_foral: bool = False, criterio_caja: bool = False,
             prorrata: bool = False, regimen_simplificado: bool = False, recargo_equivalencia: bool = False, destino_negativo: str = "C", prorrata_general: int | None = None) -> Resultado303:
    """Las casillas del 303 de `periodo` («1T»…«4T» o «01»…«12») de `ejercicio` a partir de los apuntes. `cuotas_a_compensar_anteriores` (casilla 110) son las cuotas pendientes de periodos anteriores."""
    r = Resultado303(ejercicio, periodo)
    if prorrata_general is not None:
        r.prorrata_pct = porcentaje_de_prorrata(prorrata_general)
    if periodo not in tuple(f"{m:02d}" for m in range(1, 13)) + ("1T", "2T", "3T", "4T"):
        raise ErrorDeCalculo(f"periodo no válido: {periodo!r}")
    for activo, motivo in ((tributacion_foral, "tributación foral"), (prorrata, "prorrata"), (regimen_simplificado, "régimen simplificado o agrario"),
                           (recargo_equivalencia, "recargo de equivalencia")):
        if activo:
            r.bloqueos.append(f"El titular tiene {motivo}: el cálculo automático de ese caso no está soportado todavía.")
    for i, a in enumerate(apuntes):
        (_recibidas if a.libro == RECIBIDAS else _devengado_expedidas)(a, i, r)
    if criterio_caja:
        sin_clave = [a for a in apuntes if a.libro != RECIBIDAS and a.calificacion == "S1" and not a.exenta and a.clave != "07" and en_periodo(_fecha_devengo(a), ejercicio, periodo)]
        if sin_clave:
            r.avisos.append(f"El titular está en el criterio de caja y hay {len(sin_clave)} factura(s) emitida(s) de este periodo sin la clave 07: se devengan por la regla general. Si no son una excepción del régimen, "
                            "márcalas con la clave 07 y anota sus cobros.")
    if prorrata_general is not None and periodo in ("4T", "12"):
        _regularizar_prorrata(apuntes, r)
    c = r.casillas
    c["27"] = sum(c.get(k, 0) for k in CUOTAS_DEVENGADAS)
    c["45"] = sum(c.get(k, 0) for k in CUOTAS_DEDUCIBLES)
    c["46"] = c["27"] - c["45"]
    c["64"] = c["46"]
    c["65"] = 10000                                                               # 100,00 % atribuible a la Administración del Estado (sin tributación foral)
    c["66"] = _redondear(c["64"] * c["65"], 10000)
    c["110"] = max(0, int(cuotas_a_compensar_anteriores))
    c["78"] = min(c["110"], max(0, c["66"]))
    c["69"] = c["66"] - c["78"]
    c["71"] = c["69"]
    c["87"] = c["110"] - c["78"]
    for k in [k for k, v in c.items() if v == 0 and k not in ("27", "45", "46", "64", "65", "66", "69", "71")]:
        del c[k]
    if c["71"] > 0:
        r.tipo_declaracion = "I"
    elif c["71"] == 0:
        r.tipo_declaracion = "N"
    else:                                                                         # resultado a favor del contribuyente: «C» se compensa en periodos siguientes, «D» se solicita la devolución
        if destino_negativo not in ("C", "D"):
            raise ErrorDeCalculo("el destino de un resultado negativo es «C» (compensar) o «D» (devolución)")
        r.tipo_declaracion = destino_negativo
    return r


def aplicar_rectificativa(r: Resultado303, anterior: dict[str, int], *, devolucion_acordada: bool = False, destino_negativo: str = "C") -> None:
    """Convierte el cálculo de `r` en el de una autoliquidación RECTIFICATIVA, que es un 303 completo del periodo y no una diferencia. Las instrucciones oficiales del 303 dicen:
    casilla 70 = la 69 de la autoliquidación rectificada si es positiva (esté ingresada o no); casilla 109 = esa 69 sin signo si era negativa y la devolución ya se acordó;
    casilla 71 = 69 - 70 + 109; y la casilla 111 es la parte del resultado negativo que corresponde al resultado positivo de la rectificada.
    Solo se admite la PRIMERA rectificativa: en las segundas y siguientes las instrucciones remiten a ejemplos anexos que no se han incorporado."""
    c = r.casillas
    anterior_69 = int(anterior.get("69", 0))
    c70 = max(0, anterior_69)
    c109 = -anterior_69 if (anterior_69 < 0 and devolucion_acordada) else 0
    c["71"] = c["69"] - c70 + c109
    c111 = min(c70, -c["71"]) if c["71"] < 0 else 0
    for casilla, valor in (("70", c70), ("109", c109), ("111", c111)):
        if valor:
            c[casilla] = valor
        else:
            c.pop(casilla, None)
    if c["71"] > 0:
        r.tipo_declaracion = "I"
    elif c["71"] == 0:
        r.tipo_declaracion = "N"
    else:
        if destino_negativo not in ("C", "D"):
            raise ErrorDeCalculo("el destino de un resultado negativo es «C» (compensar) o «D» (devolución)")
        r.tipo_declaracion = destino_negativo
