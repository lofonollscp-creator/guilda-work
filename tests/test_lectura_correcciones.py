"""Lo ya corregido por el despacho se aplica solo en las lecturas siguientes (app/lectura_correcciones.py)."""
import json

from app import facturas_contables as fc, lectura_facturas as lf
from tests.test_facturas_contables import PDF, _despacho
from tests.test_lectura_facturas import RESPUESTA, modelo  # noqa: F401 -- fixture


def _leer(t, u, c, sufijo):
    fid = fc.subir_archivos(t, u, c, "recibida", [("f.pdf", "application/pdf", PDF + sufijo)])[0]
    lf.leer(t, u, fid)
    return fid


def _corregir_y_revisar(t, u, fid, numero):
    f = fc.obtener(t, u, fid)
    fc.actualizar(t, u, fid, {"tipo": "recibida", "fecha": f["fecha"], "numero": numero, "tercero_nombre": f["tercero_nombre"], "tercero_nif": "B87654321"}, [{"base": "100,00", "pct_iva": "21"}])
    fc.cambiar_estado(t, u, fid, "revisada")


def test_el_nif_mal_leido_y_corregido_dos_veces_sale_bien_a_la_tercera(modelo):
    t, u, c = _despacho()
    modelo.respuesta = json.dumps({**RESPUESTA, "emisor_nif": "B87654399"})
    primera = _leer(t, u, c, b"1")
    assert fc.obtener(t, u, primera)["tercero_nif"] == "B87654399"
    _corregir_y_revisar(t, u, primera, "A-1")
    segunda = _leer(t, u, c, b"2")
    assert fc.obtener(t, u, segunda)["tercero_nif"] == "B87654399", "con una sola corrección todavía no se fía"
    _corregir_y_revisar(t, u, segunda, "A-2")
    tercera = fc.obtener(t, u, _leer(t, u, c, b"3"))
    assert tercera["tercero_nif"] == "B87654321" and "Corregido como en las facturas anteriores" in tercera["notas"]


def test_no_corrige_en_otro_cliente_ni_con_correcciones_que_no_coinciden(modelo):
    from app.db_fiscal import crear_cliente_fiscal
    t, u, c = _despacho()
    otro = crear_cliente_fiscal(t, "Otro cliente S.L.", nif="B99999999")
    fc.guardar_configuracion(t, u, otro, {"a3_empresa": "8", "digitos": "8"})
    modelo.respuesta = json.dumps({**RESPUESTA, "emisor_nif": "B87654399"})
    for i, n in enumerate(("B-1", "B-2")):
        _corregir_y_revisar(t, u, _leer(t, u, c, bytes([49 + i])), n)
    assert fc.obtener(t, u, _leer(t, u, otro, b"9"))["tercero_nif"] == "B87654399"
