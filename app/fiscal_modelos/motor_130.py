"""Motor de cálculo del **modelo 130** (IRPF, pago fraccionado de empresarios y profesionales en **estimación directa**), apartados I y III, con las instrucciones oficiales de la AEAT
(`docs/fuentes-oficiales/aeat/130_instrucciones.html`). Función PURA: recibe los importes acumulados del año (ya sumados) y devuelve las casillas.

Qué NO calcula, y por eso lo dice en `avisos` o lo bloquea: actividades agrícolas, ganaderas, forestales y pesqueras (apartado II, casillas 08 a 11), la deducción por rentas en Ceuta y Melilla (8 %), la deducción por
vivienda habitual (casilla 16), la autoliquidación complementaria (casilla 18), las amortizaciones y las provisiones (se aportan a mano como «otros gastos»), ni los rendimientos con reducción del art. 32.1 LIRPF.

Importes en céntimos; las casillas con signo (03, 07, 14, 17, 19) pueden ser negativas y el resto no."""
from __future__ import annotations

from dataclasses import dataclass, field

PORCENTAJE = 2000                      # 20 % en centésimas de punto
DIFICIL_JUSTIFICACION_PCT = 500        # 5 % del rendimiento neto previo positivo (modalidad simplificada, art. 30 RIRPF)
DIFICIL_JUSTIFICACION_MAXIMO = 200000  # 2.000 € al año
# minoración por rendimientos netos bajos del ejercicio anterior (instrucciones, casilla 13): (hasta, importe) en céntimos
TRAMOS_MINORACION = ((900000, 10000), (1000000, 7500), (1100000, 5000), (1200000, 2500))


@dataclass
class Resultado130:
    ejercicio: int
    periodo: str
    modelo: str = "130"
    casillas: dict[str, int] = field(default_factory=dict)
    bloqueos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    tipo_declaracion: str = "N"

    @property
    def calculable(self) -> bool:
        return not self.bloqueos


def _veinte_por_cien(importe: int) -> int:
    """20 % de un importe positivo, redondeado al céntimo (mitad hacia arriba)."""
    return (importe * PORCENTAJE + 5000) // 10000


def minoracion(rendimiento_anterior: int | None) -> int:
    """Casilla 13: importe según los rendimientos netos de actividades del ejercicio anterior. Más de 12.000 € (o dato desconocido) = 0."""
    if rendimiento_anterior is None:
        return 0
    for hasta, importe in TRAMOS_MINORACION:
        if rendimiento_anterior <= hasta:
            return importe
    return 0


def calcular(*, ejercicio: int, periodo: str, ingresos: int, gastos: int, retenciones: int, pagos_previos: int = 0, negativos_previos: int = 0, rendimiento_anterior: int | None = None,
             simplificada: bool = False) -> Resultado130:
    """Las casillas del 130 del trimestre `periodo` («1T»…«4T»). Todos los importes son ACUMULADOS desde el 1 de enero hasta el fin del trimestre, salvo `pagos_previos` (casilla 05: suma de las casillas 07
    positivas de los trimestres anteriores menos sus casillas 16) y `negativos_previos` (resultados negativos de la casilla 19 de trimestres anteriores aún sin deducir)."""
    r = Resultado130(ejercicio, periodo)
    if periodo not in ("1T", "2T", "3T", "4T"):
        r.bloqueos.append(f"Periodo no válido: {periodo!r} (el 130 es trimestral).")
        return r
    for nombre, valor in (("Los ingresos computables", ingresos), ("Los gastos deducibles", gastos), ("Las retenciones soportadas", retenciones), ("Los pagos de trimestres anteriores", pagos_previos),
                          ("Los resultados negativos anteriores", negativos_previos)):
        if valor < 0:
            r.bloqueos.append(f"{nombre} salen negativos ({valor / 100:.2f} €): el modelo no admite esa casilla en negativo. Revisa los abonos y las rectificativas.")
    if r.bloqueos:
        return r
    c = r.casillas
    if simplificada:
        previo = ingresos - gastos
        dificil = min(max(0, (previo * DIFICIL_JUSTIFICACION_PCT + 5000) // 10000), DIFICIL_JUSTIFICACION_MAXIMO)
        gastos += dificil
        r.avisos.append(f"Estimación directa simplificada: se han añadido {dificil / 100:.2f} € de gastos de difícil justificación (5 % del rendimiento previo positivo, hasta 2.000 € al año, art. 30 del Reglamento).")
    c["01"], c["02"] = ingresos, gastos
    c["03"] = ingresos - gastos
    c["04"] = _veinte_por_cien(max(0, c["03"]))
    c["05"] = pagos_previos
    c["06"] = retenciones
    c["07"] = c["04"] - c["05"] - c["06"]
    c["12"] = max(0, c["07"])                                   # no hay apartado II: la casilla 12 es la 07 y, si sale negativa, cero
    c["13"] = minoracion(rendimiento_anterior)
    if c["13"] > c["12"]:
        r.avisos.append(f"La minoración por rendimientos bajos ({c['13'] / 100:.2f} €) se ha limitado al pago fraccionado del trimestre ({c['12'] / 100:.2f} €): no genera resultado negativo por sí sola.")
        c["13"] = c["12"]
    c["14"] = c["12"] - c["13"]
    c["15"] = min(negativos_previos, c["14"]) if c["14"] > 0 else 0
    c["16"] = 0
    c["17"] = c["14"] - c["15"] - c["16"]
    c["19"] = c["17"]                                           # sin complementaria, la casilla 18 es cero
    if c["19"] > 0:
        r.tipo_declaracion = "I"
    elif c["19"] == 0:
        r.tipo_declaracion = "N"
    else:                                                       # negativo: a deducir en los siguientes pagos (1T a 3T) o negativa (4T)
        r.tipo_declaracion = "B" if periodo != "4T" else "N"
    for k in [k for k, v in c.items() if v == 0 and k not in ("01", "02", "03", "04", "07", "12", "14", "17", "19")]:
        del c[k]
    if c["07"] < 0:
        r.avisos.append("La casilla 07 sale negativa: el modelo no la compensa con otros trimestres por sí mismo (no se computa en la casilla 05 de los siguientes).")
    r.avisos.append("Apartado II (actividades agrícolas, ganaderas, forestales y pesqueras), deducción por Ceuta y Melilla, deducción por vivienda habitual (casilla 16) y complementarias no están soportados.")
    return r
