"""Del resultado de `motor_131` al fichero importable del **modelo 131**, con el diseño de registro OFICIAL (`disenos/131_2026.json`, extraído de `DR131_2026.xlsx`). Es un fichero **de prueba**: lleva la
página 1 (identificación, actividades del apartado I con epígrafe, rendimiento, porcentaje y resultado, apartados II y III, total) y el IBAN de domiciliación si se da. No lleva las páginas de detalle de cada
actividad (módulos, índices correctores, número de vehículos…): los datos-base no los tiene Guilda, y se completan en el formulario. Se importa en el formulario o en el simulador de la AEAT antes de presentar nada."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from . import iban as iban_mod
from .exportador_303 import ErrorDeFormato, PERIODOS, _pagina, formatear
from .motor_131 import MAX_ACTIVIDADES, Resultado131

DISENO_131 = Path(__file__).resolve().parent / "disenos" / "131_2026.json"
# nº de campo de la página 1: cada actividad del apartado I ocupa cuatro (epígrafe, rendimiento, porcentaje, resultado)
FILAS_ACTIVIDAD = tuple((13 + 4 * i, 14 + 4 * i, 15 + 4 * i, 16 + 4 * i) for i in range(MAX_ACTIVIDADES))
CEUTA_II, VENTAS_II, SUPERIOR_II = 35, 36, 37
INGRESOS_III = {"ordinarios": 43, "prioritarias": 44, "superior": 45, "ceuta": 46, "ceuta_prioritarias": 47, "superior_ceuta": 48}
TRAMO_MINORACION = 56
PAGINA_CUENTA, CUENTA_IBAN = "DID", 5                            # la página de domiciliación del 131 (hoja «DID»): el IBAN es su campo 5


class FicheroNoGenerable(ValueError):
    pass


def cargar_diseno() -> dict:
    return json.loads(DISENO_131.read_text(encoding="utf-8"))


def _euros(centimos: int) -> Decimal:
    return Decimal(centimos) / 100


def _valores_pagina(r: Resultado131, nif: str, nombre: str) -> dict:
    valores: dict = {6: r.tipo_declaracion, 7: nif, 8: nombre, 10: r.ejercicio, 11: r.periodo}
    for casilla, valor in r.casillas.items():
        valores[casilla] = _euros(valor)
    for (n_epigrafe, n_rend, n_pct, n_res), fila in zip(FILAS_ACTIVIDAD, r.filas):
        valores.update({n_epigrafe: fila["epigrafe"], n_rend: _euros(fila["rendimiento_neto"]), n_pct: _euros(fila["porcentaje"]), n_res: _euros(fila["resultado"])})
    ii = r.detalle.get("ii")
    if ii:
        valores[CEUTA_II] = "1" if ii["ceuta"] else "2"
        valores[VENTAS_II] = _euros(r.casillas.get("03", 0))
        if ii["superior"] is not None:
            valores[SUPERIOR_II] = _euros(ii["superior"])
    iii = r.detalle.get("iii")
    if iii:
        for clave in ("ordinarios", "prioritarias", "ceuta", "ceuta_prioritarias"):
            if iii[clave]:
                valores[INGRESOS_III[clave]] = _euros(iii[clave])
        if iii["superior"] is not None:
            valores[INGRESOS_III["superior"]] = _euros(iii["superior"])
            if iii["ceuta"] or iii["ceuta_prioritarias"]:
                valores[INGRESOS_III["superior_ceuta"]] = _euros(iii["superior"])
    if r.detalle.get("tramo_minoracion", "0") != "0":
        valores[TRAMO_MINORACION] = r.detalle["tramo_minoracion"]
    return valores


def generar(r: Resultado131, *, nif: str, nombre: str, iban: str | None = None, diseno: dict | None = None) -> bytes:
    if not r.calculable:
        raise FicheroNoGenerable("El cálculo está bloqueado: " + " · ".join(r.bloqueos[:3]))
    if r.periodo not in PERIODOS or r.periodo not in ("1T", "2T", "3T", "4T"):
        raise FicheroNoGenerable(f"periodo no válido: {r.periodo!r}")
    diseno = diseno or cargar_diseno()
    envoltura = {c["n"]: c for c in diseno["paginas"][0]["campos"]}
    cabecera = "".join(formatear(envoltura[1], None) + formatear(envoltura[2], None) + formatear(envoltura[3], None) + formatear(envoltura[4], str(r.ejercicio)) + formatear(envoltura[5], r.periodo)
                       + "".join(formatear(envoltura[n], None) for n in (6, 7, 8, 9, 10, 11, 12, 13)))
    cuerpo = _pagina(diseno["paginas"][1], _valores_pagina(r, nif, nombre))
    if iban:
        try:
            limpio = iban_mod.validar(iban)
        except iban_mod.IbanNoValido as e:
            raise FicheroNoGenerable(f"IBAN no válido: {e}") from None
        pagina_did = next(p for p in diseno["paginas"] if p["hoja"] == PAGINA_CUENTA)
        cuerpo += _pagina(pagina_did, {CUENTA_IBAN: limpio})
    return (cabecera + cuerpo + f"</T1310{r.ejercicio}{r.periodo}0000>").encode("iso-8859-15")


def leer_campos(datos: bytes, diseno: dict | None = None) -> dict[int, str]:
    """Los campos de la página 1 del fichero, por número (para comprobar lo generado)."""
    diseno = diseno or cargar_diseno()
    texto = datos.decode("iso-8859-15")
    pagina = diseno["paginas"][1]
    inicio = texto.index("<T13101000>")
    bloque, salida, p0 = texto[inicio:inicio + pagina["total_posiciones"]], {}, 0
    for c in pagina["campos"]:
        salida[c["n"]] = bloque[p0:p0 + c["lon"]]
        p0 += c["lon"]
    return salida


__all__ = ["generar", "leer_campos", "cargar_diseno", "FicheroNoGenerable", "ErrorDeFormato"]
