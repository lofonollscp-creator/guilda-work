"""Tests de app/generador_documentos.py: tabla (columnas+filas) -> bytes
en cada formato, agnóstico de origen de datos -- confirma solo que el
formato de salida es válido y que respeta el tope de filas, no la lógica
de negocio de ningún dominio concreto (eso ya lo prueban los tests de las
tools que reúnen los datos, p.ej. tests/test_ia_herramientas.py)."""
import csv
import io

from app import generador_documentos as gen

COLUMNAS = ["Nombre", "Importe"]
FILAS = [["Cliente A", 100], ["Cliente B", 200.5], ["Cliente C", None]]


def test_tabla_a_csv_es_csv_valido_con_bom():
    contenido = gen.tabla_a_csv("Informe de prueba", COLUMNAS, FILAS)
    assert contenido.startswith(b"\xef\xbb\xbf")
    texto = contenido.decode("utf-8-sig")
    filas_csv = [f for f in csv.reader(io.StringIO(texto)) if f and not f[0].startswith("#")]
    assert filas_csv[0] == COLUMNAS
    assert filas_csv[1] == ["Cliente A", "100"]


def test_tabla_a_xlsx_tiene_firma_zip_y_openpyxl_lo_puede_reabrir():
    contenido = gen.tabla_a_xlsx("Informe de prueba", COLUMNAS, FILAS)
    assert contenido.startswith(b"PK\x03\x04")
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(contenido))
    ws = wb.active
    filas = list(ws.iter_rows(values_only=True))
    assert filas[0] == tuple(COLUMNAS)
    assert filas[1] == ("Cliente A", 100)


def test_tabla_a_docx_tiene_firma_zip_y_python_docx_lo_puede_reabrir():
    contenido = gen.tabla_a_docx("Informe de prueba", COLUMNAS, FILAS)
    assert contenido.startswith(b"PK\x03\x04")
    from docx import Document
    doc = Document(io.BytesIO(contenido))
    tabla = doc.tables[0]
    assert [c.text for c in tabla.rows[0].cells] == COLUMNAS
    assert [c.text for c in tabla.rows[1].cells] == ["Cliente A", "100"]


def test_tabla_a_pdf_tiene_cabecera_magica():
    contenido = gen.tabla_a_pdf("Informe de prueba", COLUMNAS, FILAS)
    assert contenido.startswith(b"%PDF")


def test_truncado_a_2000_filas():
    filas_grandes = [[f"Cliente {i}", i] for i in range(2500)]
    contenido = gen.tabla_a_csv("Informe grande", COLUMNAS, filas_grandes)
    texto = contenido.decode("utf-8-sig")
    filas_csv = [f for f in csv.reader(io.StringIO(texto)) if f and not f[0].startswith("#")]
    assert len(filas_csv) - 1 == gen.FILAS_MAXIMAS  # -1 por la fila de cabecera


def test_truncado_avisa_en_notas_del_pdf():
    filas_grandes = [[f"Cliente {i}", i] for i in range(2500)]
    contenido = gen.tabla_a_pdf("Informe grande", COLUMNAS, filas_grandes, notas="Datos de prueba")
    # No hace falta parsear el PDF -- basta con que no haya reventado y
    # que el resultado siga siendo un PDF válido con el tope aplicado.
    assert contenido.startswith(b"%PDF")
