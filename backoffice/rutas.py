"""Rutas del backoffice independiente."""
from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app import db as plataforma

from . import auth, datos

bp = Blueprint("rutas", __name__)


def _destino_seguro(destino: str | None) -> str:
    """Solo rutas internas ("/algo"); nunca una URL externa ni "//host"."""
    if destino and destino.startswith("/") and not destino.startswith("//") and not urlparse(destino).netloc:
        return destino
    return url_for("rutas.dashboard")


def _entero(valor, defecto=1) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return defecto


# --- Acceso -----------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        admin, motivo = auth.verificar(request.form.get("usuario", ""), request.form.get("contrasena", ""), auth.ip_cliente())
        if admin is None:
            g.admin = None
            mensaje = ("Demasiados intentos fallidos. Espera unos minutos y vuelve a probar."
                       if motivo == "bloqueado" else "Usuario o contraseña incorrectos.")
            return render_template("login.html", error=mensaje, usuario=request.form.get("usuario", "")), 429 if motivo == "bloqueado" else 401
        auth.iniciar_sesion(admin)
        g.admin = admin
        auth.auditar("login")
        return redirect(_destino_seguro(request.args.get("siguiente")))
    if auth.sesion_valida():
        return redirect(url_for("rutas.dashboard"))
    return render_template("login.html", error=None, usuario="")


@bp.route("/logout", methods=["POST"])
@auth.login_required
def logout():
    auth.auditar("logout")
    auth.cerrar_sesion()
    return redirect(url_for("rutas.login"))


@bp.route("/healthz")
def healthz():
    return "ok", 200, {"Content-Type": "text/plain"}


# --- Dashboard --------------------------------------------------------------

@bp.route("/")
@auth.login_required
def dashboard():
    return render_template("dashboard.html", k=datos.kpis_dashboard())


# --- Tenants ----------------------------------------------------------------

@bp.route("/tenants")
@auth.login_required
def tenants():
    q, estado, plan = request.args.get("q", ""), request.args.get("estado", ""), request.args.get("plan", "")
    orden = request.args.get("orden", "nombre")
    filas, pag = datos.listar_tenants(q, estado, plan, orden, _entero(request.args.get("pagina")), _entero(request.args.get("por_pagina"), 25))
    return render_template(
        "tenants.html", tenants=filas, pag=pag, q=q, estado=estado, plan=plan, orden=orden,
        vista="rejilla" if request.args.get("vista") == "rejilla" else "lista", planes=datos.planes(),
        por_pagina_opciones=datos.POR_PAGINA_OPCIONES,
    )


@bp.route("/tenants", methods=["POST"])
@auth.login_required
def crear_tenant():
    try:
        tenant_id = datos.crear_tenant(request.form.get("nombre", ""))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("rutas.tenants"))
    auth.auditar("tenant.crear", f"tenant {tenant_id}: {request.form.get('nombre', '').strip()}")
    flash("Tenant creado.", "ok")
    return redirect(url_for("rutas.tenant", tenant_id=tenant_id))


SECCIONES_TENANT = ("resumen", "usuarios", "modulos", "suscripcion", "actividad")


@bp.route("/tenants/<int:tenant_id>")
@auth.login_required
def tenant(tenant_id: int):
    detalle = datos.detalle_tenant(tenant_id)
    if detalle is None:
        abort(404)
    seccion = request.args.get("seccion", "resumen")
    if seccion not in SECCIONES_TENANT:
        seccion = "resumen"
    usuarios, _ = datos.listar_usuarios(tenant=str(tenant_id), por_pagina=100) if seccion == "usuarios" else ([], None)
    return render_template(
        "tenant.html", d=detalle, t=detalle["tenant"], seccion=seccion, secciones=SECCIONES_TENANT,
        usuarios=usuarios, planes=datos.planes(),
    )


def _volver_a_tenant(tenant_id: int, seccion: str = "resumen"):
    return redirect(url_for("rutas.tenant", tenant_id=tenant_id, seccion=seccion))


def _tenant_o_404(tenant_id: int):
    t = plataforma.obtener_tenant(tenant_id)
    if t is None:
        abort(404)
    return t


@bp.route("/tenants/<int:tenant_id>/renombrar", methods=["POST"])
@auth.login_required
def renombrar_tenant(tenant_id: int):
    _tenant_o_404(tenant_id)
    try:
        datos.renombrar_tenant(tenant_id, request.form.get("nombre", ""))
    except ValueError as e:
        flash(str(e), "error")
    else:
        auth.auditar("tenant.renombrar", f"tenant {tenant_id} -> {request.form.get('nombre', '').strip()}")
        flash("Nombre actualizado.", "ok")
    return _volver_a_tenant(tenant_id)


@bp.route("/tenants/<int:tenant_id>/activo", methods=["POST"])
@auth.login_required
def alternar_activo(tenant_id: int):
    t = _tenant_o_404(tenant_id)
    nuevo = not t["activo"]
    plataforma.alternar_activo_tenant(tenant_id, nuevo)
    auth.auditar("tenant.reactivar" if nuevo else "tenant.suspender", f"tenant {tenant_id}")
    flash("Tenant reactivado." if nuevo else "Tenant suspendido.", "ok")
    return _volver_a_tenant(tenant_id)


@bp.route("/tenants/<int:tenant_id>/modulos/<modulo_id>", methods=["POST"])
@auth.login_required
def alternar_modulo(tenant_id: int, modulo_id: str):
    _tenant_o_404(tenant_id)
    try:
        activo = datos.alternar_modulo(tenant_id, modulo_id)
    except ValueError as e:
        abort(400, str(e))
    auth.auditar("tenant.modulo", f"tenant {tenant_id}: {modulo_id} {'activado' if activo else 'oculto'}")
    return _volver_a_tenant(tenant_id, request.form.get("seccion") if request.form.get("seccion") in SECCIONES_TENANT else "modulos")


@bp.route("/tenants/<int:tenant_id>/geolocalizacion", methods=["POST"])
@auth.login_required
def alternar_geolocalizacion(tenant_id: int):
    t = _tenant_o_404(tenant_id)
    nuevo = not t["fichaje_geolocalizacion"]
    plataforma.fijar_fichaje_geolocalizacion(tenant_id, nuevo)
    auth.auditar("tenant.geolocalizacion", f"tenant {tenant_id}: {'on' if nuevo else 'off'}")
    flash("Geolocalización del fichaje " + ("activada." if nuevo else "desactivada."), "ok")
    return _volver_a_tenant(tenant_id)


# --- Usuarios ---------------------------------------------------------------

@bp.route("/usuarios")
@auth.login_required
def usuarios():
    q, tenant_f, rol = request.args.get("q", ""), request.args.get("tenant", ""), request.args.get("rol", "")
    orden = request.args.get("orden", "creado")
    filas, pag = datos.listar_usuarios(q, tenant_f, rol, orden, _entero(request.args.get("pagina")), _entero(request.args.get("por_pagina"), 25))
    tenants_todos, _ = datos.listar_tenants(por_pagina=100)
    return render_template(
        "usuarios.html", usuarios=filas, pag=pag, q=q, tenant_f=tenant_f, rol=rol, orden=orden,
        vista="rejilla" if request.args.get("vista") == "rejilla" else "lista", tenants=tenants_todos,
        por_pagina_opciones=datos.POR_PAGINA_OPCIONES, creado=None,
    )


@bp.route("/usuarios", methods=["POST"])
@auth.login_required
def crear_usuario():
    tenant_id = request.form.get("tenant_id", type=int)
    try:
        usuario_id, temporal = datos.crear_usuario(request.form.get("email", ""), tenant_id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(request.referrer and _destino_seguro(urlparse(request.referrer).path) or url_for("rutas.usuarios"))
    auth.auditar("usuario.crear", f"usuario {usuario_id}: {request.form.get('email', '').strip().lower()}")
    # La contraseña temporal se muestra UNA vez en esta respuesta (no se guarda ni viaja por URL).
    filas, pag = datos.listar_usuarios(por_pagina=25)
    tenants_todos, _ = datos.listar_tenants(por_pagina=100)
    return render_template(
        "usuarios.html", usuarios=filas, pag=pag, q="", tenant_f="", rol="", orden="creado", vista="lista",
        tenants=tenants_todos, por_pagina_opciones=datos.POR_PAGINA_OPCIONES,
        creado={"id": usuario_id, "email": request.form.get("email", "").strip().lower(), "contrasena": temporal},
    )


@bp.route("/usuarios/<int:usuario_id>")
@auth.login_required
def usuario(usuario_id: int):
    detalle = datos.detalle_usuario(usuario_id)
    if detalle is None:
        abort(404)
    tenants_todos, _ = datos.listar_tenants(por_pagina=100)
    return render_template("usuario.html", u=detalle["usuario"], dispositivos=detalle["dispositivos"], tenants=tenants_todos)


def _usuario_o_404(usuario_id: int):
    u = plataforma.obtener_usuario(usuario_id)
    if u is None:
        abort(404)
    return u


@bp.route("/usuarios/<int:usuario_id>/tenant", methods=["POST"])
@auth.login_required
def asignar_tenant(usuario_id: int):
    _usuario_o_404(usuario_id)
    try:
        datos.asignar_tenant(usuario_id, request.form.get("tenant_id", type=int))
    except ValueError as e:
        flash(str(e), "error")
    else:
        auth.auditar("usuario.tenant", f"usuario {usuario_id} -> tenant {request.form.get('tenant_id') or 'ninguno'}")
        flash("Tenant actualizado.", "ok")
    return redirect(_destino_seguro(request.form.get("volver")) if request.form.get("volver") else url_for("rutas.usuario", usuario_id=usuario_id))


@bp.route("/usuarios/<int:usuario_id>/permiso/<permiso>", methods=["POST"])
@auth.login_required
def alternar_permiso(usuario_id: int, permiso: str):
    u = _usuario_o_404(usuario_id)
    try:
        nuevo = datos.alternar_permiso(usuario_id, permiso)
    except ValueError as e:
        abort(400, str(e))
    auth.auditar("usuario.permiso", f"{u['email']}: {permiso} {'on' if nuevo else 'off'}")
    flash(f"Permiso «{permiso}» " + ("concedido." if nuevo else "retirado."), "ok")
    return redirect(_destino_seguro(request.form.get("volver")) if request.form.get("volver") else url_for("rutas.usuario", usuario_id=usuario_id))


@bp.route("/usuarios/<int:usuario_id>/dispositivos/<int:token_id>/revocar", methods=["POST"])
@auth.login_required
def revocar_dispositivo(usuario_id: int, token_id: int):
    _usuario_o_404(usuario_id)
    if datos.revocar_dispositivo(usuario_id, token_id):
        auth.auditar("usuario.dispositivo", f"usuario {usuario_id}: token {token_id} revocado")
        flash("Dispositivo revocado.", "ok")
    return redirect(url_for("rutas.usuario", usuario_id=usuario_id))


# --- Actividad (registro de acciones del propio backoffice) -----------------

@bp.route("/actividad")
@auth.login_required
def actividad():
    return render_template("actividad.html", registros=auth.listar_auditoria(300))
