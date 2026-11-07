"""Exportación neutra a CSV y Excel de las facturas revisadas (R8)."""
import io

import pytest

from app import exportacion_generica as eg, facturas_contables as fc
from tests.test_facturas_contables import _despacho, _web


def _factura(t, u, c, numero, estado="revisada", tipo="recibida", lineas=None, nombre="Papelería Sol", fecha="2026-08-14"):
    fid = fc.crear(t, u, c, {"tipo": tipo, "fecha": fecha, "numero": numero, "tercero_nombre": nombre, "tercero_nif": "B87654323"},
                   lineas or [{"base": "100,00", "pct_iva": "21", "cuenta": "62900000"}, {"base": "50,00", "pct_iva": "10", "pct_retencion": "15"}])
    if estado == "revisada":
        fc.cambiar_estado(t, u, fid, "revisada")
    return fid


def test_filas_una_por_linea_de_iva_con_importes_decimales_y_solo_lo_revisado():
    t, u, c = _despacho()
    _factura(t, u, c, "F-1")
    _factura(t, u, c, "F-2", estado="pendiente")
    _factura(t, u, c, "F-3", tipo="emitida", lineas=[{"base": "200,00", "pct_iva": "21"}], nombre="Cliente Final")
    filas = eg.filas(t, u, c)
    assert [f["Número"] for f in filas] == ["F-1", "F-1", "F-3"]                       # la pendiente no entra
    primera, segunda = filas[0], filas[1]
    assert str(primera["Base imponible"]) == "100.00" and str(primera["% IVA"]) == "21.00" and str(primera["Cuota IVA"]) == "21.00" and primera["Cuenta de gasto o ingreso"] == "62900000"
    assert str(segunda["% Retención"]) == "15.00" and str(segunda["Cuota retención"]) == "7.50"
    assert str(primera["Total de la factura"]) != "0.00" and str(segunda["Total de la factura"]) == "0.00"       # el total solo en la primera fila de cada factura: sumar no lo duplica
    assert filas[2]["Tipo"] == "Emitida" and filas[0]["Tipo"] == "Recibida"


def test_filtra_por_fechas():
    t, u, c = _despacho()
    _factura(t, u, c, "F-1", fecha="2026-02-10")
    _factura(t, u, c, "F-2", fecha="2026-08-14")
    assert [f["Número"] for f in eg.filas(t, u, c, "2026-07-01", "2026-09-30")] == ["F-2", "F-2"]


def test_el_csv_va_con_bom_punto_y_coma_y_decimales_con_coma_y_no_ejecuta_formulas():
    t, u, c = _despacho()
    _factura(t, u, c, "=CMD()", nombre="=HYPERLINK(\"x\")")
    csv_bytes = eg.a_csv(eg.filas(t, u, c))
    assert csv_bytes[:3] == b"\xef\xbb\xbf"
    texto = csv_bytes.decode("utf-8-sig")
    cabecera, primera = texto.splitlines()[0], texto.splitlines()[1]
    assert cabecera.startswith("Fecha;Fecha de operación;Número;") and "100,00;21,00;21,00" in primera
    assert "'=CMD()" in primera and "'=HYPERLINK" in primera and ";=CMD" not in primera                      # un texto que empieza por = se neutraliza


def test_el_excel_tiene_hojas_numeros_y_totales_y_neutraliza_formulas():
    from openpyxl import load_workbook
    t, u, c = _despacho()
    _factura(t, u, c, "F-1")
    _factura(t, u, c, "+SUMA", tipo="emitida", nombre="@cliente", lineas=[{"base": "300,00", "pct_iva": "21"}])
    libro = load_workbook(io.BytesIO(eg.a_xlsx(eg.filas(t, u, c))))
    assert libro.sheetnames == ["Recibidas", "Emitidas"]
    rec, emi = libro["Recibidas"], libro["Emitidas"]
    assert rec["A1"].value == "Fecha" and rec["K2"].value == 100.0 and rec["L2"].value == 21.0 and rec.max_row == 4 and rec["A4"].value == "Total" and rec["K4"].value == "=SUM(K2:K3)"
    assert emi["C2"].value == "'+SUMA" and emi["F2"].value == "'@cliente" and emi["K3"].value == "=SUM(K2:K2)"


def test_la_descarga_web_no_marca_exportadas_ni_pide_a3(cliente):
    uid, t, c = _web(cliente, "otroprog@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})                  # para poder revisar la factura; la descarga neutra no lo usa
    fid = _factura(t, uid, c, "F-1")
    r = cliente.post("/contabilidad/exportar-otro-programa", data={"cliente_id": c, "formato": "csv"})
    assert r.status_code == 200 and r.mimetype == "text/csv" and "attachment" in r.headers["Content-Disposition"] and r.headers["Content-Disposition"].endswith(".csv") and r.data[:3] == b"\xef\xbb\xbf"
    r = cliente.post("/contabilidad/exportar-otro-programa", data={"cliente_id": c, "formato": "xlsx", "trimestre": "2026-T3"})
    assert r.status_code == 200 and r.data[:2] == b"PK" and "spreadsheetml" in r.mimetype
    assert fc.obtener(t, uid, fid)["estado"] == "revisada"                                                      # sigue pendiente de exportar a a3


def test_errores_claros_si_no_hay_nada_o_el_formato_no_vale(cliente):
    uid, t, c = _web(cliente, "otroprog2@ejemplo.com")
    r = cliente.post("/contabilidad/exportar-otro-programa", data={"cliente_id": c, "formato": "csv"}, follow_redirects=True)
    assert "No hay facturas revisadas que descargar" in r.get_data(as_text=True)
    assert "Elige CSV o Excel" in cliente.post("/contabilidad/exportar-otro-programa", data={"cliente_id": c, "formato": "pdf"}, follow_redirects=True).get_data(as_text=True)
    assert "Cliente no encontrado" in cliente.post("/contabilidad/exportar-otro-programa", data={"cliente_id": 99999, "formato": "csv"}, follow_redirects=True).get_data(as_text=True)


def test_la_pantalla_ofrece_la_descarga(cliente):
    uid, t, c = _web(cliente, "otroprog3@ejemplo.com")
    html = cliente.get(f"/contabilidad/?cliente_id={c}").get_data(as_text=True)
    assert "Descargar para otro programa" in html and 'name="formato"' in html and "Excel (libro de IVA)" in html
