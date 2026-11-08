"""«Para empezar»: lo que le falta a un cliente nuevo para sacar partido al portal, calculado con lo que ya hay (sin tablas ni marcas que mantener).

Son tres pasos: sus datos de contacto completos, su primera factura subida y el primer mensaje a su gestoría. Cada uno se da por hecho solo cuando ocurre; la lista desaparece cuando están los tres o cuando la persona pulsa «Entendido»."""
from __future__ import annotations

from flask import url_for

from . import db


def _tiene_facturas(cliente) -> bool:
    conn = db.get_connection()
    try:
        return conn.execute("SELECT 1 FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartada' LIMIT 1", (cliente["tenant_id"], cliente["id"])).fetchone() is not None
    finally:
        conn.close()


def _ha_escrito(cliente) -> bool:
    conn = db.get_connection()
    try:
        return conn.execute(
            "SELECT 1 FROM portal_conversaciones c JOIN portal_conversaciones_mensajes m ON m.conversacion_id = c.id AND m.tenant_id = c.tenant_id "
            "WHERE c.tenant_id = ? AND c.cliente_fiscal_id = ? AND m.de = 'cliente' LIMIT 1", (cliente["tenant_id"], cliente["id"])).fetchone() is not None
    finally:
        conn.close()


def pasos(cliente, con_facturas: bool, puede_subir: bool, puede_escribir: bool = True) -> list[dict]:
    """[{clave, titulo, detalle, url, accion, hecho}] en el orden en que conviene hacerlos; vacío si no hay nada que proponer."""
    from flask_babel import gettext as _
    lista = [{"clave": "datos", "hecho": bool((cliente["nif"] or "").strip() and (cliente["email"] or "").strip()), "accion": _("Avisar a tu gestoría"),
              "url": url_for("portal_cliente.conversacion_nueva") if puede_escribir else url_for("portal_cliente.cuenta"),
              "titulo": _("Tus datos de contacto están completos"), "detalle": _("Necesitamos tu NIF y tu correo. Si falta alguno, díselo a tu gestoría.")}]
    if con_facturas and puede_subir:
        lista.append({"clave": "factura", "hecho": _tiene_facturas(cliente), "accion": _("Subir una factura"), "url": url_for("portal_cliente.facturas"),
                      "titulo": _("Has subido tu primera factura"), "detalle": _("Con una foto basta: la leemos nosotros.")})
    if puede_escribir:
        lista.append({"clave": "contacto", "hecho": _ha_escrito(cliente), "accion": _("Escribir"), "url": url_for("portal_cliente.conversacion_nueva"),
                      "titulo": _("Has escrito a tu gestoría"), "detalle": _("Cuéntale cualquier duda: te contestará aquí y te avisaremos.")})
    return lista


def resumen(lista: list[dict]) -> dict:
    hechos = sum(1 for p in lista if p["hecho"])
    return {"hechos": hechos, "total": len(lista), "completo": bool(lista) and hechos == len(lista),
            "siguiente": next((p for p in lista if not p["hecho"]), None)}
