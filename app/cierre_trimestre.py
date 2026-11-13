"""Cierre guiado de un trimestre de un cliente en «Facturas para contabilizar»: una lista calculada AHORA (no se guarda: no puede quedar desfasada) con lo que queda por hacer, y el cierre que, al hacerse, deja
el trimestre cerrado, avisa al cliente por correo y le pone a mano el informe del trimestre en su portal si el despacho usa Guilda Fiscal.

Un punto es `ok`, `pendiente` (hay que hacer algo antes de cerrar) o `aviso` (conviene mirarlo, no impide cerrar). Se puede cerrar con puntos pendientes dejando constancia (`forzar`)."""
from __future__ import annotations

from datetime import date

from . import auditoria, db, facturas_contables as fc, facturas_periodicas, facturas_portal, justificantes, verticales


def _punto(puntos: list, clave: str, estado: str, cuantos: int = 0, filtro: dict | None = None) -> None:
    puntos.append({"clave": clave, "estado": estado, "cuantos": cuantos, "filtro": filtro or {}})


def checklist(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str) -> dict:
    fc._cliente(tenant_id, usuario_id, cliente_fiscal_id)                                # comprueba que la persona ve a este cliente
    desde, hasta = fc.rango_del_trimestre(trimestre)
    todas = fc.listar(tenant_id, usuario_id, cliente_fiscal_id=cliente_fiscal_id, desde=desde, hasta=hasta)
    vivas = [f for f in todas if f["estado"] != "descartada"]
    cfg = fc.configuracion(tenant_id, cliente_fiscal_id)
    por_leer = [f for f in vivas if f["estado"] == "pendiente" and f.get("lectura") in ("pendiente", "fallida")]
    por_revisar = [f for f in vivas if f["estado"] == "pendiente" and f not in por_leer]
    sin_exportar = [f for f in vivas if f["estado"] == "revisada"]
    ids = [f["id"] for f in vivas]
    mensajes = facturas_portal.con_mensajes_sin_leer_del_cliente(tenant_id, ids)
    duplicadas = fc.con_duplicado_entre(tenant_id, ids)
    devueltas = [f for f in facturas_portal.facturas_del_cliente(cliente_fiscal_id) if f["trimestre"] == trimestre and f["devuelta"] is not None and not f["atendida"]]
    puntos: list[dict] = []
    _punto(puntos, "sin_facturas", "aviso" if not vivas else "ok", 0 if vivas else 1)
    _punto(puntos, "por_leer", "pendiente" if por_leer else "ok", len(por_leer), {"estado": "pendiente"})
    _punto(puntos, "por_revisar", "pendiente" if por_revisar else "ok", len(por_revisar), {"estado": "pendiente"})
    _punto(puntos, "mensajes", "pendiente" if mensajes else "ok", len(mensajes))
    _punto(puntos, "duplicadas", "pendiente" if duplicadas else "ok", len(duplicadas))
    _punto(puntos, "sin_exportar", "pendiente" if sin_exportar else "ok", len(sin_exportar), {"estado": "revisada"})
    _punto(puntos, "a3", "pendiente" if (vivas and not cfg["a3_empresa"]) else "ok")
    _punto(puntos, "devueltas", "aviso" if devueltas else "ok", len(devueltas))
    habituales = facturas_periodicas.por_cliente_del_trimestre(tenant_id, trimestre).get(cliente_fiscal_id, [])
    _punto(puntos, "periodicas_trimestre", "aviso" if habituales else "ok", len(habituales))
    jus = justificantes.para_el_cierre(tenant_id, cliente_fiscal_id, desde, hasta)
    _punto(puntos, "justificantes_sin_contestar", "aviso" if jus["sin_contestar"] else "ok", jus["sin_contestar"])
    _punto(puntos, "justificantes_por_cerrar", "pendiente" if jus["por_cerrar"] else "ok", jus["por_cerrar"])
    cierre = fc.periodos_cerrados(tenant_id, cliente_fiscal_id, [trimestre]).get(trimestre)
    return {"trimestre": trimestre, "puntos": puntos, "total": len(vivas), "cierre": cierre, "listo": not any(p["estado"] == "pendiente" for p in puntos),
            "hechos": sum(1 for p in puntos if p["estado"] == "ok")}


def cerrar(tenant_id: int, usuario_id: int, cliente_fiscal_id: int, trimestre: str, *, forzar: bool = False) -> dict:
    """Cierra el trimestre. Con puntos pendientes solo si `forzar` (queda anotado cuáles eran). Devuelve `{avisado}`: si el cliente recibió el correo."""
    c = checklist(tenant_id, usuario_id, cliente_fiscal_id, trimestre)
    if c["cierre"]:
        raise ValueError("Este trimestre ya está cerrado.")
    pendientes = [p["clave"] for p in c["puntos"] if p["estado"] == "pendiente"]
    if pendientes and not forzar:
        raise ValueError("Quedan puntos pendientes: resuélvelos o cierra el trimestre dejando constancia.")
    fc.cerrar_periodo(tenant_id, usuario_id, cliente_fiscal_id, trimestre)
    auditoria.registrar(tenant_id, usuario_id, "contabilidad.cierre_guiado", "cliente_fiscal", cliente_fiscal_id, {"trimestre": trimestre, "forzado": bool(pendientes), "pendientes": pendientes})
    return {"avisado": _avisar_al_cliente(tenant_id, cliente_fiscal_id, trimestre)}


def etiqueta(trimestre: str) -> str:
    return facturas_portal.etiqueta_trimestre(trimestre)


def _avisar_al_cliente(tenant_id: int, cliente_fiscal_id: int, trimestre: str) -> bool:
    from . import portal_avisos, portal_recordatorios
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        return False
    et = etiqueta(trimestre)
    _ = portal_recordatorios._

    def texto():
        lineas = [_("Hola, %(nombre)s.", nombre=cliente["nombre"]), _("Tu gestoría ha cerrado el trimestre %(t)s: todas tus facturas de ese periodo están ya tratadas.", t=et)]
        if verticales.esta_activo(tenant_id, "fiscal"):
            lineas.append(_("Tienes a tu disposición el informe del trimestre en tu portal."))
        lineas.append(_("Si te falta alguna factura de ese periodo, escríbenos desde el portal."))
        return {"asunto": _("Hemos cerrado el trimestre %(t)s", t=et), "lineas": lineas, "boton": _("Ver mi trimestre"), "push": _("Hemos cerrado el trimestre %(t)s", t=et)}
    return portal_avisos.avisar(cliente, f"/portal/facturas?trimestre={trimestre}", texto) > 0


def informe_pdf(tenant_id: int, cliente_fiscal_id: int, trimestre: str) -> bytes | None:
    """El informe del trimestre para el cliente (el mismo PDF de Guilda Fiscal), o None si el despacho no usa Guilda Fiscal. Sin comprobar persona: lo llama el portal, ya autenticado como ese cliente."""
    if not verticales.esta_activo(tenant_id, "fiscal"):
        return None
    from . import fiscal_informe_trimestral, fiscal_nucleo as fn
    from flask_babel import gettext as _
    fc.rango_del_trimestre(trimestre)
    ejercicio, periodo = int(trimestre[:4]), f"{trimestre[-1]}T"
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    despacho = db.obtener_tenant(tenant_id)
    datos = fn.informe_para_cliente(tenant_id, cliente_fiscal_id, ejercicio, periodo)
    estados = {"borrador": _("borrador"), "revisada": _("revisada"), "exportada": _("exportada"), "presentada": _("presentada")}
    return fiscal_informe_trimestral.generar(datos, titular=cliente["nombre"], nif=cliente["nif"], gestoria=despacho["nombre"] if despacho else "", estados=estados)
