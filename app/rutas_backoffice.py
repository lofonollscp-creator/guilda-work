"""Backoffice (Fase 7c): gestión de tenants y usuarios desde la web, para no
depender solo de `cli.py`. Todas las rutas requieren `usuarios.rol = 'admin'`
(ver `db.hacer_admin` / `python cli.py hacer-admin`) — es una sección de solo
un puñado de administradores, no pensada para volumen ni paginación.
"""
import json
import secrets
from datetime import datetime, timezone

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from . import baserow, calcom, chatwoot, db, espocrm, eventos, facturascripts, herramientas, kratos, listmonk, metabase, nextcloud, notificaciones_email, ntfy, openproject, paperless, push, stalwart, stripe_pagos, umami, uptime_kuma
from .auth import admin_required, login_required

backoffice_bp = Blueprint("backoffice", __name__, url_prefix="/backoffice")


def _auditar(accion: str, detalle: str | None = None) -> None:
    """Best-effort, igual que el resto de efectos secundarios "de segunda
    fila" de la app (eventos, notificaciones) -- un fallo al registrar la
    auditoría nunca debe impedir la acción real de backoffice."""
    try:
        db.registrar_auditoria(g.usuario_id, accion, detalle)
    except Exception:
        pass


def _contexto_herramientas(tenants) -> dict:
    """Contexto compartido por las 4 rutas que renderizan backoffice.html
    directamente (en vez de redirigir a panel()) — la tabla de
    visibilidad de herramientas por tenant necesita el catálogo completo
    y qué está oculto para cada uno."""
    return {
        "catalogo_herramientas": herramientas.HERRAMIENTAS,
        "herramientas_ocultas_por_tenant": db.herramientas_ocultas_de_tenants([t["id"] for t in tenants]),
    }


def _contexto_webhooks(tenants) -> dict:
    """Igual que _contexto_herramientas: contexto compartido por las
    mismas 4 rutas. Incluye las últimas entregas de cada webhook para
    que el admin pueda ver por qué uno está fallando sin salir del
    backoffice (ver app/eventos.py). Batched en 3 consultas totales (en
    vez de una por tenant + una por webhook) vía db.listar_todos_los_webhooks()
    y db.entregas_de_webhooks()."""
    todos_por_tenant = db.listar_todos_los_webhooks()
    todos_los_webhooks = [w for filas in todos_por_tenant.values() for w in filas]
    entregas_por_webhook = db.entregas_de_webhooks([w["id"] for w in todos_los_webhooks], limite=5)

    webhooks_por_tenant = {}
    for t in [None, *[t["id"] for t in tenants]]:
        webhooks_por_tenant[t] = [
            {
                **dict(w),
                "eventos": json.loads(w["eventos"]),  # ya parseado: sin filtro Jinja para esto
                "entregas": [dict(e) for e in entregas_por_webhook.get(w["id"], [])],
            }
            for w in todos_por_tenant.get(t, [])
        ]
    return {"webhooks_por_tenant": webhooks_por_tenant, "eventos_disponibles": eventos.EVENTOS}


def _contexto_auditoria() -> dict:
    return {"auditoria": db.listar_auditoria_backoffice(limite=200)}


@backoffice_bp.route("/")
@login_required
@admin_required
def panel():
    tenants = db.listar_tenants_con_conteo()
    ocultas_por_tenant = db.herramientas_ocultas_de_tenants([t["id"] for t in tenants])

    q = request.args.get("q", "").strip()
    modulo_filtro = request.args.get("modulo", "").strip()
    orden = request.args.get("orden", "nombre")

    tenants = [dict(t, ultima_actividad=db.ultima_actividad_tenant(t["id"])) for t in tenants]
    if q:
        q_lower = q.lower()
        tenants = [t for t in tenants if q_lower in t["nombre"].lower()]
    if modulo_filtro:
        tenants = [t for t in tenants if modulo_filtro not in ocultas_por_tenant.get(t["id"], set())]
    if orden == "usuarios":
        tenants.sort(key=lambda t: t["n_usuarios"], reverse=True)
    elif orden == "actividad":
        tenants.sort(key=lambda t: t["ultima_actividad"] or "", reverse=True)
    else:
        tenants.sort(key=lambda t: t["nombre"].lower())

    return render_template(
        "backoffice.html",
        tenants=tenants,
        q=q,
        modulo_filtro=modulo_filtro,
        orden=orden,
        facturascripts_creado=None,
        calcom_creado=None,
        **_contexto_herramientas(tenants),
    )


@backoffice_bp.route("/usuarios")
@login_required
@admin_required
def usuarios_vista():
    return render_template(
        "backoffice_usuarios.html",
        usuarios=db.listar_usuarios(),
        tenants=db.listar_tenants(),
        resultados_alta=None,
    )


@backoffice_bp.route("/leads")
@login_required
@admin_required
def leads_vista():
    return render_template("backoffice_leads.html", leads=db.listar_leads_contacto())


@backoffice_bp.route("/solicitudes-portal")
@login_required
@admin_required
def solicitudes_portal_vista():
    return render_template(
        "backoffice_solicitudes_portal.html",
        solicitudes_portal=db.listar_solicitudes_acceso_portal(),
        clientes_fiscales_todos=db.listar_todos_los_clientes_fiscales(),
        tenants=db.listar_tenants(),
    )


@backoffice_bp.route("/webhooks")
@login_required
@admin_required
def webhooks_vista():
    tenants = db.listar_tenants()
    return render_template("backoffice_webhooks.html", tenants=tenants, **_contexto_webhooks(tenants))


@backoffice_bp.route("/auditoria")
@login_required
@admin_required
def auditoria_vista():
    return render_template("backoffice_auditoria.html", **_contexto_auditoria())


@backoffice_bp.route("/resumen")
@login_required
@admin_required
def resumen_vista():
    return render_template("backoffice_resumen.html", resumen=db.resumen_plataforma())


@backoffice_bp.route("/monitorizacion")
@login_required
@admin_required
def monitorizacion_vista():
    try:
        monitores = uptime_kuma.listar_monitores()
        error = None
    except uptime_kuma.ErrorUptimeKuma as e:
        monitores, error = [], str(e)
    return render_template("backoffice_monitorizacion.html", monitores=monitores, error=error)


@backoffice_bp.route("/ingresos")
@login_required
@admin_required
def ingresos_vista():
    return render_template(
        "backoffice_ingresos.html",
        tenants=db.listar_suscripciones_tenants(),
        mrr_centimos=db.resumen_plataforma()["mrr_centimos"],
    )


@backoffice_bp.route("/backups")
@login_required
@admin_required
def backups_vista():
    return render_template("backoffice_backups.html", backups=db.listar_backups())


@backoffice_bp.route("/backups", methods=["POST"])
@login_required
@admin_required
def hacer_backup():
    db.hacer_backup_si_hace_falta()
    _auditar("hacer_backup", None)
    return redirect(url_for("backoffice.backups_vista"))


@backoffice_bp.route("/catalogo-herramientas")
@login_required
@admin_required
def catalogo_herramientas_vista():
    tenants = db.listar_tenants()
    ocultas_por_tenant = db.herramientas_ocultas_de_tenants([t["id"] for t in tenants])
    catalogo_ids = [h["id"] for h in herramientas.HERRAMIENTAS]
    return render_template(
        "backoffice_catalogo_herramientas.html",
        catalogo_herramientas=herramientas.HERRAMIENTAS,
        total_tenants=len(tenants),
        adopcion=db.adopcion_herramientas(ocultas_por_tenant, catalogo_ids),
    )


def _diagnostico_integraciones() -> list[dict]:
    """Estado de configuración (variables de entorno puestas o no) de
    cada integración externa a nivel de PLATAFORMA -- no confundir con
    las API keys por tenant (FacturaScripts/Documenso/Cal.diy, ver
    ficha de tenant), esto es "¿está la variable de entorno del
    servidor rellenada?", lo mismo que hasta ahora había que comprobar
    a mano por SSH mirando /etc/guilda-work.env o .env."""
    return [
        {"nombre": "Email del portal de cliente (SMTP)", "configurado": notificaciones_email.configurado()},
        {"nombre": "Notificaciones push (FCM)", "configurado": push.configurado()},
        {"nombre": "Stripe (plataforma)", "configurado": stripe_pagos.configurado()},
        {"nombre": "Baserow", "configurado": bool(baserow.BASEROW_ADMIN_PASSWORD)},
        {"nombre": "Cal.diy", "configurado": bool(calcom.CALCOM_ADMIN_PASSWORD)},
        {"nombre": "Chatwoot", "configurado": bool(chatwoot.CHATWOOT_AGENT_API_TOKEN)},
        {"nombre": "EspoCRM", "configurado": bool(espocrm.ESPOCRM_API_KEY)},
        {"nombre": "FacturaScripts (aprovisionamiento)", "configurado": bool(facturascripts.FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD)},
        {"nombre": "Listmonk", "configurado": bool(listmonk.LISTMONK_ADMIN_USER and listmonk.LISTMONK_ADMIN_PASSWORD)},
        {"nombre": "Metabase", "configurado": bool(metabase.METABASE_API_KEY)},
        {"nombre": "Nextcloud", "configurado": bool(nextcloud.NEXTCLOUD_ADMIN_USER and nextcloud.NEXTCLOUD_ADMIN_PASSWORD)},
        {"nombre": "ntfy", "configurado": bool(ntfy.NTFY_ADMIN_USER and ntfy.NTFY_ADMIN_PASSWORD)},
        {"nombre": "OpenProject", "configurado": bool(openproject.OPENPROJECT_API_TOKEN)},
        {"nombre": "Paperless-ngx", "configurado": bool(paperless.PAPERLESS_ADMIN_USER and paperless.PAPERLESS_ADMIN_PASSWORD)},
        {"nombre": "Stalwart (correo por tenant)", "configurado": bool(stalwart.STALWART_ADMIN_USER and stalwart.STALWART_ADMIN_PASSWORD)},
        {"nombre": "Umami", "configurado": bool(umami.UMAMI_ADMIN_PASSWORD)},
        {"nombre": "Uptime Kuma", "configurado": bool(uptime_kuma.UPTIME_KUMA_API_KEY)},
    ]


@backoffice_bp.route("/diagnostico")
@login_required
@admin_required
def diagnostico_vista():
    return render_template("backoffice_diagnostico.html", integraciones=_diagnostico_integraciones())


@backoffice_bp.route("/tenants/<int:tenant_id>")
@login_required
@admin_required
def ficha_tenant(tenant_id: int):
    """Ficha de un tenant -- pantalla nueva (backoffice renovado): antes
    todo (usuarios, herramientas, configuración) vivía disperso en la
    tabla plana de panel(); aquí queda agrupado por tenant. Ver
    app/db.py:ultima_actividad_tenant/estadisticas_equipo_por_usuario."""
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    usuarios_ids = set(db.usuarios_de_tenant(tenant_id))
    usuarios_del_tenant = [u for u in db.listar_usuarios() if u["id"] in usuarios_ids]

    # Ingresos (bloque 6) -- historial de facturas de Stripe, best-effort
    # como el resto de integraciones opcionales de esta pantalla: un
    # fallo (Stripe no configurado, tenant sin cliente todavía) no debe
    # romper la ficha.
    facturas_stripe = []
    if tenant["stripe_customer_id"]:
        try:
            facturas_stripe = [
                {**f, "creada_en": datetime.fromtimestamp(f["created"], tz=timezone.utc).strftime("%Y-%m-%d")}
                for f in stripe_pagos.listar_facturas_cliente(tenant["stripe_customer_id"])
            ]
        except stripe_pagos.ErrorStripe as e:
            flash(f"No se han podido cargar las facturas de Stripe: {e}", "error")

    return render_template(
        "backoffice_ficha_tenant.html",
        tenant=tenant,
        usuarios=usuarios_del_tenant,
        ultima_actividad=db.ultima_actividad_tenant(tenant_id),
        estadisticas_equipo=db.estadisticas_equipo_por_usuario(tenant_id),
        catalogo_herramientas=herramientas.HERRAMIENTAS,
        herramientas_ocultas=db.herramientas_ocultas_de_tenant(tenant_id),
        planes=db.listar_planes_guilda(solo_activos=True),
        extras=db.listar_extras_guilda(),
        extras_activos=db.listar_extras_activos_tenant(tenant_id),
        facturas_stripe=facturas_stripe,
        stripe_configurado=stripe_pagos.configurado(),
    )


@backoffice_bp.route("/tenants/<int:tenant_id>/activo", methods=["POST"])
@login_required
@admin_required
def alternar_activo_tenant(tenant_id: int):
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    nuevo_valor = not tenant["activo"]
    db.alternar_activo_tenant(tenant_id, nuevo_valor)
    _auditar("suspender_tenant" if not nuevo_valor else "reactivar_tenant", tenant["nombre"])
    flash(f"{tenant['nombre']} {'reactivado' if nuevo_valor else 'suspendido'}.", "exito")
    return redirect(request.referrer or url_for("backoffice.ficha_tenant", tenant_id=tenant_id))


# --- Bloque 5: Stripe Connect (cada tenant cobra a sus propios clientes) ---

@backoffice_bp.route("/tenants/<int:tenant_id>/stripe-connect/conectar", methods=["POST"])
@login_required
@admin_required
def conectar_stripe(tenant_id: int):
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    email = request.form.get("email", "").strip()
    if not email:
        flash("Introduce un email para conectar la cuenta de Stripe.", "error")
        return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))
    try:
        url_retorno = url_for("backoffice.retorno_stripe", tenant_id=tenant_id, _external=True)
        account_id, url_onboarding = stripe_pagos.crear_cuenta_connect(email, tenant["nombre"], url_retorno, url_retorno)
        db.guardar_stripe_account_id(tenant_id, account_id)
        _auditar("conectar_stripe", tenant["nombre"])
        return redirect(url_onboarding)
    except stripe_pagos.ErrorStripe as e:
        flash(f"No se ha podido conectar con Stripe: {e}", "error")
        return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))


@backoffice_bp.route("/tenants/<int:tenant_id>/stripe-connect/retorno")
@login_required
@admin_required
def retorno_stripe(tenant_id: int):
    """Kratos de vuelta del onboarding de Stripe Connect (URL de retorno
    Y de refresco a la vez, ver conectar_stripe -- Stripe no distingue
    entre "completado" y "necesita retomar" en esta URL, así que se
    confirma consultando la cuenta directamente)."""
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    if tenant["stripe_account_id"]:
        try:
            if stripe_pagos.cuenta_connect_lista(tenant["stripe_account_id"]):
                db.marcar_stripe_onboarding_completado(tenant_id, True)
                flash("Cuenta de Stripe Connect conectada y lista para cobrar.", "exito")
            else:
                flash("La cuenta de Stripe todavía no ha terminado el onboarding -- vuelve a intentarlo cuando lo completes.", "error")
        except stripe_pagos.ErrorStripe as e:
            flash(f"No se ha podido confirmar el estado de la cuenta de Stripe: {e}", "error")
    return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))


# --- Bloque 6: facturación de plataforma -----------------------------------

@backoffice_bp.route("/planes")
@login_required
@admin_required
def planes():
    return render_template(
        "backoffice_planes.html",
        planes=db.listar_planes_guilda(),
        extras=db.listar_extras_guilda(),
        stripe_configurado=stripe_pagos.configurado(),
    )


@backoffice_bp.route("/planes", methods=["POST"])
@login_required
@admin_required
def crear_plan():
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre del plan es obligatorio.", "error")
        return redirect(url_for("backoffice.planes"))
    precio = request.form.get("precio_mensual_eur", "").strip()
    precio_centimos = round(float(precio) * 100) if precio else None
    max_usuarios = request.form.get("max_usuarios", type=int)
    db.crear_plan_guilda(nombre, request.form.get("descripcion", "").strip() or None, precio_centimos, max_usuarios)
    _auditar("crear_plan_guilda", nombre)
    flash(f"Plan '{nombre}' creado.", "exito")
    return redirect(url_for("backoffice.planes"))


@backoffice_bp.route("/planes/<int:plan_id>/editar", methods=["POST"])
@login_required
@admin_required
def editar_plan(plan_id: int):
    plan = db.obtener_plan_guilda(plan_id)
    if plan is None:
        abort(404)
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre del plan es obligatorio.", "error")
        return redirect(url_for("backoffice.planes"))
    descripcion = request.form.get("descripcion", "").strip() or None
    precio = request.form.get("precio_mensual_eur", "").strip()
    precio_centimos = round(float(precio) * 100) if precio else None
    max_usuarios = request.form.get("max_usuarios", type=int)
    db.editar_plan_guilda(plan_id, nombre, descripcion, precio_centimos, max_usuarios)
    if plan["stripe_price_id"] and precio_centimos != plan["precio_mensual_centimos"]:
        db.limpiar_stripe_price_id_plan(plan_id)
        flash(f"Plan '{nombre}' actualizado -- vuelve a sincronizar con Stripe para aplicar el nuevo precio.", "exito")
    else:
        flash(f"Plan '{nombre}' actualizado.", "exito")
    _auditar("editar_plan_guilda", nombre)
    return redirect(url_for("backoffice.planes"))


@backoffice_bp.route("/planes/<int:plan_id>/sincronizar-stripe", methods=["POST"])
@login_required
@admin_required
def sincronizar_plan_stripe(plan_id: int):
    plan = db.obtener_plan_guilda(plan_id)
    if plan is None:
        abort(404)
    try:
        stripe_price_id = stripe_pagos.sincronizar_plan(plan["nombre"], plan["precio_mensual_centimos"])
        if stripe_price_id:
            db.guardar_stripe_price_id_plan(plan_id, stripe_price_id)
            _auditar("sincronizar_plan_stripe", plan["nombre"])
            flash(f"Plan '{plan['nombre']}' sincronizado con Stripe.", "exito")
        else:
            flash(f"'{plan['nombre']}' no tiene precio fijado todavía -- fíjalo antes de sincronizar.", "error")
    except stripe_pagos.ErrorStripe as e:
        flash(f"No se ha podido sincronizar '{plan['nombre']}' con Stripe: {e}", "error")
    return redirect(url_for("backoffice.planes"))


@backoffice_bp.route("/extras", methods=["POST"])
@login_required
@admin_required
def crear_extra():
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre del extra es obligatorio.", "error")
        return redirect(url_for("backoffice.planes"))
    precio = request.form.get("precio_eur", "").strip()
    precio_centimos = round(float(precio) * 100) if precio else None
    db.crear_extra_guilda(nombre, request.form.get("descripcion", "").strip() or None, precio_centimos)
    _auditar("crear_extra_guilda", nombre)
    flash(f"Extra '{nombre}' creado.", "exito")
    return redirect(url_for("backoffice.planes"))


@backoffice_bp.route("/extras/<int:extra_id>/editar", methods=["POST"])
@login_required
@admin_required
def editar_extra(extra_id: int):
    extra = db.obtener_extra_guilda(extra_id)
    if extra is None:
        abort(404)
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre del extra es obligatorio.", "error")
        return redirect(url_for("backoffice.planes"))
    descripcion = request.form.get("descripcion", "").strip() or None
    precio = request.form.get("precio_eur", "").strip()
    precio_centimos = round(float(precio) * 100) if precio else None
    db.editar_extra_guilda(extra_id, nombre, descripcion, precio_centimos)
    if extra["stripe_price_id"] and precio_centimos != extra["precio_centimos"]:
        db.limpiar_stripe_price_id_extra(extra_id)
        flash(f"Extra '{nombre}' actualizado -- vuelve a sincronizar con Stripe para aplicar el nuevo precio.", "exito")
    else:
        flash(f"Extra '{nombre}' actualizado.", "exito")
    _auditar("editar_extra_guilda", nombre)
    return redirect(url_for("backoffice.planes"))


@backoffice_bp.route("/extras/<int:extra_id>/sincronizar-stripe", methods=["POST"])
@login_required
@admin_required
def sincronizar_extra_stripe(extra_id: int):
    extra = db.obtener_extra_guilda(extra_id)
    if extra is None:
        abort(404)
    try:
        stripe_price_id = stripe_pagos.sincronizar_extra(extra["nombre"], extra["precio_centimos"])
        if stripe_price_id:
            db.guardar_stripe_price_id_extra(extra_id, stripe_price_id)
            _auditar("sincronizar_extra_stripe", extra["nombre"])
            flash(f"Extra '{extra['nombre']}' sincronizado con Stripe.", "exito")
        else:
            flash(f"'{extra['nombre']}' no tiene precio fijado todavía -- fíjalo antes de sincronizar.", "error")
    except stripe_pagos.ErrorStripe as e:
        flash(f"No se ha podido sincronizar '{extra['nombre']}' con Stripe: {e}", "error")
    return redirect(url_for("backoffice.planes"))


@backoffice_bp.route("/tenants/<int:tenant_id>/plan", methods=["POST"])
@login_required
@admin_required
def asignar_plan(tenant_id: int):
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    plan_id = request.form.get("plan_id", type=int)
    db.asignar_plan_tenant(tenant_id, plan_id)
    _auditar("asignar_plan", tenant["nombre"])
    plan = db.obtener_plan_guilda(plan_id) if plan_id else None
    flash(f"Plan asignado: {plan['nombre']}." if plan else "Plan desasignado.", "exito")
    return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))


@backoffice_bp.route("/tenants/<int:tenant_id>/suscripcion/activar", methods=["POST"])
@login_required
@admin_required
def activar_suscripcion(tenant_id: int):
    """Redirige a una Stripe Checkout Session en modo suscripción -- NO
    crea la Subscription directamente por API (Stripe la rechaza sin un
    método de pago ya guardado, y un tenant recién asignado nunca lo
    tiene). El Checkout alojado por Stripe pide la tarjeta y crea la
    suscripción él solo; el webhook (checkout.session.completed en modo
    subscription, ver app/rutas_stripe_webhook.py) guarda el
    stripe_subscription_id resultante y marca el estado."""
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    plan = db.obtener_plan_guilda(tenant["plan_id"]) if tenant["plan_id"] else None
    email = request.form.get("email", "").strip()
    if plan is None or not plan["stripe_price_id"]:
        flash("El tenant no tiene un plan sincronizado con Stripe todavía.", "error")
        return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))
    if not email:
        flash("Introduce un email para activar la suscripción.", "error")
        return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))
    try:
        stripe_customer_id = tenant["stripe_customer_id"]
        if not stripe_customer_id:
            stripe_customer_id = stripe_pagos.crear_cliente_plataforma(email, tenant["nombre"])
            db.guardar_stripe_customer_id(tenant_id, stripe_customer_id)
        url_retorno = url_for("backoffice.ficha_tenant", tenant_id=tenant_id, _external=True)
        url_checkout = stripe_pagos.crear_sesion_suscripcion(stripe_customer_id, plan["stripe_price_id"], url_retorno, url_retorno)
        _auditar("activar_suscripcion", tenant["nombre"])
        return redirect(url_checkout)
    except stripe_pagos.ErrorStripe as e:
        flash(f"No se ha podido activar la suscripción: {e}", "error")
        return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))


@backoffice_bp.route("/tenants/<int:tenant_id>/extras", methods=["POST"])
@login_required
@admin_required
def anadir_extra_tenant(tenant_id: int):
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    extra_id = request.form.get("extra_id", type=int)
    extra = db.obtener_extra_guilda(extra_id) if extra_id else None
    if extra is None:
        flash("Elige un extra del catálogo.", "error")
        return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))
    cantidad = request.form.get("cantidad", type=int) or 1
    activo_hasta = request.form.get("activo_hasta", "").strip() or None
    db.activar_extra_tenant(tenant_id, extra_id, cantidad, activo_hasta)
    if tenant["stripe_subscription_id"] and tenant["stripe_customer_id"] and extra["stripe_price_id"]:
        try:
            stripe_pagos.anadir_extra_a_suscripcion(
                tenant["stripe_customer_id"], tenant["stripe_subscription_id"], extra["stripe_price_id"], cantidad
            )
            flash(f"Extra '{extra['nombre']}' añadido y sincronizado con Stripe.", "exito")
        except stripe_pagos.ErrorStripe as e:
            flash(f"Extra '{extra['nombre']}' añadido, pero no se ha podido facturar en Stripe: {e}", "error")
    else:
        flash(f"Extra '{extra['nombre']}' añadido.", "exito")
    _auditar("anadir_extra_tenant", f"{tenant['nombre']}: {extra['nombre']}")
    return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))


@backoffice_bp.route("/tenants/<int:tenant_id>/extras/<int:tenant_extra_id>/desactivar", methods=["POST"])
@login_required
@admin_required
def desactivar_extra_tenant(tenant_id: int, tenant_extra_id: int):
    """Corta un extra activo antes de su fecha de caducidad (o si no
    tenía, indefinidamente) -- ver db.desactivar_extra_tenant(). NO
    quita el subscription_item correspondiente en Stripe si lo hubiera
    (anadir_extra_tenant lo crea vía anadir_extra_a_suscripcion): eso
    se queda como paso manual desde el propio Dashboard de Stripe, no
    está automatizado en esta ronda."""
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    db.desactivar_extra_tenant(tenant_extra_id)
    _auditar("desactivar_extra_tenant", f"{tenant['nombre']}: extra_activo_id={tenant_extra_id}")
    flash("Extra quitado.", "exito")
    return redirect(url_for("backoffice.ficha_tenant", tenant_id=tenant_id))


@backoffice_bp.route("/tenants", methods=["POST"])
@login_required
@admin_required
def crear_tenant():
    nombre = request.form.get("nombre", "").strip()
    dominio_correo = request.form.get("dominio_correo", "").strip().lower()
    facturascripts_creado = None
    calcom_creado = None
    if not nombre:
        flash("El nombre del tenant es obligatorio.", "error")
        return redirect(url_for("backoffice.panel"))
    tenant_id = None
    try:
        tenant_id = db.crear_tenant(nombre)
        _auditar("crear_tenant", nombre)
        flash(f"Tenant '{nombre}' creado.", "exito")
    except Exception:
        flash(f"No se ha podido crear '{nombre}' -- ¿ya existe un tenant con ese nombre?", "error")
    try:
        # Equipo de EspoCRM con el mismo nombre — base del aislamiento
        # entre tenants (ver app/espocrm.py). Un fallo aquí no debe
        # impedir que el tenant se cree en Guilda Work; si EspoCRM no
        # está configurado (sin ESPOCRM_API_KEY) esto no hace nada.
        espocrm.crear_equipo(nombre)
    except espocrm.ErrorEspoCRM:
        pass
    try:
        # Grupo + Group Folder de Nextcloud con el mismo nombre — el
        # espacio "tipo Drive" compartido del tenant (ver
        # app/nextcloud.py). Mismo criterio: un fallo aquí no bloquea
        # nada más, y sin NEXTCLOUD_ADMIN_USER/PASSWORD configurados
        # no hace nada.
        nextcloud.crear_espacio_tenant(nombre)
    except nextcloud.ErrorNextcloud:
        pass
    if tenant_id is not None:
        try:
            # Instancia física propia de FacturaScripts (ver
            # app/facturascripts.py) — a diferencia de EspoCRM/
            # Nextcloud, aquí NO hay aislamiento lógico posible
            # (su plugin MultiEmpresa no restringe accesos), así
            # que cada tenant necesita su propio contenedor+BD.
            # Sin FACTURASCRIPTS_POSTGRES_ADMIN_PASSWORD configurada,
            # esto falla y se ignora, igual que el resto.
            resultado = facturascripts.aprovisionar_tenant(tenant_id, nombre)
            db.guardar_facturascripts(tenant_id, resultado["url"], resultado["admin_user"], resultado["admin_pass"])
            facturascripts_creado = resultado
        except facturascripts.ErrorFacturaScripts:
            pass
        try:
            # Grupo + usuario de servicio + token de Paperless-ngx
            # (ver app/paperless.py) — a diferencia de EspoCRM/
            # Nextcloud/FacturaScripts, aquí SÍ hay API real de
            # Usuarios y Grupos: el aprovisionamiento es completo,
            # sin ningún paso manual. Sin PAPERLESS_ADMIN_USER/
            # PASSWORD configuradas, esto no hace nada.
            resultado = paperless.aprovisionar_tenant(nombre)
            if resultado is not None:
                db.guardar_paperless(tenant_id, resultado["group_id"], resultado["user_id"], resultado["api_key"])
        except paperless.ErrorPaperless:
            pass
        try:
            # Workspace + token de base de datos de Baserow (ver
            # app/baserow.py) — igual que Paperless-ngx, se crea solo
            # por API; a diferencia de él, invitar a los USUARIOS de
            # ese tenant al Workspace se hace aparte, en
            # crear_usuario() (no hay API para añadirlos
            # directamente, solo invitación+aceptación). Sin
            # BASEROW_ADMIN_EMAIL/PASSWORD configuradas, esto no
            # hace nada.
            resultado = baserow.aprovisionar_tenant(nombre)
            if resultado is not None:
                db.guardar_baserow(tenant_id, resultado["workspace_id"], resultado["api_key"])
        except baserow.ErrorBaserow:
            pass
        try:
            # Usuario de servicio de Cal.diy (ver app/calcom.py) — a
            # diferencia de FacturaScripts, Cal.diy es una instancia
            # COMPARTIDA (no se puede tener una por tenant, su URL
            # pública se hornea en tiempo de compilación); el
            # aislamiento aquí es por cuenta individual, no por
            # contenedor. Sin CALCOM_ADMIN_EMAIL/PASSWORD (o si el
            # contenedor no está levantado) esto falla y se ignora.
            resultado = calcom.aprovisionar_tenant(tenant_id, nombre)
            db.guardar_calcom(tenant_id, resultado["email"], resultado["admin_pass"])
            calcom_creado = resultado
        except calcom.ErrorCalcom:
            pass
        try:
            # Lista + Rol de lista + usuario de servicio de
            # Listmonk (ver app/listmonk.py) — igual que Paperless-
            # ngx/Baserow, 100% automático, sin ningún paso manual:
            # el token viaja en la propia respuesta de creación. Sin
            # LISTMONK_ADMIN_USER/PASSWORD configuradas, esto no
            # hace nada.
            resultado = listmonk.aprovisionar_tenant(nombre)
            if resultado is not None:
                db.guardar_listmonk(tenant_id, resultado["list_id"], resultado["list_role_id"], resultado["api_key"])
        except listmonk.ErrorListmonk:
            pass
        if dominio_correo:
            try:
                # Tenant + Domain (con el dominio propio real del
                # cliente) + Account + ApiKey de Stalwart (ver
                # app/stalwart.py) — 100% automático una vez se
                # conoce el dominio, que es el único dato que no se
                # puede derivar de nada más (decisión del usuario:
                # cada cliente usa su propio dominio, no un
                # subdominio de guilda.cat). Sin
                # STALWART_ADMIN_USER/PASSWORD configuradas, o sin
                # dominio_correo en el formulario, esto no hace nada.
                resultado = stalwart.aprovisionar_tenant(tenant_id, nombre, dominio_correo)
                db.guardar_stalwart(
                    tenant_id, resultado["stalwart_tenant_id"], resultado["domain_id"],
                    resultado["domain_name"], resultado["account_id"], resultado["api_key"],
                )
            except stalwart.ErrorStalwart:
                pass
        try:
            # Usuario + topic + ACL + token de ntfy (ver app/ntfy.py)
            # — 100% automático salvo la concesión de ACL, que se
            # hace por `docker exec` en vez de por API (ntfy no
            # ofrece un endpoint HTTP para eso, ver el docstring del
            # módulo) — no es un paso manual del admin, solo un
            # mecanismo distinto por debajo. Sin NTFY_ADMIN_USER/
            # PASSWORD configuradas, esto no hace nada.
            resultado = ntfy.aprovisionar_tenant(tenant_id, nombre)
            db.guardar_ntfy(tenant_id, resultado["topic"], resultado["token"])
        except ntfy.ErrorNtfy:
            pass
        try:
            # Team + sitio de Umami (ver app/umami.py) — 100%
            # automático, sin ningún paso manual. Sin
            # UMAMI_ADMIN_PASSWORD configurada, esto no hace nada.
            resultado = umami.aprovisionar_tenant(tenant_id, nombre)
            if resultado is not None:
                db.guardar_umami(tenant_id, resultado["team_id"], resultado["website_id"])
        except umami.ErrorUmami:
            pass
        # "observabilidad" (Grafana+Loki, ver app/herramientas.py) nace
        # OCULTA para tenants nuevos, a diferencia del resto del
        # catálogo (que nace visible) — no hay aislamiento por tenant
        # posible en los logs de infraestructura compartida, así que
        # no tiene sentido mostrarla por defecto a un cliente. Ausencia
        # de fila en tenants_herramientas_ocultas = visible (ver
        # db.py), así que aquí hay que ocultarla explícitamente; el
        # admin puede mostrarla luego a mano desde el backoffice si
        # quiere que ese tenant en concreto la vea.
        db.ocultar_herramienta(tenant_id, "observabilidad")
        # "portainer" (ver app/herramientas.py) nace OCULTA por el
        # mismo motivo que "observabilidad": docker.sock en
        # lectura-escritura equivale a control total sobre el host,
        # no tiene sentido mostrárselo a un tenant por defecto.
        db.ocultar_herramienta(tenant_id, "portainer")

    if facturascripts_creado or calcom_creado:
        # Contraseña de admin generada al vuelo: se muestra UNA sola vez,
        # igual que la contraseña temporal de crear_usuario() — no se
        # vuelve a mostrar en la tabla de tenants después de este redirect.
        tenants = db.listar_tenants_con_conteo()
        return render_template(
            "backoffice.html",
            tenants=tenants,
            facturascripts_creado=facturascripts_creado,
            calcom_creado=calcom_creado,
            **_contexto_herramientas(tenants),
        )
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/tenants/<int:tenant_id>/renombrar", methods=["POST"])
@login_required
@admin_required
def renombrar_tenant(tenant_id: int):
    if db.obtener_tenant(tenant_id) is None:
        abort(404)
    nuevo_nombre = request.form.get("nombre", "").strip()
    if nuevo_nombre:
        try:
            db.renombrar_tenant(tenant_id, nuevo_nombre)
            flash(f"Tenant renombrado a '{nuevo_nombre}'.", "exito")
        except Exception:
            flash(f"No se ha podido renombrar a '{nuevo_nombre}' -- ¿ya existe un tenant con ese nombre?", "error")
    # CIF/dirección fiscal: identificación de empresa exigida en el
    # registro horario (art. 34.9 ET) junto a la del trabajador — se
    # guardan en el mismo formulario que el nombre del tenant, campos
    # opcionales (solo hacen falta si ese tenant usa Fichaje).
    if "cif" in request.form or "direccion_fiscal" in request.form:
        db.guardar_datos_tenant(
            tenant_id, request.form.get("cif", "").strip(), request.form.get("direccion_fiscal", "").strip()
        )
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/tenants/<int:tenant_id>/facturascripts-api-key", methods=["POST"])
@login_required
@admin_required
def guardar_facturascripts_api_key(tenant_id: int):
    """La API Key de FacturaScripts no se puede generar por API (hace
    falta una sesión ya iniciada, ver app/facturascripts.py) — este es el
    único paso manual del aprovisionamiento: el admin entra una vez con
    las credenciales generadas (tenants.facturascripts_admin_user/pass),
    crea la clave desde Ajustes → API, y la pega aquí."""
    if db.obtener_tenant(tenant_id) is None:
        abort(404)
    api_key = request.form.get("api_key", "").strip()
    if api_key:
        db.guardar_facturascripts_api_key(tenant_id, api_key)
        _auditar("guardar_facturascripts_api_key", f"tenant_id={tenant_id}")
        flash("API Key de FacturaScripts guardada.", "exito")
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/tenants/<int:tenant_id>/documenso-api-key", methods=["POST"])
@login_required
@admin_required
def guardar_documenso_api_key(tenant_id: int):
    """El Equipo de Documenso y su token se crean a mano — no hay API
    para eso (verificado en vivo, ver app/documenso.py) — esto solo
    guarda el token una vez que el admin lo pega aquí, generado desde
    dentro de la página de ese Equipo (no desde su cuenta personal)."""
    if db.obtener_tenant(tenant_id) is None:
        abort(404)
    api_key = request.form.get("api_key", "").strip()
    if api_key:
        db.guardar_documenso_api_key(tenant_id, api_key)
        _auditar("guardar_documenso_api_key", f"tenant_id={tenant_id}")
        flash("Token de Documenso guardado.", "exito")
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/tenants/<int:tenant_id>/calcom-api-key", methods=["POST"])
@login_required
@admin_required
def guardar_calcom_api_key(tenant_id: int):
    """La API Key de Cal.diy no se puede generar por API (no se ha
    encontrado un endpoint admin en la edición self-hosted, ver
    app/calcom.py) — el admin entra una vez con las credenciales
    generadas (tenants.calcom_email/calcom_admin_pass), crea la clave
    desde Configuración → Developer → API Keys, y la pega aquí."""
    if db.obtener_tenant(tenant_id) is None:
        abort(404)
    api_key = request.form.get("api_key", "").strip()
    if api_key:
        db.guardar_calcom_api_key(tenant_id, api_key)
        _auditar("guardar_calcom_api_key", f"tenant_id={tenant_id}")
        flash("API Key de Cal.diy guardada.", "exito")
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/tenants/<int:tenant_id>/borrar", methods=["POST"])
@login_required
@admin_required
def borrar_tenant(tenant_id: int):
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    try:
        # Para/borra el contenedor+BD dedicados de FacturaScripts antes de
        # borrar el tenant en Guilda Work — un fallo aquí no debe impedir
        # borrar el tenant (ver app/facturascripts.py:desaprovisionar_tenant).
        facturascripts.desaprovisionar_tenant(tenant_id)
    except facturascripts.ErrorFacturaScripts:
        pass
    try:
        # Borra el usuario de servicio y el Grupo de Paperless-ngx de este
        # tenant (ver app/paperless.py:desaprovisionar_tenant) — mismo
        # criterio de fallo aislado.
        paperless.desaprovisionar_tenant(tenant["paperless_user_id"], tenant["paperless_group_id"])
    except paperless.ErrorPaperless:
        pass
    try:
        # Borra el Workspace de Baserow de este tenant (ver
        # app/baserow.py:desaprovisionar_tenant) — mismo criterio de
        # fallo aislado.
        baserow.desaprovisionar_tenant(tenant["baserow_workspace_id"])
    except baserow.ErrorBaserow:
        pass
    # Cal.diy no tiene un desaprovisionar_tenant(): no se ha encontrado
    # un endpoint admin para borrar la cuenta de servicio de otro usuario
    # en la edición self-hosted (ver app/calcom.py) — borrar esa cuenta,
    # si hace falta, es una acción manual del admin desde Cal.diy.
    try:
        # Borra la Lista y el Rol de lista de Listmonk de este tenant
        # (ver app/listmonk.py:desaprovisionar_tenant) — mismo criterio
        # de fallo aislado.
        listmonk.desaprovisionar_tenant(tenant["listmonk_list_id"], tenant["listmonk_list_role_id"])
    except listmonk.ErrorListmonk:
        pass
    try:
        # Borra el usuario de ntfy de este tenant (ver
        # app/ntfy.py:desaprovisionar_tenant) — sus ACL de topic se
        # borran solas junto con el usuario. Mismo criterio de fallo
        # aislado que el resto.
        ntfy.desaprovisionar_tenant(tenant_id)
    except ntfy.ErrorNtfy:
        pass
    try:
        # Borra el Team (y en cascada el sitio) de Umami de este tenant
        # (ver app/umami.py:desaprovisionar_tenant) — mismo criterio de
        # fallo aislado.
        umami.desaprovisionar_tenant(tenant["umami_team_id"])
    except umami.ErrorUmami:
        pass
    try:
        # Borra la Account, el Domain y el Tenant de Stalwart de este
        # tenant (ver app/stalwart.py:desaprovisionar_tenant) — mismo
        # criterio de fallo aislado.
        stalwart.desaprovisionar_tenant(
            tenant["stalwart_tenant_id"], tenant["stalwart_domain_id"], tenant["stalwart_account_id"],
        )
    except stalwart.ErrorStalwart:
        pass
    db.borrar_tenant(tenant_id)
    _auditar("borrar_tenant", tenant["nombre"])
    flash(f"Tenant '{tenant['nombre']}' borrado.", "exito")
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/tenants/<int:tenant_id>/exportar", methods=["POST"])
@login_required
@admin_required
def exportar_datos_tenant(tenant_id: int):
    """Exportación de datos de un tenant (MVP de "derecho de acceso" GDPR,
    ver db.exportar_datos_tenant -- solo lectura, metadatos + enlaces de
    descarga, sin incrustar BLOBs). Se registra en la auditoría por ser
    una operación sensible, igual que borrar/crear un tenant."""
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    datos = db.exportar_datos_tenant(tenant_id)
    _auditar("exportar_datos_tenant", tenant["nombre"])
    cuerpo = json.dumps(datos, ensure_ascii=False, indent=2)
    nombre_archivo = f"export-{tenant['nombre']}-{db.now_iso()[:10]}.json"
    respuesta = Response(cuerpo, mimetype="application/json")
    respuesta.headers.set("Content-Disposition", "attachment", filename=nombre_archivo)
    return respuesta


@backoffice_bp.route("/tenants/<int:tenant_id>/herramientas/<herramienta_id>/alternar", methods=["POST"])
@login_required
@admin_required
def alternar_herramienta_tenant(tenant_id: int, herramienta_id: str):
    """Oculta/muestra una herramienta del catálogo (app/herramientas.py)
    para este tenant — ver app/main.py:herramientas_vista() y
    app/rutas_api.py:listar_herramientas() para dónde se aplica el
    filtro. Ausencia de fila = visible, así que "alternar" sobre una
    herramienta ya oculta la vuelve a mostrar, y viceversa."""
    if db.obtener_tenant(tenant_id) is None:
        abort(404)
    if herramienta_id not in {h["id"] for h in herramientas.HERRAMIENTAS}:
        abort(404)
    nombre_herramienta = next(h["nombre"] for h in herramientas.HERRAMIENTAS if h["id"] == herramienta_id)
    if herramienta_id in db.herramientas_ocultas_de_tenant(tenant_id):
        db.mostrar_herramienta(tenant_id, herramienta_id)
        flash(f"'{nombre_herramienta}' visible de nuevo para este tenant.", "exito")
    else:
        db.ocultar_herramienta(tenant_id, herramienta_id)
        flash(f"'{nombre_herramienta}' ocultada para este tenant.", "exito")
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/usuarios", methods=["POST"])
@login_required
@admin_required
def crear_usuario():
    email = request.form.get("email", "").strip().lower()
    tenant_id = request.form.get("tenant_id") or None
    if not email:
        return redirect(url_for("backoffice.usuarios_vista"))

    # Misma contraseña temporal para Guilda Work/Kratos, OpenProject y
    # Chatwoot (una sola que compartir con la persona, no cuatro
    # distintas) — Metabase no admite fijar una contraseña propia por API
    # (ver app/metabase.py), así que no la usa.
    contrasena_temporal = secrets.token_urlsafe(12)
    try:
        identity_id = kratos.crear_identidad(email, contrasena_temporal)
    except kratos.ErrorKratos as e:
        return render_template(
            "backoffice_usuarios.html",
            usuarios=db.listar_usuarios(),
            tenants=db.listar_tenants(),
            resultados_alta=None,
            error=str(e),
        )
    usuario_id = db.crear_usuario_vinculado_a_kratos(email, identity_id)
    if tenant_id:
        db.asignar_tenant(usuario_id, int(tenant_id))

    resultados_alta = [
        {"servicio": "Guilda Work", "estado": "creado", "detalle": f"contraseña: {contrasena_temporal}"},
    ]

    try:
        openproject.crear_usuario(email, contrasena_temporal)
        resultados_alta.append({"servicio": "OpenProject", "estado": "creado", "detalle": f"contraseña: {contrasena_temporal}"})
    except openproject.ErrorOpenProject as e:
        resultados_alta.append({"servicio": "OpenProject", "estado": "error", "detalle": str(e)})

    try:
        chatwoot.crear_usuario(email, contrasena_temporal, email.split("@")[0])
        resultados_alta.append({"servicio": "Chatwoot", "estado": "creado", "detalle": f"contraseña: {contrasena_temporal}"})
    except chatwoot.ErrorChatwoot as e:
        resultados_alta.append({"servicio": "Chatwoot", "estado": "error", "detalle": str(e)})

    try:
        metabase_id = metabase.crear_usuario(email)
        if metabase_id is not None:
            resultados_alta.append({
                "servicio": "Metabase", "estado": "creado",
                "detalle": "sin contraseña propia — usa \"¿Olvidaste tu contraseña?\" en su login",
            })
    except metabase.ErrorMetabase as e:
        resultados_alta.append({"servicio": "Metabase", "estado": "error", "detalle": str(e)})

    if tenant_id:
        tenant = db.obtener_tenant(int(tenant_id))
        if tenant is not None and tenant["baserow_workspace_id"]:
            try:
                # Invitación al Workspace de Baserow de su tenant — no
                # hay API para añadirlo directamente (ver
                # app/baserow.py), así que esto solo dispara el correo;
                # aceptarlo y crear su propia contraseña de Baserow es
                # cosa suya.
                baserow.invitar_usuario(tenant["baserow_workspace_id"], email)
                resultados_alta.append({
                    "servicio": "Baserow", "estado": "creado",
                    "detalle": "invitación enviada por email — hay que aceptarla desde ahí",
                })
            except baserow.ErrorBaserow as e:
                resultados_alta.append({"servicio": "Baserow", "estado": "error", "detalle": str(e)})
        if tenant is not None and tenant["listmonk_list_role_id"]:
            try:
                # Alta directa en Listmonk con el Rol de lista de su
                # tenant (ver app/listmonk.py) — a diferencia de
                # Baserow, no hace falta invitación/aceptación: entra
                # por SSO directamente con el alcance correcto.
                listmonk.crear_usuario_tenant(email, tenant["listmonk_list_role_id"])
                resultados_alta.append({
                    "servicio": "Listmonk", "estado": "creado",
                    "detalle": "entra con su sesión de Guilda Work (SSO)",
                })
            except listmonk.ErrorListmonk as e:
                resultados_alta.append({"servicio": "Listmonk", "estado": "error", "detalle": str(e)})
        if tenant is not None and tenant["umami_team_id"]:
            try:
                # Alta directa en Umami con el Team de su tenant (ver
                # app/umami.py) — sin SSO, así que se muestra la misma
                # contraseña temporal (mismo criterio que OpenProject/
                # Chatwoot).
                umami.crear_usuario_tenant(email, tenant["umami_team_id"], contrasena_temporal)
                resultados_alta.append({"servicio": "Umami", "estado": "creado", "detalle": f"contraseña: {contrasena_temporal}"})
            except umami.ErrorUmami as e:
                resultados_alta.append({"servicio": "Umami", "estado": "error", "detalle": str(e)})

    return render_template(
        "backoffice_usuarios.html",
        usuarios=db.listar_usuarios(),
        tenants=db.listar_tenants(),
        resultados_alta=resultados_alta,
        email_creado=email,
    )


@backoffice_bp.route("/usuarios/<int:usuario_id>/tenant", methods=["POST"])
@login_required
@admin_required
def asignar_tenant_usuario(usuario_id: int):
    if db.obtener_usuario(usuario_id) is None:
        abort(404)
    tenant_id = request.form.get("tenant_id") or None
    if tenant_id:
        db.asignar_tenant(usuario_id, int(tenant_id))
        _auditar("asignar_tenant", f"usuario_id={usuario_id} tenant_id={tenant_id}")
        tenant = db.obtener_tenant(int(tenant_id))
        flash(f"Usuario asignado a {tenant['nombre']}." if tenant else "Usuario asignado.", "exito")
    else:
        db.desasignar_tenant(usuario_id)
        _auditar("desasignar_tenant", f"usuario_id={usuario_id}")
        flash("Usuario desasignado de su tenant.", "exito")
    return redirect(url_for("backoffice.usuarios_vista"))


@backoffice_bp.route("/usuarios/<int:usuario_id>/rol", methods=["POST"])
@login_required
@admin_required
def cambiar_rol(usuario_id: int):
    usuario = db.obtener_usuario(usuario_id)
    if usuario is None:
        abort(404)
    if usuario_id == g.usuario_id:
        # Evita que un admin se quite el rol a sí mismo y se quede fuera
        # del backoffice sin nadie más que pueda devolvérselo por web.
        abort(400)
    if usuario["rol"] == "admin":
        db.quitar_admin(usuario["email"])
        _auditar("quitar_admin", usuario["email"])
        flash(f"{usuario['email']} ya no es admin.", "exito")
    else:
        db.hacer_admin(usuario["email"])
        _auditar("hacer_admin", usuario["email"])
        flash(f"{usuario['email']} ahora es admin.", "exito")
    return redirect(url_for("backoffice.usuarios_vista"))


@backoffice_bp.route("/usuarios/<int:usuario_id>/gestor-fichajes", methods=["POST"])
@login_required
@admin_required
def alternar_gestor_fichajes(usuario_id: int):
    """Gestor de fichajes: administra el registro horario SOLO de su
    propio tenant (usuarios.tenant_id) -- distinto de rol='admin', que
    es superadmin de todo el backoffice (ver app/auth.py)."""
    usuario = db.obtener_usuario(usuario_id)
    if usuario is None:
        abort(404)
    nuevo_valor = not usuario["gestor_fichajes"]
    db.asignar_gestor_fichajes(usuario_id, nuevo_valor)
    flash(f"{usuario['email']} {'ahora es' if nuevo_valor else 'ya no es'} gestor de fichajes.", "exito")
    return redirect(url_for("backoffice.usuarios_vista"))


@backoffice_bp.route("/usuarios/<int:usuario_id>/supervisor-tenant", methods=["POST"])
@login_required
@admin_required
def alternar_supervisor_tenant(usuario_id: int):
    """Supervisor de tenant: puede actuar sobre datos de otros usuarios de
    SU PROPIO tenant en los módulos que lo comprueben (hoy: tiquets, ver
    app/rutas_tiquets.py:_puede_supervisar_tiquet) -- mismo criterio que
    gestor_fichajes, pero sin scoping a un único módulo."""
    usuario = db.obtener_usuario(usuario_id)
    if usuario is None:
        abort(404)
    nuevo_valor = not usuario["supervisor_tenant"]
    db.asignar_supervisor_tenant(usuario_id, nuevo_valor)
    flash(f"{usuario['email']} {'ahora es' if nuevo_valor else 'ya no es'} supervisor de tenant.", "exito")
    return redirect(url_for("backoffice.usuarios_vista"))


@backoffice_bp.route("/tenants/<int:tenant_id>/fichaje-geolocalizacion", methods=["POST"])
@login_required
@admin_required
def alternar_fichaje_geolocalizacion(tenant_id: int):
    """Opt-in de geolocalización al fichar (Fase G3) -- ver
    db.fijar_fichaje_geolocalizacion, app/rutas_fichaje.py:marcar()."""
    tenant = db.obtener_tenant(tenant_id)
    if tenant is None:
        abort(404)
    nuevo_valor = not tenant["fichaje_geolocalizacion"]
    db.fijar_fichaje_geolocalizacion(tenant_id, nuevo_valor)
    flash(f"Geolocalización al fichar {'activada' if nuevo_valor else 'desactivada'} para {tenant['nombre']}.", "exito")
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/usuarios/<int:usuario_id>/dispositivos")
@login_required
@admin_required
def dispositivos_usuario(usuario_id: int):
    """Sesiones de la app móvil de un usuario cualquiera, para el caso de
    que se vaya de la empresa sin poder (o querer) revocarlas él mismo
    desde "Mis dispositivos" (ver main.py:mis_dispositivos) -- mismo
    alcance que el resto del backoffice, sin restringir por tenant."""
    usuario = db.obtener_usuario(usuario_id)
    if usuario is None:
        abort(404)
    return render_template(
        "backoffice_dispositivos.html",
        usuario=usuario,
        dispositivos=db.listar_tokens_api(usuario_id),
    )


@backoffice_bp.route("/usuarios/<int:usuario_id>/dispositivos/<int:token_id>/revocar", methods=["POST"])
@login_required
@admin_required
def revocar_dispositivo_usuario(usuario_id: int, token_id: int):
    db.revocar_token_api_por_id(usuario_id, token_id)
    flash("Dispositivo revocado.", "exito")
    return redirect(url_for("backoffice.dispositivos_usuario", usuario_id=usuario_id))


@backoffice_bp.route("/leads/<int:lead_id>/atendido", methods=["POST"])
@login_required
@admin_required
def marcar_lead_atendido(lead_id: int):
    atendido = request.form.get("atendido") == "1"
    db.marcar_lead_atendido(lead_id, atendido)
    flash("Lead marcado como atendido." if atendido else "Lead marcado como pendiente.", "exito")
    return redirect(url_for("backoffice.leads_vista"))


@backoffice_bp.route("/solicitudes-portal/<int:solicitud_id>/vincular", methods=["POST"])
@login_required
@admin_required
def vincular_solicitud_portal(solicitud_id: int):
    """Vincula una solicitud de acceso (app/rutas_portal_cliente.py:solicitar_acceso)
    a un cliente_fiscal_id EXISTENTE, poniéndole el email -- mismo criterio
    manual que db.marcar_lead_atendido, sin asignación automática por
    dominio de email (dos gestorías podrían compartir dominio, o el
    cliente usar Gmail)."""
    solicitudes = {s["id"]: s for s in db.listar_solicitudes_acceso_portal()}
    solicitud = solicitudes.get(solicitud_id)
    cliente_fiscal_id = request.form.get("cliente_fiscal_id", type=int)
    if solicitud is None or not cliente_fiscal_id:
        flash("Elige un cliente para vincular la solicitud.", "error")
        return redirect(url_for("backoffice.solicitudes_portal_vista"))
    # editar_cliente_fiscal exige tenant_id -- se resuelve del propio
    # cliente_fiscal elegido, no del admin (que no tiene uno fijo).
    cliente = next((c for c in db.listar_todos_los_clientes_fiscales() if c["id"] == cliente_fiscal_id), None)
    if cliente is None:
        flash("Ese cliente ya no existe.", "error")
        return redirect(url_for("backoffice.solicitudes_portal_vista"))
    db.editar_cliente_fiscal(cliente["tenant_id"], cliente_fiscal_id, email=solicitud["email"])
    db.marcar_solicitud_atendida(solicitud_id)
    flash(f"Solicitud vinculada a {cliente['nombre']}.", "exito")
    return redirect(url_for("backoffice.solicitudes_portal_vista"))


@backoffice_bp.route("/solicitudes-portal/<int:solicitud_id>/crear-cliente", methods=["POST"])
@login_required
@admin_required
def crear_cliente_desde_solicitud(solicitud_id: int):
    """Crea un clientes_fiscales NUEVO (con el email de la solicitud ya
    puesto) en el tenant elegido por el admin, para una solicitud sin
    ficha previa."""
    solicitudes = {s["id"]: s for s in db.listar_solicitudes_acceso_portal()}
    solicitud = solicitudes.get(solicitud_id)
    tenant_id = request.form.get("tenant_id", type=int)
    if solicitud is None or not tenant_id:
        flash("Elige un tenant para crear el cliente.", "error")
        return redirect(url_for("backoffice.solicitudes_portal_vista"))
    db.crear_cliente_fiscal(tenant_id, solicitud["nombre"], nif=solicitud["nif"], email=solicitud["email"])
    db.marcar_solicitud_atendida(solicitud_id)
    flash(f"Cliente '{solicitud['nombre']}' creado.", "exito")
    return redirect(url_for("backoffice.solicitudes_portal_vista"))


@backoffice_bp.route("/webhooks", methods=["POST"])
@login_required
@admin_required
def crear_webhook():
    """`tenant_id` vacío en el formulario = webhook de ámbito local
    (mismo criterio NULL ya usado en otras tablas de este archivo) —
    `eventos` llega como una lista de checkboxes marcados, ver
    app/eventos.py:EVENTOS para los nombres válidos."""
    url = request.form.get("url", "").strip()
    tenant_id_raw = request.form.get("tenant_id") or None
    eventos_marcados = [e for e in request.form.getlist("eventos") if e in eventos.EVENTOS]
    if not url or not eventos_marcados:
        flash("Indica una URL y al menos un evento para crear el webhook.", "error")
        return redirect(url_for("backoffice.webhooks_vista"))
    tenant_id = int(tenant_id_raw) if tenant_id_raw else None
    if tenant_id is not None and db.obtener_tenant(tenant_id) is None:
        abort(404)
    db.crear_webhook(g.usuario_id, tenant_id, url, eventos_marcados)
    flash("Webhook creado.", "exito")
    return redirect(url_for("backoffice.webhooks_vista"))


@backoffice_bp.route("/webhooks/<int:webhook_id>/borrar", methods=["POST"])
@login_required
@admin_required
def borrar_webhook(webhook_id: int):
    if db.obtener_webhook(webhook_id) is None:
        abort(404)
    db.borrar_webhook(webhook_id)
    flash("Webhook borrado.", "exito")
    return redirect(url_for("backoffice.webhooks_vista"))
