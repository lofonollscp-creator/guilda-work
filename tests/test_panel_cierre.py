"""«Qué falta para cerrar»: estado por cliente y trimestre (app/panel_cierre.py)."""
from datetime import date

from app import panel_cierre as cc, facturas_contables as fc
from tests.test_facturas_contables import LINEA, _datos, _despacho


def _crear(t, u, c, numero, fecha="2026-08-15", **kw):
    return fc.crear(t, u, c, _datos(numero=numero, fecha=fecha, tercero_nif="A58818501", **kw), [{**LINEA, "base": f"{100 + len(numero)},00"}])


def test_plazos_y_trimestres():
    assert cc.plazo("2026-T1") == date(2026, 4, 20) and cc.plazo("2026-T3") == date(2026, 10, 20) and cc.plazo("2026-T4") == date(2027, 1, 30)
    assert cc.trimestre_anterior(date(2026, 10, 5)) == "2026-T3" and cc.trimestre_anterior(date(2026, 1, 5)) == "2025-T4"
    assert cc.trimestre_actual(date(2026, 11, 10)) == "2026-T4"


def test_cuenta_lo_que_falta_en_cada_punto():
    t, u, c = _despacho()
    _crear(t, u, c, "A-1")                                                          # por revisar
    listas = _crear(t, u, c, "A-22")
    fc.cambiar_estado(t, u, listas, "revisada", confirmar_duplicado=True)
    p = cc.panel(t, u, "2026-T3", hoy=date(2026, 10, 10))
    assert p["dias"] == 10 and p["plazo"] == "2026-10-20"
    cl = p["clientes"][0]
    assert (cl["total"], cl["por_revisar"], cl["listas"], cl["sin_leer"], cl["listo"]) == (2, 1, 1, 0, False) and cl["faltan"] == 2
    assert p["resumen"] == {"clientes": 1, "listos": 0, "sin_facturas": 0, "faltan": 2}


def test_un_cliente_listo_y_la_confirmacion_solo_si_ya_la_usa():
    t, u, c = _despacho()
    f = _crear(t, u, c, "B-1")
    fc.cambiar_estado(t, u, f, "revisada", confirmar_duplicado=True)
    fc.exportar(t, u, c)
    cl = cc.panel(t, u, "2026-T3")["clientes"][0]
    assert cl["exportadas"] == 1 and cl["sin_confirmar"] == 0 and cl["listo"] and not cl["usa_retorno"]
    conn = fc.db.get_connection()
    try:
        conn.execute("UPDATE facturas_contables SET confirmada_en = ? WHERE id = ?", (fc.db.now_iso(), f)); conn.commit()
    finally:
        conn.close()
    g = _crear(t, u, c, "B-22", fecha="2026-08-20")
    fc.cambiar_estado(t, u, g, "revisada", confirmar_duplicado=True)
    fc.exportar(t, u, c)
    cl = cc.panel(t, u, "2026-T3")["clientes"][0]
    assert cl["usa_retorno"] and cl["sin_confirmar"] == 1 and not cl["listo"]


def test_un_cliente_configurado_sin_facturas_sale_como_sin_facturas_y_el_cerrado_al_final():
    t, u, c = _despacho()
    p = cc.panel(t, u, "2026-T3")
    assert p["clientes"][0]["sin_facturas"] and p["resumen"]["sin_facturas"] == 1
    fc.cerrar_periodo(t, u, c, "2026-T3")
    p = cc.panel(t, u, "2026-T3")
    assert p["clientes"][0]["cerrado"] and p["resumen"]["sin_facturas"] == 0 and p["resumen"]["listos"] == 1


def test_no_mezcla_trimestres_ni_clientes_ajenos():
    t, u, c = _despacho()
    _crear(t, u, c, "C-1", fecha="2026-05-10")                                      # segundo trimestre
    assert cc.panel(t, u, "2026-T3")["clientes"][0]["total"] == 0
    assert cc.panel(t, u, "2026-T2")["clientes"][0]["por_revisar"] == 1
    from tests.test_herramientas_contabilidad import _despacho as _otro_despacho
    t2, u2, c2 = _otro_despacho("Otro despacho cierre")
    assert all(x["cliente_fiscal_id"] != c for x in cc.panel(t2, u2, "2026-T2")["clientes"])


def test_la_pantalla_se_ve_y_enlaza_al_cierre_de_cada_cliente(cliente):
    from tests.test_facturas_contables import _web
    uid, t, c = _web(cliente, "panelcierre@ejemplo.com")
    fc.guardar_configuracion(t, uid, c, {"a3_empresa": "7", "digitos": "8"})
    _crear(t, uid, c, "P-1")
    r = cliente.get("/contabilidad/panel-cierre?trimestre=2026-T3")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Qué falta para cerrar" in html and "Cliente Web" in html and "/contabilidad/cierre?cliente_id=%d&amp;trimestre=2026-T3" % c in html
    assert cliente.get("/contabilidad/panel-cierre?trimestre=mal").status_code == 200       # un trimestre que no vale no rompe la pantalla
    assert "Qué falta para cerrar" in cliente.get("/contabilidad/").get_data(as_text=True)
