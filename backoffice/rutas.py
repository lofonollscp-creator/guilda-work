"""Rutas del backoffice independiente."""
from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app import db as plataforma
from app import herramientas

from . import aprovisionamiento, auth, cartera, datos, facturacion, metricas

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
    return render_template("dashboard.html", k=datos.kpis_dashboard(), cartera=cartera.cartera())


# --- Tenants ----------------------------------------------------------------

@bp.route("/tenants")
@auth.login_required
def tenants():
    q, estado, plan = request.args.get("q", ""), request.args.get("estado", ""), request.args.get("plan", "")
    orden = request.args.get("orden", "nombre")
    filas, pag = datos.listar_tenants(q, estado, plan, orden, _entero(request.args.get("pagina")), _entero(request.args.get("por_pagina"), 25))
    for f in filas:
        f["salud"] = cartera.puntuacion_tenant(f["id"])
    return render_template(
        "tenants.html", tenants=filas, pag=pag, q=q, estado=estado, plan=plan, orden=orden,
        vista="rejilla" if request.args.get("vista") == "rejilla" else "lista", planes=datos.planes(),
        por_pagina_opciones=datos.POR_PAGINA_OPCIONES,
    )


@bp.route("/tenants", methods=["POST"])
@auth.login_required
def crear_tenant():
    """Alta de tenant con aprovisionamiento de sus herramientas. Las
    credenciales que generen algunos servicios se muestran UNA vez en la
    propia respuesta (no se guardan en esta página ni viajan por URL)."""
    nombre = request.form.get("nombre", "")
    try:
        tenant_id = datos.crear_tenant(nombre)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("rutas.tenants"))
    plan_id = request.form.get("plan_id", type=int)
    if plan_id:
        try:
            facturacion.asignar_plan(tenant_id, plan_id)
        except ValueError:
            plan_id = None
    dominio = request.form.get("dominio_correo", "").strip().lower()
    pasos = aprovisionamiento.aprovisionar(tenant_id, nombre.strip(), dominio or None)
    auth.auditar("tenant.crear", f"tenant {tenant_id}: {nombre.strip()} (plan {plan_id or 'ninguno'}, dominio {dominio or '-'})")
    return render_template("tenant_creado.html", t=plataforma.obtener_tenant(tenant_id), pasos=pasos)


SECCIONES_TENANT = ("resumen", "usuarios", "modulos", "suscripcion", "integraciones", "actividad", "avanzado")


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
    extra = {}
    if seccion == "suscripcion":
        facturas, error_facturas = facturacion.facturas(tenant_id) if facturacion.configurado() else ([], None)
        extra = {
            "planes_todos": [dict(p) for p in plataforma.listar_planes_guilda(solo_activos=True)],
            "extras_catalogo": [dict(e) for e in plataforma.listar_extras_guilda()],
            "stripe_configurado": facturacion.configurado(), "email_contacto": facturacion.email_de_contacto(tenant_id),
            "facturas": facturas, "error_facturas": error_facturas, "cobros": facturacion.listar_cobros(tenant_id),
        }
    if seccion == "actividad":
        act = metricas.actividad_tenant(tenant_id, detalle["modulos"])
        extra = {"act": act, "salud": cartera.puntuacion_tenant(tenant_id, act), "notas_internas": metricas.notas_tenant(tenant_id)}
    return render_template(
        "tenant.html", d=detalle, t=detalle["tenant"], seccion=seccion, n_fichajes=plataforma.contar_fichajes_tenant(tenant_id) if seccion == "avanzado" else 0, zonas=plataforma.ZONAS_HORARIAS, zona_defecto=plataforma.ZONA_HORARIA_DEFECTO, secciones=SECCIONES_TENANT,
        usuarios=usuarios, planes=datos.planes(), **extra,
    )


def _volver_a_tenant(tenant_id: int, seccion: str = "resumen"):
    return redirect(url_for("rutas.tenant", tenant_id=tenant_id, seccion=seccion))


def _tenant_o_404(tenant_id: int):
    t = plataforma.obtener_tenant(tenant_id)
    if t is None:
        abort(404)
    return t


@bp.route("/tenants/<int:tenant_id>/datos", methods=["POST"])
@auth.login_required
def guardar_datos_tenant(tenant_id: int):
    _tenant_o_404(tenant_id)
    cif = request.form.get("cif", "").strip()[:40]
    direccion = request.form.get("direccion_fiscal", "").strip()[:300]
    zona = request.form.get("zona_horaria", "").strip()
    if zona and not plataforma.zona_horaria_valida(zona):
        flash("Zona horaria no válida.", "error")
        return _volver_a_tenant(tenant_id)
    plataforma.guardar_datos_tenant(tenant_id, cif, direccion)
    if zona:
        plataforma.guardar_zona_horaria_tenant(tenant_id, zona)
    auth.auditar("tenant.datos", f"tenant {tenant_id}: cif={'sí' if cif else 'no'}, zona={zona or '—'}")
    flash("Datos del tenant guardados.", "ok")
    return _volver_a_tenant(tenant_id)


@bp.route("/mapa")
@auth.login_required
def mapa():
    """Matriz tenants × módulos: qué ve cada organización."""
    tenants = [dict(t) for t in plataforma.listar_tenants()]
    ocultas = plataforma.herramientas_ocultas_de_tenants([t["id"] for t in tenants])
    return render_template("mapa.html", tenants=tenants, modulos=herramientas.HERRAMIENTAS, ocultas=ocultas)


@bp.route("/tenants/<int:tenant_id>/notas", methods=["POST"])
@auth.login_required
def añadir_nota_tenant(tenant_id: int):
    _tenant_o_404(tenant_id)
    try:
        metricas.añadir_nota(tenant_id, request.form.get("texto", ""), g.admin["usuario"])
    except ValueError as e:
        flash(str(e), "error")
    else:
        auth.auditar("tenant.nota", f"tenant {tenant_id}")
        flash("Nota guardada.", "ok")
    return _volver_a_tenant(tenant_id, "actividad")


@bp.route("/tenants/<int:tenant_id>/notas/<int:nota_id>/borrar", methods=["POST"])
@auth.login_required
def borrar_nota_tenant(tenant_id: int, nota_id: int):
    _tenant_o_404(tenant_id)
    metricas.borrar_nota(tenant_id, nota_id)
    auth.auditar("tenant.nota_borrar", f"tenant {tenant_id} nota {nota_id}")
    return _volver_a_tenant(tenant_id, "actividad")


@bp.route("/journey")
@auth.login_required
def journey():
    return render_template("journey.html", j=metricas.journey(), etapas=metricas.ETAPAS)


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


# --- Facturación (Stripe) ----------------------------------------------------

def _volver_suscripcion(tenant_id: int):
    return redirect(url_for("rutas.tenant", tenant_id=tenant_id, seccion="suscripcion"))


def _a_stripe(url: str):
    """Redirección (303) a una página alojada por Stripe."""
    return redirect(url, code=303)


@bp.route("/tenants/<int:tenant_id>/plan", methods=["POST"])
@auth.login_required
def asignar_plan(tenant_id: int):
    _tenant_o_404(tenant_id)
    try:
        nombre = facturacion.asignar_plan(tenant_id, request.form.get("plan_id", type=int))
    except ValueError as e:
        flash(str(e), "error")
    else:
        auth.auditar("tenant.plan", f"tenant {tenant_id}: {nombre or 'sin plan'}")
        flash(f"Plan asignado: {nombre}." if nombre else "Plan retirado.", "ok")
    return _volver_suscripcion(tenant_id)


@bp.route("/tenants/<int:tenant_id>/suscripcion/activar", methods=["POST"])
@auth.login_required
def activar_suscripcion(tenant_id: int):
    _tenant_o_404(tenant_id)
    try:
        url = facturacion.url_activar_suscripcion(
            tenant_id, request.form.get("email", ""), url_for("rutas.tenant", tenant_id=tenant_id, seccion="suscripcion", _external=True),
        )
    except ValueError as e:
        flash(str(e), "error")
        return _volver_suscripcion(tenant_id)
    auth.auditar("tenant.suscripcion", f"tenant {tenant_id}: checkout creado")
    return _a_stripe(url)


@bp.route("/tenants/<int:tenant_id>/extras", methods=["POST"])
@auth.login_required
def anadir_extra(tenant_id: int):
    _tenant_o_404(tenant_id)
    try:
        aviso = facturacion.anadir_extra(
            tenant_id, request.form.get("extra_id", type=int) or 0, request.form.get("cantidad", type=int) or 1,
            request.form.get("activo_hasta", "").strip() or None,
        )
    except ValueError as e:
        flash(str(e), "error")
    else:
        auth.auditar("tenant.extra", f"tenant {tenant_id}: extra {request.form.get('extra_id')}")
        flash(aviso, "ok")
    return _volver_suscripcion(tenant_id)


@bp.route("/tenants/<int:tenant_id>/extras/<int:extra_activo_id>/quitar", methods=["POST"])
@auth.login_required
def quitar_extra(tenant_id: int, extra_activo_id: int):
    _tenant_o_404(tenant_id)
    plataforma.desactivar_extra_tenant(extra_activo_id)
    auth.auditar("tenant.extra", f"tenant {tenant_id}: extra activo {extra_activo_id} quitado")
    flash("Extra quitado (si ya estaba facturado en Stripe, se retira desde su dashboard).", "ok")
    return _volver_suscripcion(tenant_id)


@bp.route("/tenants/<int:tenant_id>/stripe/conectar", methods=["POST"])
@auth.login_required
def conectar_stripe(tenant_id: int):
    _tenant_o_404(tenant_id)
    try:
        url = facturacion.url_conectar_stripe(
            tenant_id, request.form.get("email", ""), url_for("rutas.retorno_stripe", tenant_id=tenant_id, _external=True),
        )
    except ValueError as e:
        flash(str(e), "error")
        return _volver_suscripcion(tenant_id)
    auth.auditar("tenant.stripe_connect", f"tenant {tenant_id}: onboarding iniciado")
    return _a_stripe(url)


@bp.route("/tenants/<int:tenant_id>/stripe/retorno")
@auth.login_required
def retorno_stripe(tenant_id: int):
    _tenant_o_404(tenant_id)
    try:
        lista = facturacion.confirmar_connect(tenant_id)
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash("Cuenta de Stripe Connect conectada y lista para cobrar." if lista else
              "La cuenta de Stripe todavía no ha terminado el onboarding: vuelve a intentarlo cuando lo completes.", "ok" if lista else "error")
    return _volver_suscripcion(tenant_id)


@bp.route("/tenants/<int:tenant_id>/cobros", methods=["POST"])
@auth.login_required
def crear_cobro(tenant_id: int):
    _tenant_o_404(tenant_id)
    try:
        cobro = facturacion.crear_cobro(
            tenant_id, request.form.get("concepto", ""), request.form.get("importe", ""), request.form.get("email", ""),
            url_for("rutas.tenant", tenant_id=tenant_id, seccion="suscripcion", _external=True),
        )
    except ValueError as e:
        flash(str(e), "error")
    else:
        auth.auditar("tenant.cobro", f"tenant {tenant_id}: cobro {cobro['id']} de {cobro['importe_centimos']} céntimos")
        flash("Cobro creado: copia el enlace de pago y compártelo con el tenant.", "ok")
    return _volver_suscripcion(tenant_id)


@bp.route("/tenants/<int:tenant_id>/cobros/<int:cobro_id>/actualizar", methods=["POST"])
@auth.login_required
def actualizar_cobro(tenant_id: int, cobro_id: int):
    _tenant_o_404(tenant_id)
    try:
        estado = facturacion.refrescar_cobro(tenant_id, cobro_id)
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash(f"Estado del cobro: {estado}.", "ok")
    return _volver_suscripcion(tenant_id)


@bp.route("/planes")
@auth.login_required
def planes():
    return render_template(
        "planes.html", planes=plataforma.listar_planes_guilda(), extras=plataforma.listar_extras_guilda(),
        stripe_configurado=facturacion.configurado(),
    )


def _accion_catalogo(auditoria: str, funcion, *args, mensaje_ok: str):
    try:
        resultado = funcion(*args)
    except ValueError as e:
        flash(str(e), "error")
    else:
        auth.auditar(auditoria, str(resultado))
        flash(mensaje_ok if not isinstance(resultado, bool) or not resultado else mensaje_ok + " Vuelve a sincronizar con Stripe para aplicar el nuevo precio.", "ok")
    return redirect(url_for("rutas.planes"))


def _max_usuarios():
    return request.form.get("max_usuarios", type=int)


@bp.route("/planes", methods=["POST"])
@auth.login_required
def crear_plan():
    return _accion_catalogo("plan.crear", facturacion.crear_plan, request.form.get("nombre", ""), request.form.get("descripcion", ""),
                            request.form.get("precio", ""), _max_usuarios(), mensaje_ok="Plan creado.")


@bp.route("/planes/<int:plan_id>/editar", methods=["POST"])
@auth.login_required
def editar_plan(plan_id: int):
    return _accion_catalogo("plan.editar", facturacion.editar_plan, plan_id, request.form.get("nombre", ""), request.form.get("descripcion", ""),
                            request.form.get("precio", ""), _max_usuarios(), mensaje_ok="Plan actualizado.")


@bp.route("/planes/<int:plan_id>/sincronizar", methods=["POST"])
@auth.login_required
def sincronizar_plan(plan_id: int):
    return _accion_catalogo("plan.sincronizar", facturacion.sincronizar_plan, plan_id, mensaje_ok="Plan sincronizado con Stripe.")


@bp.route("/extras", methods=["POST"])
@auth.login_required
def crear_extra():
    return _accion_catalogo("extra.crear", facturacion.crear_extra, request.form.get("nombre", ""), request.form.get("descripcion", ""),
                            request.form.get("precio", ""), mensaje_ok="Extra creado.")


@bp.route("/extras/<int:extra_id>/editar", methods=["POST"])
@auth.login_required
def editar_extra(extra_id: int):
    return _accion_catalogo("extra.editar", facturacion.editar_extra, extra_id, request.form.get("nombre", ""), request.form.get("descripcion", ""),
                            request.form.get("precio", ""), mensaje_ok="Extra actualizado.")


@bp.route("/extras/<int:extra_id>/sincronizar", methods=["POST"])
@auth.login_required
def sincronizar_extra(extra_id: int):
    return _accion_catalogo("extra.sincronizar", facturacion.sincronizar_extra, extra_id, mensaje_ok="Extra sincronizado con Stripe.")


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
    email_nuevo = request.form.get("email", "").strip().lower()
    pasos = aprovisionamiento.aprovisionar_usuario(email_nuevo, tenant_id, temporal)
    auth.auditar("usuario.crear", f"usuario {usuario_id}: {email_nuevo}")
    # La contraseña temporal se muestra UNA vez en esta respuesta (no se guarda ni viaja por URL).
    filas, pag = datos.listar_usuarios(por_pagina=25)
    tenants_todos, _ = datos.listar_tenants(por_pagina=100)
    return render_template(
        "usuarios.html", usuarios=filas, pag=pag, q="", tenant_f="", rol="", orden="creado", vista="lista",
        tenants=tenants_todos, por_pagina_opciones=datos.POR_PAGINA_OPCIONES,
        creado={"id": usuario_id, "email": email_nuevo, "contrasena": temporal, "pasos": pasos},
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
    return render_template("actividad.html", registros=auth.listar_auditoria(300), antiguo=plataforma.listar_auditoria_backoffice(limite=100))
