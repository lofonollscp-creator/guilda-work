"""Alta de un tenant con aprovisionamiento de las herramientas conectadas
(EspoCRM, Nextcloud, FacturaScripts, Paperless, Baserow, Cal.diy, Listmonk,
Stalwart, ntfy, Umami). Cada paso es independiente: un fallo (o un servicio
sin configurar) no impide crear el tenant ni los demás pasos, y se informa
del resultado de cada uno. Las credenciales de administración que generan
algunos servicios se devuelven para mostrarlas UNA sola vez."""
from __future__ import annotations

from app import baserow, calcom, espocrm, facturascripts, listmonk, nextcloud, ntfy, paperless, stalwart, umami
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
