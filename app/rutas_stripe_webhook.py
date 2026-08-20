"""Webhook entrante de Stripe (bloques 5 y 6) -- Guilda Work escucha
eventos que llegan de la cuenta de PLATAFORMA (los cobros de Connect
del bloque 5 se hacen como "cargo de destino" desde esa misma cuenta,
ver app/stripe_pagos.py, así que un único endpoint basta para ambos
bloques).

- `checkout.session.completed` -> pago de un vencimiento fiscal
  (bloque 5, Stripe Connect).
- `invoice.paid`/`invoice.payment_failed`/`customer.subscription.updated`/
  `customer.subscription.deleted` -> estado de la suscripción de
  plataforma de un tenant (bloque 6).

Sin `@login_required`: por definición, un webhook nunca trae la sesión
de nadie -- la autenticidad se verifica con la firma HMAC de Stripe
(`app/stripe_pagos.py:verificar_firma_webhook`), no con cookies."""
from flask import Blueprint, Response, request

from . import db, eventos, stripe_pagos

stripe_webhook_bp = Blueprint("stripe_webhook", __name__, url_prefix="/webhooks")


@stripe_webhook_bp.route("/stripe", methods=["POST"])
def recibir():
    try:
        evento = stripe_pagos.verificar_firma_webhook(request.get_data(), request.headers.get("Stripe-Signature", ""))
    except stripe_pagos.ErrorStripe:
        return Response(status=400)

    tipo = evento.get("type", "")
    objeto = evento.get("data", {}).get("object", {})

    if tipo == "checkout.session.completed":
        _procesar_pago_vencimiento(objeto)
    elif tipo in ("invoice.paid", "invoice.payment_failed", "customer.subscription.updated", "customer.subscription.deleted"):
        _procesar_suscripcion(tipo, objeto)

    return Response(status=200)


def _procesar_pago_vencimiento(sesion: dict) -> None:
    """checkout.session.completed de un cobro de Connect -- solo si trae
    metadata.vencimiento_id (lo pone app/rutas_fiscal.py al crear la
    sesión de Checkout, ver stripe_pagos.crear_sesion_pago)."""
    vencimiento_id = (sesion.get("metadata") or {}).get("vencimiento_id")
    session_id = sesion.get("id")
    importe = sesion.get("amount_total")
    if not vencimiento_id or not session_id or importe is None:
        return
    registrado = db.registrar_pago_vencimiento(int(vencimiento_id), session_id, importe)
    if not registrado:
        return  # ya procesado antes (Stripe puede reintentar la misma entrega)
    tenant_id = db.tenant_id_de_vencimiento_fiscal(int(vencimiento_id))
    try:
        eventos.emitir("factura.cobrada", tenant_id, {"vencimiento_id": int(vencimiento_id), "importe_centimos": importe})
    except Exception:
        pass


def _procesar_suscripcion(tipo: str, objeto: dict) -> None:
    """Eventos de la suscripción de plataforma -- resuelve el tenant por
    stripe_customer_id, que sí viaja en los eventos de invoice/
    subscription (a diferencia de checkout.session, que no tiene
    concepto de tenant de Guilda Work sin la metadata explícita)."""
    customer_id = objeto.get("customer")
    if not customer_id:
        return
    tenant = db.tenant_por_stripe_customer_id(customer_id)
    if tenant is None:
        return
    if tipo == "invoice.paid":
        db.actualizar_suscripcion_estado(tenant["id"], "activa")
    elif tipo == "invoice.payment_failed":
        db.actualizar_suscripcion_estado(tenant["id"], "pago_fallido")
    elif tipo == "customer.subscription.deleted":
        db.actualizar_suscripcion_estado(tenant["id"], "cancelada")
    elif tipo == "customer.subscription.updated":
        estado = objeto.get("status")
        if estado:
            db.actualizar_suscripcion_estado(tenant["id"], estado)
