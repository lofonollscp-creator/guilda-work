"""Motor de cálculo del **modelo 131** (IRPF, pago fraccionado de empresarios y profesionales en **estimación objetiva**, «módulos»), con las instrucciones oficiales de la AEAT
(`docs/fuentes-oficiales/aeat/131_instrucciones.html`). Función PURA: recibe los importes ya reunidos y devuelve las casillas.

Qué NO hace, y lo dice en `avisos` o lo bloquea: calcular el rendimiento neto de cada actividad (sale de los signos o módulos, los índices correctores y los incentivos de la Orden de módulos de cada año, y los
datos-base de la actividad no los tiene Guilda: se teclea), las actividades de temporada y las que empiezan o cesan a mitad de año (el cálculo lo fija la Orden anual), la deducción por vivienda habitual
(casilla 12, solo para quien la adquirió antes de 2013) y la autoliquidación complementaria (casilla 14).

Importes en céntimos; los porcentajes, en centésimas de punto (200 = 2,00 %). La casilla 10 y las que dependen de ella (13 y 15) pueden ser negativas; el resto no."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .motor_130 import minoracion as _minoracion

# Apartado I: porcentaje según las unidades del módulo «personal asalariado» en la fecha de cómputo de los datos-base (instrucciones, casilla 02)
PORCENTAJE_SIN_ASALARIADOS, PORCENTAJE_HASTA_UNO, PORCENTAJE_MAS_DE_UNO = 200, 300, 400
PORCENTAJE_II_Y_III = 200                       # casillas 04 y 06
REDUCCION_CEUTA_MELILLA = (4, 10)               # los porcentajes se multiplican por 0,4
REDUCCION_JOVEN_AGRICULTOR = (3, 4)             # el pago fraccionado de las explotaciones prioritarias se reduce un 25 %: se paga el 75 %
MAX_ACTIVIDADES = 5                             # la página 1 recoge cinco actividades del apartado I
TRIMESTRES = ("1T", "2T", "3T", "4T")
# código del tramo de la casilla 09 en el fichero (Nota 3 del diseño): hasta 9.000, 10.000, 11.000 y 12.000 €
TRAMOS_FICHERO = ((900000, "1"), (1000000, "2"), (1100000, "3"), (1200000, "4"))


@dataclass
class Resultado131:
    ejercicio: int
    periodo: str
    modelo: str = "131"
    casillas: dict[str, int] = field(default_factory=dict)
    bloqueos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    tipo_declaracion: str = "N"
    filas: list[dict] = field(default_factory=list)          # apartado I: epígrafe, rendimiento, porcentaje (centésimas) y resultado de cada actividad
    detalle: dict = field(default_factory=dict)              # datos que el fichero lleva y no son casillas (apartados II y III, tramo de la 09)

    @property
    def calculable(self) -> bool:
        return not self.bloqueos


def _por_porcentaje(importe: int, centesimas: int) -> int:
    """`importe` por un porcentaje en centésimas de punto, redondeado al céntimo (mitad hacia arriba)."""
    return (importe * centesimas + 5000) // 10000


def _de_prioritarias(importe: int, centesimas: int) -> int:
    """Pago fraccionado de las explotaciones prioritarias: el 75 % de la cuota (reducción del 25 %), redondeado al céntimo."""
    return (importe * centesimas * REDUCCION_JOVEN_AGRICULTOR[0] + 5000 * REDUCCION_JOVEN_AGRICULTOR[1]) // (10000 * REDUCCION_JOVEN_AGRICULTOR[1])


def _con_ceuta(centesimas: int) -> int:
    return centesimas * REDUCCION_CEUTA_MELILLA[0] // REDUCCION_CEUTA_MELILLA[1]


def porcentaje_del_apartado_i(asalariados: Decimal | float | int) -> int:
    """2, 3 o 4 % según las unidades del módulo de personal asalariado (0,00 · de 0,01 a 1 · 1,01 o más)."""
    u = Decimal(str(asalariados))
    if u <= 0:
        return PORCENTAJE_SIN_ASALARIADOS
    return PORCENTAJE_HASTA_UNO if u <= 1 else PORCENTAJE_MAS_DE_UNO


def tramo_de_minoracion(rendimiento_anterior: int | None) -> str:
    """Código del fichero para los rendimientos netos del ejercicio anterior (1 a 4) o «0» si no hay minoración."""
    if rendimiento_anterior is None:
        return "0"
    for hasta, codigo in TRAMOS_FICHERO:
        if rendimiento_anterior <= hasta:
            return codigo
    return "0"


def _superior(centesimas: int | None, aplicable: int, donde: str, r: Resultado131) -> int:
    """El porcentaje que se aplica: el de la norma o el superior que elija el contribuyente (nunca inferior, art. 110.4 del Reglamento)."""
    if centesimas is None:
        return aplicable
    if centesimas < aplicable:
        r.bloqueos.append(f"{donde}: el porcentaje elegido ({centesimas / 100:g} %) es inferior al que fija la norma ({aplicable / 100:g} %): solo se permiten porcentajes superiores.")
        return aplicable
    return centesimas


def calcular(*, ejercicio: int, periodo: str, actividades: list[dict] | None = None, ventas_ii: int = 0, ceuta_ii: bool = False, superior_ii: int | None = None,
             ingresos_iii: int = 0, ingresos_iii_prioritarias: int = 0, ingresos_iii_ceuta: int = 0, ingresos_iii_ceuta_prioritarias: int = 0, superior_iii: int | None = None,
             retenciones: int = 0, rendimiento_anterior: int | None = None, negativos_previos: int = 0) -> Resultado131:
    """Las casillas del 131 del trimestre `periodo` («1T»…«4T»).

    `actividades` (apartado I): `[{"epigrafe", "rendimiento_neto" (céntimos, el que se declara en la casilla del epígrafe), "asalariados" (unidades del módulo de personal asalariado),
    "superior" (centésimas, opcional), "ceuta_melilla" (bool)}]`. `ventas_ii`: volumen de ventas o ingresos del trimestre de las actividades sin datos-base (casilla 03). `ingresos_iii*`: ingresos del trimestre de las
    actividades agrícolas, ganaderas y forestales, por separado los de explotaciones prioritarias (jóvenes agricultores) y los obtenidos en Ceuta, Melilla o La Palma. `negativos_previos`: resultados negativos de la
    casilla 15 de los 131 anteriores del mismo ejercicio aún sin deducir. `rendimiento_anterior`: rendimientos netos de actividades del ejercicio anterior, para la minoración de la casilla 09."""
    r = Resultado131(ejercicio, periodo)
    if periodo not in TRIMESTRES:
        r.bloqueos.append(f"Periodo no válido: {periodo!r} (el 131 es trimestral).")
        return r
    actividades = list(actividades or [])
    for nombre, valor in (("Las ventas del apartado II", ventas_ii), ("Los ingresos del apartado III", ingresos_iii), ("Los ingresos de explotaciones prioritarias", ingresos_iii_prioritarias),
                          ("Los ingresos obtenidos en Ceuta, Melilla o La Palma", ingresos_iii_ceuta), ("Los ingresos prioritarios de Ceuta, Melilla o La Palma", ingresos_iii_ceuta_prioritarias),
                          ("Las retenciones", retenciones), ("Los resultados negativos anteriores", negativos_previos)):
        if valor < 0:
            r.bloqueos.append(f"{nombre} salen negativos ({valor / 100:.2f} €): el modelo no admite esa casilla en negativo.")
    if len(actividades) > MAX_ACTIVIDADES:
        r.bloqueos.append(f"El apartado I recoge como máximo {MAX_ACTIVIDADES} actividades.")
    for i, a in enumerate(actividades[:MAX_ACTIVIDADES], 1):
        epigrafe = str(a.get("epigrafe") or "").strip().upper()
        if not re.fullmatch(r"[0-9A-Z]{1,4}", epigrafe):
            r.bloqueos.append(f"Actividad {i}: el epígrafe del IAE «{epigrafe}» no es válido (hasta cuatro cifras o letras).")
        rendimiento = int(a.get("rendimiento_neto") or 0)
        if rendimiento < 0:
            r.bloqueos.append(f"Actividad {i}: el rendimiento neto no puede ser negativo.")
        base = porcentaje_del_apartado_i(a.get("asalariados") or 0)
        if a.get("ceuta_melilla"):
            base = _con_ceuta(base)
        pct = _superior(a.get("superior"), base, f"Actividad {i}", r)
        r.filas.append({"epigrafe": epigrafe, "rendimiento_neto": rendimiento, "porcentaje": pct, "resultado": _por_porcentaje(rendimiento, pct)})
    if r.bloqueos:
        return r
    c = r.casillas
    if r.filas:
        c["01"] = sum(f["rendimiento_neto"] for f in r.filas)
        c["02"] = sum(f["resultado"] for f in r.filas)
    if ventas_ii:
        pct = _superior(superior_ii, _con_ceuta(PORCENTAJE_II_Y_III) if ceuta_ii else PORCENTAJE_II_Y_III, "Apartado II", r)
        c["03"], c["04"] = ventas_ii, _por_porcentaje(ventas_ii, pct)
        r.detalle["ii"] = {"ceuta": ceuta_ii, "superior": superior_ii}
    if ingresos_iii or ingresos_iii_prioritarias or ingresos_iii_ceuta or ingresos_iii_ceuta_prioritarias:
        ordinario = _superior(superior_iii, PORCENTAJE_II_Y_III, "Apartado III", r)
        ceuta = _superior(superior_iii, _con_ceuta(PORCENTAJE_II_Y_III), "Apartado III (Ceuta, Melilla o La Palma)", r)
        c["05"] = ingresos_iii + ingresos_iii_prioritarias + ingresos_iii_ceuta + ingresos_iii_ceuta_prioritarias
        c["06"] = (_por_porcentaje(ingresos_iii, ordinario) + _de_prioritarias(ingresos_iii_prioritarias, ordinario)
                   + _por_porcentaje(ingresos_iii_ceuta, ceuta) + _de_prioritarias(ingresos_iii_ceuta_prioritarias, ceuta))
        r.detalle["iii"] = {"ordinarios": ingresos_iii, "prioritarias": ingresos_iii_prioritarias, "ceuta": ingresos_iii_ceuta, "ceuta_prioritarias": ingresos_iii_ceuta_prioritarias, "superior": superior_iii}
        if ingresos_iii_prioritarias or ingresos_iii_ceuta_prioritarias:
            r.avisos.append("Las explotaciones prioritarias pagan el 75 % de la cuota (reducción del 25 % de los jóvenes agricultores o asalariados agrarios, disposición adicional sexta de la Ley del IRPF): "
                            "comprueba que se cumplen los requisitos.")
    if r.bloqueos:
        return r
    c["07"] = c.get("02", 0) + c.get("04", 0) + c.get("06", 0)
    c["08"] = retenciones
    c["09"] = _minoracion(rendimiento_anterior)
    r.detalle["tramo_minoracion"] = tramo_de_minoracion(rendimiento_anterior)
    c["10"] = c["07"] - c["08"] - c["09"]
    c["11"] = min(negativos_previos, c["10"]) if c["10"] > 0 else 0
    c["12"] = 0
    c["13"] = c["10"] - c["11"] - c["12"]
    c["14"] = 0
    c["15"] = c["13"] - c["14"]
    if c["15"] > 0:
        r.tipo_declaracion = "I"
    elif c["15"] == 0:
        r.tipo_declaracion = "N"
    else:                                                       # negativo: a deducir en los siguientes pagos (1T a 3T) o negativa (4T)
        r.tipo_declaracion = "B" if periodo != "4T" else "N"
    for k in [k for k, v in c.items() if v == 0 and k not in ("07", "08", "10", "13", "15")]:
        del c[k]
    if not r.filas and not ventas_ii and "05" not in c:
        r.avisos.append("No hay ninguna actividad declarada: el resultado es cero. Si el titular ejerce actividades en módulos, indica al menos una.")
    if r.filas:
        r.avisos.append("El rendimiento neto de cada actividad de la casilla 01 lo calculas tú con los signos o módulos, los índices correctores y los incentivos de la Orden de módulos del año: Guilda no tiene "
                        "los datos-base de la actividad. Las actividades de temporada y las que empiezan o cesan a mitad de año se rigen por la Orden anual y no se calculan aquí.")
    if c.get("09"):
        r.avisos.append("Si además presentas el modelo 130, la minoración por rendimientos bajos se puede repartir entre los dos modelos sin que la suma de las casillas 13 del 130 y 09 del 131 supere el importe.")
    if c["07"] and c["08"] > c["07"]:
        r.avisos.append("Las retenciones superan el pago fraccionado previo: la casilla 10 sale negativa.")
    r.avisos.append("La deducción por vivienda habitual (casilla 12), la autoliquidación complementaria (casilla 14) y el cálculo de los datos-base de cada módulo no están soportados.")
    return r
