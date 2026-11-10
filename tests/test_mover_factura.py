"""Mover una factura al cliente correcto del despacho (L11): sugerencia al leerla y movimiento con su archivo."""
import json

import pytest

from app import facturas_contables as fc, lectura_facturas as lf
from app.db_fiscal import crear_cliente_fiscal
from tests.test_facturas_contables import PDF, _despacho, _web
from tests.test_lectura_facturas import RESPUESTA, modelo  # noqa: F401 -- fixture

OTRO_NIF = "A58818501"


def _con_archivo(t, u, c, sufijo=b"1"):
    return fc.subir_archivos(t, u, c, "recibida", [("f.pdf", "application/pdf", PDF + sufijo)])[0]


def test_la_sugerencia_solo_sale_si_la_factura_no_es_de_este_cliente_y_si_es_de_otro():
    t, u, c = _despacho()
    otro = crear_cliente_fiscal(t, "Otro SL", nif=OTRO_NIF)
    valores = {"emisor_nif": "B87654321", "receptor_nif": OTRO_NIF}
    assert lf._cliente_probable(t, u, c, "B12345678", valores) == {"id": otro, "nombre": "Otro SL"}
    assert lf._cliente_probable(t, u, c, OTRO_NIF, valores) is None                              # es de este cliente
    assert lf._cliente_probable(t, u, c, "B12345678", {"emisor_nif": "B87654321", "receptor_nif": "B11111111"}) is None     # de nadie conocido
    assert lf._cliente_probable(t, u, c, "", valores) is None


def test_al_leer_una_factura_de_otro_cliente_avisa_y_guarda_la_sugerencia(modelo):
    t, u, c = _despacho()
    otro = crear_cliente_fiscal(t, "Otro SL", nif=OTRO_NIF)
    modelo.respuesta = json.dumps({**RESPUESTA, "emisor_nif": "B87654321", "receptor_nif": OTRO_NIF})
    fid = _con_archivo(t, u, c)
    avisos = lf.leer(t, u, fid)
    f = fc.obtener(t, u, fid)
    assert any("otro cliente de tu despacho (Otro SL)" in a for a in avisos) and lf.evidencia_de(f)["posible_cliente"] == {"id": otro, "nombre": "Otro SL"}


def test_mover_lleva_el_archivo_y_quita_las_cuentas_del_otro_cliente():
    t, u, c = _despacho()
    otro = crear_cliente_fiscal(t, "Otro SL", nif=OTRO_NIF)
    fid = _con_archivo(t, u, c)
    f = fc.obtener(t, u, fid)
    fc.actualizar(t, u, fid, {"tipo": "recibida", "fecha": "2026-08-15", "numero": "M-1", "tercero_nombre": "X", "tercero_nif": OTRO_NIF, "tercero_cuenta": "40001234"}, [{"base": "10,00", "pct_iva": "21", "cuenta": "62900001"}])
    from app import almacen_documentos
    assert len(almacen_documentos.listar_de_cliente_fiscal(t, c)) == 1
    fc.mover_a_cliente(t, u, fid, otro)
    g = fc.obtener(t, u, fid)
    assert g["cliente_fiscal_id"] == otro and g["tercero_cuenta"] is None and g["lineas"][0]["cuenta"] is None
    assert len(almacen_documentos.listar_de_cliente_fiscal(t, otro)) == 1 and almacen_documentos.listar_de_cliente_fiscal(t, c) == []
    assert almacen_documentos.leer_de_cliente_fiscal(t, otro, g["documento_id"], u) is not None
    assert [h["que"] for h in fc.historial(t, u, fid)][0] == "Movida a otro cliente"


def test_no_se_mueve_lo_que_no_esta_pendiente_ni_al_mismo_cliente_ni_a_uno_inexistente():
    t, u, c = _despacho()
    otro = crear_cliente_fiscal(t, "Otro SL", nif=OTRO_NIF)
    fid = fc.crear(t, u, c, {"tipo": "recibida", "fecha": "2026-08-15", "numero": "N-1", "tercero_nombre": "X", "tercero_nif": OTRO_NIF}, [{"base": "10,00", "pct_iva": "21"}])
    with pytest.raises(ValueError, match="ya es de ese cliente"):
        fc.mover_a_cliente(t, u, fid, c)
    with pytest.raises(ValueError):
        fc.mover_a_cliente(t, u, fid, 999999)
    fc.cambiar_estado(t, u, fid, "revisada")
    with pytest.raises(ValueError, match="pendiente"):
        fc.mover_a_cliente(t, u, fid, otro)


def test_la_ficha_ofrece_mover_y_la_ruta_lo_hace(cliente):
    uid, t, c = _web(cliente, "moverfactura@ejemplo.com")
    otro = crear_cliente_fiscal(t, "Otro SL", nif=OTRO_NIF)
    fid = fc.crear(t, uid, c, {"tipo": "recibida", "fecha": "2026-08-15", "numero": "R-1", "tercero_nombre": "X", "tercero_nif": OTRO_NIF}, [{"base": "10,00", "pct_iva": "21"}])
    conn = fc.db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET lectura = 'ia', lectura_evidencia = ? WHERE id = ?", (json.dumps({"campos": {}, "posible_cliente": {"id": otro, "nombre": "Otro SL"}}), fid)); conn.commit()
    finally:
        conn.close()
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "Moverla a Otro SL" in html
    r = cliente.post(f"/contabilidad/{fid}/mover", data={"cliente_destino": otro})
    assert r.status_code == 302 and fc.obtener(t, uid, fid)["cliente_fiscal_id"] == otro
    assert "La factura se ha movido" in cliente.get(f"/contabilidad/{fid}?movida=1").get_data(as_text=True)


# --- L13: tiques y facturas simplificadas ---------------------------------------------------------------------------------------------------------------------

def test_un_tique_emitido_no_necesita_el_nif_del_cliente_y_uno_recibido_si():
    from app import facturas_control as ctrl
    from tests.test_facturas_contables import _datos
    t, u, c = _despacho()
    sin_nif = {"tipo": "emitida", "fecha": "2026-08-15", "numero": "T-1", "tercero_nombre": "Cliente de mostrador"}
    normal = fc.crear(t, u, c, sin_nif, [{"base": "10,00", "pct_iva": "21"}])
    assert any("Falta el NIF" in p for p in fc.obtener(t, u, normal)["problemas"])
    tique = fc.crear(t, u, c, {**sin_nif, "numero": "T-2", "clave_340": "1"}, [{"base": "10,00", "pct_iva": "21"}])
    f = fc.obtener(t, u, tique)
    assert not any("Falta el NIF" in p for p in f["problemas"]) and f["a3"] == {"clave_340": "1"}
    recibido = fc.crear(t, u, c, {**_datos(numero="T-3"), "tercero_nif": "", "clave_340": "1"}, [{"base": "10,00", "pct_iva": "21"}])
    assert any("Falta el NIF" in p for p in fc.obtener(t, u, recibido)["problemas"])
    grande = fc.crear(t, u, c, {**sin_nif, "numero": "T-4", "clave_340": "1"}, [{"base": "500,00", "pct_iva": "21"}])
    assert any("no puede pasar de 400" in m for m in ctrl.avisos(t, fc.obtener(t, u, grande)))
    assert not any("no puede pasar de" in m for m in ctrl.avisos(t, f))


def test_la_lectura_marca_el_tique_y_no_toca_lo_que_ya_habia_si_no_es_tique():
    t, u, c = _despacho()
    f = {"tipo": "emitida", "tercero_nombre": "X", "tercero_nif": "", "numero": "1", "fecha": "2026-08-15"}
    base = {"emisor_nif": "B12345678", "receptor_nif": None, "numero": "7", "fecha": "2026-08-15", "total": 12.10, "lineas": [{"base": 10, "pct_iva": 21, "cuota_iva": 2.1}]}
    _, nuevos, _, _ = lf._a_factura({**base, "simplificada": True}, f, "B12345678", "")
    assert nuevos["datos_a3"] == {"clave_340": "1"}
    _, nuevos, _, _ = lf._a_factura(base, f, "B12345678", "")
    assert "datos_a3" not in nuevos
    _, nuevos, _, _ = lf._a_factura({**base, "simplificada": True, "receptor_nif": "A58818501"}, f, "B12345678", "")
    assert "datos_a3" not in nuevos, "con NIF del cliente ya no es un tique"
