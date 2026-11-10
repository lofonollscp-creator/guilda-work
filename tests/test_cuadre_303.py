"""Cuadre del IVA de las facturas con el 303 simulado (app/cuadre_303.py)."""
import io

import pytest

from app import consultas_fiscal, cuadre_303 as cu, facturas_contables as fc, retorno_a3
from tests.test_facturas_contables import LINEA, _datos, _despacho, _web

NIF = "A58818501"


def _revisada(t, u, c, numero, tipo="recibida", lineas=None, **kw):
    fid = fc.crear(t, u, c, _datos(numero=numero, tipo=tipo, tercero_nif=NIF, **kw), lineas or [LINEA])          # 1.000 de base y 210 de IVA
    fc.cambiar_estado(t, u, fid, "revisada", confirmar_duplicado=True)
    return fid


def _simula(monkeypatch, casillas=None, bloqueos=()):
    monkeypatch.setattr(consultas_fiscal, "simular_303", lambda *a, **k: {"bloqueos": list(bloqueos), "casillas": casillas if casillas is not None else {}})


def test_el_iva_de_las_facturas_solo_cuenta_operaciones_interiores_y_los_abonos_restan():
    t, u, c = _despacho()
    _revisada(t, u, c, "C-1")                                                               # soportado 210
    _revisada(t, u, c, "V-1", tipo="emitida")                                               # repercutido 210
    _revisada(t, u, c, "C-2", lineas=[{**LINEA, "subtipo": "03"}])                          # intracomunitaria: no se compara
    _revisada(t, u, c, "C-3", abono="1", rectifica_numero="C-1", rectifica_fecha="2026-08-01", lineas=[{**LINEA, "base": "100,00"}])    # abono: resta 21
    fc.crear(t, u, c, _datos(numero="C-4", tercero_nif=NIF), [LINEA])                       # pendiente: no cuenta
    assert cu.iva_de_las_facturas(t, c, "2026-T3") == {"repercutido": 21000, "soportado": 21000 - 2100, "facturas": 3}


def test_las_que_no_van_a_guilda_fiscal_no_cuentan():
    t, u, c = _despacho()
    f = _revisada(t, u, c, "C-1")
    conn = fc.db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET incluir_en_fiscal = 0 WHERE id = ?", (f,)); conn.commit()
    finally:
        conn.close()
    assert cu.iva_de_las_facturas(t, c, "2026-T3")["soportado"] == 0


def test_la_diferencia_con_las_casillas_27_y_45(monkeypatch):
    t, u, c = _despacho()
    _revisada(t, u, c, "C-1"); _revisada(t, u, c, "V-1", tipo="emitida")
    _simula(monkeypatch, {"27": 210.0, "45": 168.0})
    r = cu.cuadrar(t, u, c, "2026-T3")
    assert r["disponible"] and r["modelo_303"] == {"devengado": 21000, "deducible": 16800} and r["diferencia"] == {"repercutido": 0, "soportado": 4200}


def test_sin_303_calculable_no_hay_con_que_comparar(monkeypatch):
    t, u, c = _despacho()
    _simula(monkeypatch, {}, bloqueos=["Falta el perfil fiscal"])
    r = cu.cuadrar(t, u, c, "2026-T3")
    assert not r["disponible"] and "perfil" in r["motivo"]
    monkeypatch.setattr(consultas_fiscal, "simular_303", lambda *a, **k: (_ for _ in ()).throw(ValueError("El módulo Guilda Fiscal no está activo")))
    assert not cu.cuadrar(t, u, c, "2026-T3")["disponible"]
    with pytest.raises(ValueError):
        cu.cuadrar(t, u, c, "mal")


def test_la_pantalla_del_retorno_enseña_el_cuadre_con_el_303(cliente, monkeypatch):
    uid, t, c = _web(cliente, "cuadre303@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    _revisada(t, uid, c, "C-1")
    fc.exportar(t, uid, c)
    _simula(monkeypatch, {"27": 0.0, "45": 210.0})
    listado = "Nº Factura;Fecha;Total;Cuota IVA\nC-1;15/08/2026;1.210,00;210,00\n".encode("cp1252")
    r = cliente.post("/contabilidad/retorno", data={"cliente_id": c, "archivo": (io.BytesIO(listado), "a3.csv")}, content_type="multipart/form-data")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Cuadre con el modelo 303" in html and "Casilla 45" in html
