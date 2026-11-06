"""«Ver el portal como lo ve este cliente»: una persona del equipo con acceso a ese cliente entra en su portal en **solo lectura**, durante 30 minutos y con constancia en la auditoría, para saber qué le sale ahora.

Nada de lo que se haga ahí cambia datos del cliente: toda petición que no sea de lectura se rechaza, y las pantallas que al abrirse marcarían como leídos los mensajes del cliente no lo hacen. No se crea ningún enlace de acceso ni se toca su
sesión: la vista previa vive en la sesión de quien la abre y se cierra con el botón del aviso (o sola a los 30 minutos)."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import acceso, auditoria, db

DURACION = timedelta(minutes=30)
CLAVE = "portal_vista_previa"


def iniciar(sesion, tenant_id: int, usuario_id: int, cliente_fiscal_id: int) -> None:
    """Abre la vista previa. `ValueError` si el cliente no es de este despacho o la persona no puede verlo."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None or cliente["tenant_id"] != tenant_id or not acceso.puede_ver_cliente(tenant_id, usuario_id, cliente_fiscal_id):
        raise ValueError("No tienes acceso a este cliente.")
    sesion[CLAVE] = {"usuario_id": usuario_id, "cliente_fiscal_id": cliente_fiscal_id, "hasta": (datetime.now() + DURACION).isoformat(timespec="seconds")}
    sesion["cliente_fiscal_id"] = cliente_fiscal_id
    auditoria.registrar(tenant_id, usuario_id, "portal.vista_previa", "cliente_fiscal", cliente_fiscal_id, {})


def activa(sesion) -> dict | None:
    """La vista previa vigente de esta sesión, o None. Si caducó (o no cuadra con el cliente de la sesión) se cierra del todo, sin dejar la sesión puesta como la del cliente."""
    v = sesion.get(CLAVE)
    if not v:
        return None
    try:
        vigente = datetime.fromisoformat(v["hasta"]) > datetime.now() and sesion.get("cliente_fiscal_id") == v["cliente_fiscal_id"]
    except (KeyError, ValueError, TypeError):
        vigente = False
    if not vigente:
        salir(sesion)
        return None
    return v


def salir(sesion) -> None:
    sesion.pop(CLAVE, None)
    sesion.pop("cliente_fiscal_id", None)
