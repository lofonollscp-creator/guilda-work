"""La portada del portal de cliente: lo que esa persona tiene que hacer hoy, ordenado por urgencia, y nada más.

Cada punto es una acción concreta con su enlace (subir un documento, corregir una factura, leer un mensaje, pedir ayuda con el certificado). Si no queda ninguno, la portada lo dice.
No inventa obligaciones: solo recoge lo que el despacho ya ha pedido o lo que el propio cliente aún no ha hecho."""
from __future__ import annotations

from datetime import date, datetime

from flask import url_for

from . import db, facturas_portal
from .facturas_portal import etiqueta_trimestre

DIAS_AVISO_FACTURAS = 21


def _dias_hasta(fecha: str | None, hoy: date) -> int | None:
    try:
        return (datetime.strptime((fecha or "")[:10], "%Y-%m-%d").date() - hoy).days
    except ValueError:
        return None


def _cuando(dias: int | None) -> str:
    from flask_babel import gettext as _
    if dias is None:
        return ""
    if dias < 0:
        return _("venció hace %(n)s días", n=-dias) if dias < -1 else _("venció ayer")
    if dias == 0:
        return _("vence hoy")
    return _("vence mañana") if dias == 1 else _("vence en %(n)s días", n=dias)


def para_hacer(cliente: dict, vencimientos, solicitudes, certificados, trabajo, con_facturas: bool, hoy: date | None = None) -> list[dict]:
    """[{clave, titulo, detalle, url, accion, urgente}] de lo que el cliente tiene pendiente, lo urgente primero."""
    from flask_babel import gettext as _, ngettext
    hoy = hoy or date.today()
    puntos: list[dict] = []

    for c in certificados:
        if c["estado"] == "vigente" or c["ayuda_solicitada"]:
            continue
        caducado = c["estado"] == "caducado"
        puntos.append({"clave": f"certificado-{c['id']}", "urgente": caducado, "accion": _("Pedir ayuda"), "url": url_for("portal_cliente.dashboard") + "#certificado",
                       "titulo": _("Tu certificado digital ha caducado") if caducado else _("Tu certificado digital caduca pronto"),
                       "detalle": _("Sin él, tu gestoría no puede presentar impuestos en tu nombre.") if caducado else _("Conviene renovarlo cuanto antes.")})

    for v in solicitudes:
        dias = _dias_hasta(v["fecha_limite"], hoy)
        puntos.append({"clave": f"documento-{v['id']}", "urgente": dias is not None and dias <= 7, "accion": _("Subir documento"),
                       "url": url_for("portal_cliente.documentos_vencimiento", vencimiento_id=v["id"]),
                       "titulo": _("Tu gestoría necesita: %(doc)s", doc=v["documento_solicitado"]),
                       "detalle": f"{v['modelo']} {etiqueta_trimestre(v['periodo']) if facturas_portal._trimestre_de_periodo(v['periodo']) else v['periodo']} · {_cuando(dias)}".strip(" ·")})

    if con_facturas:
        for f in facturas_portal.devueltas_sin_atender(cliente["id"])[:5]:
            puntos.append({"clave": f"factura-{f['id']}", "urgente": True, "accion": _("Corregir"),
                           "url": url_for("portal_cliente.facturas", trimestre=f["trimestre"]) + f"#factura-{f['id']}",
                           "titulo": _("Tu gestoría te devuelve una factura: %(tercero)s", tercero=f["tercero_nombre"]), "detalle": f["devuelta"] or ""})
        for m in facturas_portal.sin_leer_para_cliente(cliente["id"])[:5]:
            puntos.append({"clave": f"factura-mensaje-{m['factura_id']}", "urgente": False, "accion": _("Leer"), "url": url_for("portal_cliente.factura", factura_id=m["factura_id"]) + "#mensajes",
                           "titulo": ngettext("Tienes %(n)s mensaje nuevo sobre una factura", "Tienes %(n)s mensajes nuevos sobre una factura", m["n"], n=m["n"]),
                           "detalle": f"{m['tercero_nombre']} · {m['numero']}" if m["numero"] != "(por leer)" else m["tercero_nombre"]})
        cuentas = facturas_portal.para_el_inicio(cliente["id"])
        if cuentas["para_corregir"] > 5:
            puntos.append({"clave": "facturas-mas", "urgente": True, "accion": _("Ver facturas"), "url": url_for("portal_cliente.facturas"),
                           "titulo": ngettext("Tienes %(n)s factura por corregir", "Tienes %(n)s facturas por corregir", cuentas["para_corregir"], n=cuentas["para_corregir"]), "detalle": ""})
        proximo = next((v for v in vencimientos if v["estado"] != "presentado" and v["modelo"] in facturas_portal.MODELOS_DEL_TRIMESTRE and facturas_portal._trimestre_de_periodo(v["periodo"])), None)
        if proximo is not None:
            dias = _dias_hasta(proximo["fecha_limite"], hoy)
            tablero = facturas_portal.tablero(cliente["id"], proximo["periodo"], hoy)
            if dias is not None and 0 <= dias <= DIAS_AVISO_FACTURAS and tablero["cuentas"]["total"] == 0:
                puntos.append({"clave": "facturas-trimestre", "urgente": dias <= 7, "accion": _("Subir facturas"), "url": url_for("portal_cliente.facturas", trimestre=proximo["periodo"]),
                               "titulo": _("¿Tienes facturas del %(t)s por enviar?", t=etiqueta_trimestre(proximo["periodo"])),
                               "detalle": f"{_('Aún no has enviado ninguna.')} {proximo['modelo']} {_cuando(dias)}"})

    for m in db.mensajes_sin_leer_para_cliente(cliente["id"]):
        puntos.append({"clave": f"mensaje-{m['vencimiento_id']}", "urgente": False, "accion": _("Leer"), "url": url_for("portal_cliente.mensajes_vencimiento", vencimiento_id=m["vencimiento_id"]),
                       "titulo": ngettext("Tienes %(n)s mensaje nuevo de tu gestoría", "Tienes %(n)s mensajes nuevos de tu gestoría", m["n"], n=m["n"]),
                       "detalle": f"{m['modelo']} · {m['periodo']}"})

    for t in trabajo:
        if t["puede_comentar"] and t["comentarios"] and t["comentarios"][-1]["autor"] != "cliente":
            puntos.append({"clave": f"tarea-{t['id']}", "urgente": False, "accion": _("Responder"), "url": url_for("portal_cliente.dashboard") + f"#tarea-{t['id']}",
                           "titulo": _("Tu gestoría te ha escrito en «%(asunto)s»", asunto=t["asunto"]), "detalle": t["comentarios"][-1]["texto"][:140]})

    puntos.sort(key=lambda p: not p["urgente"])
    return puntos
