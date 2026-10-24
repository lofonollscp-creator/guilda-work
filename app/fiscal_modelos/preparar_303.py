"""De los apuntes al borrador del 303 en un solo paso: valida, calcula y (si es posible) genera el fichero importable. NO presenta ni aprueba nada: devuelve el borrador y, junto a él, todo lo que
una persona debe mirar antes (errores de los datos, avisos, bloqueos del cálculo). Si hay errores en los datos, no se genera fichero."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import fichero_303, motor_303, validacion_apuntes
from .apuntes import Apunte


@dataclass
class Borrador303:
    resultado: motor_303.Resultado303
    problemas: list[validacion_apuntes.Problema] = field(default_factory=list)
    fichero: bytes | None = None
    motivo_sin_fichero: str = ""

    @property
    def listo_para_revisar(self) -> bool:
        return self.fichero is not None and not validacion_apuntes.errores(self.problemas)


def preparar(apuntes: list[Apunte], *, ejercicio: int, periodo: str, nif: str, nombre: str, hoy: date | None = None, **ajustes) -> Borrador303:
    """`ajustes` son los de `motor_303.calcular` (cuotas_a_compensar_anteriores, criterio_caja, prorrata, destino_negativo…)."""
    problemas = validacion_apuntes.validar(apuntes, hoy=hoy, nif_titular=nif)
    resultado = motor_303.calcular(apuntes, ejercicio=ejercicio, periodo=periodo, **ajustes)
    b = Borrador303(resultado, problemas)
    if validacion_apuntes.errores(problemas):
        b.motivo_sin_fichero = "Hay errores en los datos de las facturas: corrígelos antes de generar el fichero."
    elif not resultado.calculable:
        b.motivo_sin_fichero = "El cálculo está bloqueado: " + " · ".join(resultado.bloqueos[:3])
    else:
        try:
            b.fichero = fichero_303.generar(resultado, nif=nif, nombre=nombre)
        except fichero_303.FicheroNoGenerable as e:
            b.motivo_sin_fichero = str(e)
    return b
