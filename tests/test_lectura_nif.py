"""AC2: NIF que el modelo deja vacíos pero están en el texto del documento (con facturas reales anonimizadas)."""
from app import lectura_nif as n

EMITIDA = """Factura
Número 2026 0008
Documento emitido por:
MARTA SOLER VIDAL
12345678Z
CARRER DEL MOLÍ, 7
SERVEIS DEL PLA, S.L.
B77123453
CARRER DE LA FONT
Concepto Cantidad Precio Total
Total (EUR) 778,63€"""

IONOS = """IONOS Cloud S.L.U. · Avenida de La Vega, 1
ASSESSORS DEL RIU SL
Camí del Riu 4
N.° de factura: 202786130350
NIF/CIF: B86543212
IONOS Cloud S.L.U., NIF B-85049435, Madre de Dios nº 21, 26004-Logroño (La Rioja) Spain"""

ANTHROPIC = """Invoice number HGBVOBQK 0003
VAT Registration EU VAT  IE4276970QH
Anthropic, PBC @anthropic
548 Market Street
Bill to
ASSESSORS DEL RIU SL
CAMÍ DEL RIU, 4
ES VAT ESB86543212"""


def test_el_nif_suelto_bajo_el_nombre_se_toma_del_texto():
    d = {"emisor_nombre": "MARTA SOLER VIDAL", "receptor_nombre": "SERVEIS DEL PLA, S.L.", "emisor_nif": None, "receptor_nif": None}
    avisos = n.completar(d, EMITIDA)
    assert d["emisor_nif"] == "12345678Z" and d["receptor_nif"] == "B77123453" and len(avisos) == 2


def test_nif_con_guion_y_el_unico_que_sobra_se_asignan():
    d = {"emisor_nombre": "IONOS Cloud S.L.U.", "receptor_nombre": "ASSESSORS DEL RIU SL"}
    n.completar(d, IONOS)
    assert d["emisor_nif"] == "B85049435" and d["receptor_nif"] == "B86543212"


def test_nif_iva_europeo_antes_del_nombre_y_prefijo_es():
    d = {"emisor_nombre": "Anthropic, PBC", "receptor_nombre": "ASSESSORS DEL RIU SL", "receptor_nif": "ESB86543212"}
    n.completar(d, ANTHROPIC)
    assert d["emisor_nif"] == "IE4276970QH" and d["receptor_nif"] == "ESB86543212"          # el que ya traía el modelo no se toca
    assert n.sin_es("ESB86543212") == "B86543212" and n.sin_es("B-8654 3212") == "B86543212"


def test_un_nif_con_mal_digito_de_control_no_se_toma_y_no_se_repite():
    d = {"emisor_nombre": "MARTA SOLER VIDAL", "receptor_nombre": "SERVEIS DEL PLA, S.L."}
    n.completar(d, EMITIDA.replace("12345678Z", "12345678A"))
    assert d.get("emisor_nif") != "12345678A"
    d2 = {"emisor_nombre": "MARTA SOLER VIDAL", "receptor_nombre": "MARTA SOLER VIDAL"}
    n.completar(d2, EMITIDA)
    assert d2.get("emisor_nif") != d2.get("receptor_nif") or d2.get("emisor_nif") is None


def test_avisa_del_nif_leido_que_no_esta_en_el_texto():
    d = {"emisor_nombre": "MARTA SOLER VIDAL", "emisor_nif": "99999999R", "receptor_nif": "B77123453"}
    avisos = n.completar(d, EMITIDA)
    assert any("emisor" in a and "no aparece" in a for a in avisos) and not any("receptor" in a for a in avisos)
    assert n.completar({"emisor_nif": "X"}, "corto") == []                                          # sin texto suficiente no se opina


def test_con_saldo_corto_se_reintenta_con_un_tope_de_tokens(monkeypatch):
    from app import ia_asistente as ia
    llamadas = []

    def falsa(uid, tarea, payload, timeout, cands=None):
        llamadas.append(payload.get("max_tokens"))
        if len(llamadas) == 1:
            raise ia.ErrorIA("OpenRouter devolvió un error (402): This request requires more credits, or fewer max_tokens. You requested up to 64000 tokens, but can only afford 5375.", codigo_http=402)
        return {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setattr(ia, "_llamar", falsa)
    monkeypatch.setattr(ia, "candidatos", lambda u, t: [{"proveedor": "openrouter", "modelo": "m"}])
    monkeypatch.setattr(ia, "_reservar_uso", lambda u, f="asistente": None)
    monkeypatch.setattr(ia, "_envio_protegido", lambda u, m: (type("S", (), {"restaurar": lambda self, x: x})(), m))
    assert ia.completar_partes(1, "s", [{"type": "text", "text": "x"}]) == "{}"
    assert llamadas == [None, 5175]


def test_el_texto_del_pdf_no_lleva_caracteres_nulos():
    from app import pdf_facturas
    assert pdf_facturas._sin_nulos("HGBVOBQK\x000003") == "HGBVOBQK 0003"


def test_nif_cruzados_se_recolocan_segun_su_posicion():
    from app import lectura_nif
    texto = "IONOS CLOUD SL\nCIF: B85049435\nCalle Uno 1\n\nFactura para:\nCLIENTE PRUEBA SL\nCIF: B99887762\nTotal 10,00 EUR"
    datos = {"emisor_nombre": "IONOS CLOUD SL", "receptor_nombre": "CLIENTE PRUEBA SL", "emisor_nif": "B99887762", "receptor_nif": "B85049435"}
    avisos = lectura_nif.completar(datos, texto)
    assert (datos["emisor_nif"], datos["receptor_nif"]) == ("B85049435", "B99887762") and any("cambiado" in a for a in avisos)


def test_nif_bien_colocados_no_se_tocan():
    from app import lectura_nif
    texto = "IONOS CLOUD SL\nCIF: B85049435\nCalle Uno 1\n\nFactura para:\nCLIENTE PRUEBA SL\nCIF: B99887762\nTotal 10,00 EUR"
    datos = {"emisor_nombre": "IONOS CLOUD SL", "receptor_nombre": "CLIENTE PRUEBA SL", "emisor_nif": "B85049435", "receptor_nif": "B99887762"}
    assert lectura_nif.completar(datos, texto) == [] and datos["emisor_nif"] == "B85049435"


def test_dia_y_mes_cambiados_se_corrigen_si_el_texto_solo_tiene_la_fecha_inversa():
    from app import lectura_nif
    texto = "Rechnung Nr. RE-2026-0415\nDatum: 05.11.2026\nGesamtbetrag 200,00 EUR por favor pague en 30 dias, gracias"
    datos = {"fecha": "2026-05-11"}                                    # el modelo leyó mes/día
    avisos = lectura_nif.completar(datos, texto)
    assert datos["fecha"] == "2026-11-05" and any("día y el mes" in a for a in avisos)
    bien = {"fecha": "2026-11-05"}
    assert lectura_nif.completar(bien, texto) == [] and bien["fecha"] == "2026-11-05"
    ambigua = {"fecha": "2026-07-07"}                                  # día = mes: no hay nada que corregir
    assert lectura_nif.corregir_fecha(ambigua, "Fecha 07.07.2026 ........ texto de relleno para pasar el mínimo") == []
