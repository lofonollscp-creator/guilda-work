"""«Tu negocio este trimestre» (A3): previsión del IVA, mayores gastos y avisos con diferencias claras."""
from datetime import date

from app import db, portal_negocio as pn, verticales
from tests.test_portal_dossier import _factura
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def test_sin_facturas_no_hay_nada_que_enseñar():
    t, u, c = _despacho("Negocio vacio")
    assert pn.calcular(_ficha(c), date(2026, 11, 20)) is None


def test_la_prevision_extrapola_el_iva_solo_cuando_ya_ha_pasado_bastante_trimestre():
    t, u, c = _despacho("Negocio prevision")
    _factura(c, "emitida", "2026-10-05", "1210,00")                    # base 1000, IVA 210
    _factura(c, "recibida", "2026-10-10", "605,00")                    # base 500, IVA 105
    _factura(c, "recibida", "2026-10-12", "121,00", estado="pendiente")
    antes = pn.calcular(_ficha(c), date(2026, 10, 10))                 # día 10: demasiado pronto
    assert antes["prevision_iva"] is None and antes["pendientes"] == 1
    r = pn.calcular(_ficha(c), date(2026, 11, 15))                     # día 46 de 92: la mitad
    assert r["iva_ahora"] == 21000 - 10500 and r["prevision_iva"] == (21000 - 10500) * 2 and (r["dias_pasados"], r["dias_totales"]) == (46, 92)
    assert r["proveedores"][0]["base"] == 50000


def test_avisa_de_gastos_muy_por_encima_de_la_media_y_no_con_diferencias_pequenas():
    t, u, c = _despacho("Negocio avisos")
    for mes in ("2026-01-10", "2026-04-10", "2026-07-10"):             # tres trimestres normales: 1000 € de gastos
        _factura(c, "recibida", mes, "1210,00")
        _factura(c, "emitida", mes.replace("-10", "-12"), "6050,00")
    _factura(c, "recibida", "2026-10-05", "3025,00")                   # este trimestre ya lleva 2500 € a mitad: 5000 al ritmo
    _factura(c, "emitida", "2026-10-06", "6050,00")
    a = pn.calcular(_ficha(c), date(2026, 11, 15))["avisos"]
    assert any(x["clave"] == "gastos_altos" and x["pct"] > 100 for x in a)
    t2, u2, c2 = _despacho("Negocio sin aviso", cliente_email="otro@ejemplo.com", cliente_nombre="Otra SL")
    for mes in ("2026-01-10", "2026-04-10", "2026-07-10"):
        _factura(c2, "recibida", mes, "1210,00")
    _factura(c2, "recibida", "2026-10-05", "700,00")                   # ~1200 al ritmo: dentro de lo normal
    assert not any(x["clave"] == "gastos_altos" for x in pn.calcular(_ficha(c2), date(2026, 11, 15))["avisos"])


def test_avisa_de_ventas_que_caen_y_del_iva_a_pagar_sin_ruido_si_hay_poco_dinero():
    t, u, c = _despacho("Negocio ventas")
    for mes in ("2026-01-10", "2026-04-10", "2026-07-10"):
        _factura(c, "emitida", mes, "12100,00")
    _factura(c, "emitida", "2026-10-05", "1210,00")
    assert any(x["clave"] == "ventas_bajas" for x in pn.calcular(_ficha(c), date(2026, 11, 15))["avisos"])
    t2, u2, c2 = _despacho("Negocio poco", cliente_email="poco@ejemplo.com", cliente_nombre="Poco SL")
    _factura(c2, "emitida", "2026-10-05", "60,50")                      # IVA minúsculo: no se avisa
    assert pn.calcular(_ficha(c2), date(2026, 11, 15))["avisos"] == []


def test_la_pagina_de_impuestos_lo_enseña_solo_con_el_modulo_de_facturas(cliente, correo):
    t, u, c = _despacho("Negocio web")
    _factura(c, "emitida", date.today().replace(day=1).isoformat(), "1210,00")
    _entrar(cliente, c, "titular@ejemplo.com")
    html = _html(cliente, "/portal/impuestos")
    assert "Tu negocio este trimestre" in html and "Ventas hasta hoy" in html
    verticales.fijar_activo(t, "contabilizacion", False)
    assert "Tu negocio este trimestre" not in _html(cliente, "/portal/impuestos")
