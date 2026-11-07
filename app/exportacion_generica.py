"""Exportación neutra de las facturas revisadas (R8): un diario en CSV y un libro de IVA en Excel que sirven para llevar los datos a CUALQUIER programa que no sea a3 (Contasol, Sage, Holded, el Excel
de la gestoría…). No sigue ningún formato propietario: una línea por tipo de IVA de cada factura con todos los datos ya validados (base, tipo, cuota, recargo, retención, cuenta, tipo de operación).

A diferencia del fichero de a3, esta descarga NO marca las facturas como exportadas (no es un lote contable) ni exige configurar a3: es una copia de lectura de lo que ya está revisado."""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from . import facturas_contables as fc

COLUMNAS = ("Fecha", "Fecha de operación", "Número", "Tipo", "Abono", "Proveedor o cliente", "NIF", "Subcuenta del tercero", "Cuenta de gasto o ingreso", "Tipo de operación", "Base imponible",
            "% IVA", "Cuota IVA", "% Recargo", "Cuota recargo", "% Retención", "Cuota retención", "Total de la factura")
ESTADOS = ("revisada", "exportada")


def _eur(centimos: int | None) -> Decimal:
    return (Decimal(centimos or 0) / 100).quantize(Decimal("0.01"))


def _pct(centesimas: int | None) -> Decimal:
    return (Decimal(centesimas or 0) / 100).quantize(Decimal("0.01"))


def filas(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, desde: str | None = None, hasta: str | None = None) -> list[dict]:
    """Una fila por línea de IVA de cada factura revisada o ya exportada del cliente (las más antiguas primero), con los importes como decimales. Las facturas sin líneas salen con una fila vacía de importes."""
    salida = []
    for resumen in sorted(fc.listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, desde=desde, hasta=hasta, limite=5000), key=lambda f: (f["fecha"], f["id"])):
        if resumen["estado"] not in ESTADOS:
            continue
        f = fc.obtener(tenant_id, usuario_id, resumen["id"])
        if f is None:
            continue
        cuenta_tercero = fc.cuenta_efectiva(tenant_id, f) or ""
        lineas = f.get("lineas") or [{}]
        for i, l in enumerate(lineas):
            salida.append({"Fecha": f["fecha"], "Fecha de operación": f.get("fecha_operacion") or f["fecha"], "Número": f["numero"], "Tipo": "Emitida" if f["tipo"] == "emitida" else "Recibida",
                           "Abono": "Sí" if f.get("abono") else "No", "Proveedor o cliente": f["tercero_nombre"], "NIF": f.get("tercero_nif") or "", "Subcuenta del tercero": cuenta_tercero,
                           "Cuenta de gasto o ingreso": l.get("cuenta") or "", "Tipo de operación": l.get("subtipo") or "", "Base imponible": _eur(l.get("base_centimos")), "% IVA": _pct(l.get("pct_iva")),
                           "Cuota IVA": _eur(l.get("cuota_iva")), "% Recargo": _pct(l.get("pct_recargo")), "Cuota recargo": _eur(l.get("cuota_recargo")), "% Retención": _pct(l.get("pct_retencion")),
                           "Cuota retención": _eur(l.get("cuota_retencion")), "Total de la factura": _eur(f["total_centimos"]) if i == 0 else Decimal("0.00")})
    return salida


def _celda_csv(v) -> str:
    return f"{v:.2f}".replace(".", ",") if isinstance(v, Decimal) else str(v)


def a_csv(filas_: list[dict]) -> bytes:
    """CSV con punto y coma, decimales con coma y UTF-8 con marca (BOM): lo abre bien Excel en español y lo leen la mayoría de importadores."""
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    escritor.writerow(COLUMNAS)
    for f in filas_:
        escritor.writerow([_celda_csv(f[c]) if not str(f[c]).startswith(("=", "+", "-", "@")) or isinstance(f[c], Decimal) else "'" + str(f[c]) for c in COLUMNAS])
    return "﻿".encode("utf-8") + salida.getvalue().encode("utf-8")


def a_xlsx(filas_: list[dict], titulo: str = "Libro de IVA") -> bytes:
    """Excel con una hoja de recibidas y otra de emitidas, con los importes como números y una fila de totales."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    libro = Workbook()
    libro.remove(libro.active)
    for nombre, tipo in (("Recibidas", "Recibida"), ("Emitidas", "Emitida")):
        hoja = libro.create_sheet(nombre)
        hoja.append(list(COLUMNAS))
        for c in hoja[1]:
            c.font = Font(bold=True)
        propias = [f for f in filas_ if f["Tipo"] == tipo]
        for f in propias:
            hoja.append([float(f[c]) if isinstance(f[c], Decimal) else _seguro(f[c]) for c in COLUMNAS])
        if propias:
            fin = hoja.max_row
            total = ["Total"] + [""] * (len(COLUMNAS) - 1)
            for nombre_columna in ("Base imponible", "Cuota IVA", "Cuota recargo", "Cuota retención", "Total de la factura"):
                letra = hoja.cell(row=1, column=COLUMNAS.index(nombre_columna) + 1).column_letter
                total[COLUMNAS.index(nombre_columna)] = f"=SUM({letra}2:{letra}{fin})"
            hoja.append(total)
            for c in hoja[hoja.max_row]:
                c.font = Font(bold=True)
        for i, ancho in enumerate((11, 11, 16, 10, 7, 30, 13, 14, 14, 10) + (12,) * 8, start=1):
            hoja.column_dimensions[hoja.cell(row=1, column=i).column_letter].width = ancho
        for fila in hoja.iter_rows(min_row=2):
            for celda in fila:
                if isinstance(celda.value, float) or (isinstance(celda.value, str) and celda.value.startswith("=SUM")):
                    celda.number_format = "#,##0.00"
    libro.properties.title = titulo
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def _seguro(valor):
    """Un texto que empieza por = + - @ lo trataría Excel como una fórmula: se le antepone una comilla para que sea texto."""
    t = str(valor)
    return "'" + t if t[:1] in ("=", "+", "-", "@") else t
