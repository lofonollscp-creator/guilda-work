"""Capa fina de la presentación directa AEAT (app/aeat_presentacion.py): petición, comprobaciones y respuestas, con los ejemplos de la especificación v30. Sin red."""
import json

import pytest

from app import aeat_presentacion as ap

F01 = "<T303020262T0000><AUX> </AUX><T30301000> IJ21938519LO FONOLL SCP, S.L. - Ñandú & Hijos (Ñ)</T30301000></T303020262T0000>"


def _peticion(**cambios):
    datos = dict(modelo="303", ejercicio=2026, periodo="2T", f01=F01, nif_presentador="89890001k", nombre_presentador="USUARIO PRUEBA")
    datos.update(cambios)
    return ap.construir_peticion(datos.pop("modelo"), datos.pop("ejercicio"), datos.pop("periodo"), datos.pop("f01"), **datos)


def test_la_peticion_lleva_los_campos_de_la_especificacion():
    p = _peticion()
    assert p == {"MODELO": "303", "EJERCICIO": "2026", "PERIODO": "2T", "NRC": "", "IDI": "ES", "F01": F01, "FIR": "FirmaBasica", "FIRNIF": "89890001K", "FIRNOMBRE": "USUARIO PRUEBA"}
    cuerpo = ap.cuerpo_json(p)
    assert json.loads(cuerpo.decode("utf-8")) == p and b"\n" not in cuerpo
    assert ap.huella_fichero(F01) == ap.huella_fichero(F01) != ap.huella_fichero(F01 + " ")


@pytest.mark.parametrize("cambio,mensaje", [({"modelo": "006"}, "no está entre"), ({"modelo": "190"}, "no está entre"), ({"ejercicio": "26"}, "cuatro cifras"), ({"periodo": "2"}, "dos caracteres"),
                                            ({"idioma": "FR"}, "Idioma"), ({"nif_presentador": "123"}, "NIF"), ({"nombre_presentador": " "}, "nombre"), ({"nrc": "123"}, "NRC"),
                                            ({"f01": ""}, "vacío"), ({"f01": F01 + "\n"}, "saltos"), ({"f01": F01.replace(" S.L.", "\t")}, "saltos"), ({"f01": F01.replace("Hijos", "Hijos *")}, "no admite"),
                                            ({"f01": F01.replace("Hijos", "Hijos €")}, "no admite")])
def test_una_peticion_que_no_cumple_la_especificacion_no_se_construye(cambio, mensaje):
    with pytest.raises(ap.PeticionInvalida, match=mensaje):
        _peticion(**cambio)


def test_las_etiquetas_del_diseno_no_cuentan_como_caracteres_prohibidos():
    ap.comprobar_fichero("<T30301000>texto</T30301000>")
    with pytest.raises(ap.PeticionInvalida):
        ap.comprobar_fichero("texto < 5 y > 3")


def test_nrc_valido_solo_con_22_caracteres():
    assert _peticion(nrc="1110000000000000000000")["NRC"] == "1110000000000000000000"


CORRECTA = {"respuesta": {"correcta": {"CodigoSeguroVerificacion ": "AAAAAAAAAAAAAAAA", "Fecha": "2020-09-03", "Hora": "14:04", "Expediente": "2020111111111111", "NIFPresentador": "999999999",
                                       "ApellidosNombrePresentador": "XXXX", "TipoRepresentacion": "Colaborador", "NIFDeclarante": "88888888K", "Modelo": "303", "Ejercicio": 2026, "Periodo": "2T",
                                       "Justificante": "3030000000123", "NRCPago": "", "ImporteAIngresar": "21.00", "FormaPago": "U", "urlPdf": "https://www1.agenciatributaria.gob.es/x.pdf",
                                       "avisos": ["20932 - Verifique el contenido de las claves 00634"], "advertencias": ["16412 - No puede aplicarse la clave"]}}}


def test_respuesta_correcta():
    r = ap.interpretar_presentacion(json.dumps(CORRECTA))
    assert (r.estado, r.csv, r.justificante, r.tipo_representacion, r.forma_pago, r.importe_a_ingresar) == ("aceptada", "AAAAAAAAAAAAAAAA", "3030000000123", "Colaborador", "U", "21.00")
    assert r.url_pdf.endswith("x.pdf") and r.avisos == ["20932 - Verifique el contenido de las claves 00634"] and r.advertencias and r.bruto


def test_avisos_como_cadena_separada_por_comas():
    cuerpo = json.loads(json.dumps(CORRECTA)); cuerpo["respuesta"]["correcta"]["avisos"] = "A1 - uno, A2 - dos"
    assert ap.interpretar_presentacion(json.dumps(cuerpo)).avisos == ["A1 - uno", "A2 - dos"]


def test_respuesta_con_errores_es_un_rechazo_claro():
    r = ap.interpretar_presentacion('{"respuesta": {"errores": ["E00 - Error.  Código de error: E00000000000C Ejemplo 23/10/2020 08:49:12"]}}')
    assert r.estado == "rechazada" and len(r.errores) == 1 and not r.csv


@pytest.mark.parametrize("texto", ["", None, "<html>Error 502</html>", "{}", '{"respuesta": {}}', '{"respuesta": []}', '{"respuesta": {"correcta": {}}}', "[1, 2]"])
def test_lo_que_no_se_entiende_es_dudoso_y_nunca_un_fallo(texto):
    r = ap.interpretar_presentacion(texto)
    assert r.estado == "dudosa" and r.motivo and not r.errores


def test_una_aceptacion_sin_csv_o_sin_pdf_es_dudosa():
    sin_csv = json.loads(json.dumps(CORRECTA)); sin_csv["respuesta"]["correcta"]["CodigoSeguroVerificacion "] = "CORTO"
    sin_pdf = json.loads(json.dumps(CORRECTA)); sin_pdf["respuesta"]["correcta"]["urlPdf"] = ""
    assert ap.interpretar_presentacion(json.dumps(sin_csv)).estado == "dudosa" and ap.interpretar_presentacion(json.dumps(sin_pdf)).estado == "dudosa"


def test_justificante_raro_se_avisa_pero_se_acepta():
    raro = json.loads(json.dumps(CORRECTA)); raro["respuesta"]["correcta"]["Justificante"] = "123"
    r = ap.interpretar_presentacion(json.dumps(raro))
    assert r.estado == "aceptada" and any("13 cifras" in a for a in r.advertencias)


def test_respuesta_de_validacion():
    v = ap.interpretar_validacion('{"RESPUESTA":{"AVISOS":["7113 - AVISO: la cuenta ha cambiado"],"PDF":["JVBERi0xLjQK"]}}')
    assert v == {"avisos": ["7113 - AVISO: la cuenta ha cambiado"], "errores": [], "pdf_base64": "JVBERi0xLjQK"}
    e = ap.interpretar_validacion('{"respuesta":{"errores":["E1 - mal"]}}')
    assert e["errores"] == ["E1 - mal"] and not e["pdf_base64"]
    assert ap.interpretar_validacion("<html>")["errores"], "si no se entiende cuenta como error: validar no tiene efectos y se repite"


def test_las_urls_separan_pruebas_y_produccion():
    assert "prewww1" in ap.URL_PRESENTACION["pruebas"] and "prewww" not in ap.URL_PRESENTACION["produccion"] and ap.URL_VALIDACION.startswith("https://prewww2.")
