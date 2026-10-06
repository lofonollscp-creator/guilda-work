"""Alta de un tenant con aprovisionamiento de las herramientas conectadas
(EspoCRM, Nextcloud, FacturaScripts, Paperless, Baserow, Cal.diy, Listmonk,
Stalwart, ntfy, Umami). Cada paso es independiente: un fallo (o un servicio
sin configurar) no impide crear el tenant ni los demás pasos, y se informa
del resultado de cada uno. Las credenciales de administración que generan
algunos servicios se devuelven para mostrarlas UNA sola vez."""
from __future__ import annotations

from app import baserow, calcom, chatwoot, espocrm, facturascripts, listmonk, metabase, nextcloud, ntfy, openproject, paperless, stalwart, umami
from app import db as plataforma

CREADO, OMITIDO, ERROR = "creado", "no configurado", "error"


def _ejecutar(servicio: str, funcion, errores: tuple) -> dict:
    """Corre un paso. `funcion` devuelve el resultado del servicio, o None si
    está desactivado/no configurado."""
    try:
        resultado = funcion()
    except errores as e:
        mensaje = str(e)
        sin_configurar = any(t in mensaje.lower() for t in ("configurad", "falta ", "faltan "))
        return {"servicio": servicio, "estado": OMITIDO if sin_configurar else ERROR,
                "detalle": mensaje, "datos": None}
    except Exception as e:  # noqa: BLE001 -- un servicio caído nunca debe romper el alta
        return {"servicio": servicio, "estado": ERROR, "detalle": f"{type(e).__name__}: {e}", "datos": None}
    if resultado is None:
        return {"servicio": servicio, "estado": OMITIDO, "detalle": "", "datos": None}
    return {"servicio": servicio, "estado": CREADO, "detalle": "", "datos": resultado if isinstance(resultado, dict) else {}}


def aprovisionar(tenant_id: int, nombre: str, dominio_correo: str | None = None) -> list[dict]:
    pasos = []

    pasos.append(_ejecutar("EspoCRM", lambda: espocrm.crear_equipo(nombre), (espocrm.ErrorEspoCRM,)))

    def _nextcloud():
        nextcloud.crear_espacio_tenant(nombre)
        return {} if nextcloud_configurado() else None

    pasos.append(_ejecutar("Nextcloud", _nextcloud, (nextcloud.ErrorNextcloud,)))

    def _facturascripts():
        r = facturascripts.aprovisionar_tenant(tenant_id, nombre)
        plataforma.guardar_facturascripts(tenant_id, r["url"], r["admin_user"], r["admin_pass"])
        return {"URL": r["url"], "Usuario": r["admin_user"], "Contraseña": r["admin_pass"]}

    pasos.append(_ejecutar("FacturaScripts", _facturascripts, (facturascripts.ErrorFacturaScripts,)))

    def _paperless():
        r = paperless.aprovisionar_tenant(nombre)
        if r is not None:
            plataforma.guardar_paperless(tenant_id, r["group_id"], r["user_id"], r["api_key"])
        return {} if r is not None else None

    pasos.append(_ejecutar("Paperless-ngx", _paperless, (paperless.ErrorPaperless,)))

    def _baserow():
        r = baserow.aprovisionar_tenant(nombre)
        if r is not None:
            plataforma.guardar_baserow(tenant_id, r["workspace_id"], r["api_key"])
        return {} if r is not None else None

    pasos.append(_ejecutar("Baserow", _baserow, (baserow.ErrorBaserow,)))

    def _calcom():
        r = calcom.aprovisionar_tenant(tenant_id, nombre)
        plataforma.guardar_calcom(tenant_id, r["email"], r["admin_pass"])
        return {"Email": r["email"], "Contraseña": r["admin_pass"]}

    pasos.append(_ejecutar("Cal.diy", _calcom, (calcom.ErrorCalcom,)))

    def _listmonk():
        r = listmonk.aprovisionar_tenant(nombre)
        if r is not None:
            plataforma.guardar_listmonk(tenant_id, r["list_id"], r["list_role_id"], r["api_key"])
        return {} if r is not None else None

    pasos.append(_ejecutar("Listmonk", _listmonk, (listmonk.ErrorListmonk,)))

    if dominio_correo:
        def _stalwart():
            r = stalwart.aprovisionar_tenant(tenant_id, nombre, dominio_correo)
            plataforma.guardar_stalwart(
                tenant_id, r["stalwart_tenant_id"], r["domain_id"], r["domain_name"], r["account_id"], r["api_key"],
            )
            return {"Dominio": r["domain_name"]}

        pasos.append(_ejecutar("Correo (Stalwart)", _stalwart, (stalwart.ErrorStalwart,)))

    def _ntfy():
        r = ntfy.aprovisionar_tenant(tenant_id, nombre)
        plataforma.guardar_ntfy(tenant_id, r["topic"], r["token"])
        return {"Topic": r["topic"]}

    pasos.append(_ejecutar("ntfy", _ntfy, (ntfy.ErrorNtfy,)))

    def _umami():
        r = umami.aprovisionar_tenant(tenant_id, nombre)
        if r is not None:
            plataforma.guardar_umami(tenant_id, r["team_id"], r["website_id"])
        return {} if r is not None else None

    pasos.append(_ejecutar("Umami", _umami, (umami.ErrorUmami,)))

    # Herramientas que nacen ocultas: infraestructura compartida sin
    # aislamiento por tenant (se pueden mostrar luego desde la ficha).
    plataforma.ocultar_herramienta(tenant_id, "observabilidad")
    plataforma.ocultar_herramienta(tenant_id, "portainer")
    return pasos


def nextcloud_configurado() -> bool:
    return bool(getattr(nextcloud, "NEXTCLOUD_ADMIN_USER", None) and getattr(nextcloud, "NEXTCLOUD_ADMIN_PASSWORD", None))


def aprovisionar_usuario(email: str, tenant_id: int | None, contrasena_temporal: str) -> list[dict]:
    """Altas de una persona en las herramientas conectadas (la misma
    contraseña temporal para las que no tienen SSO). Cada paso es independiente."""
    pasos = []

    def _con_clave(servicio, funcion, errores):
        paso = _ejecutar(servicio, lambda: (funcion(), {"Contraseña": contrasena_temporal})[1], errores)
        return paso

    pasos.append(_con_clave("OpenProject", lambda: openproject.crear_usuario(email, contrasena_temporal), (openproject.ErrorOpenProject,)))
    pasos.append(_con_clave("Chatwoot", lambda: chatwoot.crear_usuario(email, contrasena_temporal, email.split("@")[0]), (chatwoot.ErrorChatwoot,)))

    def _metabase():
        r = metabase.crear_usuario(email)
        return {"Acceso": "sin contraseña propia: usa «¿Olvidaste tu contraseña?» en su login"} if r is not None else None

    pasos.append(_ejecutar("Metabase", _metabase, (metabase.ErrorMetabase,)))
    tenant = plataforma.obtener_tenant(tenant_id) if tenant_id else None
    if tenant is not None:
        if tenant["baserow_workspace_id"]:
            pasos.append(_ejecutar("Baserow", lambda: (baserow.invitar_usuario(tenant["baserow_workspace_id"], email),
                                                       {"Acceso": "invitación enviada por email: hay que aceptarla desde ahí"})[1], (baserow.ErrorBaserow,)))
        if tenant["listmonk_list_role_id"]:
            pasos.append(_ejecutar("Listmonk", lambda: (listmonk.crear_usuario_tenant(email, tenant["listmonk_list_role_id"]),
                                                        {"Acceso": "entra con su sesión de Guilda Work (SSO)"})[1], (listmonk.ErrorListmonk,)))
        if tenant["umami_team_id"]:
            pasos.append(_con_clave("Umami", lambda: umami.crear_usuario_tenant(email, tenant["umami_team_id"], contrasena_temporal), (umami.ErrorUmami,)))
    return pasos


def desaprovisionar_tenant(tenant) -> list[dict]:
    """Retira las instancias/espacios de un tenant en las herramientas conectadas
    antes de borrarlo. Un fallo no impide el borrado; se informa de cada paso."""
    pasos = []

    def paso(servicio, funcion, errores):
        def ejecutar():
            funcion()
            return {}
        pasos.append(_ejecutar(servicio, ejecutar, errores))

    tid = tenant["id"]
    paso("FacturaScripts", lambda: facturascripts.desaprovisionar_tenant(tid), (facturascripts.ErrorFacturaScripts,))
    paso("Paperless-ngx", lambda: paperless.desaprovisionar_tenant(tenant["paperless_user_id"], tenant["paperless_group_id"]), (paperless.ErrorPaperless,))
    paso("Baserow", lambda: baserow.desaprovisionar_tenant(tenant["baserow_workspace_id"]), (baserow.ErrorBaserow,))
    paso("Listmonk", lambda: listmonk.desaprovisionar_tenant(tenant["listmonk_list_id"], tenant["listmonk_list_role_id"]), (listmonk.ErrorListmonk,))
    paso("ntfy", lambda: ntfy.desaprovisionar_tenant(tid), (ntfy.ErrorNtfy,))
    paso("Umami", lambda: umami.desaprovisionar_tenant(tenant["umami_team_id"]), (umami.ErrorUmami,))
    paso("Correo (Stalwart)", lambda: stalwart.desaprovisionar_tenant(
        tenant["stalwart_tenant_id"], tenant["stalwart_domain_id"], tenant["stalwart_account_id"]), (stalwart.ErrorStalwart,))
    paso("EspoCRM", lambda: espocrm.desaprovisionar_tenant(tenant["nombre"]), (espocrm.ErrorEspoCRM,))
    paso("Nextcloud", lambda: nextcloud.desaprovisionar_tenant(tenant["nombre"]), (nextcloud.ErrorNextcloud,))
    return pasos
