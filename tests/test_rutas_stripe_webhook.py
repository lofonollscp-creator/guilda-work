"""Webhook entrante de Stripe (app/rutas_stripe_webhook.py) -- firma
verificada mockeando app.stripe_pagos.verificar_firma_webhook (su propia
lógica HMAC ya está cubierta en tests/test_stripe_pagos.py), aquí solo se
comprueba el enrutado por tipo de evento y la idempotencia."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db, rutas_stripe_webhook
from app.stripe_pagos import ErrorStripe


def _mock_evento(monkeypatch, evento: dict):
    monkeypatch.setattr(rutas_stripe_webhook.stripe_pagos, "verificar_firma_webhook", lambda payload, cabecera: evento)


def test_firma_invalida_da_400(cliente, monkeypatch):
    def _falla(payload, cabecera):
        raise ErrorStripe("firma inválida")
    monkeypatch.setattr(rutas_stripe_webhook.stripe_pagos, "verificar_firma_webhook", _falla)

    resp = cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    assert resp.status_code == 400


def test_checkout_completado_registra_el_pago_y_emite_evento(cliente, monkeypatch):
    usuario_id = iniciar_sesion_de_prueba(cliente, "webhook-pago@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Webhook Pago")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Webhook")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")

    llamadas_eventos = []
    monkeypatch.setattr(rutas_stripe_webhook.eventos, "emitir", lambda tipo, tid, datos: llamadas_eventos.append((tipo, tid, datos)))
    _mock_evento(monkeypatch, {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_1", "amount_total": 8000, "metadata": {"vencimiento_id": str(v_id)}}},
    })

    resp = cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    assert resp.status_code == 200
    assert db.pago_de_vencimiento(v_id) is not None
    assert llamadas_eventos == [("factura.cobrada", tenant_id, {"vencimiento_id": v_id, "importe_centimos": 8000})]


def test_checkout_completado_es_idempotente(cliente, monkeypatch):
    usuario_id = iniciar_sesion_de_prueba(cliente, "webhook-idempotente@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Webhook Idempotente")
    db.asignar_tenant(usuario_id, tenant_id)
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Webhook Idem")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")

    llamadas_eventos = []
    monkeypatch.setattr(rutas_stripe_webhook.eventos, "emitir", lambda tipo, tid, datos: llamadas_eventos.append(1))
    _mock_evento(monkeypatch, {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_repetido", "amount_total": 8000, "metadata": {"vencimiento_id": str(v_id)}}},
    })

    cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})  # reintento de Stripe
    assert len(llamadas_eventos) == 1


def test_checkout_completado_sin_metadata_no_hace_nada(cliente, monkeypatch):
    _mock_evento(monkeypatch, {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_sin_metadata", "amount_total": 8000, "metadata": {}}},
    })
    resp = cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    assert resp.status_code == 200


def test_invoice_paid_marca_suscripcion_activa(cliente, monkeypatch):
    usuario_id = iniciar_sesion_de_prueba(cliente, "webhook-invoice-paid@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Webhook Invoice Paid")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_stripe_customer_id(tenant_id, "cus_1")

    _mock_evento(monkeypatch, {"type": "invoice.paid", "data": {"object": {"customer": "cus_1"}}})
    resp = cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    assert resp.status_code == 200
    tenant = db.obtener_tenant(tenant_id)
    assert tenant["suscripcion_estado"] == "activa"


def test_invoice_payment_failed_marca_pago_fallido(cliente, monkeypatch):
    usuario_id = iniciar_sesion_de_prueba(cliente, "webhook-invoice-failed@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Webhook Invoice Failed")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_stripe_customer_id(tenant_id, "cus_2")

    _mock_evento(monkeypatch, {"type": "invoice.payment_failed", "data": {"object": {"customer": "cus_2"}}})
    cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    tenant = db.obtener_tenant(tenant_id)
    assert tenant["suscripcion_estado"] == "pago_fallido"


def test_subscription_deleted_marca_cancelada(cliente, monkeypatch):
    usuario_id = iniciar_sesion_de_prueba(cliente, "webhook-sub-deleted@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Webhook Sub Deleted")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_stripe_customer_id(tenant_id, "cus_3")

    _mock_evento(monkeypatch, {"type": "customer.subscription.deleted", "data": {"object": {"customer": "cus_3"}}})
    cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    tenant = db.obtener_tenant(tenant_id)
    assert tenant["suscripcion_estado"] == "cancelada"


def test_subscription_updated_usa_el_status_del_evento(cliente, monkeypatch):
    usuario_id = iniciar_sesion_de_prueba(cliente, "webhook-sub-updated@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Webhook Sub Updated")
    db.asignar_tenant(usuario_id, tenant_id)
    db.guardar_stripe_customer_id(tenant_id, "cus_4")

    _mock_evento(monkeypatch, {
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_4", "status": "past_due"}},
    })
    cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    tenant = db.obtener_tenant(tenant_id)
    assert tenant["suscripcion_estado"] == "past_due"


def test_customer_desconocido_no_rompe(cliente, monkeypatch):
    _mock_evento(monkeypatch, {"type": "invoice.paid", "data": {"object": {"customer": "cus_no_existe"}}})
    resp = cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    assert resp.status_code == 200


def test_tipo_de_evento_desconocido_responde_200_sin_hacer_nada(cliente, monkeypatch):
    _mock_evento(monkeypatch, {"type": "algo.que.no.escuchamos", "data": {"object": {}}})
    resp = cliente.post("/webhooks/stripe", data=b"{}", headers={"Stripe-Signature": "x"})
    assert resp.status_code == 200
