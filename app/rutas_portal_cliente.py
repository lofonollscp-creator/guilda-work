"""Portal de cliente: acceso mínimo, sin cuenta, para que un CLIENTE de la
gestoría (no un empleado) consulte el estado de sus vencimientos fiscales
y suba un documento -- vía enlace mágico por email, no contraseña.

El "principal" de este blueprint es session["cliente_fiscal_id"], un
concepto completamente distinto de g.usuario_id (empleado autenticado vía
Kratos/sesión de escritorio, ver app/main.py:_resolver_usuario_actual).
Este before_request NO toca esa función ni g.usuario_id -- son dos
sistemas de sesión independientes que conviven en la misma cookie de
Flask sin pisarse (claves de session distintas).

v1 deliberadamente NO incluye: auto-registro (el acceso es opt-in, un
empleado pone el email desde /fiscal/clientes/<id>/editar), mensajería
cliente<->gestoría, ni contraseña (solo enlace mágico)."""
from datetime import datetime, timedelta

from flask import Blueprint, abort, g, redirect, render_template, request, session, url_for
from flask_babel import gettext as _

from . import captcha, db, notificaciones
from .auth import limiter
from .notificaciones_email import ErrorNotificacionesEmail, enviar_enlace_portal

portal_bp = Blueprint("portal_cliente", __name__, url_prefix="/portal")

_MINUTOS_COOLDOWN_ENVIO = 2


@portal_bp.before_request
def _resolver_cliente_actual():
    g.cliente_fiscal_id = session.get("cliente_fiscal_id")


def cliente_login_required(vista):
    from functools import wraps

    @wraps(vista)
    def decorada(*args, **kwargs):
        if not g.cliente_fiscal_id:
            return redirect(url_for("portal_cliente.entrar"))
        return vista(*args, **kwargs)
    return decorada


@portal_bp.route("/solicitar-acceso", methods=["GET", "POST"])
@limiter.limit("10/hour")
def solicitar_acceso():
    """Cola de solicitudes para quien NO tiene ficha previa en
    clientes_fiscales (v1 es opt-in, un empleado pone el email desde
    /fiscal/clientes/<id>/editar) -- a diferencia de /entrar (que no
    revela si un email existe), este SÍ es un formulario público visible
    sin autenticar detrás de él, así que lleva ALTCHA desde el principio
    (mismo captcha.py que /login tras varios fallos)."""
    enviado = False
    error = None
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        email = (request.form.get("email") or "").strip()
        if not nombre or not email or "@" not in email:
            error = _("Faltan datos: nombre y email son obligatorios.")
        elif not captcha.verificar_solucion(request.form.get("altcha")):
            error = _("No se ha podido comprobar el captcha. Resuélvelo de nuevo.")
        else:
            db.crear_solicitud_acceso_portal(
                nombre, email, nif=request.form.get("nif"), mensaje=request.form.get("mensaje"),
            )
            enviado = True
    return render_template("portal_solicitar_acceso.html", enviado=enviado, error=error)


@portal_bp.route("/entrar", methods=["GET", "POST"])
@limiter.limit("10/hour")
def entrar():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        if email and "@" in email:
            for cliente in db.clientes_fiscales_por_email(email):
                ultimo_envio = db.ultimo_acceso_solicitado_en(cliente["id"])
                # Cooldown por email (no solo el rate-limit por IP de arriba):
                # sin esto, alguien con la IP de otro (o varias IPs) podría
                # seguir mandando enlaces a un email ajeno sin parar.
                if ultimo_envio and datetime.fromisoformat(ultimo_envio) > datetime.now() - timedelta(minutes=_MINUTOS_COOLDOWN_ENVIO):
                    continue
                token = db.crear_acceso_cliente_fiscal(cliente["id"], request.remote_addr)
                enlace = url_for("portal_cliente.entrar_con_token", token=token, _external=True)
                try:
                    enviar_enlace_portal(cliente["email"], enlace)
                except ErrorNotificacionesEmail:
                    pass
        # Mismo mensaje exista o no el email -- no confirmar si un email
        # concreto está asociado a algún cliente.
        return render_template("portal_entrar.html", enviado=True)
    return render_template("portal_entrar.html", enviado=False)


@portal_bp.route("/entrar/<token>")
def entrar_con_token(token: str):
    cliente_fiscal_id = db.consumir_acceso_cliente_fiscal(token)
    if cliente_fiscal_id is None:
        return render_template("portal_entrar.html", enviado=False, enlace_invalido=True)
    session["cliente_fiscal_id"] = cliente_fiscal_id
    return redirect(url_for("portal_cliente.dashboard"))


@portal_bp.route("/salir", methods=["POST"])
def salir():
    session.pop("cliente_fiscal_id", None)
    return redirect(url_for("portal_cliente.entrar"))


@portal_bp.route("/")
@cliente_login_required
def dashboard():
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        session.pop("cliente_fiscal_id", None)
        return redirect(url_for("portal_cliente.entrar"))
    vencimientos = db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"])
    # Peticiones de documento concreto (app/rutas_fiscal.py:editar_vencimiento)
    # todavía sin resolver -- "sin resolver" es "no hay ningún documento
    # subido para ese vencimiento todavía", no un campo aparte que haya que
    # mantener sincronizado.
    solicitudes_pendientes = [
        v for v in vencimientos if v["documento_solicitado"] and not db.listar_documentos_vencimiento(v["id"])
    ]
    return render_template(
        "portal_dashboard.html", cliente=cliente, vencimientos=vencimientos,
        solicitudes_pendientes=solicitudes_pendientes,
    )


def _vencimiento_del_cliente_actual(vencimiento_id: int):
    cliente = db.obtener_cliente_fiscal_por_id(g.cliente_fiscal_id)
    if cliente is None:
        abort(404)
    vencimiento = db.obtener_vencimiento_fiscal(cliente["tenant_id"], vencimiento_id)
    if vencimiento is None or vencimiento["cliente_fiscal_id"] != cliente["id"]:
        abort(404)
    return vencimiento


@portal_bp.route("/vencimientos/<int:vencimiento_id>/documentos", methods=["GET", "POST"])
@cliente_login_required
def documentos_vencimiento(vencimiento_id: int):
    vencimiento = _vencimiento_del_cliente_actual(vencimiento_id)
    error = None
    if request.method == "POST":
        f = request.files.get("documento")
        if f and f.filename:
            contenido = f.read()
            if f.mimetype not in db.MIME_PERMITIDOS_DOCUMENTO_VENCIMIENTO or len(contenido) > db.TAMANO_MAXIMO_DOCUMENTO_VENCIMIENTO:
                error = _("Archivo no válido: solo imágenes o PDF, hasta 8MB.")
            else:
                db.subir_documento_vencimiento(vencimiento_id, f.filename, f.mimetype, contenido)
                return redirect(url_for("portal_cliente.documentos_vencimiento", vencimiento_id=vencimiento_id))
    return render_template(
        "portal_vencimiento_documentos.html",
        vencimiento=vencimiento, documentos=db.listar_documentos_vencimiento(vencimiento_id), error=error,
    )


@portal_bp.route("/vencimientos/<int:vencimiento_id>/mensajes", methods=["GET", "POST"])
@cliente_login_required
def mensajes_vencimiento(vencimiento_id: int):
    vencimiento = _vencimiento_del_cliente_actual(vencimiento_id)
    if request.method == "POST":
        texto = (request.form.get("texto") or "").strip()
        if texto:
            db.crear_mensaje_vencimiento(vencimiento_id, "cliente", texto)
            # Avisa al empleado asignado -- mismo patrón que el recordatorio
            # de vencimientos (app/main.py) y el correo nuevo (app/correo.py):
            # notificaciones.crear_y_enviar (app/notificaciones.py) registra
            # el aviso en el centro de notificaciones Y manda el push, nunca
            # lanza; si no hay usuario_id asignado simplemente no se
            # notifica a nadie (v2 no tiene "avisar a todo el tenant" todavía).
            if vencimiento["usuario_id"]:
                notificaciones.crear_y_enviar(
                    vencimiento["usuario_id"], "portal_mensaje_nuevo", _("Nuevo mensaje del cliente"), texto[:100],
                    url=f"/fiscal/vencimientos/{vencimiento_id}/editar",
                    datos={"tipo": "portal_mensaje_nuevo", "vencimiento_id": vencimiento_id},
                )
        return redirect(url_for("portal_cliente.mensajes_vencimiento", vencimiento_id=vencimiento_id))
    db.marcar_mensajes_leidos(vencimiento_id, "cliente")
    return render_template(
        "portal_vencimiento_mensajes.html",
        vencimiento=vencimiento, mensajes=db.listar_mensajes_vencimiento(vencimiento_id),
    )
