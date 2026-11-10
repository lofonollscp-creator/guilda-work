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


def test_segunda_opinion_solo_si_esta_activada_y_la_primera_es_dudosa(modelo, monkeypatch):
    from app import ia_asistente, ia_despacho
    t, u, c = _despacho()
    limpia = {**RESPUESTA, "emisor_nif": "A58818501"}                        # un NIF con el control bien: sin avisos
    modelo.respuesta = json.dumps({**limpia, "total": 150})                  # la primera lectura no cuadra (150 con una línea de 121): es dudosa
    buena = {"choices": [{"message": {"content": json.dumps(limpia)}}]}
    llamadas = []
    monkeypatch.setattr(ia_asistente, "candidatos", lambda uid, tarea="asistente": [{"proveedor": "a", "modelo": "uno"}, {"proveedor": "b", "modelo": "dos"}])
    monkeypatch.setattr(ia_asistente, "_llamar", lambda uid, tarea, payload, timeout=90, cands=None: llamadas.append(cands[0]["modelo"]) or buena)
    _leer(t, u, c, b"1")
    assert llamadas == [], "desactivada: no hay segunda consulta"
    ia_despacho.guardar_config(t, solo_ue=False, claves_personales=True, facturas_modo="compartida", umbral_confianza=90, segunda_lectura=True, por=u)
    con = fc.obtener(t, u, _leer(t, u, c, b"2"))
    assert llamadas == ["dos"] and con["total_centimos"] == 12100 and "segundo modelo" in con["notas"]
    llamadas.clear()
    modelo.respuesta = json.dumps(limpia)
    _leer(t, u, c, b"3")
    assert llamadas == [], "una lectura limpia no gasta una segunda consulta"
