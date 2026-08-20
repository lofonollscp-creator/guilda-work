"""Tests de app/db.py -- CRUD nuevo de los bloques 5/6 de Stripe: cuenta
Connect por tenant, planes/extras de la plataforma, suscripción de cada
tenant, y el registro local de pagos de vencimientos. Sin llamar nunca a
la API real de Stripe (eso lo cubre tests/test_stripe_pagos.py) -- aquí
solo se comprueba la propia base de datos."""
from app import db


# --- Stripe Connect (bloque 5) ----------------------------------------------

def test_guardar_y_marcar_onboarding_stripe_connect():
    tenant_id = db.crear_tenant("Gestoria Connect")
    assert db.obtener_tenant(tenant_id)["stripe_account_id"] is None

    db.guardar_stripe_account_id(tenant_id, "acct_123")
    tenant = db.obtener_tenant(tenant_id)
    assert tenant["stripe_account_id"] == "acct_123"
    assert tenant["stripe_onboarding_completado"] == 0

    db.marcar_stripe_onboarding_completado(tenant_id, True)
    assert db.obtener_tenant(tenant_id)["stripe_onboarding_completado"] == 1


def test_registrar_pago_vencimiento_es_idempotente():
    tenant_id = db.crear_tenant("Gestoria Pagos")
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Pagos")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")

    assert db.pago_de_vencimiento(v_id) is None
    assert db.registrar_pago_vencimiento(v_id, "cs_1", 8000) is True
    pago = db.pago_de_vencimiento(v_id)
    assert pago["importe_centimos"] == 8000
    assert pago["stripe_checkout_session_id"] == "cs_1"

    # Un reintento de entrega del mismo webhook (misma session_id) no debe
    # duplicar la fila ni fallar -- la UNIQUE constraint lo garantiza.
    assert db.registrar_pago_vencimiento(v_id, "cs_1", 8000) is False


def test_tenant_id_de_vencimiento_fiscal():
    tenant_id = db.crear_tenant("Gestoria Resolver Tenant")
    cliente_id = db.crear_cliente_fiscal(tenant_id, "Cliente Resolver")
    v_id = db.crear_vencimiento_fiscal(tenant_id, cliente_id, "303", "2026-T1", "2026-04-20")

    assert db.tenant_id_de_vencimiento_fiscal(v_id) == tenant_id
    assert db.tenant_id_de_vencimiento_fiscal(999999) is None


# --- Planes y extras de plataforma (bloque 6) -------------------------------

def test_crud_planes_guilda():
    plan_id = db.crear_plan_guilda("Básico", "Plan de entrada", None, 5)
    plan = db.obtener_plan_guilda(plan_id)
    assert plan["nombre"] == "Básico"
    assert plan["precio_mensual_centimos"] is None
    assert plan["activo"] == 1

    db.editar_plan_guilda(plan_id, "Básico Plus", "Con más usuarios", 2900, 10)
    plan = db.obtener_plan_guilda(plan_id)
    assert plan["nombre"] == "Básico Plus"
    assert plan["precio_mensual_centimos"] == 2900
    assert plan["max_usuarios"] == 10

    db.guardar_stripe_price_id_plan(plan_id, "price_abc")
    assert db.obtener_plan_guilda(plan_id)["stripe_price_id"] == "price_abc"

    assert any(p["id"] == plan_id for p in db.listar_planes_guilda())


def test_crud_extras_guilda():
    extra_id = db.crear_extra_guilda("Usuario adicional", "Por usuario extra al mes", 500)
    extra = db.obtener_extra_guilda(extra_id)
    assert extra["nombre"] == "Usuario adicional"
    assert extra["precio_centimos"] == 500

    db.guardar_stripe_price_id_extra(extra_id, "price_extra_1")
    assert db.obtener_extra_guilda(extra_id)["stripe_price_id"] == "price_extra_1"

    assert any(e["id"] == extra_id for e in db.listar_extras_guilda())


def test_asignar_plan_y_activar_suscripcion_tenant():
    tenant_id = db.crear_tenant("Gestoria Suscripcion")
    plan_id = db.crear_plan_guilda("Pro", None, 4900, None)

    db.asignar_plan_tenant(tenant_id, plan_id)
    assert db.obtener_tenant(tenant_id)["plan_id"] == plan_id

    db.guardar_stripe_customer_id(tenant_id, "cus_1")
    db.guardar_stripe_subscription_id(tenant_id, "sub_1")
    tenant = db.obtener_tenant(tenant_id)
    assert tenant["stripe_customer_id"] == "cus_1"
    assert tenant["stripe_subscription_id"] == "sub_1"

    db.actualizar_suscripcion_estado(tenant_id, "activa")
    assert db.obtener_tenant(tenant_id)["suscripcion_estado"] == "activa"

    assert db.tenant_por_stripe_customer_id("cus_1")["id"] == tenant_id
    assert db.tenant_por_stripe_customer_id("cus_no_existe") is None


def test_asignar_plan_tenant_a_none_lo_desasigna():
    tenant_id = db.crear_tenant("Gestoria Desasignar Plan")
    plan_id = db.crear_plan_guilda("Pro", None, 4900, None)
    db.asignar_plan_tenant(tenant_id, plan_id)
    assert db.obtener_tenant(tenant_id)["plan_id"] == plan_id

    db.asignar_plan_tenant(tenant_id, None)
    assert db.obtener_tenant(tenant_id)["plan_id"] is None


def test_activar_extra_tenant_y_listar_activos():
    tenant_id = db.crear_tenant("Gestoria Extras")
    extra_id = db.crear_extra_guilda("Almacenamiento extra", None, 300)

    db.activar_extra_tenant(tenant_id, extra_id, cantidad=2, activo_hasta="2026-12-31")
    activos = db.listar_extras_activos_tenant(tenant_id)
    assert len(activos) == 1
    assert activos[0]["extra_id"] == extra_id
    assert activos[0]["cantidad"] == 2
    assert activos[0]["activo_hasta"] == "2026-12-31"

    otro_tenant_id = db.crear_tenant("Gestoria Extras Otra")
    assert db.listar_extras_activos_tenant(otro_tenant_id) == []
