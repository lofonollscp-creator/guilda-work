"""Presupuestos y propuestas aceptables desde el portal (A6/Q7): líneas e importes, envío con huella, aceptación con evidencia, caducidad, rechazo, pago con Stripe (simulado) y webhook idempotente."""
import hashlib
import hmac
import json
import time
from datetime import date, timedelta

import pytest

from app import db, portal_personas, portal_propuestas as pp, stripe_pagos
from tests.test_portal_personas_avisos import _despacho, _entrar, _ficha, _html, correo  # noqa: F401 -- fixtures

LINEAS = "Contabilidad mensual; 12; 80; 21\nAlta de la sociedad; 300"


def _enviada(t, u, c, cobro="no", valida=""):
    pid = pp.crear(t, c, "Servicios 2027", "Todo el año.", LINEAS, valida, cobro, u)
    pp.enviar(t, pid)
    return pid


def test_las_lineas_se_leen_y_el_total_lleva_iva():
    l = pp.leer_lineas(LINEAS)
    assert l == [{"concepto": "Contabilidad mensual", "cantidad": 12, "precio_centimos": 8000, "iva": 21}, {"concepto": "Alta de la sociedad", "cantidad": 1, "precio_centimos": 30000, "iva": 21}]
    assert pp.total_de(l) == round((12 * 8000 + 30000) * 1.21) and pp.desglose(l)["base"] == 126000
    assert pp.leer_lineas("Formación; 2; 49,90; 10")[0]["precio_centimos"] == 4990
    for malo in ("", "solo concepto", "x; 0; 10", "x; 1,5; 10", "x; 1; -5", "x; 1; 10; 40", "x; 1; abc"):
        with pytest.raises(pp.ErrorPropuesta):
            pp.leer_lineas(malo)
    with pytest.raises(pp.ErrorPropuesta):
        pp.leer_lineas("\n".join(f"c{i}; 10" for i in range(31)))


def test_crear_valida_titulo_cliente_fecha_y_cobro():
    t, u, c = _despacho("Prop crear")
    otro_t, _u, otro_c = _despacho("Prop otro")
    for args in (("", "d", LINEAS, "", "no"), ("T", "d", LINEAS, (date.today() - timedelta(days=1)).isoformat(), "no"), ("T", "d", LINEAS, "ayer", "no"), ("T", "d", LINEAS, "", "100"), ("T", "d", LINEAS, "", "xx"), ("T", "d", "x; 0,10", "", "total")):
        with pytest.raises(pp.ErrorPropuesta):
            pp.crear(t, c, *args, u)
    with pytest.raises(pp.ErrorPropuesta):
        pp.crear(t, otro_c, "T", "d", LINEAS, "", "no", u)                          # un cliente de otro despacho
    pid = pp.crear(t, c, "Anticipo", "", LINEAS, "", "30", u)
    assert pp.obtener_del_despacho(t, pid)["cobro_centimos"] == round(pp.total_de(pp.leer_lineas(LINEAS)) * 0.3)
    assert pp.obtener_del_despacho(otro_t, pid) is None


def test_el_cliente_solo_ve_lo_enviado_y_el_envio_fija_la_huella():
    t, u, c = _despacho("Prop envio")
    pid = pp.crear(t, c, "Borrador", "", LINEAS, "", "no", u)
    ficha = _ficha(c)
    assert pp.listar(ficha) == [] and pp.obtener(ficha, pid) is None and pp.hay(ficha) is False
    p = pp.enviar(t, pid)
    assert p["estado"] == "enviada" and len(p["huella"]) == 64 and pp.hay(ficha) and [x["id"] for x in pp.pendientes(ficha)] == [pid]
    with pytest.raises(pp.ErrorPropuesta):
        pp.enviar(t, pid)                                                            # ya no es un borrador


def test_aceptar_registra_nombre_correo_y_no_se_puede_repetir():
    t, u, c = _despacho("Prop aceptar")
    pid = _enviada(t, u, c)
    ficha = _ficha(c)
    with pytest.raises(pp.ErrorPropuesta):
        pp.aceptar(ficha, pid, "titular@ejemplo.com", "  ")
    pp.aceptar(ficha, pid, "titular@ejemplo.com", "Ana Titular")
    p = pp.obtener(ficha, pid)
    assert p["estado"] == "aceptada" and p["nombre_firmante"] == "Ana Titular" and p["respondida_por"] == "titular@ejemplo.com" and p["respondida_en"]
    with pytest.raises(pp.ErrorPropuesta):
        pp.aceptar(ficha, pid, "titular@ejemplo.com", "Ana Titular")
    with pytest.raises(pp.ErrorPropuesta):
        pp.rechazar(ficha, pid, "titular@ejemplo.com", "tarde")


def test_rechazar_guarda_el_motivo_y_una_propuesta_caducada_o_retirada_no_se_acepta(monkeypatch):
    t, u, c = _despacho("Prop rechazo")
    ficha = _ficha(c)
    p1 = _enviada(t, u, c)
    pp.rechazar(ficha, p1, "titular@ejemplo.com", "Es cara")
    assert pp.obtener(ficha, p1)["estado"] == "rechazada" and pp.obtener(ficha, p1)["motivo"] == "Es cara"
    p2 = _enviada(t, u, c, valida=(date.today() + timedelta(days=1)).isoformat())
    conn = db.get_connection(); conn.execute("UPDATE portal_propuestas SET valida_hasta = ? WHERE id = ?", ((date.today() - timedelta(days=1)).isoformat(), p2)); conn.commit(); conn.close()
    assert pp.obtener(ficha, p2)["efectivo"] == "caducada" and pp.pendientes(ficha) == []
    with pytest.raises(pp.ErrorPropuesta):
        pp.aceptar(ficha, p2, "titular@ejemplo.com", "Ana Titular")
    p3 = _enviada(t, u, c)
    assert pp.retirar(t, p3) is True and pp.obtener(ficha, p3) is None
    with pytest.raises(pp.ErrorPropuesta):
        pp.aceptar(ficha, p3, "titular@ejemplo.com", "Ana Titular")


def test_el_pago_se_abre_solo_tras_aceptar_con_el_importe_del_despacho_y_se_registra_una_vez(monkeypatch):
    t, u, c = _despacho("Prop pago")
    ficha = _ficha(c)
    pid = _enviada(t, u, c, cobro="total")
    llamadas = []
    monkeypatch.setattr(stripe_pagos, "configurado", lambda: True)
    monkeypatch.setattr(stripe_pagos, "crear_sesion_pago", lambda cuenta, importe, concepto, ok, no, moneda="eur", metadata=None: llamadas.append((cuenta, importe, metadata)) or "https://stripe.test/pago")
    db.guardar_stripe_account_id(t, "acct_prueba")
    with pytest.raises(pp.ErrorPropuesta):
        pp.crear_pago(ficha, pid, "ok", "no")                                        # sin aceptar no hay pago
    pp.aceptar(ficha, pid, "titular@ejemplo.com", "Ana Titular")
    p = pp.obtener(ficha, pid)
    assert pp.puede_pagar(p, t) and pp.crear_pago(ficha, pid, "ok", "no") == "https://stripe.test/pago"
    assert llamadas == [("acct_prueba", p["cobro_centimos"], {"propuesta_id": pid, "tenant_id": t})]
    assert pp.registrar_pago(t, pid, "cs_1", p["cobro_centimos"]) is True and pp.registrar_pago(t, pid, "cs_1", p["cobro_centimos"]) is False
    assert pp.registrar_pago(t + 99, pid, "cs_2", 1) is False and pp.obtener(ficha, pid)["pagado_en"]
    with pytest.raises(pp.ErrorPropuesta):
        pp.crear_pago(ficha, pid, "ok", "no")                                        # ya pagada
    sin = _enviada(t, u, c, cobro="no")
    pp.aceptar(ficha, sin, "titular@ejemplo.com", "Ana Titular")
    with pytest.raises(pp.ErrorPropuesta):
        pp.crear_pago(ficha, sin, "ok", "no")                                        # no había nada que cobrar


def test_el_webhook_de_stripe_anota_el_pago_de_la_propuesta_una_sola_vez(cliente, monkeypatch):
    t, u, c = _despacho("Prop webhook")
    ficha = _ficha(c)
    pid = _enviada(t, u, c, cobro="total")
    pp.aceptar(ficha, pid, "titular@ejemplo.com", "Ana Titular")
    monkeypatch.setattr(stripe_pagos, "STRIPE_WEBHOOK_SECRET", "whsec_falso")
    importe = pp.obtener(ficha, pid)["cobro_centimos"]
    cuerpo = json.dumps({"type": "checkout.session.completed", "data": {"object": {"id": "cs_web", "mode": "payment", "amount_total": importe, "payment_status": "paid", "metadata": {"propuesta_id": str(pid), "tenant_id": str(t)}}}}).encode()
    ts = int(time.time())
    firma = f"t={ts},v1=" + hmac.new(b"whsec_falso", f"{ts}.{cuerpo.decode()}".encode(), hashlib.sha256).hexdigest()
    for _i in range(2):
        assert cliente.post("/webhooks/stripe", data=cuerpo, headers={"Stripe-Signature": firma, "Content-Type": "application/json"}).status_code == 200
    p = pp.obtener(ficha, pid)
    assert p["pagado_en"] and p["pagado_centimos"] == importe and p["stripe_session_id"] == "cs_web"


def test_el_portal_muestra_acepta_y_descarga_el_pdf(cliente, correo):
    t, u, c = _despacho("Prop web")
    pid = _enviada(t, u, c, valida=(date.today() + timedelta(days=30)).isoformat())
    _entrar(cliente, c, "titular@ejemplo.com")
    assert "Servicios 2027" in _html(cliente, "/portal/propuestas") and "Servicios 2027" in _html(cliente, "/portal/")        # también en «Para hacer»
    pagina = _html(cliente, f"/portal/propuestas/{pid}")
    assert "Contabilidad mensual" in pagina and "prop-nombre" in pagina and "1524.60 €" in pagina
    r = cliente.post(f"/portal/propuestas/{pid}/aceptar", data={"nombre": "Ana Titular"})            # sin marcar la casilla
    assert pp.obtener(_ficha(c), pid)["estado"] == "enviada"
    cliente.post(f"/portal/propuestas/{pid}/aceptar", data={"nombre": "Ana Titular", "conforme": "1"})
    assert pp.obtener(_ficha(c), pid)["estado"] == "aceptada" and "Aceptada por Ana Titular" in _html(cliente, f"/portal/propuestas/{pid}")
    pdf = cliente.get(f"/portal/propuestas/{pid}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and pdf.headers["Cache-Control"] == "private, no-store"
    assert cliente.get(f"/portal/propuestas/{pid + 99}").status_code == 404


def test_un_contacto_sin_acceso_completo_no_puede_responder_y_otro_cliente_no_la_ve(cliente, correo):
    t, u, c = _despacho("Prop perfiles")
    pid = _enviada(t, u, c)
    portal_personas.anadir(_ficha(c), "admin@ejemplo.com", "Admin", "administracion", por=u)
    _entrar(cliente, c, "admin@ejemplo.com")
    assert "prop-nombre" not in _html(cliente, f"/portal/propuestas/{pid}")
    cliente.post(f"/portal/propuestas/{pid}/aceptar", data={"nombre": "Admin Admin", "conforme": "1"})
    assert pp.obtener(_ficha(c), pid)["estado"] == "enviada"
    t2, u2, c2 = _despacho("Prop ajeno", cliente_email="otro@ejemplo.com")
    cliente.get("/portal/salir")
    _entrar(cliente, c2, "otro@ejemplo.com")
    assert cliente.get(f"/portal/propuestas/{pid}").status_code == 404


def test_la_bandeja_del_equipo_recoge_las_respuestas_hasta_que_se_ven(cliente):
    t, u, c = _despacho("Prop equipo", cliente_email="eq@ejemplo.com")
    from app import portal_bandeja
    pid = _enviada(t, u, c)
    pp.aceptar(_ficha(c), pid, "eq@ejemplo.com", "Equipo Cliente")
    with cliente.application.test_request_context():
        assert any(i["tipo"] == "propuesta" and "aceptada" in i["titulo"] for i in portal_bandeja.listar(t, u))
        pp.marcar_vista(t, pid)
        assert not any(i["tipo"] == "propuesta" for i in portal_bandeja.listar(t, u))
