"""Herramientas MCP del backoffice (gestión de despachos y personas).

Parte de la antigua `__init__.py`, dividida por dominios sin cambiar su comportamiento: todo lo que no está aquí (la conexión, las constantes y las funciones de otros
dominios) se usa a través de `_mt`, que sigue siendo el único espacio de nombres (`_mt.nombre` funciona igual que antes y se puede parchear en los tests)."""
from __future__ import annotations
import base64
import contextvars
import mimetypes
import secrets
import sqlite3
import uuid
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from app import (
    baserow,
    busqueda,
    calcom,
    chatwoot,
    correo,
    db,
    documenso,
    espocrm,
    eventos,
    export,
    facturascripts,
    importador,
    jitsi,
    kratos,
    listmonk,
    metabase,
    minio_cliente,
    n8n,
    nextcloud,
    ntfy,
    openproject,
    outline,
    outlook_ics,
    paperless,
    stalwart,
    synapse,
    umami,
    uptime_kuma,
)

import mcp_tools as _mt


def _exigir_admin() -> None:
    if not _mt.db.es_admin(_mt._uid()):
        raise ValueError("Solo un administrador de Guilda Work puede usar las herramientas de backoffice.")


def backoffice_listar_tenants() -> list[dict]:
    """Lista todos los tenants con su número de usuarios asignados. Solo administradores."""
    _mt._exigir_admin()
    return _mt._filas(_mt.db.listar_tenants_con_conteo())


def backoffice_listar_usuarios() -> list[dict]:
    """Lista todos los usuarios de la plataforma, con su tenant y rol. Solo administradores."""
    _mt._exigir_admin()
    return _mt._filas(_mt.db.listar_usuarios())


def backoffice_crear_tenant(nombre: str) -> dict:
    """Crea un tenant nuevo (sin aprovisionar ningún servicio externo
    todavía -- eso se hace aparte, por ahora solo desde la web). Solo
    administradores."""
    _mt._exigir_admin()
    tenant_id = _mt.db.crear_tenant(nombre)
    return _mt._fila(_mt.db.obtener_tenant(tenant_id))


def backoffice_renombrar_tenant(tenant_id: int, nombre: str) -> dict:
    """Renombra un tenant existente. Solo administradores."""
    _mt._exigir_admin()
    if _mt.db.obtener_tenant(tenant_id) is None:
        raise ValueError(f"No existe el tenant {tenant_id}.")
    _mt.db.renombrar_tenant(tenant_id, nombre)
    return _mt._fila(_mt.db.obtener_tenant(tenant_id))


def backoffice_guardar_datos_tenant(tenant_id: int, cif: str | None = None, direccion_fiscal: str | None = None) -> dict:
    """Guarda el CIF/dirección fiscal de un tenant (identificación de
    empresa exigida en el registro de fichaje). Solo administradores."""
    _mt._exigir_admin()
    if _mt.db.obtener_tenant(tenant_id) is None:
        raise ValueError(f"No existe el tenant {tenant_id}.")
    _mt.db.guardar_datos_tenant(tenant_id, cif, direccion_fiscal)
    return _mt._fila(_mt.db.obtener_tenant(tenant_id))


def backoffice_alternar_herramienta_tenant(tenant_id: int, herramienta_id: str, visible: bool) -> dict:
    """Muestra u oculta una herramienta del catálogo para un tenant
    concreto (no afecta a los demás tenants). Solo administradores."""
    _mt._exigir_admin()
    if _mt.db.obtener_tenant(tenant_id) is None:
        raise ValueError(f"No existe el tenant {tenant_id}.")
    if visible:
        _mt.db.mostrar_herramienta(tenant_id, herramienta_id)
    else:
        _mt.db.ocultar_herramienta(tenant_id, herramienta_id)
    return {"tenant_id": tenant_id, "herramienta_id": herramienta_id, "visible": visible}


def backoffice_crear_usuario(email: str, tenant_id: int | None = None) -> dict:
    """Da de alta un usuario nuevo en Guilda Work (vía Kratos) y, si se
    aprovisionaron para su tenant, también en OpenProject/Chatwoot/
    Metabase/Baserow/Listmonk/Umami -- mismo flujo exacto que el alta desde
    el backoffice web. Devuelve el resultado por cada servicio (contraseña
    temporal incluida donde aplica). Solo administradores."""
    _mt._exigir_admin()
    email = email.strip().lower()
    if not email:
        raise ValueError("Falta el email.")

    contrasena_temporal = secrets.token_urlsafe(12)
    identity_id = _mt.kratos.crear_identidad(email, contrasena_temporal)
    usuario_id = _mt.db.crear_usuario_vinculado_a_kratos(email, identity_id)
    if tenant_id:
        _mt.db.asignar_tenant(usuario_id, tenant_id)

    resultados = [{"servicio": "Guilda Work", "estado": "creado", "detalle": f"contraseña: {contrasena_temporal}"}]

    try:
        _mt.openproject.crear_usuario(email, contrasena_temporal)
        resultados.append({"servicio": "OpenProject", "estado": "creado", "detalle": f"contraseña: {contrasena_temporal}"})
    except _mt.openproject.ErrorOpenProject as e:
        resultados.append({"servicio": "OpenProject", "estado": "error", "detalle": str(e)})

    try:
        _mt.chatwoot.crear_usuario(email, contrasena_temporal, email.split("@")[0])
        resultados.append({"servicio": "Chatwoot", "estado": "creado", "detalle": f"contraseña: {contrasena_temporal}"})
    except _mt.chatwoot.ErrorChatwoot as e:
        resultados.append({"servicio": "Chatwoot", "estado": "error", "detalle": str(e)})

    try:
        metabase_id = _mt.metabase.crear_usuario(email)
        if metabase_id is not None:
            resultados.append({"servicio": "Metabase", "estado": "creado", "detalle": "sin contraseña propia -- usa \"¿Olvidaste tu contraseña?\" en su login"})
    except _mt.metabase.ErrorMetabase as e:
        resultados.append({"servicio": "Metabase", "estado": "error", "detalle": str(e)})

    tenant = _mt.db.obtener_tenant(tenant_id) if tenant_id else None
    if tenant is not None and tenant["baserow_workspace_id"]:
        try:
            _mt.baserow.invitar_usuario(tenant["baserow_workspace_id"], email)
            resultados.append({"servicio": "Baserow", "estado": "creado", "detalle": "invitación enviada por email -- hay que aceptarla desde ahí"})
        except _mt.baserow.ErrorBaserow as e:
            resultados.append({"servicio": "Baserow", "estado": "error", "detalle": str(e)})
    if tenant is not None and tenant["listmonk_list_role_id"]:
        try:
            _mt.listmonk.crear_usuario_tenant(email, tenant["listmonk_list_role_id"])
            resultados.append({"servicio": "Listmonk", "estado": "creado", "detalle": "entra con su sesión de Guilda Work (SSO)"})
        except _mt.listmonk.ErrorListmonk as e:
            resultados.append({"servicio": "Listmonk", "estado": "error", "detalle": str(e)})
    if tenant is not None and tenant["umami_team_id"]:
        try:
            _mt.umami.crear_usuario_tenant(email, tenant["umami_team_id"], contrasena_temporal)
            resultados.append({"servicio": "Umami", "estado": "creado", "detalle": f"contraseña: {contrasena_temporal}"})
        except _mt.umami.ErrorUmami as e:
            resultados.append({"servicio": "Umami", "estado": "error", "detalle": str(e)})

    return {"usuario_id": usuario_id, "email": email, "resultados": resultados}


def backoffice_asignar_tenant_usuario(usuario_id: int, tenant_id: int | None = None) -> dict:
    """Asigna (o quita, con tenant_id=None) el tenant de un usuario. Solo administradores."""
    _mt._exigir_admin()
    if _mt.db.obtener_usuario(usuario_id) is None:
        raise ValueError(f"No existe el usuario {usuario_id}.")
    if tenant_id:
        _mt.db.asignar_tenant(usuario_id, tenant_id)
    else:
        _mt.db.desasignar_tenant(usuario_id)
    return _mt._fila(_mt.db.obtener_usuario(usuario_id))


def backoffice_cambiar_rol(usuario_id: int, rol: str) -> dict:
    """Cambia el rol de un usuario a 'admin' o 'usuario'. No se puede
    quitar el rol admin a uno mismo (misma protección que la web, para no
    quedarse fuera del backoffice sin nadie que lo devuelva). Solo
    administradores."""
    _mt._exigir_admin()
    if rol not in ("admin", "usuario"):
        raise ValueError("rol debe ser 'admin' o 'usuario'.")
    usuario = _mt.db.obtener_usuario(usuario_id)
    if usuario is None:
        raise ValueError(f"No existe el usuario {usuario_id}.")
    if usuario_id == _mt._uid() and rol != "admin":
        raise ValueError("No puedes quitarte el rol de admin a ti mismo.")
    if rol == "admin":
        _mt.db.hacer_admin(usuario["email"])
    else:
        _mt.db.quitar_admin(usuario["email"])
    return _mt._fila(_mt.db.obtener_usuario(usuario_id))


def backoffice_asignar_gestor_fichajes(usuario_id: int, valor: bool) -> dict:
    """Marca o desmarca a un usuario como gestor de fichajes de su propio
    tenant (ver app/rutas_fichaje.py). Solo administradores."""
    _mt._exigir_admin()
    if _mt.db.obtener_usuario(usuario_id) is None:
        raise ValueError(f"No existe el usuario {usuario_id}.")
    _mt.db.asignar_gestor_fichajes(usuario_id, valor)
    return _mt._fila(_mt.db.obtener_usuario(usuario_id))
