"""Bandejas de firmas y de honorarios del portal (L5, L6): lo pendiente y lo hecho en un solo sitio, con el recibo de cada pago."""
import pytest

from app import db, portal_firmas_honorarios as pfh, stripe_pagos
from tests.test_portal_justificantes_firma_carpeta import _como_cliente, _con_honorarios, _despacho, _html  # noqa: F401


def test_las_firmas_separan_lo_pendiente_de_lo_firmado(cliente):
    uid, t, c = _despacho(cliente, "firmas1@ejemplo.com")
    v1 = db.crear_vencimiento_fiscal(t, c, "303", "2026-T2", "2026-07-20", usuario_id=uid)
    v2 = db.crear_vencimiento_fiscal(t, c, "115", "2026-T2", "2026-07-20", usuario_id=uid)
    v3 = db.crear_vencimiento_fiscal(t, c, "130", "2026-T2", "2026-07-20", usuario_id=uid)
    db.editar_vencimiento_fiscal(t, v1, documenso_documento_id="env_1")
    db.editar_vencimiento_fiscal(t, v2, documenso_documento_id="env_2", documenso_firmado_en="2026-07-10T10:00:00")
    ficha = db.obtener_cliente_fiscal_por_id(c)
    f = pfh.firmas(ficha)
    assert [d["modelo"] for d in f["pendientes"]] == ["303"] and [d["modelo"] for d in f["firmadas"]] == ["115"]
    _como_cliente(cliente, c)
    pagina = _html(cliente, "/portal/firmas")
    assert "Modelo 303" in pagina and f"/portal/vencimientos/{v1}/firma" in pagina and "Modelo 115" in pagina and "Firmado el 2026-07-10" in pagina and "130" not in pagina
    assert "Mis firmas" in _html(cliente, "/portal/impuestos")


def test_sin_documentos_la_bandeja_de_firmas_lo_dice(cliente):
    uid, t, c = _despacho(cliente, "firmas2@ejemplo.com")
    _como_cliente(cliente, c)
    assert "No tienes ningún documento pendiente de firma" in _html(cliente, "/portal/firmas")


def test_los_honorarios_separan_lo_pendiente_de_lo_pagado_y_suman_lo_que_se_debe(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    uid, t, c, v = _con_honorarios(cliente, "hon1@ejemplo.com")
    v2 = db.crear_vencimiento_fiscal(t, c, "111", "2026-T2", "2026-07-20", usuario_id=uid)
    conn = db.get_connection()
    conn.execute("INSERT INTO honorarios_aplicados (tenant_id, vencimiento_id, cliente_fiscal_id, regla_nombre, concepto, importe_centimos, estado, confirmado_en) VALUES (?, ?, ?, 'Fija', 'Honorarios 111', 2500, 'confirmado', ?)", (t, v2, c, db.now_iso()))
    conn.commit(); conn.close()
    db.registrar_pago_vencimiento(v2, "cs_hon_1", 2500)
    h = pfh.honorarios(db.obtener_cliente_fiscal_por_id(c))
    assert [x["modelo"] for x in h["pendientes"]] == ["303"] and h["debe"] == 4500 and [x["modelo"] for x in h["pagados"]] == ["111"] and h["pagados"][0]["pago_id"]
    _como_cliente(cliente, c)
    pagina = _html(cliente, "/portal/honorarios")
    assert "45.00 €" in pagina and "Pagar con tarjeta" in pagina and "Honorarios 111" in pagina and "Recibo" in pagina and "Pendiente de pago · 45.00 €" in pagina


def test_el_recibo_es_un_pdf_solo_de_lo_pagado_y_solo_del_propio_cliente(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    uid, t, c, v = _con_honorarios(cliente, "hon2@ejemplo.com")
    _como_cliente(cliente, c)
    assert cliente.get(f"/portal/honorarios/{v}/recibo.pdf").status_code == 404, "sin pagar no hay recibo"
    db.registrar_pago_vencimiento(v, "cs_hon_2", 4500)
    r = cliente.get(f"/portal/honorarios/{v}/recibo.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF") and r.headers["Cache-Control"] == "private, no-store"
    assert cliente.get(f"/portal/honorarios/{v + 999}/recibo.pdf").status_code == 404


def test_otro_cliente_no_puede_pedir_el_recibo_ajeno(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    uid, t, c, v = _con_honorarios(cliente, "hon3@ejemplo.com")
    db.registrar_pago_vencimiento(v, "cs_hon_3", 4500)
    from tests.test_portal_personas_avisos import _despacho as despacho_ligero, _entrar
    t2, u2, c2 = despacho_ligero("Hon ajeno", cliente_email="ajeno@ejemplo.com", cliente_nombre="Ajeno SL")
    conn = db.get_connection(); conn.execute("UPDATE clientes_fiscales SET portal_honorarios = 1 WHERE id = ?", (c2,)); conn.commit(); conn.close()
    _entrar(cliente, c2, "ajeno@ejemplo.com")
    assert cliente.get(f"/portal/honorarios/{v}/recibo.pdf").status_code == 404


def test_sin_honorarios_activados_la_pagina_lo_explica_y_no_hay_recibos(cliente, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    uid, t, c, v = _con_honorarios(cliente, "hon5@ejemplo.com", visible=False)
    db.registrar_pago_vencimiento(v, "cs_hon_5", 4500)
    _como_cliente(cliente, c)
    assert "no tiene activados los honorarios" in _html(cliente, "/portal/honorarios") and cliente.get(f"/portal/honorarios/{v}/recibo.pdf").status_code == 404
    assert "Mis honorarios y recibos" not in _html(cliente, "/portal/impuestos")
