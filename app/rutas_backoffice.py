"""Backoffice (Fase 7c): gestión de tenants y usuarios desde la web, para no
depender solo de `cli.py`. Todas las rutas requieren `usuarios.rol = 'admin'`
(ver `db.hacer_admin` / `python cli.py hacer-admin`) — es una sección de solo
un puñado de administradores, no pensada para volumen ni paginación.
"""
import secrets

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from . import db, kratos
from .auth import admin_required, login_required

backoffice_bp = Blueprint("backoffice", __name__, url_prefix="/backoffice")


@backoffice_bp.route("/")
@login_required
@admin_required
def panel():
    return render_template(
        "backoffice.html",
        tenants=db.listar_tenants_con_conteo(),
        usuarios=db.listar_usuarios(),
        contrasena_temporal=None,
        email_creado=None,
    )


@backoffice_bp.route("/tenants", methods=["POST"])
@login_required
@admin_required
def crear_tenant():
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        try:
            db.crear_tenant(nombre)
        except Exception:
            pass  # nombre duplicado: no hace falta más que ignorarlo, se ve en la lista
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
        except Exception:
            pass  # nombre duplicado: se ignora, el admin ve que no cambió
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/tenants/<int:tenant_id>/borrar", methods=["POST"])
@login_required
@admin_required
def borrar_tenant(tenant_id: int):
    if db.obtener_tenant(tenant_id) is None:
        abort(404)
    db.borrar_tenant(tenant_id)
    return redirect(url_for("backoffice.panel"))


@backoffice_bp.route("/usuarios", methods=["POST"])
@login_required
@admin_required
def crear_usuario():
    email = request.form.get("email", "").strip().lower()
    tenant_id = request.form.get("tenant_id") or None
    if not email:
        return redirect(url_for("backoffice.panel"))

    contrasena_temporal = secrets.token_urlsafe(12)
    try:
        identity_id = kratos.crear_identidad(email, contrasena_temporal)
    except kratos.ErrorKratos as e:
        return render_template(
            "backoffice.html",
            tenants=db.listar_tenants_con_conteo(),
            usuarios=db.listar_usuarios(),
            contrasena_temporal=None,
            email_creado=None,
            error=str(e),
        )
    usuario_id = db.crear_usuario_vinculado_a_kratos(email, identity_id)
    if tenant_id:
        db.asignar_tenant(usuario_id, int(tenant_id))

    return render_template(
        "backoffice.html",
        tenants=db.listar_tenants_con_conteo(),
        usuarios=db.listar_usuarios(),
        contrasena_temporal=contrasena_temporal,
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
    else:
        db.desasignar_tenant(usuario_id)
    return redirect(url_for("backoffice.panel"))


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
    else:
        db.hacer_admin(usuario["email"])
    return redirect(url_for("backoffice.panel"))
