"""Facturación de la plataforma desde el backoffice: planes y extras
(catálogo + sincronización con Stripe), suscripción de cada tenant (Checkout
de Stripe), Stripe Connect, facturas y cobros puntuales. Toda la comunicación
con Stripe pasa por app.stripe_pagos; los errores de Stripe se convierten en
ValueError con un mensaje legible."""
from __future__ import annotations

from app import db as plataforma
from app import stripe_pagos

from . import auth


def _stripe(funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except stripe_pagos.ErrorStripe as e:
        raise ValueError(str(e)) from e


def configurado() -> bool:
    return stripe_pagos.configurado()


def euros(texto: str | None) -> int | None:
    """"11,50" / "11.5" -> 1150; vacío -> None (sin precio)."""
    texto = (texto or "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        valor = float(texto)
    except ValueError:
        raise ValueError("El importe no es un número válido.") from None
    if valor < 0 or valor > 1_000_000:
        raise ValueError("El importe debe estar entre 0 y 1.000.000 €.")
    return stripe_pagos.euros_a_centimos(texto)


# --- Catálogo ---------------------------------------------------------------

def crear_plan(nombre: str, descripcion: str, precio: str, max_usuarios: int | None) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del plan es obligatorio.")
    return plataforma.crear_plan_guilda(nombre, descripcion.strip() or None, euros(precio), max_usuarios)


def editar_plan(plan_id: int, nombre: str, descripcion: str, precio: str, max_usuarios: int | None) -> bool:
    """True si el precio cambió y el plan ya estaba sincronizado (hay que volver a sincronizar)."""
    plan = plataforma.obtener_plan_guilda(plan_id)
    if plan is None:
        raise ValueError("El plan no existe.")
    if not nombre.strip():
        raise ValueError("El nombre del plan es obligatorio.")
    centimos = euros(precio)
    plataforma.editar_plan_guilda(plan_id, nombre.strip(), descripcion.strip() or None, centimos, max_usuarios)
    if plan["stripe_price_id"] and centimos != plan["precio_mensual_centimos"]:
        plataforma.limpiar_stripe_price_id_plan(plan_id)
        return True
    return False


def sincronizar_plan(plan_id: int) -> str:
    plan = plataforma.obtener_plan_guilda(plan_id)
    if plan is None:
        raise ValueError("El plan no existe.")
    price_id = _stripe(stripe_pagos.sincronizar_plan, plan["nombre"], plan["precio_mensual_centimos"])
    if not price_id:
        raise ValueError(f"«{plan['nombre']}» no tiene precio fijado todavía: fíjalo antes de sincronizar.")
    plataforma.guardar_stripe_price_id_plan(plan_id, price_id)
    return plan["nombre"]


def crear_extra(nombre: str, descripcion: str, precio: str) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del extra es obligatorio.")
    return plataforma.crear_extra_guilda(nombre, descripcion.strip() or None, euros(precio))


def editar_extra(extra_id: int, nombre: str, descripcion: str, precio: str) -> bool:
    extra = plataforma.obtener_extra_guilda(extra_id)
    if extra is None:
        raise ValueError("El extra no existe.")
    if not nombre.strip():
        raise ValueError("El nombre del extra es obligatorio.")
    centimos = euros(precio)
    plataforma.editar_extra_guilda(extra_id, nombre.strip(), descripcion.strip() or None, centimos)
    if extra["stripe_price_id"] and centimos != extra["precio_centimos"]:
        plataforma.limpiar_stripe_price_id_extra(extra_id)
        return True
    return False


def sincronizar_extra(extra_id: int) -> str:
    extra = plataforma.obtener_extra_guilda(extra_id)
    if extra is None:
        raise ValueError("El extra no existe.")
    price_id = _stripe(stripe_pagos.sincronizar_extra, extra["nombre"], extra["precio_centimos"])
    if not price_id:
        raise ValueError(f"«{extra['nombre']}» no tiene precio fijado todavía: fíjalo antes de sincronizar.")
    plataforma.guardar_stripe_price_id_extra(extra_id, price_id)
    return extra["nombre"]


# --- Suscripción de un tenant -------------------------------------------------

def asignar_plan(tenant_id: int, plan_id: int | None) -> str | None:
    if plan_id is not None and plataforma.obtener_plan_guilda(plan_id) is None:
        raise ValueError("El plan no existe.")
    plataforma.asignar_plan_tenant(tenant_id, plan_id)
    plan = plataforma.obtener_plan_guilda(plan_id) if plan_id else None
    return plan["nombre"] if plan else None


def email_de_contacto(tenant_id: int) -> str:
    """Primer administrador del tenant, o el primer usuario: se propone como
    email de facturación."""
    filas = [u for u in plataforma.listar_usuarios() if u["tenant_id"] == tenant_id]
    filas.sort(key=lambda u: (u["rol"] != "admin", u["email"]))
    return filas[0]["email"] if filas else ""


def _cliente_stripe(tenant, email: str) -> str:
    cliente = tenant["stripe_customer_id"]
    if cliente:
        return cliente
    if not email.strip() or "@" not in email:
        raise ValueError("Indica un email de facturación válido.")
    cliente = _stripe(stripe_pagos.crear_cliente_plataforma, email.strip(), tenant["nombre"])
    plataforma.guardar_stripe_customer_id(tenant["id"], cliente)
    return cliente


def url_activar_suscripcion(tenant_id: int, email: str, url_retorno: str) -> str:
    """URL del Checkout de Stripe (modo suscripción) donde el tenant mete su
    tarjeta. El webhook de la app marca la suscripción como activa."""
    tenant = plataforma.obtener_tenant(tenant_id)
    plan = plataforma.obtener_plan_guilda(tenant["plan_id"]) if tenant["plan_id"] else None
    if plan is None:
        raise ValueError("Asigna un plan al tenant antes de activar la suscripción.")
    if not plan["stripe_price_id"]:
        raise ValueError("El plan todavía no está sincronizado con Stripe (hazlo en Planes y extras).")
    cliente = _cliente_stripe(tenant, email)
    return _stripe(stripe_pagos.crear_sesion_suscripcion, cliente, plan["stripe_price_id"], url_retorno, url_retorno)


def anadir_extra(tenant_id: int, extra_id: int, cantidad: int, activo_hasta: str | None) -> str:
    """Activa un extra en el tenant y, si ya tiene suscripción y el extra está
    sincronizado, lo añade a su próxima factura. Devuelve un aviso."""
    tenant = plataforma.obtener_tenant(tenant_id)
    extra = plataforma.obtener_extra_guilda(extra_id)
    if extra is None:
        raise ValueError("Elige un extra del catálogo.")
    cantidad = max(1, min(cantidad or 1, 999))
    plataforma.activar_extra_tenant(tenant_id, extra_id, cantidad, activo_hasta or None)
    if tenant["stripe_subscription_id"] and tenant["stripe_customer_id"] and extra["stripe_price_id"]:
        try:
            _stripe(stripe_pagos.anadir_extra_a_suscripcion, tenant["stripe_customer_id"], tenant["stripe_subscription_id"],
                    extra["stripe_price_id"], cantidad)
        except ValueError as e:
            return f"Extra «{extra['nombre']}» añadido, pero no se pudo facturar en Stripe: {e}"
        return f"Extra «{extra['nombre']}» añadido y facturado en Stripe."
    return f"Extra «{extra['nombre']}» añadido."


# --- Stripe Connect, facturas y cobros ---------------------------------------

def url_conectar_stripe(tenant_id: int, email: str, url_retorno: str) -> str:
    tenant = plataforma.obtener_tenant(tenant_id)
    if not email.strip() or "@" not in email:
        raise ValueError("Indica un email de contacto válido para Stripe.")
    cuenta, url = _stripe(stripe_pagos.crear_cuenta_connect, email.strip(), tenant["nombre"], url_retorno, url_retorno)
    plataforma.guardar_stripe_account_id(tenant_id, cuenta)
    return url


def confirmar_connect(tenant_id: int) -> bool:
    tenant = plataforma.obtener_tenant(tenant_id)
    if not tenant["stripe_account_id"]:
        return False
    lista = _stripe(stripe_pagos.cuenta_connect_lista, tenant["stripe_account_id"])
    if lista:
        plataforma.marcar_stripe_onboarding_completado(tenant_id, True)
    return bool(lista)


def facturas(tenant_id: int) -> tuple[list[dict], str | None]:
    """(facturas, error). Un fallo de Stripe no rompe la ficha."""
    from datetime import datetime, timezone

    tenant = plataforma.obtener_tenant(tenant_id)
    if not tenant["stripe_customer_id"]:
        return [], None
    try:
        filas = stripe_pagos.listar_facturas_cliente(tenant["stripe_customer_id"])
    except stripe_pagos.ErrorStripe as e:
        return [], str(e)
    return [
        {
            "fecha": datetime.fromtimestamp(f["created"], tz=timezone.utc).strftime("%d/%m/%Y"),
            "importe": f.get("amount_paid") or f.get("amount_due") or 0, "estado": f.get("status") or "",
            "url": f.get("hosted_invoice_url"),
        } for f in filas
    ], None


def crear_cobro(tenant_id: int, concepto: str, importe: str, email: str, url_retorno: str) -> dict:
    """Cobro puntual al tenant: crea la Checkout Session y lo registra para seguirlo."""
    tenant = plataforma.obtener_tenant(tenant_id)
    concepto = concepto.strip()
    if not concepto or len(concepto) > 200:
        raise ValueError("Indica el concepto del cobro (máx. 200 caracteres).")
    centimos = euros(importe)
    if not centimos or centimos <= 0:
        raise ValueError("Indica un importe mayor que cero.")
    cliente = _cliente_stripe(tenant, email)
    sesion = _stripe(stripe_pagos.crear_sesion_cobro, cliente, centimos, concepto, url_retorno, url_retorno,
                     metadata={"tenant_id": str(tenant_id), "origen": "backoffice"})
    from flask import g

    conn = auth.conectar()
    try:
        admin = g.get("admin")
        cur = conn.execute(
            "INSERT INTO cobros (tenant_id, concepto, importe_centimos, stripe_session_id, url, admin_usuario, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, concepto, centimos, sesion["id"], sesion["url"], admin["usuario"] if admin else None, auth._ahora()),
        )
        conn.commit()
        return {"id": cur.lastrowid, "url": sesion["url"], "importe_centimos": centimos}
    finally:
        conn.close()


def listar_cobros(tenant_id: int) -> list[dict]:
    conn = auth.conectar()
    try:
        return [dict(f) for f in conn.execute("SELECT * FROM cobros WHERE tenant_id = ? ORDER BY id DESC LIMIT 50", (tenant_id,)).fetchall()]
    finally:
        conn.close()


_ESTADOS_COBRO = {"paid": "pagado", "unpaid": "pendiente", "no_payment_required": "pagado"}


def refrescar_cobro(tenant_id: int, cobro_id: int) -> str:
    conn = auth.conectar()
    try:
        cobro = conn.execute("SELECT * FROM cobros WHERE id = ? AND tenant_id = ?", (cobro_id, tenant_id)).fetchone()
        if cobro is None:
            raise ValueError("El cobro no existe.")
        sesion = _stripe(stripe_pagos.estado_sesion, cobro["stripe_session_id"])
        estado = "caducado" if sesion["estado"] == "expired" else _ESTADOS_COBRO.get(sesion["pago"], "pendiente")
        conn.execute("UPDATE cobros SET estado = ?, actualizado_en = ? WHERE id = ?", (estado, auth._ahora(), cobro_id))
        conn.commit()
        return estado
    finally:
        conn.close()
