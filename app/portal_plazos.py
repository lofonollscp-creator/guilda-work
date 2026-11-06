"""«Plazos y lo que falta»: para cada modelo que vence pronto, qué le falta todavía a la gestoría de parte del cliente — el documento que pidió, las facturas que hay que corregir, los movimientos del banco sin explicar, un documento por firmar
o el modelo por revisar — con el enlace a cada cosa; o «todo en orden» si no necesita nada. Así el cliente no se entera del plazo cuando ya no llega."""
from __future__ import annotations

import re
from datetime import date, datetime

from . import db, facturas_contables as fc, facturas_portal, verticales

HORIZONTE_DIAS = 30
MAX_PLAZOS = 4


def _periodo(periodo: str | None) -> tuple[int, int] | None:
    """«2026-T3» y «3T 2026» (las dos formas en que se guardan los periodos trimestrales) → (2026, 3)."""
    m = re.fullmatch(r"(\d{4})-T([1-4])", periodo or "") or re.fullmatch(r"([1-4])T\s*(\d{4})", periodo or "")
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if a > 4 else (b, a)


def _dias(fecha: str | None, hoy: date) -> int | None:
    try:
        return (datetime.strptime((fecha or "")[:10], "%Y-%m-%d").date() - hoy).days
    except ValueError:
        return None


def proximos(cliente, vencimientos, rol: str = "completo", hoy: date | None = None) -> list[dict]:
    """[{id, modelo, periodo, fecha_limite, dias, urgente, faltan: [{texto, url}], en_orden}] de lo que vence en los próximos 30 días (o ya venció sin presentar), lo más cercano primero.
    Requiere contexto de petición (construye enlaces del portal)."""
    from flask import url_for
    from flask_babel import gettext as _, ngettext
    hoy = hoy or date.today()
    con_facturas = verticales.esta_activo(cliente["tenant_id"], "contabilizacion")
    candidatos = [v for v in vencimientos if v["estado"] != "presentado"]
    cerca = sorted((v for v in candidatos if (d := _dias(v["fecha_limite"], hoy)) is not None and d <= HORIZONTE_DIAS), key=lambda v: v["fecha_limite"])[:MAX_PLAZOS]
    if not cerca:
        return []
    devueltas = facturas_portal.devueltas_sin_atender(cliente["id"]) if con_facturas else []
    from . import justificantes
    sin_explicar = justificantes.pendientes_del_cliente(cliente["id"]) if con_facturas else []
    conformidades = {}
    if verticales.esta_activo(cliente["tenant_id"], "fiscal"):
        from . import conformidad_declaracion
        conformidades = {_periodo(f"{p['periodo']} {p['ejercicio']}"): p for p in conformidad_declaracion.pendientes_del_cliente(cliente["id"])}
    plazos = []
    for v in cerca:
        faltan = []
        if v["documento_solicitado"] and not db.listar_documentos_vencimiento(v["id"], origen="cliente"):
            faltan.append({"texto": _("Subir: %(doc)s", doc=v["documento_solicitado"]), "url": url_for("portal_cliente.documentos_vencimiento", vencimiento_id=v["id"])})
        trimestre = v["periodo"] if facturas_portal._trimestre_de_periodo(v["periodo"]) and v["modelo"] in facturas_portal.MODELOS_DEL_TRIMESTRE else None
        if trimestre and con_facturas:
            propias = [f for f in devueltas if f["trimestre"] == trimestre]
            if propias:
                faltan.append({"texto": ngettext("%(n)s factura por corregir", "%(n)s facturas por corregir", len(propias), n=len(propias)), "url": url_for("portal_cliente.facturas", trimestre=trimestre)})
            desde, hasta = fc.rango_del_trimestre(trimestre)
            del_periodo = [j for j in sin_explicar if desde <= j["fecha"] <= hasta]
            if del_periodo:
                faltan.append({"texto": ngettext("%(n)s movimiento del banco sin explicar", "%(n)s movimientos del banco sin explicar", len(del_periodo), n=len(del_periodo)), "url": url_for("portal_cliente.justificantes_cliente")})
        if rol == "completo":
            if v["documenso_documento_id"] and not v["documenso_firmado_en"]:
                faltan.append({"texto": _("Firmar el documento"), "url": url_for("portal_cliente.firma_vencimiento", vencimiento_id=v["id"])})
            p = conformidades.get(_periodo(v["periodo"])) if v["modelo"] == "303" else None
            if p is not None:
                faltan.append({"texto": _("Revisar tu modelo 303"), "url": url_for("portal_cliente.declaracion", declaracion_id=p["id"])})
        dias = _dias(v["fecha_limite"], hoy)
        plazos.append({"id": v["id"], "modelo": v["modelo"], "periodo": v["periodo"], "fecha_limite": v["fecha_limite"][:10], "dias": dias, "urgente": dias is not None and dias <= 7 and bool(faltan),
                       "faltan": faltan, "en_orden": not faltan})
    return plazos
