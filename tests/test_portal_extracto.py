"""«Revisar mi extracto» (L4), parte del servidor: solo sale lo mínimo para comparar en el navegador y solo del propio cliente."""
import json
from datetime import date, timedelta

from app import db, portal_extracto
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures


def _factura(t, c, fecha, total, estado="revisada"):
    conn = db.get_connection()
    conn.execute("INSERT INTO facturas_contables (tenant_id, cliente_fiscal_id, tipo, estado, fecha, numero, tercero_nombre, total_centimos, origen, creado_en, actualizado_en) VALUES (?, ?, 'recibida', ?, ?, 'N', 'Proveedor', ?, 'portal', ?, ?)",
                 (t, c, estado, fecha, total, db.now_iso(), db.now_iso()))
    conn.commit(); conn.close()


def test_datos_trae_facturas_y_tiquets_del_cliente_sin_las_descartadas_ni_las_antiguas():
    t, u, c = _despacho("Ext datos")
    _t2, _u2, c2 = _despacho("Ext otro", cliente_email="otro@ejemplo.com", cliente_nombre="Otro SL")
    hoy = date.today()
    _factura(t, c, (hoy - timedelta(days=10)).isoformat(), 12100)
    _factura(t, c, (hoy - timedelta(days=10)).isoformat(), 999, estado="descartada")
    _factura(t, c, (hoy - timedelta(days=2000)).isoformat(), 555)
    _factura(_t2, c2, (hoy - timedelta(days=10)).isoformat(), 777)
    conn = db.get_connection()
    conn.execute("INSERT INTO justificantes_pendientes (tenant_id, cliente_fiscal_id, origen, fecha, importe_centimos, concepto, estado, huella, creado_en) VALUES (?, ?, 'cliente', ?, -450, 'Parking', 'tiquet', 'h1', ?)", (t, c, (hoy - timedelta(days=5)).isoformat(), db.now_iso()))
    conn.commit(); conn.close()
    d = portal_extracto.datos(_ficha(c))
    assert d["facturas"] == [{"f": (hoy - timedelta(days=10)).isoformat(), "t": 12100}]
    assert d["justificantes"] == [{"f": (hoy - timedelta(days=5)).isoformat(), "i": -450}]


def test_la_pagina_y_los_datos_exigen_sesion_y_no_se_guardan_en_cache(cliente, correo):
    t, u, c = _despacho("Ext rutas")
    assert cliente.get("/portal/extracto").status_code == 302 and cliente.get("/portal/extracto/datos.json").status_code == 302
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Revisar mi extracto" in _html(cliente, "/portal/extracto") and "no se envía a nadie" in _html(cliente, "/portal/extracto")
    r = cliente.get("/portal/extracto/datos.json")
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store" and json.loads(r.data) == {"facturas": [], "justificantes": []}
    assert "Revisar mi extracto del banco" in _html(cliente, "/portal/facturas")


def test_sin_el_modulo_de_facturas_no_existe(cliente, correo):
    from app import verticales
    t, u, c = _despacho("Ext sin modulo")
    verticales.fijar_activo(t, "contabilizacion", False)
    _entrar(cliente, c, "titular@ejemplo.com")
    assert cliente.get("/portal/extracto").status_code == 404 and cliente.get("/portal/extracto/datos.json").status_code == 404
