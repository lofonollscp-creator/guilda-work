"""Asientos de cobro y pago de las facturas ya exportadas (J26): generador, chequeo, función de negocio, pantalla y herramientas."""
import io

import pytest

from app import enlace_a3 as a3, enlace_a3_chequeo as ch, facturas_contables as fc
from tests.test_facturas_contables import LINEA, _datos, _despacho, _web

NIF = "A58818501"


def _campo(r, d, h):
    return r[d - 1:h]


def _asiento(**kw):
    base = {"fecha": "2026-10-05", "referencia": "F-123", "descripcion": "Pago fra. F-123",
            "lineas": [{"cuenta": "40000001", "nombre": "Proveedor", "debe": True, "importe_centimos": 121000}, {"cuenta": "57200000", "nombre": "Banco", "debe": False, "importe_centimos": 121000}]}
    return {**base, **kw}


def test_el_registro_tipo_0_campo_a_campo():
    ls = a3.generar_asientos([_asiento()], empresa=12).decode("latin-1").split("\r\n")[:-1]
    assert len(ls) == 2 and all(len(l) == 254 and l[0] == "4" and l[252:] == "EN" for l in ls)
    primero, ultimo = ls
    for r, dh, linea, cuenta, nombre in ((primero, "D", "I", "400000010000", "Proveedor"), (ultimo, "H", "U", "572000000000", "Banco")):
        assert (_campo(r, 2, 6), _campo(r, 7, 14), _campo(r, 15, 15), _campo(r, 16, 27), _campo(r, 28, 57).strip(), _campo(r, 58, 58), _campo(r, 59, 68).strip(), _campo(r, 69, 69), _campo(r, 100, 113)) == \
               ("00012", "20261005", "0", cuenta, nombre, dh, "F-123", linea, "+0000001210.00")
        assert _campo(r, 70, 99).strip() == "Pago fra. F-123" and _campo(r, 114, 252) == " " * 139


def test_un_asiento_de_tres_lineas_lleva_i_m_u_y_uno_descuadrado_o_corto_no_se_genera():
    tres = _asiento(lineas=[{"cuenta": "40000001", "debe": True, "importe_centimos": 100}, {"cuenta": "47200000", "debe": True, "importe_centimos": 21}, {"cuenta": "57200000", "debe": False, "importe_centimos": 121}])
    assert [l[68] for l in a3.generar_asientos([tres], empresa=1).decode("latin-1").split("\r\n")[:-1]] == ["I", "M", "U"]
    with pytest.raises(ValueError, match="no cuadra"):
        a3.generar_asientos([_asiento(lineas=[{"cuenta": "40000001", "debe": True, "importe_centimos": 5}, {"cuenta": "57200000", "debe": False, "importe_centimos": 6}])], empresa=1)
    with pytest.raises(ValueError, match="dos líneas"):
        a3.generar_asientos([_asiento(lineas=[{"cuenta": "40000001", "debe": True, "importe_centimos": 5}])], empresa=1)


def test_el_chequeo_acepta_un_fichero_bueno_y_detecta_asientos_rotos():
    bueno = a3.generar_asientos([_asiento(), _asiento(referencia="F-2")], empresa=12)
    assert ch.chequear(bueno, 8)["ok"] and ch.formato_de(bueno) == "256"
    mal = bytearray(bueno)
    mal[2 * 256 + 68 - 0] = ord("M")                                                    # la primera línea del 2.º asiento pasa de I a M
    r = ch.chequear(bytes(mal), 8)
    assert not r["ok"] and any("«I»" in e["mensaje"] for e in r["errores"])
    descuadrado = bytearray(bueno)
    descuadrado[99 + 13 - 2:99 + 13] = b"99"                                           # cambia los céntimos de la 1.ª línea
    assert any("no cuadra" in e["mensaje"] for e in ch.chequear(bytes(descuadrado), 8)["errores"])
    sin_u = bueno[:256]
    assert any("no acaba" in e["mensaje"] for e in ch.chequear(sin_u, 8)["errores"])


def _exportada(t, u, c, numero="F-1", tipo="recibida", **kw):
    fid = fc.crear(t, u, c, _datos(numero=numero, tipo=tipo, tercero_nif=NIF, **kw), [LINEA])
    fc.cambiar_estado(t, u, fid, "revisada", confirmar_duplicado=True)
    fc.exportar(t, u, c)
    return fid


def test_un_pago_y_un_cobro_salen_con_el_debe_y_el_haber_que_tocan_y_no_se_repiten():
    t, u, c = _despacho()
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "256", "cuenta_tesoreria": "57200001"})
    pago = _exportada(t, u, c, "F-1")
    cobro = _exportada(t, u, c, "V-1", tipo="emitida")
    assert {f["id"] for f in fc.facturas_para_asiento_de_pago(t, u, c)} == {pago, cobro}
    r = fc.asientos_de_pago(t, u, c, [{"factura_id": pago, "fecha": "2026-10-05"}, {"factura_id": cobro, "fecha": "2026-10-06", "importe": 50000}])
    ls = r["contenido"].decode("latin-1").split("\r\n")[:-1]
    assert r["asientos"] == 2 and r["registros"] == 4
    assert (ls[0][57], ls[0][15:27], ls[1][57], ls[1][15:27]) == ("D", "400000000000", "H", "572000010000")                 # pago: Debe el proveedor (genérica), Haber el banco
    assert (ls[2][57], ls[2][15:27], ls[3][57], ls[3][15:27], ls[3][99:113]) == ("D", "572000010000", "H", "430000000000", "+0000000500.00")      # cobro parcial: Debe el banco, Haber el cliente
    assert ch.chequear(r["contenido"], 8)["ok"] and fc.facturas_para_asiento_de_pago(t, u, c) == []
    lote = fc.listar_lotes(t, u)[0]
    assert lote["clase"] == "pagos" and lote["id"] == r["lote"] and fc.contenido_del_lote(t, u, r["lote"]) == r["contenido"]
    with pytest.raises(ValueError, match="ya tiene su asiento"):
        fc.asientos_de_pago(t, u, c, [{"factura_id": pago}])
    assert fc.asientos_de_pago(t, u, c, [{"factura_id": pago}], repetir=True)["asientos"] == 1
    assert [h["que"] for h in fc.historial(t, u, pago)][0] == "Asiento de cobro o pago generado"


def test_las_condiciones_formato_estado_y_importe_se_comprueban():
    t, u, c = _despacho()
    pendiente = fc.crear(t, u, c, _datos(numero="P-1", tercero_nif=NIF), [LINEA])
    with pytest.raises(ValueError, match="256 posiciones"):
        fc.asientos_de_pago(t, u, c, [{"factura_id": pendiente}])
    fc.guardar_configuracion(t, u, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "256"})
    with pytest.raises(ValueError, match="exportada"):
        fc.asientos_de_pago(t, u, c, [{"factura_id": pendiente}])
    ok = _exportada(t, u, c, "E-1")
    for malo in ({"factura_id": ok, "importe": 0}, {"factura_id": ok, "importe": 10 ** 9}, {"factura_id": ok, "fecha": "ayer"}, {"factura_id": 999999}):
        with pytest.raises(ValueError):
            fc.asientos_de_pago(t, u, c, [malo])
    with pytest.raises(ValueError):
        fc.asientos_de_pago(t, u, c, [])


def test_la_pantalla_lista_y_baja_el_fichero(cliente):
    uid, t, c = _web(cliente, "asientospago@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "256"})
    fid = _exportada(t, uid, c, "W-1")
    html = cliente.get(f"/contabilidad/pagos?cliente_id={c}").get_data(as_text=True)
    assert "Asientos de cobro y pago" in html and "W-1" in html and "Generar el fichero" in html
    r = cliente.post("/contabilidad/pagos", data={"cliente_id": c, "factura": fid, "fecha": "2026-10-05"})
    assert r.status_code == 200 and r.headers["Content-Disposition"].startswith("attachment") and ch.chequear(r.data, 8)["ok"]
    assert "No hay facturas pendientes de asiento" in cliente.get(f"/contabilidad/pagos?cliente_id={c}").get_data(as_text=True)
    assert "Cobros y pagos" in cliente.get("/contabilidad/lotes").get_data(as_text=True)
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8", "formato_enlace": "512"})
    assert "formato de 512 posiciones" in cliente.get(f"/contabilidad/pagos?cliente_id={c}").get_data(as_text=True)
