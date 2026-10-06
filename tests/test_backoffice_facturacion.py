"""Backoffice independiente: alta de tenants con aprovisionamiento y
facturación con Stripe (catálogo, suscripción, extras, Connect, facturas y
cobros). Stripe y los servicios conectados se sustituyen por dobles."""
import pytest

from app import calcom, db, espocrm, facturascripts, nextcloud, ntfy, stripe_pagos
from backoffice import aprovisionamiento, auth, facturacion
from backoffice.main import create_app
from tests.test_backoffice_app import CLAVE, entrar, post

STRIPE_FALSO = {}


@pytest.fixture
def bo(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "backoffice.db")
    monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "bo_secret.key")
    auth.crear_admin("jorge", CLAVE, "Jorge")
    cliente = create_app(testing=True).test_client()
    entrar(cliente)
    return cliente


@pytest.fixture
def stripe(monkeypatch):
    """Stripe falso: registra las llamadas y devuelve ids predecibles."""
    llamadas = []
    monkeypatch.setattr(stripe_pagos, "STRIPE_SECRET_KEY", "sk_test_falsa")

    def peticion(endpoint, *, metodo="GET", cuerpo=None):
        llamadas.append((metodo, endpoint, cuerpo))
        if endpoint == "/products":
            return {"id": "prod_1"}
        if endpoint == "/prices":
            return {"id": f"price_{len(llamadas)}"}
        if endpoint == "/customers":
            return {"id": "cus_1"}
        if endpoint == "/checkout/sessions" and metodo == "POST":
            modo = cuerpo["mode"]
            return {"id": f"cs_{modo}_{len(llamadas)}", "url": f"https://checkout.stripe.com/c/{modo}/{len(llamadas)}"}
        if endpoint.startswith("/checkout/sessions/"):
            return {"status": "complete", "payment_status": "paid"}
        if endpoint.startswith("/invoices"):
            return {"data": [{"created": 1790000000, "amount_paid": 11600, "status": "paid", "hosted_invoice_url": "https://invoice.stripe.com/i/1"}]}
        if endpoint == "/accounts" or endpoint.startswith("/accounts"):
            return {"id": "acct_1", "charges_enabled": True}
        if endpoint == "/account_links":
            return {"url": "https://connect.stripe.com/setup/1"}
        return {}

    monkeypatch.setattr(stripe_pagos, "_peticion", peticion)
    return llamadas


def _plan(nombre="Pro", precio=11600):
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO planes_guilda (nombre, precio_mensual_centimos, activo, creado_en) VALUES (?, ?, 1, ?)", (nombre, precio, db.now_iso()))
        conn.commit()
        return conn.execute("SELECT id FROM planes_guilda WHERE nombre = ?", (nombre,)).fetchone()[0]
    finally:
        conn.close()


# --- Alta de tenant con aprovisionamiento --------------------------------------

def test_crear_tenant_aprovisiona_y_muestra_el_resultado_de_cada_servicio(bo, monkeypatch):
    plan = _plan()
    monkeypatch.setattr(espocrm, "crear_equipo", lambda n: "equipo-1")
    monkeypatch.setattr(nextcloud, "crear_espacio_tenant", lambda n: None)
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_USER", "admin")
    monkeypatch.setattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", "x")
    monkeypatch.setattr(facturascripts, "aprovisionar_tenant", lambda tid, n: {"url": "https://fs.ejemplo", "admin_user": "admin", "admin_pass": "SECRETO-FS"})
    def calcom_roto(tid, n):
        raise calcom.ErrorCalcom("contenedor caído")
    monkeypatch.setattr(calcom, "aprovisionar_tenant", calcom_roto)
    def ntfy_sin_config(tid, n):
        raise ntfy.ErrorNtfy("ntfy no está configurado")
    monkeypatch.setattr(ntfy, "aprovisionar_tenant", ntfy_sin_config)
    for modulo in ("paperless", "baserow", "listmonk", "umami"):
        monkeypatch.setattr(__import__(f"app.{modulo}", fromlist=["x"]), "aprovisionar_tenant", lambda *a, **k: None)
    r = post(bo, "/tenants", nombre="Gestoría Nueva", plan_id=str(plan), dominio_correo="")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Tenant creado: Gestoría Nueva" in html and "SECRETO-FS" in html and "contenedor caído" in html
    assert "CREADO" in html and "ERROR" in html and "NO CONFIGURADO" in html
    t = db.listar_tenants()[0]
    assert t["id"] and db.obtener_tenant(t["id"])["plan_id"] == plan
    assert {"observabilidad", "portainer"} <= db.herramientas_ocultas_de_tenant(t["id"])
    assert "SECRETO-FS" not in bo.get(f"/tenants/{t['id']}").get_data(as_text=True)   # no vuelve a salir
    assert all("SECRETO-FS" not in (a["detalle"] or "") for a in auth.listar_auditoria())


def test_crear_tenant_duplicado_o_vacio_no_aprovisiona(bo, monkeypatch):
    llamadas = []
    monkeypatch.setattr(aprovisionamiento, "aprovisionar", lambda *a, **k: llamadas.append(a) or [])
    post(bo, "/tenants", nombre="Uno")
    post(bo, "/tenants", nombre="Uno")
    post(bo, "/tenants", nombre="   ")
    assert len(llamadas) == 1 and len(db.listar_tenants()) == 1


def test_un_servicio_que_revienta_con_cualquier_excepcion_no_impide_el_alta(bo, monkeypatch):
    def explota(n):
        raise RuntimeError("fallo raro")
    monkeypatch.setattr(espocrm, "crear_equipo", explota)
    for modulo in ("calcom", "facturascripts", "ntfy"):
        monkeypatch.setattr(__import__(f"app.{modulo}", fromlist=["x"]), "aprovisionar_tenant", explota)
    r = post(bo, "/tenants", nombre="Resiliente")
    assert r.status_code == 200 and "fallo raro" in r.get_data(as_text=True) and db.listar_tenants()[0]["nombre"] == "Resiliente"


# --- Catálogo -------------------------------------------------------------------

def test_catalogo_de_planes_y_extras_con_sincronizacion(bo, stripe):
    post(bo, "/planes", nombre="Básico", descripcion="Para empezar", precio="29,50", max_usuarios="5")
    plan = db.listar_planes_guilda()[0]
    assert plan["precio_mensual_centimos"] == 2950 and plan["max_usuarios"] == 5
    post(bo, f"/planes/{plan['id']}/sincronizar")
    assert db.obtener_plan_guilda(plan["id"])["stripe_price_id"]
    assert ("POST", "/prices", {"product": "prod_1", "unit_amount": 2950, "currency": "eur", "recurring": {"interval": "month"}}) in stripe
    post(bo, f"/planes/{plan['id']}/editar", nombre="Básico", descripcion="", precio="39", max_usuarios="")
    assert db.obtener_plan_guilda(plan["id"])["stripe_price_id"] is None      # cambió el precio: hay que resincronizar
    post(bo, "/extras", nombre="Fichaje extra", descripcion="", precio="5")
    extra = db.listar_extras_guilda()[0]
    post(bo, f"/extras/{extra['id']}/sincronizar")
    assert db.obtener_extra_guilda(extra["id"])["stripe_price_id"]
    post(bo, "/planes", nombre="", precio="1")
    post(bo, "/planes", nombre="Raro", precio="abc")
    assert len(db.listar_planes_guilda()) == 1


def test_sincronizar_sin_precio_o_sin_stripe_da_un_mensaje(bo, monkeypatch):
    monkeypatch.setattr(stripe_pagos, "STRIPE_SECRET_KEY", None)
    post(bo, "/planes", nombre="Sin precio", precio="")
    plan_id = db.listar_planes_guilda()[0]["id"]
    post(bo, f"/planes/{plan_id}/sincronizar")
    assert "falta STRIPE_SECRET_KEY" in bo.get("/planes").get_data(as_text=True)


def test_importes_en_euros(bo):
    assert facturacion.euros("11,50") == 1150 and facturacion.euros("2.675") == 268 and facturacion.euros("") is None
    for malo in ("abc", "-3", "2000000"):
        with pytest.raises(ValueError):
            facturacion.euros(malo)


# --- Suscripción de un tenant -----------------------------------------------------

def _tenant_con_plan(sincronizado=True):
    tid = db.crear_tenant("Cliente SL")
    plan = _plan()
    if sincronizado:
        db.guardar_stripe_price_id_plan(plan, "price_plan")
    db.asignar_plan_tenant(tid, plan)
    uid = db.crear_usuario_vinculado_a_kratos("dueno@cliente.com", "k-dueno")
    db.asignar_tenant(uid, tid)
    return tid


def test_activar_suscripcion_crea_cliente_y_redirige_al_checkout_de_stripe(bo, stripe):
    tid = _tenant_con_plan()
    r = post(bo, f"/tenants/{tid}/suscripcion/activar", email="facturas@cliente.com")
    assert r.status_code == 303 and r.headers["Location"].startswith("https://checkout.stripe.com/c/subscription/")
    assert db.obtener_tenant(tid)["stripe_customer_id"] == "cus_1"
    sesion = next(c for c in stripe if c[1] == "/checkout/sessions")
    assert sesion[2]["customer"] == "cus_1" and sesion[2]["line_items"][0]["price"] == "price_plan"
    r = post(bo, f"/tenants/{tid}/suscripcion/activar", email="otra@cliente.com")   # reutiliza el cliente de Stripe
    assert sum(1 for c in stripe if c[1] == "/customers") == 1


def test_activar_suscripcion_sin_plan_o_sin_sincronizar_avisa(bo, stripe):
    tid = db.crear_tenant("Sin plan")
    post(bo, f"/tenants/{tid}/suscripcion/activar", email="a@b.com")
    assert "Asigna un plan" in bo.get(f"/tenants/{tid}?seccion=suscripcion").get_data(as_text=True)
    tid2 = _tenant_con_plan(sincronizado=False)
    post(bo, f"/tenants/{tid2}/suscripcion/activar", email="a@b.com")
    assert "no está sincronizado" in bo.get(f"/tenants/{tid2}?seccion=suscripcion").get_data(as_text=True)
    assert not any(c[1] == "/checkout/sessions" for c in stripe)


def test_asignar_plan_extras_y_factura_en_stripe(bo, stripe):
    tid = db.crear_tenant("Extras SL")
    plan = _plan("Premium", 20000)
    post(bo, f"/tenants/{tid}/plan", plan_id=str(plan))
    assert db.obtener_tenant(tid)["plan_id"] == plan
    post(bo, f"/tenants/{tid}/plan", plan_id="")
    assert db.obtener_tenant(tid)["plan_id"] is None
    post(bo, f"/tenants/{tid}/plan", plan_id="9999")
    extra = db.crear_extra_guilda("Usuario extra", None, 500)
    db.guardar_stripe_price_id_extra(extra, "price_extra")
    post(bo, f"/tenants/{tid}/extras", extra_id=str(extra), cantidad="3")
    assert len(db.listar_extras_activos_tenant(tid)) == 1 and not any(c[1] == "/invoiceitems" for c in stripe)
    db.guardar_stripe_customer_id(tid, "cus_9"); db.guardar_stripe_subscription_id(tid, "sub_9")
    post(bo, f"/tenants/{tid}/extras", extra_id=str(extra), cantidad="2")
    item = next(c for c in stripe if c[1] == "/invoiceitems")
    assert item[2] == {"customer": "cus_9", "subscription": "sub_9", "price": "price_extra", "quantity": 2}
    activo = db.listar_extras_activos_tenant(tid)[0]["id"]
    post(bo, f"/tenants/{tid}/extras/{activo}/quitar")
    assert len(db.listar_extras_activos_tenant(tid)) == 1


def test_cobro_puntual_se_registra_se_comparte_y_se_actualiza(bo, stripe):
    tid = _tenant_con_plan()
    post(bo, f"/tenants/{tid}/cobros", concepto="Formación inicial", importe="250,00", email="facturas@cliente.com")
    cobro = facturacion.listar_cobros(tid)[0]
    assert cobro["importe_centimos"] == 25000 and cobro["estado"] == "pendiente" and cobro["url"].startswith("https://checkout.stripe.com/c/payment/")
    sesion = next(c for c in stripe if c[1] == "/checkout/sessions" and c[2]["mode"] == "payment")
    assert sesion[2]["line_items"][0]["price_data"]["unit_amount"] == 25000 and sesion[2]["metadata"]["tenant_id"] == str(tid)
    html = bo.get(f"/tenants/{tid}?seccion=suscripcion").get_data(as_text=True)
    assert "Formación inicial" in html and cobro["url"] in html and "250 €" in html
    post(bo, f"/tenants/{tid}/cobros/{cobro['id']}/actualizar")
    assert facturacion.listar_cobros(tid)[0]["estado"] == "pagado"
    for malo in ({"concepto": "", "importe": "5"}, {"concepto": "x", "importe": "0"}, {"concepto": "x", "importe": "-4"}, {"concepto": "x", "importe": "abc"}):
        post(bo, f"/tenants/{tid}/cobros", email="a@b.com", **malo)
    assert len(facturacion.listar_cobros(tid)) == 1
    assert post(bo, f"/tenants/{tid}/cobros/999/actualizar").status_code == 302


def test_stripe_connect_y_facturas_y_fallos_de_stripe(bo, stripe, monkeypatch):
    tid = _tenant_con_plan()
    r = post(bo, f"/tenants/{tid}/stripe/conectar", email="conta@cliente.com")
    assert r.status_code == 303 and "connect.stripe.com" in r.headers["Location"]
    assert db.obtener_tenant(tid)["stripe_account_id"] == "acct_1"
    bo.get(f"/tenants/{tid}/stripe/retorno")
    assert db.obtener_tenant(tid)["stripe_onboarding_completado"] == 1
    db.guardar_stripe_customer_id(tid, "cus_f")
    html = bo.get(f"/tenants/{tid}?seccion=suscripcion").get_data(as_text=True)
    assert "116 €" in html and "invoice.stripe.com" in html and "CUENTA CONECTADA" in html
    def cae(*a, **k):
        raise stripe_pagos.ErrorStripe("Stripe caído")
    monkeypatch.setattr(stripe_pagos, "listar_facturas_cliente", cae)
    r = bo.get(f"/tenants/{tid}?seccion=suscripcion")
    assert r.status_code == 200 and "Stripe caído" in r.get_data(as_text=True)         # la ficha no se rompe
    monkeypatch.setattr(stripe_pagos, "crear_sesion_suscripcion", cae)
    post(bo, f"/tenants/{tid}/suscripcion/activar", email="a@b.com")
    assert "Stripe caído" in bo.get(f"/tenants/{tid}?seccion=suscripcion").get_data(as_text=True)


def test_las_acciones_de_facturacion_requieren_sesion_y_csrf(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "b.db"); monkeypatch.setattr(auth, "SECRET_PATH", tmp_path / "k.key")
    anonimo = create_app(testing=True).test_client()
    tid = db.crear_tenant("X")
    for ruta in (f"/tenants/{tid}/cobros", f"/tenants/{tid}/plan", f"/tenants/{tid}/suscripcion/activar", "/planes", "/extras"):
        assert anonimo.post(ruta, data={}).status_code == 400          # sin token CSRF
    assert anonimo.get("/planes").status_code == 302 and anonimo.get(f"/tenants/{tid}/stripe/retorno").status_code == 302
    auth.crear_admin("a", CLAVE)
    c = create_app(testing=True).test_client(); entrar(c, "a")
    assert c.post(f"/tenants/{tid}/cobros", data={"concepto": "x", "importe": "1"}).status_code == 400
    assert "form-action 'self' https://checkout.stripe.com" in c.get("/planes").headers["Content-Security-Policy"]
