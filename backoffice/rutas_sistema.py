"""Resto de funciones del backoffice: comercial (leads, solicitudes del
portal), sistema (salud, estado, diagnóstico, copias, webhooks, actividad,
catálogo de herramientas, ingresos) y operaciones avanzadas sobre un tenant
(API keys de integraciones, exportación RGPD y borrado)."""
from __future__ import annotations

import json

from flask import Response, abort, flash, redirect, render_template, request, url_for

from app import db as plataforma
from app import eventos, herramientas, salud, uptime_kuma

from . import aprovisionamiento, auth, diagnostico, datos
from .rutas import _tenant_o_404, bp


# --- Comercial ----------------------------------------------------------------

@bp.route("/leads")
@auth.login_required
def leads():
    solo = request.args.get("estado", "pendientes")
    filas = [dict(l) for l in plataforma.listar_leads_contacto()]
    if solo == "pendientes":
        filas = [l for l in filas if not l["atendido"]]
    return render_template("leads.html", leads=filas, estado=solo)


@bp.route("/leads/<int:lead_id>/atendido", methods=["POST"])
@auth.login_required
def lead_atendido(lead_id: int):
    atendido = request.form.get("atendido") == "1"
    plataforma.marcar_lead_atendido(lead_id, atendido)
    auth.auditar("lead.atendido" if atendido else "lead.pendiente", f"lead {lead_id}")
    return redirect(url_for("rutas.leads", estado=request.form.get("estado") or "pendientes"))


@bp.route("/solicitudes-portal")
@auth.login_required
def solicitudes():
    todas = [dict(s) for s in plataforma.listar_solicitudes_acceso_portal()]
    if request.args.get("estado", "pendientes") == "pendientes":
        todas = [s for s in todas if not s["atendida"]]
    return render_template(
        "solicitudes.html", solicitudes=todas, estado=request.args.get("estado", "pendientes"),
        clientes=[dict(c) for c in plataforma.listar_todos_los_clientes_fiscales()], tenants=datos.listar_tenants(por_pagina=100)[0],
    )


def _solicitud_o_aviso(solicitud_id: int):
    return next((s for s in plataforma.listar_solicitudes_acceso_portal() if s["id"] == solicitud_id), None)


@bp.route("/solicitudes-portal/<int:solicitud_id>/vincular", methods=["POST"])
@auth.login_required
def vincular_solicitud(solicitud_id: int):
    solicitud = _solicitud_o_aviso(solicitud_id)
    cliente_id = request.form.get("cliente_fiscal_id", type=int)
    cliente = next((c for c in plataforma.listar_todos_los_clientes_fiscales() if c["id"] == cliente_id), None)
    if solicitud is None or cliente is None:
        flash("Elige un cliente existente para vincular la solicitud.", "error")
    else:
        plataforma.editar_cliente_fiscal(cliente["tenant_id"], cliente_id, email=solicitud["email"])
        plataforma.marcar_solicitud_atendida(solicitud_id)
        auth.auditar("solicitud.vincular", f"solicitud {solicitud_id} -> cliente {cliente_id}")
        flash(f"Solicitud vinculada a {cliente['nombre']}.", "ok")
    return redirect(url_for("rutas.solicitudes"))


@bp.route("/solicitudes-portal/<int:solicitud_id>/crear-cliente", methods=["POST"])
@auth.login_required
def crear_cliente_solicitud(solicitud_id: int):
    solicitud = _solicitud_o_aviso(solicitud_id)
    tenant_id = request.form.get("tenant_id", type=int)
    if solicitud is None or not tenant_id or plataforma.obtener_tenant(tenant_id) is None:
        flash("Elige un tenant para crear el cliente.", "error")
    else:
        plataforma.crear_cliente_fiscal(tenant_id, solicitud["nombre"], nif=solicitud["nif"], email=solicitud["email"])
        plataforma.marcar_solicitud_atendida(solicitud_id)
        auth.auditar("solicitud.crear_cliente", f"solicitud {solicitud_id} -> tenant {tenant_id}")
        flash(f"Cliente «{solicitud['nombre']}» creado.", "ok")
    return redirect(url_for("rutas.solicitudes"))


# --- Catálogo de herramientas e ingresos -----------------------------------------

@bp.route("/herramientas")
@auth.login_required
def catalogo():
    tenants = plataforma.listar_tenants()
    ocultas = plataforma.herramientas_ocultas_de_tenants([t["id"] for t in tenants])
    adopcion = plataforma.adopcion_herramientas(ocultas, [h["id"] for h in herramientas.HERRAMIENTAS])
    return render_template("catalogo.html", catalogo=herramientas.HERRAMIENTAS, total=len(tenants), adopcion=adopcion)


@bp.route("/ingresos")
@auth.login_required
def ingresos():
    filas = [dict(t) for t in plataforma.listar_suscripciones_tenants()]
    activos = [t for t in filas if t["suscripcion_estado"] == "activa" and t["plan_precio_centimos"]]
    return render_template(
        "ingresos.html", tenants=filas, mrr=sum(t["plan_precio_centimos"] for t in activos), n_activas=len(activos),
    )


# --- Sistema ----------------------------------------------------------------------

@bp.route("/salud")
@auth.login_required
def salud_vista():
    items = salud.panel()
    grupos: dict[str, list] = {}
    for i in items:
        grupos.setdefault(i["grupo"], []).append(i)
    return render_template("salud.html", grupos=grupos, general=salud.peor_estado(items))


@bp.route("/diagnostico")
@auth.login_required
def diagnostico_vista():
    return render_template("diagnostico.html", integraciones=diagnostico.integraciones())


@bp.route("/estado")
@auth.login_required
def estado():
    try:
        monitores, error = uptime_kuma.listar_monitores(), None
    except uptime_kuma.ErrorUptimeKuma as e:
        monitores, error = [], str(e)
    return render_template("estado.html", monitores=monitores, error=error)


@bp.route("/copias")
@auth.login_required
def copias():
    return render_template("copias.html", copias=plataforma.listar_backups())


@bp.route("/copias", methods=["POST"])
@auth.login_required
def hacer_copia():
    try:
        plataforma.hacer_backup_si_hace_falta(forzar=True)
    except Exception as e:  # noqa: BLE001 -- se informa; la copia anterior se conserva
        flash(f"No se pudo hacer la copia: {e}", "error")
    else:
        auth.auditar("copia.crear")
        flash("Copia de seguridad creada y verificada.", "ok")
    return redirect(url_for("rutas.copias"))


def _propietario_webhooks() -> int:
    """Los webhooks cuelgan de un usuario de la plataforma: el primer administrador (o el local)."""
    admins = [u["id"] for u in plataforma.listar_usuarios() if u["rol"] == "admin"]
    return admins[0] if admins else plataforma.usuario_local_id()


@bp.route("/webhooks")
@auth.login_required
def webhooks():
    tenants = plataforma.listar_tenants()
    por_tenant = plataforma.listar_todos_los_webhooks()
    todos = [w for filas in por_tenant.values() for w in filas]
    entregas = plataforma.entregas_de_webhooks([w["id"] for w in todos], limite=5)
    nombres = {None: "Ámbito local"} | {t["id"]: t["nombre"] for t in tenants}
    grupos = []
    for tid, filas in por_tenant.items():
        grupos.append({
            "nombre": nombres.get(tid, f"Tenant {tid}"),
            "webhooks": [dict(w, eventos=json.loads(w["eventos"]), entregas=[dict(e) for e in entregas.get(w["id"], [])]) for w in filas],
        })
    return render_template("webhooks.html", grupos=grupos, tenants=tenants, eventos=eventos.EVENTOS, creado=None)


@bp.route("/webhooks", methods=["POST"])
@auth.login_required
def crear_webhook():
    url = request.form.get("url", "").strip()
    marcados = [e for e in request.form.getlist("eventos") if e in eventos.EVENTOS]
    tenant_id = request.form.get("tenant_id", type=int)
    if not url.lower().startswith(("https://", "http://")) or len(url) > 500 or not marcados:
        flash("Indica una URL http(s) válida y al menos un evento.", "error")
        return redirect(url_for("rutas.webhooks"))
    if tenant_id is not None and plataforma.obtener_tenant(tenant_id) is None:
        abort(404)
    webhook = plataforma.crear_webhook(_propietario_webhooks(), tenant_id, url, marcados)
    auth.auditar("webhook.crear", f"webhook {webhook['id']}: {url}")
    tenants = plataforma.listar_tenants()
    # El secreto de firma se muestra UNA vez, en esta respuesta.
    return render_template("webhooks.html", grupos=[], tenants=tenants, eventos=eventos.EVENTOS,
                           creado={"url": url, "secreto": webhook["secreto"]})


@bp.route("/webhooks/<int:webhook_id>/borrar", methods=["POST"])
@auth.login_required
def borrar_webhook(webhook_id: int):
    if plataforma.obtener_webhook(webhook_id) is None:
        abort(404)
    plataforma.borrar_webhook(webhook_id)
    auth.auditar("webhook.borrar", f"webhook {webhook_id}")
    flash("Webhook borrado.", "ok")
    return redirect(url_for("rutas.webhooks"))


# --- Operaciones avanzadas de un tenant ----------------------------------------------

_CLAVES_API = {
    "facturascripts": ("API Key de FacturaScripts", plataforma.guardar_facturascripts_api_key),
    "documenso": ("token de Documenso", plataforma.guardar_documenso_api_key),
    "calcom": ("API Key de Cal.diy", plataforma.guardar_calcom_api_key),
}


@bp.route("/tenants/<int:tenant_id>/claves/<servicio>", methods=["POST"])
@auth.login_required
def guardar_clave_api(tenant_id: int, servicio: str):
    """Pasos manuales del aprovisionamiento: estas claves no se pueden generar
    por API; se crean dentro de cada servicio y se pegan aquí."""
    _tenant_o_404(tenant_id)
    if servicio not in _CLAVES_API:
        abort(404)
    etiqueta, guardar = _CLAVES_API[servicio]
    clave = request.form.get("api_key", "").strip()
    if not clave or len(clave) > 500:
        flash("Pega la clave (máx. 500 caracteres).", "error")
    else:
        guardar(tenant_id, clave)
        auth.auditar("tenant.clave_api", f"tenant {tenant_id}: {servicio}")  # nunca el valor
        flash(f"{etiqueta[0].upper() + etiqueta[1:]} guardado.", "ok")
    return redirect(url_for("rutas.tenant", tenant_id=tenant_id, seccion="integraciones"))


@bp.route("/tenants/<int:tenant_id>/exportar", methods=["POST"])
@auth.login_required
def exportar_tenant(tenant_id: int):
    """Exportación de datos del tenant (derecho de acceso RGPD): metadatos y
    enlaces de descarga, sin incrustar archivos. Queda auditada."""
    t = _tenant_o_404(tenant_id)
    cuerpo = json.dumps(plataforma.exportar_datos_tenant(tenant_id), ensure_ascii=False, indent=2, default=str)
    auth.auditar("tenant.exportar", f"tenant {tenant_id}")
    nombre = "".join(c if c.isalnum() or c in "-_" else "-" for c in t["nombre"])
    respuesta = Response(cuerpo, mimetype="application/json")
    respuesta.headers.set("Content-Disposition", "attachment", filename=f"export-{nombre}-{plataforma.now_iso()[:10]}.json")
    return respuesta


@bp.route("/tenants/<int:tenant_id>/borrar", methods=["POST"])
@auth.login_required
def borrar_tenant(tenant_id: int):
    """Borrado definitivo. Exige escribir el nombre exacto del tenant; retira
    primero sus instancias en las herramientas conectadas (un fallo no lo impide)."""
    t = _tenant_o_404(tenant_id)
    if request.form.get("confirmacion", "").strip() != t["nombre"]:
        flash("Para borrar el tenant escribe su nombre exacto en la confirmación.", "error")
        return redirect(url_for("rutas.tenant", tenant_id=tenant_id, seccion="avanzado"))
    pasos = aprovisionamiento.desaprovisionar_tenant(t)
    plataforma.borrar_tenant(tenant_id)
    auth.auditar("tenant.borrar", f"tenant {tenant_id}: {t['nombre']}")
    return render_template("tenant_borrado.html", nombre=t["nombre"], pasos=pasos)
