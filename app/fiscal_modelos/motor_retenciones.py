"""Motor de cálculo de los **modelos 111** (retenciones de trabajo y actividades profesionales) y **115** (retenciones de alquileres): de las retenciones de los apuntes recibidos a las casillas. Función PURA, como
`motor_303`: las mismas retenciones dan siempre las mismas casillas y cada casilla sabe de qué retenciones sale (`origen`).

**Es una simulación, no una declaración.** Falta el diseño de registro oficial de la AEAT de estos modelos, así que no hay fichero ni presentación, y las casillas siguen la numeración del formulario, que se contrastará con
ese diseño antes de exportar nada. Lo que no está soportado no se calcula, se BLOQUEA: percepciones en especie, premios, ganancias forestales, derechos de imagen, retenciones a no residentes…

La retención se imputa al periodo de la fecha de expedición de la factura (la norma la devenga al pagar: es una aproximación que se avisa). Importes en céntimos (con signo: un abono resta), porcentajes en centésimas."""
from __future__ import annotations

from dataclasses import dataclass, field

CASILLAS_111 = {"A": ("01", "02", "03"), "G": ("07", "08", "09")}         # clave -> (perceptores, importe de las percepciones, retenciones)
CONCEPTOS_111 = {"01": "Rendimientos del trabajo: perceptores", "02": "Rendimientos del trabajo: importe de las percepciones", "03": "Rendimientos del trabajo: retenciones",
                 "07": "Actividades económicas: perceptores", "08": "Actividades económicas: importe de las percepciones", "09": "Actividades económicas: retenciones",
                 "28": "Total de retenciones e ingresos a cuenta", "29": "A deducir (declaraciones anteriores)", "30": "Resultado de la liquidación"}
CONCEPTOS_115 = {"01": "Número de perceptores", "02": "Base de las retenciones", "03": "Retenciones e ingresos a cuenta", "04": "A deducir (declaraciones anteriores)", "05": "Resultado de la liquidación"}


@dataclass(frozen=True)
class Retencion:
    modelo: str                  # "111" | "115"
    clave: str                   # 111: "G" actividades profesionales · "A" trabajo; 115: ""
    base: int                    # céntimos
    importe: int                 # céntimos
    nif: str = ""                # perceptor (para contar perceptores distintos)


@dataclass
class ResultadoRetenciones:
    modelo: str
    ejercicio: int
    periodo: str
    casillas: dict[str, int] = field(default_factory=dict)
    origen: dict[str, list[int]] = field(default_factory=dict)
    bloqueos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    tipo_declaracion: str = "N"

    @property
    def calculable(self) -> bool:
        return not self.bloqueos


def _perceptor(r: Retencion, i: int) -> str:
    return (r.nif or "").strip().upper() or f"#{i}"          # sin NIF, cada retención cuenta como un perceptor y se avisa


def calcular(retenciones: list[Retencion], *, modelo: str, ejercicio: int, periodo: str, a_deducir: int = 0) -> ResultadoRetenciones:
    """Las casillas del `modelo` («111» o «115») para las retenciones del periodo. `a_deducir`: resultado de declaraciones anteriores que se descuenta (casilla 29 del 111, 04 del 115)."""
    if modelo not in ("111", "115"):
        raise ValueError(f"modelo no soportado: {modelo!r}")
    if periodo not in tuple(f"{m:02d}" for m in range(1, 13)) + ("1T", "2T", "3T", "4T"):
        raise ValueError(f"periodo no válido: {periodo!r}")
    r = ResultadoRetenciones(modelo, ejercicio, periodo)
    perceptores: dict[str, set[str]] = {}
    sin_nif = False
    for i, ret in enumerate(retenciones):
        if ret.modelo != modelo:
            continue
        clave = ret.clave if modelo == "111" else ""
        if modelo == "111" and clave not in CASILLAS_111:
            r.bloqueos.append(f"Clave de percepción {clave!r} no soportada todavía.")
            continue
        n, base, imp = CASILLAS_111[clave] if modelo == "111" else ("01", "02", "03")
        sin_nif = sin_nif or not (ret.nif or "").strip()
        perceptores.setdefault(n, set()).add(_perceptor(ret, i))
        for cas, valor in ((base, ret.base), (imp, ret.importe)):
            r.casillas[cas] = r.casillas.get(cas, 0) + valor
            r.origen.setdefault(cas, []).append(i)
    for n, quienes in perceptores.items():
        r.casillas[n] = len(quienes)
    if sin_nif:
        r.avisos.append("Hay retenciones sin NIF del perceptor: se cuenta cada una como un perceptor distinto. Complétalo para que el número sea exacto.")
    c = r.casillas
    if modelo == "111":
        c["28"] = c.get("03", 0) + c.get("09", 0)
        c["29"] = max(0, int(a_deducir))
        c["30"] = c["28"] - c["29"]
        resultado = c["30"]
    else:
        c["04"] = max(0, int(a_deducir))
        c["05"] = c.get("03", 0) - c["04"]
        resultado = c["05"]
    if resultado < 0:
        r.bloqueos.append("El resultado sale negativo: revisa las retenciones del periodo y lo que se deduce de declaraciones anteriores.")
    r.tipo_declaracion = "I" if resultado > 0 else "N"
    r.avisos.append("La retención se imputa al periodo de la fecha de la factura; la norma la devenga al pagarla. Comprueba los pagos del periodo antes de presentar.")
    return r
