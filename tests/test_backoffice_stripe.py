"""Tests de las rutas de Stripe del backoffice renovado (app/rutas_backoffice.py,
bloques 5-6): Connect por tenant y facturación de plataforma (planes/extras/
suscripciones). La API real de Stripe siempre mockeada (rutas_backoffice.stripe_pagos)
-- eso ya lo cubre tests/test_stripe_pagos.py; aquí se comprueba el pegamento:
persistencia en BD, admin_required, y que un fallo de Stripe nunca rompe la ruta."""
from tests.conftest import iniciar_sesion_de_prueba

from app import db


def _admin(cliente, email="admin-stripe@ejemplo.com"):
    usuario_id = iniciar_sesion_de_prueba(cliente, email, "contrasena123")
    db.hacer_admin(db.obtener_usuario(usuario_id)["email"])
    return usuario_id


# --- Stripe Connect (bloque 5) ----------------------------------------------

def test_conectar_stripe_sin_admin_da_403(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-stripe@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Sin Admin")
    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/stripe-connect/conectar", data={"email": "x@x.com"})
    assert resp.status_code == 403


def test_conectar_stripe_ok_guarda_account_id_y_redirige_a_onboarding(cliente, monkeypatch):
    from app import rutas_backoffice
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Conectar")

    monkeypatch.setattr(
        rutas_backoffice.stripe_pagos, "crear_cuenta_connect",
        lambda email, nombre, url_retorno, url_refrescar: ("acct_nuevo", "https://connect.stripe.com/setup/acct_nuevo"),
    )
    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/stripe-connect/conectar", data={"email": "cliente@ejemplo.com"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://connect.stripe.com/setup/acct_nuevo"
    assert db.obtener_tenant(tenant_id)["stripe_account_id"] == "acct_nuevo"


def test_conectar_stripe_roto_muestra_error_sin_500(cliente, monkeypatch):
    from app import rutas_backoffice
    from app.stripe_pagos import ErrorStripe
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Conectar Roto")

    def _falla(*a, **k):
        raise ErrorStripe("Stripe caído")
    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "crear_cuenta_connect", _falla)

    resp = cliente.post(
        f"/backoffice/tenants/{tenant_id}/stripe-connect/conectar", data={"email": "cliente@ejemplo.com"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    # tojson escapa acentos a \uXXXX en el <script> -- se busca un tramo
    # sin acentos del propio mensaje de flash en vez del texto del mock.
    assert "No se ha podido conectar con Stripe" in resp.get_data(as_text=True)
    assert db.obtener_tenant(tenant_id)["stripe_account_id"] is None


def test_retorno_stripe_marca_onboarding_completado_si_charges_enabled(cliente, monkeypatch):
    from app import rutas_backoffice
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Retorno")
    db.guardar_stripe_account_id(tenant_id, "acct_1")

    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "cuenta_connect_lista", lambda account_id: True)
    resp = cliente.get(f"/backoffice/tenants/{tenant_id}/stripe-connect/retorno")
    assert resp.status_code == 302
    assert db.obtener_tenant(tenant_id)["stripe_onboarding_completado"] == 1


def test_retorno_stripe_sin_completar_no_marca_nada(cliente, monkeypatch):
    from app import rutas_backoffice
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Retorno Incompleto")
    db.guardar_stripe_account_id(tenant_id, "acct_2")

    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "cuenta_connect_lista", lambda account_id: False)
    cliente.get(f"/backoffice/tenants/{tenant_id}/stripe-connect/retorno")
    assert db.obtener_tenant(tenant_id)["stripe_onboarding_completado"] == 0


# --- Planes y extras (bloque 6) ---------------------------------------------

def test_planes_sin_admin_da_403(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-planes@ejemplo.com", "contrasena123")
    resp = cliente.get("/backoffice/planes")
    assert resp.status_code == 403


def test_crear_plan_ok(cliente):
    _admin(cliente)
    resp = cliente.post("/backoffice/planes", data={
        "nombre": "Básico", "descripcion": "Plan de entrada", "precio_mensual_eur": "29.00", "max_usuarios": "5",
    }, follow_redirects=True)
    assert resp.status_code == 200
    planes = db.listar_planes_guilda()
    assert any(p["nombre"] == "Básico" and p["precio_mensual_centimos"] == 2900 for p in planes)


def test_crear_plan_confirma_con_toast(cliente):
    """El backoffice no tenía conectado el sistema de toast de la app
    principal (toasts.js) -- antes de este arreglo, crear un plan
    redirigía en silencio sin confirmar nada. Confirma que el mensaje
    de éxito llega al HTML (vía mostrarToast(), ver backoffice_base.html)."""
    _admin(cliente)
    resp = cliente.post(
        "/backoffice/planes", data={"nombre": "Basico Toast", "precio_mensual_eur": "10.00"}, follow_redirects=True,
    )
    assert "mostrarToast" in resp.get_data(as_text=True)
    assert "creado" in resp.get_data(as_text=True)


def test_crear_plan_sin_nombre_no_crea_nada_y_avisa(cliente):
    _admin(cliente)
    antes = len(db.listar_planes_guilda())
    resp = cliente.post("/backoffice/planes", data={"nombre": "  "}, follow_redirects=True)
    assert len(db.listar_planes_guilda()) == antes
    assert "obligatorio" in resp.get_data(as_text=True)


def test_crear_plan_sin_precio_deja_precio_nulo(cliente):
    _admin(cliente)
    cliente.post("/backoffice/planes", data={"nombre": "Sin precio todavía"})
    plan = next(p for p in db.listar_planes_guilda() if p["nombre"] == "Sin precio todavía")
    assert plan["precio_mensual_centimos"] is None


def test_sincronizar_plan_stripe_guarda_price_id(cliente, monkeypatch):
    from app import rutas_backoffice
    _admin(cliente)
    plan_id = db.crear_plan_guilda("Pro", None, 4900, None)

    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "sincronizar_plan", lambda nombre, precio: "price_pro_1")
    cliente.post(f"/backoffice/planes/{plan_id}/sincronizar-stripe")
    assert db.obtener_plan_guilda(plan_id)["stripe_price_id"] == "price_pro_1"


def test_sincronizar_plan_stripe_roto_no_rompe_la_ruta(cliente, monkeypatch):
    from app import rutas_backoffice
    from app.stripe_pagos import ErrorStripe
    _admin(cliente)
    plan_id = db.crear_plan_guilda("Pro Roto", None, 4900, None)

    def _falla(*a, **k):
        raise ErrorStripe("caído")
    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "sincronizar_plan", _falla)

    resp = cliente.post(f"/backoffice/planes/{plan_id}/sincronizar-stripe")
    assert resp.status_code == 302
    assert db.obtener_plan_guilda(plan_id)["stripe_price_id"] is None


def test_editar_plan_actualiza_precio(cliente):
    _admin(cliente)
    plan_id = db.crear_plan_guilda("Básico", None, None, None)
    cliente.post(f"/backoffice/planes/{plan_id}/editar", data={
        "nombre": "Básico", "descripcion": "Ahora con precio", "precio_mensual_eur": "19.00", "max_usuarios": "3",
    })
    plan = db.obtener_plan_guilda(plan_id)
    assert plan["precio_mensual_centimos"] == 1900
    assert plan["descripcion"] == "Ahora con precio"
    assert plan["max_usuarios"] == 3


def test_editar_plan_de_id_inexistente_da_404(cliente):
    _admin(cliente)
    resp = cliente.post("/backoffice/planes/999999/editar", data={"nombre": "X"})
    assert resp.status_code == 404


def test_editar_plan_sincronizado_al_cambiar_precio_limpia_stripe_price_id(cliente):
    """Los Price de Stripe son inmutables -- si el plan ya estaba
    sincronizado y se le cambia el precio, el price_id guardado deja
    de corresponder al importe mostrado y hay que limpiarlo para que
    "Sincronizar con Stripe" pueda crear uno nuevo con el importe
    correcto."""
    _admin(cliente)
    plan_id = db.crear_plan_guilda("Pro", None, 4900, None)
    db.guardar_stripe_price_id_plan(plan_id, "price_pro_viejo")

    cliente.post(f"/backoffice/planes/{plan_id}/editar", data={"nombre": "Pro", "precio_mensual_eur": "59.00"})
    assert db.obtener_plan_guilda(plan_id)["stripe_price_id"] is None


def test_editar_plan_sincronizado_sin_cambiar_precio_conserva_stripe_price_id(cliente):
    _admin(cliente)
    plan_id = db.crear_plan_guilda("Pro", None, 4900, None)
    db.guardar_stripe_price_id_plan(plan_id, "price_pro_1")

    cliente.post(f"/backoffice/planes/{plan_id}/editar", data={"nombre": "Pro renombrado", "precio_mensual_eur": "49.00"})
    assert db.obtener_plan_guilda(plan_id)["stripe_price_id"] == "price_pro_1"
    assert db.obtener_plan_guilda(plan_id)["nombre"] == "Pro renombrado"


def test_editar_extra_actualiza_precio(cliente):
    _admin(cliente)
    extra_id = db.crear_extra_guilda("Usuario adicional", None, None)
    cliente.post(f"/backoffice/extras/{extra_id}/editar", data={
        "nombre": "Usuario adicional", "descripcion": "Ahora con precio", "precio_eur": "6.50",
    })
    extra = db.obtener_extra_guilda(extra_id)
    assert extra["precio_centimos"] == 650
    assert extra["descripcion"] == "Ahora con precio"


def test_editar_extra_de_id_inexistente_da_404(cliente):
    _admin(cliente)
    resp = cliente.post("/backoffice/extras/999999/editar", data={"nombre": "X"})
    assert resp.status_code == 404


def test_editar_extra_sincronizado_al_cambiar_precio_limpia_stripe_price_id(cliente):
    _admin(cliente)
    extra_id = db.crear_extra_guilda("Usuario adicional", None, 500)
    db.guardar_stripe_price_id_extra(extra_id, "price_extra_viejo")

    cliente.post(f"/backoffice/extras/{extra_id}/editar", data={"nombre": "Usuario adicional", "precio_eur": "7.00"})
    assert db.obtener_extra_guilda(extra_id)["stripe_price_id"] is None


def test_crear_extra_ok(cliente):
    _admin(cliente)
    cliente.post("/backoffice/extras", data={"nombre": "Usuario adicional", "precio_eur": "5.00"})
    extra = next(e for e in db.listar_extras_guilda() if e["nombre"] == "Usuario adicional")
    assert extra["precio_centimos"] == 500


def test_asignar_plan_a_tenant(cliente):
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Asignar Plan")
    plan_id = db.crear_plan_guilda("Pro", None, 4900, None)

    cliente.post(f"/backoffice/tenants/{tenant_id}/plan", data={"plan_id": str(plan_id)})
    assert db.obtener_tenant(tenant_id)["plan_id"] == plan_id


def test_activar_suscripcion_ok_redirige_a_checkout(cliente, monkeypatch):
    """activar_suscripcion NUNCA crea la Subscription directamente por API
    (Stripe la rechaza sin un método de pago ya guardado, ver hallazgo de
    la verificación en vivo) -- redirige a una Checkout Session en modo
    suscripción; es el webhook quien guarda stripe_subscription_id y
    activa el estado tras completarse el pago (test aparte, ver
    test_rutas_stripe_webhook.py)."""
    from app import rutas_backoffice
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Activar Suscripcion")
    plan_id = db.crear_plan_guilda("Pro", None, 4900, None)
    db.guardar_stripe_price_id_plan(plan_id, "price_pro_2")
    db.asignar_plan_tenant(tenant_id, plan_id)

    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "crear_cliente_plataforma", lambda email, nombre: "cus_nuevo")
    monkeypatch.setattr(
        rutas_backoffice.stripe_pagos, "crear_sesion_suscripcion",
        lambda cus, price, url_exito, url_cancelar: "https://checkout.stripe.com/pay/cs_sub_1",
    )

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/suscripcion/activar", data={"email": "facturacion@ejemplo.com"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://checkout.stripe.com/pay/cs_sub_1"
    tenant = db.obtener_tenant(tenant_id)
    assert tenant["stripe_customer_id"] == "cus_nuevo"
    # Todavía sin suscripción real -- eso lo hace el webhook al completarse
    # el pago en la página de Stripe, no esta ruta.
    assert tenant["stripe_subscription_id"] is None
    assert tenant["suscripcion_estado"] is None


def test_activar_suscripcion_roto_muestra_error_sin_500(cliente, monkeypatch):
    from app import rutas_backoffice
    from app.stripe_pagos import ErrorStripe
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Activar Suscripcion Rota")
    plan_id = db.crear_plan_guilda("Pro", None, 4900, None)
    db.guardar_stripe_price_id_plan(plan_id, "price_pro_3")
    db.asignar_plan_tenant(tenant_id, plan_id)

    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "crear_cliente_plataforma", lambda email, nombre: "cus_roto")

    def _falla(*a, **k):
        raise ErrorStripe("no attached payment source")
    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "crear_sesion_suscripcion", _falla)

    resp = cliente.post(
        f"/backoffice/tenants/{tenant_id}/suscripcion/activar", data={"email": "facturacion@ejemplo.com"}, follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "no attached payment source" in resp.get_data(as_text=True)


def test_activar_suscripcion_sin_plan_con_price_no_hace_nada(cliente):
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Sin Plan")
    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/suscripcion/activar", data={"email": "x@x.com"})
    assert resp.status_code == 302
    assert db.obtener_tenant(tenant_id)["suscripcion_estado"] is None


def test_anadir_extra_tenant_sin_suscripcion_activa_solo_en_local(cliente):
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Extra Local")
    extra_id = db.crear_extra_guilda("Almacenamiento extra", None, 300)

    cliente.post(f"/backoffice/tenants/{tenant_id}/extras", data={"extra_id": str(extra_id), "cantidad": "2"})
    activos = db.listar_extras_activos_tenant(tenant_id)
    assert len(activos) == 1
    assert activos[0]["cantidad"] == 2


def test_anadir_extra_tenant_con_suscripcion_sincroniza_stripe(cliente, monkeypatch):
    from app import rutas_backoffice
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Extra Sincronizado")
    db.guardar_stripe_customer_id(tenant_id, "cus_1")
    db.guardar_stripe_subscription_id(tenant_id, "sub_1")
    extra_id = db.crear_extra_guilda("Usuario adicional", None, 500)
    db.guardar_stripe_price_id_extra(extra_id, "price_extra_1")

    llamadas = []
    monkeypatch.setattr(
        rutas_backoffice.stripe_pagos, "anadir_extra_a_suscripcion",
        lambda cus_id, sub_id, price_id, cantidad: llamadas.append((cus_id, sub_id, price_id, cantidad)),
    )
    cliente.post(f"/backoffice/tenants/{tenant_id}/extras", data={"extra_id": str(extra_id), "cantidad": "3"})
    assert llamadas == [("cus_1", "sub_1", "price_extra_1", 3)]


def test_anadir_extra_tenant_con_stripe_roto_aclara_que_el_extra_si_se_anadio(cliente, monkeypatch):
    """Si Stripe falla, el extra YA se activó en local (db.activar_extra_tenant
    corre antes del try/except) -- el aviso debe dejar claro que la parte
    local funcionó y solo falló la facturación, no un fallo total."""
    from app import rutas_backoffice
    from app.stripe_pagos import ErrorStripe
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Extra Stripe Roto")
    db.guardar_stripe_customer_id(tenant_id, "cus_2")
    db.guardar_stripe_subscription_id(tenant_id, "sub_2")
    extra_id = db.crear_extra_guilda("Usuario adicional", None, 500)
    db.guardar_stripe_price_id_extra(extra_id, "price_extra_2")

    def _falla(*a, **k):
        raise ErrorStripe("Stripe no disponible")
    monkeypatch.setattr(rutas_backoffice.stripe_pagos, "anadir_extra_a_suscripcion", _falla)

    resp = cliente.post(
        f"/backoffice/tenants/{tenant_id}/extras", data={"extra_id": str(extra_id), "cantidad": "1"}, follow_redirects=True,
    )
    assert len(db.listar_extras_activos_tenant(tenant_id)) == 1
    assert "no se ha podido facturar" in resp.get_data(as_text=True)


def test_anadir_extra_tenant_con_suscripcion_pero_sin_customer_id_no_llama_a_stripe(cliente, monkeypatch):
    """Guarda de regresión: sin stripe_customer_id no se puede formar
    el invoiceitem (lo exige la API de Stripe) -- confirmar que la
    ruta no intenta llamar a Stripe sin él en vez de fallar a medias."""
    from app import rutas_backoffice
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Extra Sin Customer")
    db.guardar_stripe_subscription_id(tenant_id, "sub_1")
    extra_id = db.crear_extra_guilda("Usuario adicional", None, 500)
    db.guardar_stripe_price_id_extra(extra_id, "price_extra_1")

    llamadas = []
    monkeypatch.setattr(
        rutas_backoffice.stripe_pagos, "anadir_extra_a_suscripcion",
        lambda *a: llamadas.append(a),
    )
    cliente.post(f"/backoffice/tenants/{tenant_id}/extras", data={"extra_id": str(extra_id), "cantidad": "1"})
    assert llamadas == []


def test_desactivar_extra_tenant_requiere_admin(cliente):
    iniciar_sesion_de_prueba(cliente, "no-admin-desactivar-extra@ejemplo.com", "contrasena123")
    tenant_id = db.crear_tenant("Gestoria Desactivar Extra Sin Admin")
    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/extras/999999/desactivar")
    assert resp.status_code == 403


def test_desactivar_extra_tenant_lo_quita_de_los_activos(cliente):
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Desactivar Extra")
    extra_id = db.crear_extra_guilda("Almacenamiento extra", None, 300)
    tenant_extra_id = db.activar_extra_tenant(tenant_id, extra_id, cantidad=1)
    assert len(db.listar_extras_activos_tenant(tenant_id)) == 1

    resp = cliente.post(f"/backoffice/tenants/{tenant_id}/extras/{tenant_extra_id}/desactivar")
    assert resp.status_code == 302
    assert db.listar_extras_activos_tenant(tenant_id) == []


def test_desactivar_extra_tenant_de_tenant_inexistente_da_404(cliente):
    _admin(cliente)
    resp = cliente.post("/backoffice/tenants/999999/extras/1/desactivar")
    assert resp.status_code == 404


def test_ficha_tenant_formatea_la_fecha_de_las_facturas_stripe(cliente, monkeypatch):
    from app import rutas_backoffice
    _admin(cliente)
    tenant_id = db.crear_tenant("Gestoria Fecha Factura")
    db.guardar_stripe_customer_id(tenant_id, "cus_fecha")

    # created de Stripe es un timestamp Unix (segundos), no una fecha
    # legible -- confirma que la ficha lo formatea antes de mostrarlo.
    monkeypatch.setattr(
        rutas_backoffice.stripe_pagos, "listar_facturas_cliente",
        lambda cus_id: [{"created": 1735689600, "amount_paid": 2900, "status": "paid"}],
    )
    resp = cliente.get(f"/backoffice/tenants/{tenant_id}")
    html = resp.get_data(as_text=True)
    assert "2025-01-01" in html
    assert "1735689600" not in html
