"""La portada del portal de cliente: lo que esa persona tiene que hacer hoy, ordenado por urgencia, y nada más.

Cada punto es una acción concreta con su enlace (subir un documento, corregir una factura, leer un mensaje, pedir ayuda con el certificado). Si no queda ninguno, la portada lo dice.
No inventa obligaciones: solo recoge lo que el despacho ya ha pedido o lo que el propio cliente aún no ha hecho."""
from __future__ import annotations

from datetime import date, datetime

from flask import url_for

from . import db, facturas_portal, tareas_trabajo, verticales
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


def datos(cliente, rol: str = "completo", hoy: date | None = None) -> dict:
    """Todo lo que necesita la portada (y el resumen semanal por correo) de este cliente, calculado de una vez: sus vencimientos, lo que se le ha pedido, sus certificados, el trabajo en curso y «Para hacer».
    Con un perfil que no es `completo` no aparece lo que solo puede hacer el titular (firmar, pagar, dar la conformidad)."""
    from . import certificados
    vencimientos = db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente["id"], sin_internos=True)
    # Peticiones de documento concreto todavía sin resolver -- "sin resolver" es "no hay ningún documento subido para ese vencimiento todavía", no un campo aparte que haya que mantener sincronizado.
    solicitudes = [v for v in vencimientos if v["documento_solicitado"] and not db.listar_documentos_vencimiento(v["id"], origen="cliente")]
    visibles = certificados.visibles_para_cliente(cliente["id"])
    trabajo = tareas_trabajo.tareas_para_cliente(cliente["tenant_id"], cliente["id"])
    con_facturas = verticales.esta_activo(cliente["tenant_id"], "contabilizacion")
    puntos = para_hacer(cliente, vencimientos, solicitudes, visibles, trabajo, con_facturas, hoy)
    if rol != "completo":
        puntos = [p for p in puntos if not p["clave"].startswith(("firma-", "conformidad-")) and p["clave"] != "honorarios"]
    return {"vencimientos": vencimientos, "solicitudes": solicitudes, "certificados": visibles, "trabajo": trabajo, "con_facturas": con_facturas, "para_hacer": puntos,
            "presentados": sum(1 for v in vencimientos if v["estado"] == "presentado"), "proximo_pendiente": next((v for v in vencimientos if v["estado"] != "presentado"), None)}


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

    from . import portal_peticiones
    for pet in portal_peticiones.pendientes_del_cliente(cliente["id"])[:10]:
        puntos.append({"clave": f"peticion-{pet['id']}", "urgente": pet["dias"] is not None and pet["dias"] <= 7, "accion": _("Subir documento"), "url": url_for("portal_cliente.peticion", peticion_id=pet["id"]),
                       "titulo": _("Tu gestoría te pide: %(titulo)s", titulo=pet["titulo"]), "detalle": (pet["nota"] + " · " if pet["nota"] else "") + _cuando(pet["dias"])})

    from . import portal_firma, portal_pagos
    for v in portal_firma.pendientes(vencimientos):
        puntos.append({"clave": f"firma-{v['id']}", "urgente": False, "accion": _("Firmar"), "url": url_for("portal_cliente.firma_vencimiento", vencimiento_id=v["id"]),
                       "titulo": _("Tienes un documento por firmar: %(m)s", m=f"{v['modelo']} {v['periodo']}"), "detalle": _("Te lleva directo a la página de firma.")})
    por_pagar = [(vid, c) for vid, c in portal_pagos.cobros(cliente, vencimientos).items() if not c["pagado"]]
    if por_pagar:
        total = sum(c["importe"] for _vid, c in por_pagar)
        puntos.append({"clave": "honorarios", "urgente": False, "accion": _("Ver"), "url": url_for("portal_cliente.impuestos") + f"#vencimiento-{por_pagar[0][0]}",
                       "titulo": ngettext("Tienes %(n)s pago de honorarios pendiente", "Tienes %(n)s pagos de honorarios pendientes", len(por_pagar), n=len(por_pagar)), "detalle": f"{total / 100:.2f} €"})

    if verticales.esta_activo(cliente["tenant_id"], "fiscal"):
        from . import conformidad_declaracion
        from .fiscal_resumen_pdf import frase_resultado
        for p in conformidad_declaracion.pendientes_del_cliente(cliente["id"]):
            limite = next((v["fecha_limite"] for v in vencimientos if v["modelo"] == "303" and v["periodo"] == f"{p['periodo']} {p['ejercicio']}"), None)
            dias = _dias_hasta(limite, hoy)
            puntos.append({"clave": f"conformidad-{p['id']}", "urgente": dias is not None and dias <= 7, "accion": _("Revisar"), "url": url_for("portal_cliente.declaracion", declaracion_id=p["id"]),
                           "titulo": _("Revisa tu modelo 303 de %(p)s antes de presentarlo", p=f"{p['periodo']} {p['ejercicio']}"), "detalle": f"{frase_resultado(p['tipo_declaracion'], p['resultado_centimos'])} {_cuando(dias)}".strip()})

    if con_facturas:
        for f in facturas_portal.devueltas_sin_atender(cliente["id"])[:5]:
            puntos.append({"clave": f"factura-{f['id']}", "urgente": True, "accion": _("Corregir"),
                           "url": url_for("portal_cliente.facturas", trimestre=f["trimestre"]) + f"#factura-{f['id']}",
                           "titulo": _("Tu gestoría te devuelve una factura: %(tercero)s", tercero=f["tercero_nombre"]), "detalle": f["devuelta"] or ""})
        from . import justificantes
        sin_explicar = justificantes.pendientes_del_cliente(cliente["id"])
        if sin_explicar:
            puntos.append({"clave": "justificantes", "urgente": False, "accion": _("Contestar"), "url": url_for("portal_cliente.justificantes_cliente"),
                           "titulo": ngettext("Tu gestoría pregunta por %(n)s movimiento de tu banco", "Tu gestoría pregunta por %(n)s movimientos de tu banco", len(sin_explicar), n=len(sin_explicar)),
                           "detalle": _("Cuéntale qué son: puedes subir la factura, decir que es un tiquet o que es personal.")})
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
