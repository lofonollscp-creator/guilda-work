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
