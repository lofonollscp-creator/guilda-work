"""Controles previos de una factura (app/facturas_control.py): duplicados, NIF, numeración, fechas e intracomunitarias."""
from datetime import date

import pytest

from app import db, facturas_contables as fc, facturas_control as ctl
from tests.test_facturas_contables import LINEA, _datos, _despacho


@pytest.mark.parametrize("nif,esperado", [("12345678Z", True), ("12345678A", False), ("X1234567L", True), ("X1234567A", False), ("A58818501", True), ("A58818502", False), ("FR12345678901", None), ("", None)])
def test_nif_espanol(nif, esperado):
    assert ctl.nif_espanol_valido(nif) is esperado


def test_nif_ue_con_formato():
    assert ctl.nif_ue_con_formato("FR12345678901") is True and ctl.nif_ue_con_formato("DE123456789") is True
    assert ctl.nif_ue_con_formato("XX123") is False and ctl.nif_ue_con_formato("") is None


def test_vies_contesta_y_no_contesta(monkeypatch):
    from app import vies
    monkeypatch.setattr(vies, "valido", lambda nif: True if nif == "FR12345678901" else None)
    assert ctl.comprobar_vies("FR12345678901") == {"valido": True, "error": ""}
    assert ctl.comprobar_vies("DE123456789")["valido"] is None and "no contestó" in ctl.comprobar_vies("DE123456789")["error"]
    assert ctl.comprobar_vies("12345678Z")["valido"] is None and "código del país" in ctl.comprobar_vies("12345678Z")["error"]


def test_duplicados_por_numero_importe_y_sin_nif():
    t, u, c = _despacho()
    a = fc.crear(t, u, c, _datos(numero="F-9"), [LINEA])
    b = fc.crear(t, u, c, _datos(numero="f-9"), [LINEA])
    d = fc.crear(t, u, c, _datos(numero="F-10", fecha="2026-08-17"), [LINEA])
    assert [x["motivo"] for x in ctl.duplicados(t, fc.obtener(t, u, b)) if x["id"] == a] == ["mismo número"]
    assert [x["motivo"] for x in ctl.duplicados(t, fc.obtener(t, u, d)) if x["id"] == a] == ["mismo importe y fecha"]


def test_un_abono_no_es_duplicado_de_su_factura():
    t, u, c = _despacho()
    a = fc.crear(t, u, c, _datos(numero="F-5"), [LINEA])
    ab = fc.crear(t, u, c, _datos(numero="F-5", abono="1", rectifica_numero="F-5", rectifica_fecha="2026-08-15"), [LINEA])
    assert ctl.duplicados(t, fc.obtener(t, u, ab)) == [] and a


def test_revisar_una_copia_pide_confirmar():
    t, u, c = _despacho()
    a = fc.crear(t, u, c, _datos(numero="F-7"), [LINEA]); fc.cambiar_estado(t, u, a, "revisada")
    b = fc.crear(t, u, c, _datos(numero="F-7"), [LINEA])
    with pytest.raises(ValueError, match="repetida"):
        fc.cambiar_estado(t, u, b, "revisada")
    fc.cambiar_estado(t, u, b, "revisada", confirmar_duplicado=True)
    assert fc.obtener(t, u, b)["estado"] == "revisada"


def test_avisos_de_nif_fecha_total_y_propio():
    t, u, c = _despacho()
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(tercero_nif="12345678A", fecha="2020-01-01"), [LINEA]))
    texto = " ".join(ctl.avisos(t, f, hoy=date(2026, 8, 20)))
    assert "dígito de control" in texto and "más de 4 años" in texto
    propio = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="P-1", tercero_nif="B12345678"), [LINEA]))
    assert "del propio titular" in " ".join(ctl.avisos(t, propio, hoy=date(2026, 8, 20)))
    futura = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="P-2", fecha="2026-12-01"), [LINEA]))
    assert "futura" in " ".join(ctl.avisos(t, futura, hoy=date(2026, 8, 20)))


def test_aviso_de_hueco_en_la_numeracion_de_emitidas():
    t, u, c = _despacho()
    base = {"tipo": "emitida", "tercero_nombre": "Cliente A", "tercero_nif": "B87654321", "concepto": "Servicio"}
    fc.crear(t, u, c, {**base, "fecha": "2026-08-01", "numero": "2026-001"}, [LINEA])
    fc.crear(t, u, c, {**base, "fecha": "2026-08-02", "numero": "2026-002"}, [LINEA])
    f4 = fc.obtener(t, u, fc.crear(t, u, c, {**base, "fecha": "2026-08-04", "numero": "2026-004"}, [LINEA]))
    assert any("falta la factura 2026-003" in a for a in ctl.avisos(t, f4, hoy=date(2026, 8, 20)) if "numeración" in a)
    f3 = fc.obtener(t, u, fc.crear(t, u, c, {**base, "fecha": "2026-08-03", "numero": "2026-003"}, [LINEA]))
    assert not any("numeración" in a for a in ctl.avisos(t, fc.obtener(t, u, f4["id"]), hoy=date(2026, 8, 20)))
    assert not any("numeración" in a for a in ctl.avisos(t, f3, hoy=date(2026, 8, 20)))


def test_aviso_intracomunitaria_sin_nif_ue():
    t, u, c = _despacho()
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="I-1", tercero_nif="B87654321"), [{**LINEA, "pct_iva": "0", "subtipo": "03"}]))
    assert any("intracomunitaria" in a for a in ctl.avisos(t, f, hoy=date(2026, 8, 20)))


# --- Revisión rápida (L5) ----------------------------------------------------------------------------------------------------------------------

def _leida(t, c, numero, confianza, lectura="ia", **kw):
    f = fc.crear(t, db_usuario(t), c, _datos(numero=numero, **kw), [LINEA])
    conn = db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET lectura = ?, lectura_confianza = ? WHERE id = ?", (lectura, confianza, f)); conn.commit()
    finally:
        conn.close()
    return f


def db_usuario(t):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT id FROM usuarios WHERE tenant_id = ? ORDER BY id LIMIT 1", (t,)).fetchone()["id"]
    finally:
        conn.close()


def test_listar_las_dudosas_primero():
    t, u, c = _despacho()
    a = _leida(t, c, "C-1", 95); b = _leida(t, c, "C-2", 40, fecha="2026-08-14"); d = _leida(t, c, "C-3", 70, fecha="2026-08-13")
    assert [f["id"] for f in fc.listar(t, u, cliente_fiscal_id=c, estado="pendiente", orden="confianza")] == [b, d, a]


def test_revision_en_lote_solo_de_las_seguras():
    t, u, c = _despacho()
    segura = _leida(t, c, "L-1", 97, tercero_nif="A58818501")
    dudosa = _leida(t, c, "L-2", 60, tercero_nif="B87654322")
    sin_leer = fc.crear(t, u, c, _datos(numero="L-3", tercero_nif="B87654323"), [LINEA])
    mala = _leida(t, c, "L-4", 99, tercero_nif="12345678A")           # NIF con el control mal: hay algo que mirar
    assert [f["id"] for f in fc.revisables_en_lote(t, u, c)] == [segura]
    assert fc.revisar_en_lote(t, u, c) == {"revisadas": 1, "omitidas": 0}
    assert {fc.obtener(t, u, i)["estado"] for i in (dudosa, sin_leer, mala)} == {"pendiente"} and fc.obtener(t, u, segura)["estado"] == "revisada"
    assert fc.revisar_en_lote(t, u, c)["revisadas"] == 0


def test_siguiente_pendiente():
    t, u, c = _despacho()
    a = _leida(t, c, "S-1", 95); b = _leida(t, c, "S-2", 50, fecha="2026-08-14")
    assert fc.siguiente_pendiente(t, u, a) == b and fc.siguiente_pendiente(t, u, b) == a
    fc.cambiar_estado(t, u, b, "descartada")
    assert fc.siguiente_pendiente(t, u, a) is None


def test_rutas_de_revision_rapida(cliente):
    from tests.test_facturas_contables import _web
    uid, t, c = _web(cliente, "rapida@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    a = _leida(t, c, "R-1", 96, tercero_nif="A58818501")
    b = _leida(t, c, "R-2", 40, fecha="2026-08-14", tercero_nif="B87654322")
    lista = cliente.get(f"/contabilidad/?cliente_id={c}&estado=pendiente&orden=confianza").get_data(as_text=True)
    assert "Dar por buena 1 factura segura" in lista and lista.index("R-2") < lista.index("R-1")
    r = cliente.post("/contabilidad/revisar-seguras", data={"cliente_id": c})
    assert r.status_code == 302 and "en_lote=1" in r.headers["Location"]
    assert fc.obtener(t, uid, a)["estado"] == "revisada" and fc.obtener(t, uid, b)["estado"] == "pendiente"
    ficha = cliente.get(f"/contabilidad/{b}").get_data(as_text=True)
    assert "Revisar y pasar a la siguiente" in ficha and "contabilidad_atajos.js" in ficha and "Comprobar NIF en VIES" in ficha
    d = _leida(t, c, "R-3", 80, fecha="2026-08-13", tercero_nif="B87654323")
    r = cliente.post(f"/contabilidad/{b}/estado", data={"estado": "revisada", "siguiente": "1", "no_es_duplicado": "1"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/contabilidad/{d}")


# --- Mapa de cuentas de a3 (J1) ------------------------------------------------------------------------------------------------------------------

def test_mapa_de_cuentas_origen_y_cambio_a_mano():
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(numero="M-1", tercero_nif="B11111111", tercero_nombre="Genérico S.L."), [LINEA])
    fc.crear(t, u, c, _datos(numero="M-2", tercero_nif="B22222222", tercero_nombre="Fijado S.L.", tercero_cuenta="40000007"), [LINEA])
    fc.crear(t, u, c, _datos(numero="M-3", tercero_nif="", tercero_nombre="Sin NIF"), [LINEA])
    m = fc.mapa_de_cuentas(t, u, c)
    assert [(x["nif"], x["origen"]) for x in m["terceros"]] == [("B11111111", "generica"), ("B22222222", "recordada")] and m["sin_nif"] == 1 and m["faltan"] == 1
    fc.fijar_cuenta_tercero(t, u, c, "proveedor", "B11111111", "40000042")
    m = fc.mapa_de_cuentas(t, u, c)
    assert {x["nif"]: (x["cuenta"], x["origen"]) for x in m["terceros"]}["B11111111"] == ("40000042", "recordada") and m["faltan"] == 0
    with pytest.raises(ValueError, match="no tiene los dígitos"):
        fc.fijar_cuenta_tercero(t, u, c, "proveedor", "B11111111", "4000042")
    f = fc.obtener(t, u, fc.crear(t, u, c, _datos(numero="M-4", tercero_nif="B11111111"), [LINEA]))
    assert fc.cuenta_efectiva(t, f) == "40000042"


def test_mapa_con_numeracion_automatica_y_pagina(cliente):
    from tests.test_facturas_contables import _web
    uid, t, c = _web(cliente, "mapa@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8", "subcuentas_auto": "1"})
    fc.crear(t, uid, c, _datos(numero="N-1", tercero_nif="B33333333"), [LINEA])
    assert [x["origen"] for x in fc.mapa_de_cuentas(t, uid, c)["terceros"]] == ["nueva"]
    html = cliente.get(f"/contabilidad/cliente/{c}/cuentas").get_data(as_text=True)
    assert "Mapa de cuentas" in html and "B33333333" in html and "Nueva: se numerará sola" in html
    r = cliente.post(f"/contabilidad/cliente/{c}/cuentas", data={"cuenta__proveedor__B33333333": "40000099"})
    assert "Subcuentas guardadas: 1 cambios" in r.get_data(as_text=True) and fc.mapa_de_cuentas(t, uid, c)["terceros"][0]["cuenta"] == "40000099"
    assert "Mapa de cuentas" in cliente.get(f"/contabilidad/cliente/{c}/configuracion").get_data(as_text=True)


# --- F3: historial de la factura ---------------------------------------------------------------------------------------------------------------------------

def test_el_historial_cuenta_lo_que_paso_con_la_factura_y_sus_cambios():
    from app import facturas_contables as fc
    from tests.test_facturas_contables import LINEA, _datos, _despacho
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(numero="H-1", tercero_nif="A58818501"), [LINEA])
    fc.actualizar(t, u, fid, _datos(numero="H-2", tercero_nif="A58818501", concepto="Otro"), [{**LINEA, "base": "2.000,00"}])
    fc.cambiar_estado(t, u, fid, "revisada")
    fc.exportar(t, u, c)
    h = fc.historial(t, u, fid)
    que = [x["que"] for x in h]
    assert que == ["Exportada a a3", "Dada por revisada", "Editada", "Anotada"]                  # lo más reciente primero
    editada = next(x for x in h if x["que"] == "Editada")
    assert "el número: H-1 → H-2" in editada["detalle"] and "el total: 1210.00 → 2420.00" in editada["detalle"] and "los importes" in editada["detalle"]
    assert h[0]["detalle"].startswith("#")
    assert fc.historial(t, u, 999999) == []


def test_la_ficha_muestra_el_historial(cliente):
    from app import facturas_contables as fc
    from tests.test_facturas_contables import LINEA, _datos, _web
    uid, t, c = _web(cliente, "historialficha@ejemplo.com")
    fid = fc.crear(t, uid, c, _datos(numero="H-9", tercero_nif="A58818501"), [LINEA])
    html = cliente.get(f"/contabilidad/{fid}").get_data(as_text=True)
    assert "Historial de la factura" in html and "Anotada" in html


# --- L12: abonos frente a la factura que rectifican --------------------------------------------------------------------------------------------------------

def _abono(t, u, c, numero, rectifica, base, **kw):
    from app import facturas_contables as fc
    from tests.test_facturas_contables import _datos
    return fc.crear(t, u, c, _datos(numero=numero, abono="1", rectifica_numero=rectifica, rectifica_fecha="2026-08-01", tercero_nif="A58818501", **kw), [{"base": base, "pct_iva": "21"}])


def test_un_abono_avisa_si_su_factura_no_esta_o_si_la_supera():
    from app import facturas_contables as fc, facturas_control as ctrl
    from tests.test_facturas_contables import LINEA, _datos, _despacho
    t, u, c = _despacho()
    a1 = _abono(t, u, c, "AB-1", "F-100", "10,00")
    assert any("No tengo en este cliente la factura F-100" in m for m in ctrl.avisos(t, fc.obtener(t, u, a1)))
    original = fc.crear(t, u, c, _datos(numero="F-100", tercero_nif="A58818501"), [{**LINEA, "base": "100,00"}])           # 121,00 con IVA
    assert not any("No tengo" in m for m in ctrl.avisos(t, fc.obtener(t, u, a1)))
    grande = _abono(t, u, c, "AB-2", "f-100", "500,00")
    assert any("es mayor que la factura que rectifica" in m for m in ctrl.avisos(t, fc.obtener(t, u, grande)))


def test_varios_abonos_que_juntos_superan_la_factura_se_avisan():
    from app import facturas_contables as fc, facturas_control as ctrl
    from tests.test_facturas_contables import LINEA, _datos, _despacho
    t, u, c = _despacho()
    fc.crear(t, u, c, _datos(numero="F-200", tercero_nif="A58818501"), [{**LINEA, "base": "100,00"}])                      # 121,00
    _abono(t, u, c, "AB-1", "F-200", "60,00")                                                                              # 72,60
    segundo = _abono(t, u, c, "AB-2", "F-200", "60,00")                                                                    # 72,60: juntos 145,20 > 121,00
    m = ctrl.avisos(t, fc.obtener(t, u, segundo))
    assert any("se supera lo facturado" in x and "145.20" in x for x in m) and not any("es mayor" in x for x in m)


# --- J10: reabierta tras exportarla ----------------------------------------------------------------------------------------------------------------------

def test_una_factura_reabierta_tras_exportarla_avisa_de_que_a3_ya_tiene_la_anterior():
    from app import facturas_contables as fc, facturas_control as ctrl, panel_cierre
    from tests.test_facturas_contables import LINEA, _datos, _despacho
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(numero="X-1", tercero_nif="A58818501"), [LINEA])
    fc.cambiar_estado(t, u, fid, "revisada")
    lote = fc.exportar(t, u, c)["lote"]
    assert not any("Ya salió" in m for m in ctrl.avisos(t, fc.obtener(t, u, fid)))
    fc.cambiar_estado(t, u, fid, "pendiente")
    m = [x for x in ctrl.avisos(t, fc.obtener(t, u, fid)) if "Ya salió" in x]
    assert len(m) == 1 and f"#{lote}" in m[0] and "confirmada" not in m[0]
    assert panel_cierre.panel(t, u, "2026-T3")["clientes"][0]["a_corregir"] == 1


def test_si_a3_la_habia_confirmado_antes_de_reabrirla_el_aviso_lo_dice():
    from app import facturas_contables as fc, facturas_control as ctrl, retorno_a3
    from tests.test_facturas_contables import LINEA, _datos, _despacho
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(numero="X-3", fecha="2026-08-15", tercero_nif="A58818501"), [LINEA])
    fc.cambiar_estado(t, u, fid, "revisada")
    fc.exportar(t, u, c)
    retorno_a3.cruzar(t, u, c, retorno_a3.leer("Nº Factura;Fecha;Total\nX-3;15/08/2026;1.210,00\n".encode("cp1252"), "l.csv"))
    fc.cambiar_estado(t, u, fid, "pendiente")
    assert any("a3 la tiene contabilizada (confirmada el" in x for x in ctrl.avisos(t, fc.obtener(t, u, fid)))


def test_el_prechequeo_de_la_exportacion_repite_ese_aviso():
    from app import facturas_contables as fc
    from tests.test_facturas_contables import LINEA, _datos, _despacho
    t, u, c = _despacho()
    fid = fc.crear(t, u, c, _datos(numero="X-2", tercero_nif="A58818501"), [LINEA])
    fc.cambiar_estado(t, u, fid, "revisada")
    fc.exportar(t, u, c)
    fc.cambiar_estado(t, u, fid, "pendiente")
    fc.cambiar_estado(t, u, fid, "revisada")
    assert any("X-2" in a["mensaje"] and "Ya salió" in a["mensaje"] for a in fc.comprobar_exportacion(t, u, c)["avisos"])
