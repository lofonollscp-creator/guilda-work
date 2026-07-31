"""Backoffice (Fase 7c): gestión de tenants y usuarios desde la web, para no
depender solo de `cli.py`. Todas las rutas requieren `usuarios.rol = 'admin'`
(ver `db.hacer_admin` / `python cli.py hacer-admin`) — es una sección de solo
un puñado de administradores, no pensada para volumen ni paginación.
"""
import secrets

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from . import baserow, calcom, chatwoot, db, espocrm, facturascripts, kratos, listmonk, metabase, nextcloud, openproject, paperless
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
        resultados_alta=None,
        facturascripts_creado=None,
        calcom_creado=None,
    )


@backoffice_bp.route("/tenants", methods=["POST"])
@login_required
@admin_required
def crear_tenant():
    nombre = request.form.get("nombre", "").strip()
    facturascripts_creado = None
    calcom_creado = None
    if nombre:
        tenant_id = None
        try:
            tenant_id = db.crear_tenant(nombre)
        except Exception:
            pass  # nombre duplicado: no hace falta más que ignorarlo, se ve en la lista
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

    if facturascripts_creado or calcom_creado:
        # Contraseña de admin generada al vuelo: se muestra UNA sola vez,
        # igual que la contraseña temporal de crear_usuario() — no se
        # vuelve a mostrar en la tabla de tenants después de este redirect.
        return render_template(
            "backoffice.html",
            tenants=db.listar_tenants_con_conteo(),
            usuarios=db.listar_usuarios(),
            resultados_alta=None,
            facturascripts_creado=facturascripts_creado,
            calcom_creado=calcom_creado,
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
        except Exception:
            pass  # nombre duplicado: se ignora, el admin ve que no cambió
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

    # Misma contraseña temporal para Guilda Work/Kratos, OpenProject y
    # Chatwoot (una sola que compartir con la persona, no cuatro
    # distintas) — Metabase no admite fijar una contraseña propia por API
    # (ver app/metabase.py), así que no la usa.
    contrasena_temporal = secrets.token_urlsafe(12)
    try:
        identity_id = kratos.crear_identidad(email, contrasena_temporal)
    except kratos.ErrorKratos as e:
        return render_template(
            "backoffice.html",
            tenants=db.listar_tenants_con_conteo(),
            usuarios=db.listar_usuarios(),
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

    return render_template(
        "backoffice.html",
        tenants=db.listar_tenants_con_conteo(),
        usuarios=db.listar_usuarios(),
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
