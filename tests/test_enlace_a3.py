"""Fichero de enlace de a3 (app/enlace_a3.py): cada campo en su posición. Las posiciones salen de una implementación abierta de referencia y deben contrastarse con el manual «Enlace contable
entrada» de Wolters Kluwer; estos tests fijan el formato actual para que cualquier ajuste sea deliberado."""
import pytest

from app import enlace_a3 as a3

FACTURA = {"tipo": "recibida", "fecha": "2026-09-30", "fecha_operacion": "2026-09-28", "numero": "A-123", "concepto": "Compra de material", "referencia": "FRA-2026-0001234", "nif": "B12345678",
           "nombre": "Proveedor Ñandú S.L.", "cuenta_tercero": "40000001", "total_centimos": 121000,
           "lineas": [{"cuenta": "62900000", "subtipo": "01", "base_centimos": 100000, "pct_iva": 2100, "cuota_iva": 21000, "cuenta_iva": "47200000"}]}


def _campo(linea: str, desde: int, hasta: int) -> str:
    """Posiciones de 1 a 254, inclusivas, como en la documentación."""
    return linea[desde - 1:hasta]


def _lineas(facturas, **kw):
    return a3.generar(facturas, empresa=kw.get("empresa", 12), digitos=kw.get("digitos", 8)).decode("latin-1").split("\r\n")[:-1]


def test_cada_registro_mide_254_mas_el_salto_de_linea():
    contenido = a3.generar([FACTURA], empresa=12)
    assert len(contenido) == 2 * 256 and contenido.endswith(b"\r\n")
    assert all(len(l) == 254 for l in _lineas([FACTURA]))


def test_cabecera_campo_a_campo():
    c = _lineas([FACTURA])[0]
    esperado = [(1, 1, "4"), (2, 6, "00012"), (7, 14, "20260930"), (15, 15, "1"), (16, 27, "400000010000"), (28, 57, "Proveedor Ñandú S.L.".ljust(30)), (58, 58, "2"), (59, 68, "A-123".ljust(10)),
                (69, 69, "I"), (70, 99, "Compra de material".ljust(30)), (100, 113, "+0000001210.00"), (114, 143, "FRA-2026-0001234".ljust(30)), (144, 175, " " * 32), (176, 189, "B12345678".ljust(14)),
                (190, 229, "Proveedor Ñandú S.L.".ljust(40)), (230, 236, " " * 7), (237, 244, "20260928"), (245, 252, "20260930"), (253, 253, "E"), (254, 254, "N")]
    for desde, hasta, valor in esperado:
        assert _campo(c, desde, hasta) == valor, f"posiciones {desde}-{hasta}"


def test_detalle_campo_a_campo():
    d = _lineas([FACTURA])[1]
    esperado = [(1, 1, "4"), (2, 6, "00012"), (7, 14, "20260930"), (15, 15, "9"), (16, 27, "629000000000"), (28, 57, " " * 30), (58, 58, "C"), (59, 68, "A-123".ljust(10)), (69, 69, "U"),
                (70, 99, "Compra de material".ljust(30)), (100, 101, "01"), (102, 115, "+0000001000.00"), (116, 120, "21.00"), (121, 134, "+0000000210.00"), (135, 139, "00.00"),
                (140, 153, "+0000000000.00"), (154, 158, "00.00"), (159, 172, "+0000000000.00"), (173, 174, "01"), (175, 175, "S"), (176, 177, "  "), (178, 191, " " * 14),
                (192, 203, "472000000000"), (204, 215, " " * 12), (216, 227, " " * 12), (228, 251, " " * 24), (252, 252, " "), (253, 253, "E"), (254, 254, "N")]
    for desde, hasta, valor in esperado:
        assert _campo(d, desde, hasta) == valor, f"posiciones {desde}-{hasta}"


def test_una_linea_por_tipo_de_iva_y_solo_la_ultima_lleva_la_marca_u():
    f = dict(FACTURA, total_centimos=100000 + 21000 + 50000 + 5000,
             lineas=FACTURA["lineas"] + [{"cuenta": "62900000", "base_centimos": 50000, "pct_iva": 1000, "cuota_iva": 5000, "cuenta_iva": "47200000"}])
    ls = _lineas([f])
    assert [(l[14], l[68]) for l in ls] == [("1", "I"), ("9", "M"), ("9", "U")]


def test_un_abono_usa_el_registro_2_y_los_importes_en_negativo():
    f = dict(FACTURA, abono=True)
    c, d = _lineas([f])
    assert _campo(c, 15, 15) == "2" and _campo(c, 100, 113) == "+0000001210.00", "el total de la cabecera va siempre en positivo"
    assert _campo(d, 58, 58) == "A" and _campo(d, 102, 115) == "-0000001000.00" and _campo(d, 121, 134) == "-0000000210.00"


def test_la_retencion_va_siempre_en_positivo_y_con_su_cuenta():
    f = dict(FACTURA, total_centimos=100000 + 21000 - 15000,
             lineas=[{"cuenta": "62300000", "base_centimos": 100000, "pct_iva": 2100, "cuota_iva": 21000, "pct_retencion": 1500, "cuota_retencion": 15000, "cuenta_iva": "47200000", "cuenta_retencion": "47510000"}])
    d = _lineas([f])[1]
    assert _campo(d, 154, 158) == "15.00" and _campo(d, 159, 172) == "+0000000150.00" and _campo(d, 216, 227) == "475100000000"


def test_recargo_de_equivalencia_e_iva_no_sujeto():
    f = dict(FACTURA, lineas=[{"cuenta": "60000000", "base_centimos": 100000, "pct_iva": 2100, "cuota_iva": 21000, "pct_recargo": 520, "cuota_recargo": 5200, "sujeta_iva": False}])
    d = _lineas([f])[1]
    assert _campo(d, 135, 139) == "05.20" and _campo(d, 140, 153) == "+0000000052.00" and _campo(d, 175, 175) == "N"


def test_emitida_lleva_tipo_de_factura_1():
    c = _lineas([dict(FACTURA, tipo="emitida")])[0]
    assert _campo(c, 58, 58) == "1"


def test_la_cuenta_se_ajusta_a_los_digitos_del_plan_y_a_12_posiciones():
    assert a3._cuenta("4000000", 8) == "400000000000" and a3._cuenta("400000012345", 8) == "400000010000" and a3._cuenta("40.000.001", 10) == "400000010000"
    assert a3._cuenta("", 8) == " " * 12 and a3._cuenta_o_blancos(None, 8) == " " * 12


def test_textos_largos_se_recortan_y_los_caracteres_raros_no_rompen_el_latin_1():
    f = dict(FACTURA, numero="1234567890123", nombre="Compañía “Ñ” – €" + "x" * 80, concepto="Línea\nnueva\r")
    ls = _lineas([f])
    assert all(len(l) == 254 for l in ls)
    assert _campo(ls[0], 59, 68) == "1234567890" and "\n" not in ls[0][:254]
    a3.generar([f], empresa=1).decode("latin-1")


def test_importes_y_porcentajes():
    assert a3._importe(123456) == "+0000001234.56" and a3._importe(-5, True) == "-0000000000.05" and a3._importe(-5) == "+0000000000.05"
    assert a3._porcentaje(2100) == "21.00" and a3._porcentaje(400) == "04.00" and a3._porcentaje(2150) == "21.50" and a3._porcentaje(0) == "00.00"


@pytest.mark.parametrize("base,pct,esperado", [(100000, 2100, 21000), (1, 2100, 0), (50, 2100, 11), (33333, 1000, 3333), (33335, 1000, 3334)])
def test_cuota_redondea_al_centimo(base, pct, esperado):
    assert a3.cuota(base, pct) == esperado


def test_fechas():
    assert a3._fecha("2026-02-03") == "20260203" and a3._fecha(None) == "00000000" and a3._fecha("basura") == "00000000"
