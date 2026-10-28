"""Del resultado de `motor_retenciones` (casillas) al fichero importable de los **modelos 111 y 115**, con los diseños de registro OFICIALES de la AEAT (`disenos/111_v18.json`, `disenos/115_v13.json`,
extraídos de los `.xls` descargados). Posiciones, longitudes y constantes salen del diseño; aquí solo se decide qué casilla va en qué campo. Es un fichero **de prueba**: no hay un fichero exportado por el
formulario oficial con el que contrastar la codificación, así que se importa en el simulador de la AEAT antes de presentar nada."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .exportador_303 import ErrorDeFormato, PERIODOS, _decimales, _pagina, formatear
from .motor_retenciones import ResultadoRetenciones  # noqa: F401  (el 130 usa el mismo molde: modelo, ejercicio, periodo, casillas, tipo_declaracion y bloqueos)

DISENOS = {"111": Path(__file__).resolve().parent / "disenos" / "111_v18.json", "115": Path(__file__).resolve().parent / "disenos" / "115_v13.json",
           "130": Path(__file__).resolve().parent / "disenos" / "130_v12.json"}


class FicheroNoGenerable(ValueError):
    pass


def _campo_111(casilla: str) -> int:
    """Casilla del 111 -> nº de campo de la página: los campos 12 a 38 son las casillas 01 a 27 por orden; el 39, la 28 (suma); el 40, la 29 (anteriores); el 41, la 30 (resultado)."""
    c = int(casilla)
    return c + 11 if c <= 27 else {28: 39, 29: 40, 30: 41}[c]


CAMPO_115 = {"01": 12, "02": 13, "03": 14, "04": 15, "05": 16}


def _campo_130(casilla: str) -> int:
    """Casilla del 130 -> nº de campo de la página: los campos 12 a 30 son las casillas 01 a 19 por orden."""
    c = int(casilla)
    if not 1 <= c <= 19:
        raise FicheroNoGenerable(f"La casilla {casilla} no existe en el diseño del modelo 130.")
    return c + 11


def _campo(modelo: str, casilla: str) -> int:
    return {"111": _campo_111, "115": CAMPO_115.get, "130": _campo_130}[modelo](casilla)
# nombre en el diseño de cada campo, para que una prueba compruebe la correspondencia (casilla -> palabras de su descripción)
DESCRIPCION_ESPERADA = {"111": {"03": "Rendimientos dinerarios - Importe retenciones", "07": "actividades económicas - Rendimientos dinerarios -Nº de percep", "09": "actividades económicas - Rendimientos dinerarios -Importe rete",
                                "28": "Suma retenciones", "29": "Resultado de anteriores declaraciones", "30": "Resultado a ingresar"},
                        "115": {"01": "Número perceptores", "02": "Base retenciones", "03": "Retenciones e ingresos a cuenta [03]", "04": "Resultado anteriores declaraciones", "05": "Resultado a ingresar"},
                        "130": {"01": "[01] Ingresos computables", "02": "[02] Gastos fiscalmente deducibles", "03": "[03 ]Rendimiento neto", "04": "[04] 20 por 100", "05": "[05] A deducir : De los trim. anteriores",
                                "06": "[06] A deducir: Retenciones", "07": "[07] Pago fraccionado previo", "12": "[12] Suma de pagos fraccionados", "13": "[13] A deducir: Minorac.", "14": "[14] Diferencia",
                                "15": "[15] A deducir: Resultados negativos", "16": "[16] A deducir: cantidades al pago", "17": "[17] Total", "19": "[19] Resultado de la autoliquidación"}}


def cargar_diseno(modelo: str) -> dict:
    return json.loads(DISENOS[modelo].read_text(encoding="utf-8"))


def _valores_pagina(diseno: dict, r: ResultadoRetenciones, nif: str, nombre: str) -> dict[int, object]:
    pagina = diseno["paginas"][1]
    por_n = {c["n"]: c for c in pagina["campos"]}
    mapa = {c: _campo(r.modelo, c) for c in r.casillas}
    valores: dict[int, object] = {6: r.tipo_declaracion, 7: nif, 8: nombre, 10: r.ejercicio, 11: r.periodo}
    for casilla, valor in r.casillas.items():
        campo = por_n[mapa[casilla]]
        valores[campo["n"]] = valor if _decimales(campo) == 0 else Decimal(valor) / 100
    return valores


def generar(r, *, nif: str, nombre: str, diseno: dict | None = None) -> bytes:
    if not r.calculable:
        raise FicheroNoGenerable("El cálculo está bloqueado: " + " · ".join(r.bloqueos[:3]))
    if r.periodo not in PERIODOS:
        raise FicheroNoGenerable(f"periodo no válido: {r.periodo!r}")
    diseno = diseno or cargar_diseno(r.modelo)
    envoltura, pagina = diseno["paginas"][0], diseno["paginas"][1]
    campos = {c["n"]: c for c in envoltura["campos"]}
    cabecera = "".join(formatear(campos[1], None) + formatear(campos[2], None) + formatear(campos[3], None) + formatear(campos[4], str(r.ejercicio)) + formatear(campos[5], r.periodo)
                       + "".join(formatear(campos[n], None) for n in (6, 7, 8, 9, 10, 11, 12, 13)))
    cuerpo = _pagina(pagina, _valores_pagina(diseno, r, nif, nombre))
    return (cabecera + cuerpo + f"</T{r.modelo}0{r.ejercicio}{r.periodo}0000>").encode("iso-8859-15")


def leer_campos(modelo: str, datos: bytes, diseno: dict | None = None) -> dict[int, str]:
    """Los campos de la página del fichero, por número (para comprobar lo generado)."""
    diseno = diseno or cargar_diseno(modelo)
    texto = datos.decode("iso-8859-15")
    pagina = diseno["paginas"][1]
    inicio = texto.index(f"<T{modelo}01000>")
    bloque, salida, p0 = texto[inicio:inicio + pagina["total_posiciones"]], {}, 0
    for c in pagina["campos"]:
        salida[c["n"]] = bloque[p0:p0 + c["lon"]]
        p0 += c["lon"]
    return salida


__all__ = ["generar", "leer_campos", "cargar_diseno", "FicheroNoGenerable", "ErrorDeFormato"]
