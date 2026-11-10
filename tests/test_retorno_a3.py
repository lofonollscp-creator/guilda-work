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
    r = retorno_a3.cruzar(t, u, c, otro_total)
    assert r["confirmadas"] == [] and r["faltan"] == [] and [(d["campo"], d["guilda"], d["a3"]) for d in r["con_diferencias"][0]["diferencias"]] == [("total", 121000, 999)]
    assert retorno_a3.cruzar(t, u, c, otro_nif)["confirmadas"] == []
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


def test_el_libro_de_iva_con_una_fila_por_tipo_se_agrupa_y_cuadra_el_iva():
    t, u, c = _despacho()
    (a,) = _exportadas(t, u, c, "F-1")                                   # base 1.000 al 21 %: IVA 210, total 1.210
    filas = [{"numero": "F-1", "fecha": "2026-08-15", "nif": "B87654321", "total": 121000, "base": 60000, "cuota": 12600},
             {"numero": "F-1", "fecha": "2026-08-15", "nif": "B87654321", "total": 121000, "base": 40000, "cuota": 8400}]
    r = retorno_a3.cruzar(t, u, c, filas)
    assert [f["id"] for f in r["confirmadas"]] == [a] and r["con_diferencias"] == []
    assert r["cuadre"] == [{"trimestre": "2026-T3", "tipo": "recibida", "facturas": 1, "iva_guilda": 21000, "iva_a3": 21000, "diferencia": 0}]
    filas[1]["cuota"] = 8000
    r = retorno_a3.cruzar(t, u, c, filas, confirmar=False)
    assert r["cuadre"][0]["diferencia"] == 400 and [d["campo"] for d in r["con_diferencias"][0]["diferencias"]] == ["cuota"]


# --- J8: columnas indicadas a mano y posibles parejas --------------------------------------------------------------------------------------------------------

SIN_TITULOS = "Registro de facturas\nB;15/08/2026;F-1;1.210,00;B87654321\nB;16/08/2026;F-2;1.210,00;B87654321\n".encode("utf-8")


def test_letras_y_cifras_de_columna():
    assert [retorno_a3.letra_de_columna(i) for i in (0, 1, 25, 26, 27)] == ["A", "B", "Z", "AA", "AB"]
    assert [retorno_a3.indice_de_columna(x) for x in ("A", "b", "AA", "3", "1", "0", "", "ñ", "ABC")] == [0, 1, 26, 2, 0, None, None, None, None]


def test_un_listado_sin_titulos_reconocibles_se_lee_con_las_columnas_indicadas():
    with pytest.raises(ValueError, match="No encuentro las columnas"):
        retorno_a3.leer(SIN_TITULOS, "a3.csv")
    mapa = retorno_a3.mapa_de_columnas(numero="C", fecha="b", total="D", nif="E")
    filas = retorno_a3.leer(SIN_TITULOS, "a3.csv", mapa, fila_de_titulos=0)
    assert [f["numero"] for f in filas] == ["F-1", "F-2"] and filas[0]["total"] == 121000 and filas[0]["fecha"] == "2026-08-15" and filas[0]["nif"] == "B87654321"
    una_fila_de_titulos = retorno_a3.leer("x\nA;B;C;D\n1;15/08/2026;F-7;5,00\n".encode(), "a3.csv", {"numero": 2, "fecha": 1, "total": 3}, fila_de_titulos=2)
    assert [f["numero"] for f in una_fila_de_titulos] == ["F-7"]


def test_las_columnas_indicadas_se_validan():
    assert retorno_a3.mapa_de_columnas() is None and retorno_a3.mapa_de_columnas(numero="  ") is None
    for malo in ({"numero": "A"}, {"fecha": "B", "total": "C"}, {"numero": "A", "fecha": "??"}):
        with pytest.raises(ValueError):
            retorno_a3.mapa_de_columnas(**malo)


def test_la_vista_previa_da_la_letra_de_cada_columna():
    v = retorno_a3.vista_previa(SIN_TITULOS, "a3.csv")
    assert v["letras"] == ["A", "B", "C", "D", "E"] and v["filas"][1][2] == "F-1"


def test_una_exportada_que_a3_tiene_con_otro_numero_se_ofrece_como_posible_pareja():
    t, u, c = _despacho()
    a, = _exportadas(t, u, c, "F-1")
    listado = "Fecha;Nº Factura;NIF;Total\n15/08/2026;F-1/2026;B87654321;1.210,00\n20/08/2026;Z-9;B87654321;1.210,00\n".encode("cp1252")
    r = retorno_a3.cruzar(t, u, c, retorno_a3.leer(listado, "l.csv"))
    assert [f["id"] for f in r["faltan"]] == [a] and [(p["factura"]["id"], p["a3"]["numero"]) for p in r["posibles_parejas"]] == [(a, "F-1/2026")]   # el Z-9 está a 5 días: no
    assert not fc.obtener(t, u, a)["confirmada_en"]


def test_la_pantalla_acepta_las_columnas_indicadas_y_ensena_la_vista_previa(cliente):
    uid, t, c = _web(cliente, "retornocolumnas@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    r = cliente.post("/contabilidad/retorno", data={"cliente_id": c, "archivo": (io.BytesIO(SIN_TITULOS), "a3.csv")}, content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "No encuentro las columnas" in html and "<th>E</th>" in html and "F-1" in html        # se enseña el archivo con sus letras
    r = cliente.post("/contabilidad/retorno", data={"cliente_id": c, "archivo": (io.BytesIO(SIN_TITULOS), "a3.csv"), "col_numero": "C", "col_fecha": "B", "col_total": "D", "fila_titulos": "0"},
                     content_type="multipart/form-data")
    assert r.status_code == 200 and "No encuentro las columnas" not in r.get_data(as_text=True) and "Resultado" in r.get_data(as_text=True)


# --- J24: el mapeo de columnas se recuerda por cliente ---------------------------------------------------------------------------------------------------------

def test_las_columnas_indicadas_se_recuerdan_para_el_siguiente_listado_del_mismo_cliente():
    t, u, c = _despacho()
    assert retorno_a3.mapeo_guardado(t, c) is None
    with pytest.raises(ValueError, match="No encuentro las columnas"):
        retorno_a3.leer_de_cliente(t, c, SIN_TITULOS, "a3.csv")                                            # sin mapeo guardado, falla como siempre
    mapa = retorno_a3.mapa_de_columnas(numero="C", fecha="B", total="D")
    assert [f["numero"] for f in retorno_a3.leer_de_cliente(t, c, SIN_TITULOS, "a3.csv", mapa, 0)] == ["F-1", "F-2"]
    assert retorno_a3.mapeo_guardado(t, c) == ({"numero": 2, "fecha": 1, "total": 3}, 0)
    siguiente = "Registro de facturas\nB;20/09/2026;F-9;50,00;B87654321\n".encode()
    assert [f["numero"] for f in retorno_a3.leer_de_cliente(t, c, siguiente, "a3.csv")] == ["F-9"]       # ya no hace falta indicarlas
    assert [f["numero"] for f in retorno_a3.leer_de_cliente(t, c, CSV, "a3.csv")][:1] == ["F-1"]          # un listado con títulos reconocibles se lee por sus títulos
    retorno_a3.guardar_mapeo(t, c, None)
    assert retorno_a3.mapeo_guardado(t, c) is None


def test_guardar_el_mapeo_no_cambia_la_configuracion_heredada_del_despacho():
    from app import db, verticales
    from app.db_fiscal import crear_cliente_fiscal
    t = db.crear_tenant("Despacho mapeo")
    u = db.crear_usuario_vinculado_a_kratos("mapeo@ejemplo.com", "k-mapeo"); db.asignar_tenant(u, t); db.asignar_supervisor_tenant(u, True)
    verticales.fijar_activo(t, "contabilizacion", True)
    c = crear_cliente_fiscal(t, "Sin fila SL", nif="B12345679")
    fc.guardar_configuracion_despacho(t, u, {"digitos": "8", "cuenta_gasto": "62100000"})
    retorno_a3.guardar_mapeo(t, c, {"numero": 0, "total": 1}, 1)
    assert fc.configuracion(t, c)["cuenta_gasto"] == "62100000" and "columnas_retorno" not in fc.configuracion(t, c)
