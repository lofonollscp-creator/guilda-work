"""Retorno desde a3 (app/retorno_a3.py): leer el listado, cruzarlo con lo exportado y confirmar."""
import io

import pytest

from app import facturas_contables as fc, facturas_portal, retorno_a3
from tests.test_facturas_contables import LINEA, _datos, _despacho, _web

CSV = ("Fecha;Nº Factura;NIF;Base imponible;Cuota IVA;Total\n"
       "15/08/2026;F-1;B87654321;1.000,00;210,00;1.210,00\n"
       "16/08/2026;F-2;B87654321;1.000,00;210,00;1.210,00\n"
       "17/08/2026;X-99;B11111111;10,00;2,10;12,10\n").encode("cp1252")


def _exportadas(t, u, c, *numeros, **kw):
    ids = [fc.crear(t, u, c, _datos(numero=n, fecha="2026-08-%02d" % (15 + i), tercero_nif="B87654321", **kw), [LINEA]) for i, n in enumerate(numeros)]
    for i in ids:
        fc.cambiar_estado(t, u, i, "revisada", confirmar_duplicado=True)
    fc.exportar(t, u, c)
    return ids


def test_leer_csv_con_acentos_y_cabeceras_variadas():
    filas = retorno_a3.leer(CSV, "listado.csv")
    assert [f["numero"] for f in filas] == ["F-1", "F-2", "X-99"] and filas[0]["total"] == 121000 and filas[0]["fecha"] == "2026-08-15" and filas[0]["nif"] == "B87654321"


def test_leer_excel():
    import openpyxl
    libro = openpyxl.Workbook(); hoja = libro.active
    hoja.append(["Listado de facturas"]); hoja.append(["Factura", "Fecha factura", "CIF", "Total factura"]); hoja.append(["F-1", "15/08/2026", "B87654321", 1210.0])
    ruta = io.BytesIO(); libro.save(ruta)
    filas = retorno_a3.leer(ruta.getvalue(), "a3.xlsx")
    assert filas == [{"numero": "F-1", "fecha": "2026-08-15", "nif": "B87654321", "total": 121000, "base": None, "cuota": None}]


@pytest.mark.parametrize("contenido", [b"", b"hola;mundo\n1;2\n", b"Fecha;Total\n01/01/2026;5\n"])
def test_un_listado_que_no_sirve_da_un_error_legible(contenido):
    with pytest.raises(ValueError):
        retorno_a3.leer(contenido, "x.csv")


def test_cruce_confirma_las_que_estan_y_senala_las_que_faltan():
    t, u, c = _despacho()
    a, b = _exportadas(t, u, c, "F-1", "F-2")
    # a3 solo devuelve la F-1 (y una X-99 que aquí no se exportó)
    filas = [f for f in retorno_a3.leer(CSV, "l.csv") if f["numero"] != "F-2"]
    r = retorno_a3.cruzar(t, u, c, filas)
    assert [f["id"] for f in r["confirmadas"]] == [a] and [f["id"] for f in r["faltan"]] == [b] and [x["numero"] for x in r["sobran"]] == ["X-99"]
    assert fc.obtener(t, u, a)["confirmada_en"] and not fc.obtener(t, u, b)["confirmada_en"]
    lote = fc.listar_lotes(t, u)[0]
    assert lote["n_confirmadas"] == 1 and lote["comprobado_en"]
    r2 = retorno_a3.cruzar(t, u, c, filas)
    assert [f["id"] for f in r2["ya_confirmadas"]] == [a] and r2["confirmadas"] == []


def test_si_el_total_o_el_nif_no_coinciden_no_se_confirma():
    t, u, c = _despacho()
    (a,) = _exportadas(t, u, c, "F-1")
    otro_total = [{"numero": "F-1", "fecha": "2026-08-15", "nif": "B87654321", "total": 999, "base": None, "cuota": None}]
    otro_nif = [{"numero": "F-1", "fecha": "2026-08-15", "nif": "B00000000", "total": 121000, "base": None, "cuota": None}]
    assert retorno_a3.cruzar(t, u, c, otro_total)["confirmadas"] == [] and retorno_a3.cruzar(t, u, c, otro_nif)["confirmadas"] == []
    assert not fc.obtener(t, u, a)["confirmada_en"]
    solo_numero = [{"numero": "f 1", "fecha": None, "nif": None, "total": None, "base": None, "cuota": None}]
    assert [f["id"] for f in retorno_a3.cruzar(t, u, c, solo_numero, confirmar=False)["confirmadas"]] == [a]
    assert not fc.obtener(t, u, a)["confirmada_en"], "sin «confirmar» no se escribe nada"


def test_reabrir_una_factura_quita_su_confirmacion():
    t, u, c = _despacho()
    (a,) = _exportadas(t, u, c, "F-1")
    retorno_a3.cruzar(t, u, c, retorno_a3.leer(CSV, "l.csv"))
    assert fc.obtener(t, u, a)["confirmada_en"]
    fc.cambiar_estado(t, u, a, "pendiente")
    assert not fc.obtener(t, u, a)["confirmada_en"]


def test_el_portal_enseña_el_paso_confirmada_solo_si_el_despacho_comprueba():
    t, u, c = _despacho()
    a, b = _exportadas(t, u, c, "F-1", "F-2")
    pasos = lambda i: [p["clave"] for p in next(f for f in facturas_portal.facturas_del_cliente(c) if f["id"] == i)["pasos"]]
    assert "confirmada" not in pasos(a)
    retorno_a3.cruzar(t, u, c, [f for f in retorno_a3.leer(CSV, "l.csv") if f["numero"] == "F-1"])
    filas = {f["id"]: f for f in facturas_portal.facturas_del_cliente(c)}
    assert "confirmada" in pasos(a) and filas[a]["pasos"][-1]["hecho"] and filas[b]["pasos"][-1]["actual"]
    assert "Falta comprobar" in filas[b]["explicacion"] and "Contabilizada" in filas[a]["explicacion"]


def test_la_pagina_sube_el_listado_y_lo_cruza(cliente):
    uid, t, c = _web(cliente, "retorno@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    _exportadas(t, uid, c, "F-1")
    assert "Lo que devuelve a3" in cliente.get("/contabilidad/retorno").get_data(as_text=True)
    r = cliente.post("/contabilidad/retorno", data={"cliente_id": c, "confirmar": "1", "archivo": (io.BytesIO(CSV), "a3.csv")}, content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Confirmadas ahora" in html and "X-99" in html
    assert "1 / 1" in cliente.get("/contabilidad/lotes").get_data(as_text=True)
    r = cliente.post("/contabilidad/retorno", data={"cliente_id": c, "archivo": (io.BytesIO(b"nada"), "a3.csv")}, content_type="multipart/form-data")
    assert "No encuentro las columnas" in r.get_data(as_text=True)
