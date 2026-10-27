"""Conciliación con el banco: lectura del extracto (CSV y Excel), importes en formato español e inglés, cruce por importe exacto con puntuación y reparto en tres listas."""
import io
from datetime import date

import pytest

from app import db, fiscal_conciliacion as fc, fiscal_perfiles as fp
from app.db_fiscal import crear_cliente_fiscal
from app.fiscal_perfiles import ErrorFiscal


@pytest.mark.parametrize("texto, esperado", [("1.234,56", 123456), ("-1234,56", -123456), ("1,234.56", 123456), ("(50,00)", -5000), ("50,00-", -5000), ("12,5", 1250), ("1.234", 123400),
                                             ("1,234,567.89", 123456789), ("0,99", 99), ("1234.5", 123450), (12.34, 1234), ("abc", None), ("", None), (None, None)])
def test_importes(texto, esperado):
    assert fc._importe(texto) == esperado


CSV = """Banco Ejemplo;;;
Cuenta ES00 0000;;;
Fecha;Concepto;Importe;Saldo
03/05/2026;TRANSFERENCIA DE CLIENTE SL FRA F-1;1.210,00;5.000,00
10/05/2026;RECIBO PROVEEDOR SUMINISTROS;-605,00;4.395,00
15/05/2026;COMISION MANTENIMIENTO;-6,00;4.389,00
20/05/2026;PAGO SIN IDENTIFICAR;-99,99;4.289,01
31/05/2026;fila rara;sin importe;
"""


def test_lee_un_csv_con_cabecera_no_en_la_primera_fila():
    movs, avisos = fc.leer_extracto("extracto.csv", CSV.encode("utf-8"))
    assert [(m.fecha, m.importe) for m in movs] == [(date(2026, 5, 3), 121000), (date(2026, 5, 10), -60500), (date(2026, 5, 15), -600), (date(2026, 5, 20), -9999)]
    assert any("1 fila" in a for a in avisos) and movs[0].fila == 4


def test_lee_cargo_y_abono_en_columnas_separadas_y_latin1():
    texto = "Fecha;Descripción;Cargo;Abono\n01/04/2026;Cobro cliente ñ;;100,00\n02/04/2026;Pago;40,00;\n"
    movs, _ = fc.leer_extracto("x.csv", texto.encode("latin-1"))
    assert [m.importe for m in movs] == [10000, -4000] and "ñ" in movs[0].concepto


def test_lee_un_excel():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Fecha", "Concepto", "Importe"])
    ws.append([date(2026, 5, 3), "Cobro", 121.0])
    ws.append([date(2026, 5, 4), "Pago", -50.5])
    b = io.BytesIO()
    wb.save(b)
    movs, _ = fc.leer_extracto("x.xlsx", b.getvalue())
    assert [m.importe for m in movs] == [12100, -5050]


def test_extractos_no_validos():
    for contenido in (b"", b"hola\nmundo\n", b"Fecha;Concepto;Importe\n", b"\x00\x01\x02" * 10):
        with pytest.raises(ErrorFiscal):
            fc.leer_extracto("x.csv", contenido)
    with pytest.raises(ErrorFiscal):
        fc.leer_extracto("x.csv", b"a" * (fc.MAX_BYTES + 1))


def _f(id, tipo, fecha, numero, nombre, esperado, nif="", en_periodo=True, origen="factura"):
    return {"id": id, "origen": origen, "tipo": tipo, "fecha": fecha, "numero": numero, "tercero_nombre": nombre, "tercero_nif": nif, "esperado": esperado, "en_periodo": en_periodo}


def test_el_cruce_reparte_en_tres_listas():
    movs, _ = fc.leer_extracto("extracto.csv", CSV.encode("utf-8"))
    facturas = [_f(1, "emitida", date(2026, 5, 2), "F-1", "Cliente SL", 121000), _f(2, "recibida", date(2026, 5, 5), "P-77", "Suministros Norte SA", -60500),
                _f(3, "recibida", date(2026, 5, 6), "P-80", "Otro Proveedor", -30000)]
    r = fc.conciliar(movs, facturas)
    pares = {c["factura"]["id"]: c for c in r["conciliados"]}
    assert set(pares) == {1, 2} and pares[1]["confianza"] == "seguro" and "número de factura" in pares[1]["motivos"][0] and pares[2]["confianza"] == "probable"
    assert [f["id"] for f in r["facturas_sin_movimiento"]] == [3]
    sin = {s["movimiento"].importe: s["sin_factura_esperable"] for s in r["movimientos_sin_factura"]}
    assert sin == {-600: True, -9999: False}


def test_importes_iguales_se_reparten_y_la_duda_se_avisa():
    movs = [fc.Movimiento(2, date(2026, 5, 10), -10000, "TRANSFERENCIA"), fc.Movimiento(3, date(2026, 5, 11), -10000, "TRANSFERENCIA")]
    facturas = [_f(1, "recibida", date(2026, 5, 1), "A-1", "Uno SL", -10000), _f(2, "recibida", date(2026, 5, 2), "A-2", "Dos SL", -10000)]
    r = fc.conciliar(movs, facturas)
    assert len(r["conciliados"]) == 2 and {c["factura"]["id"] for c in r["conciliados"]} == {1, 2}
    assert all(c["confianza"] == "posible" for c in r["conciliados"])
    # el número en el concepto desempata
    movs[0] = fc.Movimiento(2, date(2026, 5, 10), -10000, "PAGO FRA A-2")
    r = fc.conciliar(movs, facturas)
    assert next(c for c in r["conciliados"] if c["movimiento"].fila == 2)["factura"]["id"] == 2


def test_signo_y_fechas_cuentan():
    mov = [fc.Movimiento(2, date(2026, 5, 10), 10000, "COBRO")]
    assert not fc.conciliar(mov, [_f(1, "recibida", date(2026, 5, 1), "A", "X", -10000)])["conciliados"]                  # una recibida no se cobra
    assert not fc.conciliar(mov, [_f(1, "emitida", date(2025, 1, 1), "A", "X", 10000)])["conciliados"]                    # demasiado antigua
    assert not fc.conciliar(mov, [_f(1, "emitida", date(2026, 6, 30), "A", "X", 10000)])["conciliados"]                   # cobro muy anterior a la factura
    assert fc.conciliar(mov, [_f(1, "emitida", date(2026, 5, 12), "A", "X", 10000)])["conciliados"]                       # unos días antes, vale


def _despacho(nombre="Despacho conciliacion"):
    t = db.crear_tenant(nombre)
    u = db.crear_usuario_vinculado_a_kratos("concilia@ejemplo.com", "k-concilia"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    c = crear_cliente_fiscal(t, "Empresa de prueba SL", nif="A12345674")
    fp.guardar_perfil(t, u, c, {"forma_juridica": "sociedad"}, vigente_desde="2026-01-01")
    return t, u, c


def test_con_las_facturas_del_titular_y_sin_guardar_el_extracto():
    from app import facturas_contables as fcont, fiscal_nucleo as fn
    from tests.escenarios_303 import venta
    t, u, c = _despacho()
    fid = fcont.crear(t, u, c, {"tipo": "emitida", "fecha": "2026-05-02", "numero": "F-1", "tercero_nombre": "Cliente SL", "tercero_nif": "B87654321"}, [{"base": "1000,00", "pct_iva": 21}])
    fcont.crear(t, u, c, {"tipo": "recibida", "fecha": "2026-05-05", "numero": "P-77", "tercero_nombre": "Suministros Norte SA"}, [{"base": "500,00", "pct_iva": 21}])
    fn.aprobar_apunte(t, u, c, venta(20000, 2100, numero="9", fecha=date(2026, 5, 3)))                       # un apunte manual sin factura: 242,00 €
    csv = "Fecha;Concepto;Importe\n03/05/2026;FRA F-1 CLIENTE SL;1.210,00\n10/05/2026;SUMINISTROS NORTE;-605,00\n12/05/2026;INGRESO A9;242,00\n20/05/2026;ALGO;-1,23\n"
    r = fc.conciliar_extracto(t, u, c, 2026, "2T", "extracto.csv", csv.encode())
    assert {(x["factura"]["origen"], x["confianza"]) for x in r["conciliados"]} == {("factura", "seguro"), ("factura", "probable"), ("apunte", "seguro")}
    assert len(r["conciliados"]) == 3 and r["facturas_sin_movimiento"] == [] and [s["movimiento"].importe for s in r["movimientos_sin_factura"]] == [-123]
    assert r["movimientos"] == 4 and any("importes exactos" in a for a in r["avisos"]) and fid
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT count(*) FROM auditoria_eventos WHERE accion = 'fiscal.conciliacion'").fetchone()[0] == 1
        assert "CLIENTE" not in str(conn.execute("SELECT detalle FROM auditoria_eventos WHERE accion = 'fiscal.conciliacion'").fetchone()[0])
    finally:
        conn.close()
    with pytest.raises(ErrorFiscal):
        fc.conciliar_extracto(t, u, c, 2026, "13", "x.csv", csv.encode())
