"""Motor de cálculo del **modelo 303** (IVA): de los apuntes de los libros registro a las casillas de la autoliquidación. Es una función PURA (sin base de datos, sin red, sin IA): los mismos apuntes dan siempre
las mismas casillas, y cada casilla sabe de qué apuntes sale (`Resultado303.origen`) para poder explicarla.

Las reglas son las de la tabla oficial de la AEAT «Cálculo de casillas del 303 desde los libros registro» (`docs/fuentes-oficiales/aeat/CALCULO_CASILLAS_IVA_PRE303-LSI.xlsx`) y se contrastan con la propia AEAT
(`scripts/fiscal/simulador_libros.py`: el mismo libro se sube al simulador público y se comparan las casillas). **Lo que no está soportado no se calcula: se BLOQUEA** (`bloqueos`) en vez de dar un número que
podría ser falso: criterio de caja, recargo de equivalencia, prorrata, régimen simplificado y agrario, OSS, tributación foral, compensaciones, regularización de inversiones, claves de operación y tipos no contemplados…

Importes en céntimos enteros (con signo), porcentajes en centésimas; el redondeo es al céntimo, mitad hacia arriba."""
from __future__ import annotations

from dataclasses import dataclass, field

from .apuntes import RECIBIDAS, RECTIFICATIVAS, Apunte, en_periodo, periodo_de

CLAVES_DEVENGO_S1 = {"01", "11", "12", "13", "15", "03", "05", "09"}
TIPOS_EMITIDAS_NORMALES = {"F1", "F2", "F4"}
TIPOS_RECIBIDAS_NORMALES = {"F1", "F3", "F4", "F6"}
# tipo de IVA (centésimas) -> (casilla de base, casilla de cuota) del régimen general
CASILLAS_TIPO = {0: ("150", "152"), 400: ("01", "03"), 500: ("154", "155"), 1000: ("04", "06"), 2100: ("07", "09")}
CUOTAS_DEVENGADAS = ("152", "03", "155", "06", "09", "11", "13", "15")                 # casilla 27 (las demás del diseño —recargo, 167, 170— están bloqueadas)
CUOTAS_DEDUCIBLES = ("29", "31", "33", "35", "37", "39", "41")                         # casilla 45 (42, 43 y 44 están bloqueadas)


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


def _devengado_expedidas(a: Apunte, i: int, r: Resultado303) -> None:
    if not en_periodo(_fecha_devengo(a), r.ejercicio, r.periodo):
        return
    if a.tipo_factura not in TIPOS_EMITIDAS_NORMALES | set(RECTIFICATIVAS):
        r.bloqueos.append(f"Expedida {a.serie}{a.numero}: el tipo de factura {a.tipo_factura} no está soportado.")
        return
    if a.clave in ("07", "17"):
        r.bloqueos.append(f"Expedida {a.serie}{a.numero}: la clave {a.clave} (criterio de caja / ventanilla única) no está soportada.")
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
        return
    if a.tipo_iva not in CASILLAS_TIPO:
        r.bloqueos.append(f"Expedida {a.serie}{a.numero}: el tipo de IVA {a.tipo_iva / 100:g} % no está soportado (solo 0, 4, 5, 10 y 21).")
        return
    base, cuota = CASILLAS_TIPO[a.tipo_iva]
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


def _recibidas(a: Apunte, i: int, r: Resultado303) -> None:
    if not _periodo_de_deduccion(a, r):
        return
    nombre = f"Recibida {a.serie}{a.numero}"
    if a.tipo_factura not in TIPOS_RECIBIDAS_NORMALES | set(RECTIFICATIVAS) | {"F5", "LC"}:
        r.bloqueos.append(f"{nombre}: el tipo de factura {a.tipo_factura} no está soportado.")
        return
    if a.clave in ("07", "02"):
        r.bloqueos.append(f"{nombre}: la clave {a.clave} (criterio de caja / régimen agrario) no está soportada.")
        return
    if a.clave not in ("01", "09", "12"):
        r.bloqueos.append(f"{nombre}: la clave de operación {a.clave} no está soportada en las recibidas.")
        return
    if a.cuota_deducible is not None and a.cuota_deducible not in (0, a.cuota):
        r.bloqueos.append(f"{nombre}: deducción parcial (prorrata o afectación) no soportada.")
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


def calcular(apuntes: list[Apunte], *, ejercicio: int, periodo: str, cuotas_a_compensar_anteriores: int = 0, tributacion_foral: bool = False, criterio_caja: bool = False,
             prorrata: bool = False, regimen_simplificado: bool = False, recargo_equivalencia: bool = False, destino_negativo: str = "C") -> Resultado303:
    """Las casillas del 303 de `periodo` («1T»…«4T» o «01»…«12») de `ejercicio` a partir de los apuntes. `cuotas_a_compensar_anteriores` (casilla 110) son las cuotas pendientes de periodos anteriores."""
    r = Resultado303(ejercicio, periodo)
    if periodo not in tuple(f"{m:02d}" for m in range(1, 13)) + ("1T", "2T", "3T", "4T"):
        raise ErrorDeCalculo(f"periodo no válido: {periodo!r}")
    for activo, motivo in ((tributacion_foral, "tributación foral"), (criterio_caja, "criterio de caja"), (prorrata, "prorrata"), (regimen_simplificado, "régimen simplificado o agrario"),
                           (recargo_equivalencia, "recargo de equivalencia")):
        if activo:
            r.bloqueos.append(f"El titular tiene {motivo}: el cálculo automático de ese caso no está soportado todavía.")
    for i, a in enumerate(apuntes):
        (_recibidas if a.libro == RECIBIDAS else _devengado_expedidas)(a, i, r)
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
