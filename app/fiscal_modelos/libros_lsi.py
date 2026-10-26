"""Escritor del **libro registro de IVA** en el formato de importación de la AEAT (`.xlsx`, «LSI»): lo que acepta la opción «Libros de registro → Importar libro de registro» del modelo 303.

Formato descubierto contra el simulador público (docs/fiscal-vias-aeat.md): tres hojas con los nombres oficiales `EXPEDIDAS_INGRESOS`, `RECIBIDAS_GASTOS` y `BIENES-INVERSIÓN`; los datos empiezan en la **fila 1**
(SIN filas de cabecera: el simulador las leería como registros) y las columnas son las de las plantillas oficiales (`docs/fuentes-oficiales/aeat/LSI*.xlsx`). Fechas como fecha de Excel, importes con dos decimales.
Desde 2023 hay que importar el libro COMPLETO del ejercicio hasta el periodo (el 4T incluye 1T-3T)."""
from __future__ import annotations

import io
from datetime import datetime

from .apuntes import EXPEDIDAS, RECIBIDAS, Apunte, periodo_de

HOJAS = ("EXPEDIDAS_INGRESOS", "RECIBIDAS_GASTOS", "BIENES-INVERSIÓN")
ACTIVIDAD = ("B", "01")                      # código y tipo de actividad: B = actividad no incluida en A, C ni D; tipo 01 (la pareja que el simulador acepta sin pedir inmueble ni epígrafe IAE)


def _euros(centimos: int | None) -> float | None:
    return None if centimos is None else round(centimos / 100, 2)


def _pct(centesimas: int) -> float:
    return round(centesimas / 100, 2)


def _fecha(d) -> datetime | None:
    return datetime(d.year, d.month, d.day) if d else None


def periodo_natural(a: Apunte, periodo_objetivo: str) -> str:
    """El periodo con el que se anota la fila en el libro: el de la fecha que manda en cada libro (operación o expedición en las expedidas; recepción o periodo de deducción en las recibidas)."""
    mensual = periodo_objetivo[-1] != "T"
    if a.libro == RECIBIDAS:
        return periodo_de(a.fecha_recepcion or a.fecha_expedicion, mensual)
    return periodo_de(a.fecha_operacion or a.fecha_expedicion, mensual)


def fila_expedida(a: Apunte, ejercicio: int, periodo: str) -> dict[int, object]:
    """Columnas (base 0) del libro de expedidas."""
    f = {0: ejercicio, 1: periodo, 2: ACTIVIDAD[0], 3: ACTIVIDAD[1], 5: a.tipo_factura, 8: _fecha(a.fecha_expedicion), 9: _fecha(a.fecha_operacion), 10: a.serie or None, 11: a.numero,
         15: a.contraparte_nif or None, 16: a.contraparte_nombre, 17: a.clave, 18: a.calificacion or None, 19: a.exenta or None, 20: _euros(a.total_efectivo), 21: _euros(a.base)}
    if a.contraparte_nif_tipo:
        f[13], f[14] = a.contraparte_nif_tipo, a.contraparte_pais or None
    f[22], f[23] = (_pct(a.tipo_iva), _euros(a.cuota)) if a.calificacion == "S1" else (0.0, 0.0)       # S2/N/exentas: tipo y cuota a cero, no vacíos
    if a.inmueble_situacion:
        f[33], f[34] = a.inmueble_situacion, a.inmueble_referencia or None
    return f


def fila_recibida(a: Apunte, ejercicio: int, periodo: str) -> dict[int, object]:
    """Columnas (base 0) del libro de recibidas."""
    f = {0: ejercicio, 1: periodo, 2: ACTIVIDAD[0], 3: ACTIVIDAD[1], 5: a.tipo_factura, 8: _fecha(a.fecha_expedicion), 9: _fecha(a.fecha_operacion), 10: f"{a.serie}{a.numero}",
         12: _fecha(a.fecha_recepcion or a.fecha_expedicion), 17: a.contraparte_nif or None, 18: a.contraparte_nombre, 19: a.clave, 20: "S" if a.bien_inversion else None,
         21: "S" if a.isp else None, 22: "S" if a.deducible_periodo_posterior else None, 25: _euros(a.total_efectivo), 26: _euros(a.base), 27: _pct(a.tipo_iva), 28: _euros(a.cuota),
         29: _euros(a.deducible)}
    if a.contraparte_nif_tipo:
        f[15], f[16] = a.contraparte_nif_tipo, a.contraparte_pais or None
    if a.periodo_deduccion:
        f[23], f[24] = a.periodo_deduccion
    if a.inmueble_situacion:
        f[39], f[40] = a.inmueble_situacion, a.inmueble_referencia or None
    return f


def escribir_xlsx(apuntes: list[Apunte], *, ejercicio: int, periodo: str) -> bytes:
    """El libro (expedidas y recibidas) como `.xlsx`. `periodo` es el de la autoliquidación objetivo («2T»); cada fila se anota con SU periodo natural (`periodo_natural`), así que el libro puede llevar todo el ejercicio."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nombre, libro, fila in ((HOJAS[0], EXPEDIDAS, fila_expedida), (HOJAS[1], RECIBIDAS, fila_recibida), (HOJAS[2], None, None)):
        ws = wb.create_sheet(nombre)
        if libro is None:
            continue
        n = 0
        for a in apuntes:
            if a.libro != libro:
                continue
            n += 1
            for col, valor in fila(a, ejercicio, periodo_natural(a, periodo)).items():
                if valor is None or valor == "":
                    continue
                celda = ws.cell(n, col + 1)
                celda.value = valor
                if isinstance(valor, datetime):
                    celda.number_format = "dd/mm/yyyy"
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
