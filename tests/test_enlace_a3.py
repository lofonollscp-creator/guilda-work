"""Fichero de enlace de entrada de a3asesor Eco / Con (app/enlace_a3.py): cada campo en la posición que fija el documento oficial de Wolters Kluwer «Enlace de entrada en a3asesor Eco y a3asesor Con
para el SII» (descripción de registros 9.80): registros de 512 bytes (510 caracteres + CR LF), posiciones de 1 a 512."""
import pytest

from app import enlace_a3 as a3

FACTURA = {"tipo": "recibida", "fecha": "2026-09-30", "fecha_operacion": "2026-09-28", "numero": "A-123", "concepto": "Compra de material", "nif": "B12345678",
           "nombre": "Proveedor Ñandú S.L.", "cuenta_tercero": "40000001", "total_centimos": 121000,
           "lineas": [{"cuenta": "62900000", "descripcion_cuenta": "Compras", "subtipo": "01", "base_centimos": 100000, "pct_iva": 2100, "cuota_iva": 21000, "cuenta_iva": "47200000"}]}


def _campo(linea: str, desde: int, hasta: int) -> str:
    """Posiciones del documento: de 1 a 510 (las 511-512 son el CR LF), inclusivas."""
    return linea[desde - 1:hasta]


def _lineas(facturas, **kw):
    return a3.generar(facturas, empresa=kw.get("empresa", 12), digitos=kw.get("digitos", 8)).decode("latin-1").split("\r\n")[:-1]


def _comprobar(linea, esperado):
    for desde, hasta, valor in esperado:
        assert _campo(linea, desde, hasta) == valor, f"posiciones {desde}-{hasta}"


def test_cada_registro_mide_512_bytes_y_acaba_en_cr_lf():
    contenido = a3.generar([FACTURA], empresa=12)
    assert len(contenido) == 2 * 512 and contenido.endswith(b"\r\n")
    assert all(len(l) == 510 for l in _lineas([FACTURA]))
    assert all(c[508:] == "EN" for c in _lineas([FACTURA])), "moneda euros (509) e indicador de generado N (510)"


def test_cabecera_tipo_1_campo_a_campo():
    c = _lineas([FACTURA])[0]
    _comprobar(c, [(1, 1, "5"), (2, 6, "00012"), (7, 14, "20260930"), (15, 15, "1"), (16, 27, "400000010000"), (28, 57, "Proveedor Ñandú S.L.".ljust(30)), (58, 58, "2"), (59, 68, "A-123".ljust(10)),
                   (69, 69, "I"), (70, 99, "Compra de material".ljust(30)), (100, 113, "+0000001210.00"), (114, 175, " " * 62), (176, 189, "B12345678".ljust(14)),
                   (190, 229, "Proveedor Ñandú S.L.".ljust(40)), (230, 234, " " * 5), (235, 236, "  "), (237, 244, "20260928"), (245, 252, "20260930"), (253, 312, " " * 60), (313, 373, " " * 61),
                   (374, 375, "ES"), (376, 377, "02"), (378, 508, " " * 131), (509, 509, "E"), (510, 510, "N")])


def test_detalle_tipo_9_campo_a_campo():
    d = _lineas([FACTURA])[1]
    _comprobar(d, [(1, 1, "5"), (2, 6, "00012"), (7, 14, "20260930"), (15, 15, "9"), (16, 27, "629000000000"), (28, 57, "Compras".ljust(30)), (58, 58, "C"), (59, 68, "A-123".ljust(10)),
                   (69, 69, "U"), (70, 99, "Compra de material".ljust(30)), (100, 101, "01"), (102, 115, "+0000001000.00"), (116, 120, "21.00"), (121, 134, "+0000000210.00"), (135, 139, "00.00"),
                   (140, 153, "+0000000000.00"), (154, 158, "00.00"), (159, 172, "+0000000000.00"), (173, 174, "  "), (175, 175, "S"), (176, 178, "   "), (179, 191, " " * 13),
                   (192, 203, "472000000000"), (204, 215, " " * 12), (216, 227, " " * 12), (228, 239, " " * 12), (240, 251, " " * 12), (252, 252, " "), (253, 508, " " * 256), (509, 509, "E"), (510, 510, "N")])


def test_una_emitida_lleva_tipo_1_y_su_iva_repercutido_en_su_sitio():
    f = dict(FACTURA, tipo="emitida", nif="12345678Z", lineas=[dict(FACTURA["lineas"][0], cuenta="70000000", cuenta_iva="47700000")])
    c, d = _lineas([f])
    assert _campo(c, 58, 58) == "1"
    assert _campo(d, 192, 203) == " " * 12 and _campo(d, 228, 239) == "477000000000", "IVA repercutido: «cuenta de IVA 2 repercutido» (228-239)"


def test_una_linea_por_tipo_de_iva_y_solo_la_ultima_lleva_la_marca_u():
    f = dict(FACTURA, total_centimos=100000 + 21000 + 50000 + 5000,
             lineas=FACTURA["lineas"] + [{"cuenta": "62900000", "base_centimos": 50000, "pct_iva": 1000, "cuota_iva": 5000, "cuenta_iva": "47200000"}])
    assert [(l[14], l[68]) for l in _lineas([f])] == [("1", "I"), ("9", "M"), ("9", "U")]


def test_un_abono_usa_el_tipo_2_importes_en_positivo_tipo_de_importe_a_y_registro_4():
    f = dict(FACTURA, abono=True, rectifica_fecha="2026-08-01", rectifica_numero="A-100")
    c, d, r = _lineas([f])
    assert _campo(c, 15, 15) == "2" and _campo(c, 100, 113) == "+0000001210.00"
    assert _campo(d, 58, 58) == "A" and _campo(d, 102, 115) == "+0000001000.00" and _campo(d, 121, 134) == "+0000000210.00", "las rectificativas que disminuyen se informan en positivo"
    _comprobar(r, [(1, 1, "5"), (2, 6, "00012"), (7, 14, "20260930"), (15, 15, "4"), (16, 58, " " * 43), (59, 66, "20260801"), (67, 126, "A-100".ljust(60)), (127, 156, " " * 30), (157, 157, "R"),
                   (158, 303, " " * 146), (304, 304, "R"), (305, 508, " " * 204), (509, 509, " "), (510, 510, "N")])


def test_el_registro_4_de_una_emitida_dice_e_en_el_tipo_de_factura():
    f = dict(FACTURA, tipo="emitida", abono=True, rectifica_fecha="2026-08-01", rectifica_numero="E-9")
    assert _campo(_lineas([f])[2], 304, 304) == "E"


def test_la_retencion_va_con_su_cuenta_y_el_recargo_con_su_porcentaje():
    f = dict(FACTURA, total_centimos=100000 + 21000 + 5200 - 15000,
             lineas=[{"cuenta": "62300000", "base_centimos": 100000, "pct_iva": 2100, "cuota_iva": 21000, "pct_recargo": 520, "cuota_recargo": 5200, "pct_retencion": 1500, "cuota_retencion": 15000,
                      "cuenta_iva": "47200000", "cuenta_retencion": "47510000"}])
    d = _lineas([f])[1]
    _comprobar(d, [(135, 139, "05.20"), (140, 153, "+0000000052.00"), (154, 158, "15.00"), (159, 172, "+0000000150.00"), (216, 227, "475100000000")])


def test_iva_no_sujeto_marca_n():
    f = dict(FACTURA, lineas=[dict(FACTURA["lineas"][0], sujeta_iva=False, pct_iva=0, cuota_iva=0)])
    assert _campo(_lineas([f])[1], 175, 175) == "N"


def test_un_numero_largo_va_completo_en_el_campo_ampliado_y_resumido_en_las_10_posiciones():
    largo = "FRA/2026/0000012345-A"
    c = _lineas([dict(FACTURA, numero=largo)])[0]
    assert _campo(c, 59, 68) == largo[-10:] and _campo(c, 253, 312) == largo.ljust(60)
    d = _lineas([dict(FACTURA, numero=largo)])[1]
    assert _campo(d, 59, 68) == largo[-10:]
    assert a3.numero_corto("A-123") == "A-123" and a3.numero_corto("12345678901") == "2345678901" and a3.numero_corto(None) == ""


def test_nif_espanol_informa_pais_y_tipo_de_documento_y_uno_extranjero_no():
    assert (_campo(_lineas([dict(FACTURA, nif="12345678z")])[0], 374, 377)) == "ES02"
    assert (_campo(_lineas([dict(FACTURA, nif="DE123456789")])[0], 374, 377)) == "    "
    c = _lineas([dict(FACTURA, nif="")])[0]
    assert _campo(c, 176, 189) == " " * 14 and _campo(c, 190, 229) == " " * 40, "sin NIF no se informan ni nombre ni país"


def test_la_cuenta_se_ajusta_a_los_digitos_del_plan_y_a_12_posiciones():
    assert a3._cuenta("4000000", 8) == "400000000000" and a3._cuenta("400000012345", 8) == "400000010000" and a3._cuenta("40.000.001", 10) == "400000010000"
    assert a3._cuenta("", 8) == " " * 12 and a3._cuenta_o_blancos(None, 8) == " " * 12


def test_textos_largos_se_recortan_y_los_caracteres_raros_no_rompen_el_latin_1():
    f = dict(FACTURA, numero="1234567890123", nombre="Compañía “Ñ” – €" + "x" * 80, concepto="Línea\nnueva\r")
    ls = _lineas([f])
    assert all(len(l) == 510 for l in ls) and "\n" not in ls[0]
    a3.generar([f], empresa=1).decode("latin-1")


def test_importes_y_porcentajes():
    assert a3._importe(123456) == "+0000001234.56" and a3._importe(-5, True) == "-0000000000.05" and a3._importe(-5) == "+0000000000.05"
    assert a3._porcentaje(2100) == "21.00" and a3._porcentaje(400) == "04.00" and a3._porcentaje(2150) == "21.50" and a3._porcentaje(0) == "00.00"


@pytest.mark.parametrize("base,pct,esperado", [(100000, 2100, 21000), (1, 2100, 0), (50, 2100, 11), (33333, 1000, 3333), (33335, 1000, 3334)])
def test_cuota_redondea_al_centimo(base, pct, esperado):
    assert a3.cuota(base, pct) == esperado


def test_fechas():
    assert a3._fecha("2026-02-03") == "20260203" and a3._fecha(None) == "00000000" and a3._fecha("basura") == "00000000"


# --- Formato clásico de 256 posiciones (documento «Enlace contable de entrada. Descripción de registros») ---------------------------------------------------------

def _lineas256(facturas, **kw):
    return a3.generar(facturas, empresa=12, digitos=8, formato="256").decode("latin-1").split("\r\n")[:-1]


def test_en_256_cada_registro_mide_256_bytes_empieza_por_4_y_cierra_con_moneda_y_n():
    contenido = a3.generar([FACTURA], empresa=12, formato="256")
    assert len(contenido) == 2 * 256 and contenido.endswith(b"\r\n")
    ls = _lineas256([FACTURA])
    assert all(len(l) == 254 and l[0] == "4" and l[252:] == "EN" for l in ls), "tipo de formato 4 (1), moneda E (253), generado N (254)"


def test_en_256_la_cabecera_y_el_detalle_llevan_los_mismos_campos_hasta_la_252():
    c512, d512 = _lineas([FACTURA])
    c256, d256 = _lineas256([FACTURA])
    assert c256[1:252] == c512[1:252] and d256[1:252] == d512[1:252]            # solo cambian el tipo de formato (1) y el cierre; el resto es el mismo
    assert c256[14] == "1" and d256[14] == "9" and c256[57] == "2"


def test_en_256_el_numero_largo_se_recorta_a_las_10_posiciones_de_siempre():
    c = _lineas256([dict(FACTURA, numero="FRA/2026/0000123")])[0]
    assert _campo(c, 59, 68) == "2026/0000123"[-10:]


def test_un_bien_de_inversion_lleva_tipo_de_factura_3_y_en_las_ventas_no_vale():
    assert _campo(_lineas([dict(FACTURA, bien_inversion=True)])[0], 58, 58) == "3"
    assert _campo(_lineas([dict(FACTURA, tipo="emitida", bien_inversion=True, nif="12345678Z")])[0], 58, 58) == "1"


def test_ampliacion_del_formato_clasico_campo_a_campo():
    f = dict(FACTURA, ampliacion={"dua": "DUA-2026-777", "clave_340": "1", "nif_representante": "12345678z", "autofactura": "AUTO-9", "metalico": 150000, "inmuebles": True})
    registros = _lineas256([f])
    assert [r[14] for r in registros] == ["1", "9", "4"]
    a = registros[2]
    _comprobar(a, [(1, 1, "4"), (2, 6, "00012"), (7, 14, "20260930"), (15, 15, "4"), (16, 58, " " * 43), (59, 66, " " * 8), (67, 76, " " * 10), (77, 94, "DUA-2026-777".ljust(18)),
                   (95, 106, "400000010000"), (107, 107, "1"), (108, 121, "12345678Z".ljust(14)), (122, 131, "AUTO-9".ljust(10)), (132, 132, " "), (133, 146, "+0000001500.00"),
                   (147, 147, "S"), (148, 161, " " * 14), (162, 253, " " * 92), (254, 254, "N")])


def test_una_rectificativa_en_256_lleva_su_factura_en_59_a_76():
    f = dict(FACTURA, abono=True, rectifica_fecha="2026-08-01", rectifica_numero="A-100")
    a = _lineas256([f])[2]
    _comprobar(a, [(15, 15, "4"), (59, 66, "20260801"), (67, 76, "A-100".ljust(10)), (77, 94, " " * 18), (254, 254, "N")])


def test_sin_datos_de_ampliacion_ni_abono_no_hay_registro_4():
    assert [r[14] for r in _lineas256([FACTURA])] == ["1", "9"]
    assert [r[14] for r in _lineas([dict(FACTURA, ampliacion={"dua": "X"})])] == ["1", "9"], "en 512 las ampliaciones del 340 y 347 aún no salen (se desconocen sus posiciones)"


def test_formato_desconocido():
    with pytest.raises(ValueError):
        a3.generar([FACTURA], empresa=12, formato="128")


# --- Vencimientos (registros V) del formato clásico ---------------------------------------------------------------------------------------------------------

def test_el_vencimiento_se_genera_tras_la_factura_en_256_campo_a_campo():
    f = dict(FACTURA, vencimiento={"fecha": "2026-10-30", "forma_pago": "TR", "ccc": "21000418450200051332", "cuenta_tesoreria": "57200000"})
    registros = _lineas256([f])
    assert [r[14] for r in registros] == ["1", "9", "V", "V"]
    v, a = registros[2], registros[3]
    _comprobar(v, [(1, 1, "4"), (2, 6, "00012"), (7, 14, "20261030"), (15, 15, "V"), (16, 27, "400000010000"), (28, 57, "Proveedor Ñandú S.L.".ljust(30)), (58, 58, "P"), (59, 68, "A-123".ljust(10)),
                   (69, 69, " "), (70, 99, "Compra de material".ljust(30)), (100, 113, "+0000001210.00"), (114, 121, "20260930"), (122, 133, "572000000000"), (134, 135, "  "), (136, 137, "  "),
                   (138, 252, " " * 115), (253, 253, "E"), (254, 254, "N")])
    _comprobar(a, [(1, 1, "4"), (7, 14, "20261030"), (15, 15, "V"), (16, 58, " " * 43), (59, 60, "TR"), (61, 68, " " * 8), (69, 69, "A"), (70, 70, "P"), (71, 85, " " * 15), (86, 93, " " * 8),
                   (94, 113, "21000418450200051332"), (114, 252, " " * 139), (253, 253, "E"), (254, 254, "N")])


def test_una_emitida_genera_un_cobro_y_sin_forma_ni_cuenta_no_hay_ampliacion():
    f = dict(FACTURA, tipo="emitida", nif="12345678Z", vencimiento={"fecha": "2026-10-30"})
    registros = _lineas256([f])
    assert [r[14] for r in registros] == ["1", "9", "V"] and registros[2][57] == "C"


def test_ni_un_abono_ni_el_formato_de_512_llevan_vencimientos():
    assert [r[14] for r in _lineas256([dict(FACTURA, abono=True, rectifica_fecha="2026-08-01", rectifica_numero="A-1", vencimiento={"fecha": "2026-10-30"})])] == ["2", "9", "4"]
    assert [r[14] for r in _lineas([dict(FACTURA, vencimiento={"fecha": "2026-10-30"})])] == ["1", "9"]
