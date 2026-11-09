"""«Lo que hemos hecho por ti»: una línea del tiempo con lo que la gestoría ha hecho para este cliente, sacada de lo que ya existe (sin tablas nuevas).

Cuenta hechos de verdad: modelos presentados, justificantes y documentos que la gestoría ha dejado en su carpeta, facturas revisadas (por días), peticiones y cuestionarios recibidos y respuestas escritas. Sirve para
que el cliente vea que su dinero y su papeleo avanzan y llame menos para preguntar «¿cómo va lo mío?». Los últimos 90 días, lo más reciente primero."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import url_for

from . import db

DIAS = 90
LIMITE = 60


def _desde(hoy: date | None, dias: int) -> str:
    return ((hoy or date.today()) - timedelta(days=dias)).isoformat()


def eventos(cliente, hoy: date | None = None, dias: int = DIAS, limite: int = LIMITE) -> list[dict]:
    """[{cuando, tipo, titulo, detalle, url}] del más reciente al más antiguo."""
    from flask_babel import gettext as _, ngettext
    tid, cid, desde = cliente["tenant_id"], cliente["id"], _desde(hoy, dias)
    ev: list[dict] = []
    conn = db.get_connection()
    try:
        for v in conn.execute("SELECT id, modelo, periodo, actualizado_en FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'presentado' AND papelera_en IS NULL "
                              "AND actualizado_en >= ? ORDER BY actualizado_en DESC LIMIT 20", (tid, cid, desde)).fetchall():
            ev.append({"cuando": v["actualizado_en"], "tipo": "presentado", "titulo": _("Hemos presentado tu modelo %(m)s", m=f"{v['modelo']} {v['periodo']}"), "detalle": "",
                       "url": url_for("portal_cliente.documentos_vencimiento", vencimiento_id=v["id"])})
        for d in conn.execute("SELECT d.id, d.nombre_archivo, d.creado_en, d.vencimiento_id, v.modelo, v.periodo FROM vencimientos_fiscales_documentos d JOIN vencimientos_fiscales v ON v.id = d.vencimiento_id "
                              "WHERE v.tenant_id = ? AND v.cliente_fiscal_id = ? AND d.origen <> 'cliente' AND d.creado_en >= ? ORDER BY d.creado_en DESC LIMIT 20", (tid, cid, desde)).fetchall():
            ev.append({"cuando": d["creado_en"], "tipo": "documento", "titulo": _("Hemos dejado un documento en tu carpeta: %(nombre)s", nombre=d["nombre_archivo"]), "detalle": f"{d['modelo']} {d['periodo']}",
                       "url": url_for("portal_cliente.documentos_vencimiento", vencimiento_id=d["vencimiento_id"])})
        por_dia: dict[str, int] = {}
        for f in conn.execute("SELECT substr(revisado_en, 1, 10) AS dia FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND revisado_en IS NOT NULL AND revisado_en >= ? "
                              "AND estado IN ('revisada', 'exportada')", (tid, cid, desde)).fetchall():
            por_dia[f["dia"]] = por_dia.get(f["dia"], 0) + 1
        for dia, n in por_dia.items():
            ev.append({"cuando": dia + "T12:00:00", "tipo": "facturas", "titulo": ngettext("Hemos revisado %(n)s factura tuya", "Hemos revisado %(n)s facturas tuyas", n, n=n), "detalle": "",
                       "url": url_for("portal_cliente.facturas")})
        for p in conn.execute("SELECT id, titulo, revisada_en FROM portal_peticiones WHERE tenant_id = ? AND cliente_fiscal_id = ? AND revisada_en IS NOT NULL AND revisada_en >= ? ORDER BY revisada_en DESC LIMIT 10",
                              (tid, cid, desde)).fetchall():
            ev.append({"cuando": p["revisada_en"], "tipo": "peticion", "titulo": _("Hemos recibido y revisado lo que nos mandaste: %(titulo)s", titulo=p["titulo"]), "detalle": "", "url": url_for("portal_cliente.peticion", peticion_id=p["id"])})
        for q in conn.execute("SELECT id, titulo, respondido_en FROM portal_cuestionarios WHERE tenant_id = ? AND cliente_fiscal_id = ? AND respondido_en IS NOT NULL AND respondido_en >= ? ORDER BY respondido_en DESC LIMIT 10",
                              (tid, cid, desde)).fetchall():
            ev.append({"cuando": q["respondido_en"], "tipo": "cuestionario", "titulo": _("Hemos recibido tus respuestas: %(titulo)s", titulo=q["titulo"]), "detalle": "", "url": url_for("portal_cliente.cuestionario", cuestionario_id=q["id"])})
        for m in conn.execute("SELECT c.id, c.asunto, m.creado_en FROM portal_conversaciones_mensajes m JOIN portal_conversaciones c ON c.id = m.conversacion_id AND c.tenant_id = m.tenant_id "
                              "WHERE m.tenant_id = ? AND c.cliente_fiscal_id = ? AND m.de = 'despacho' AND m.creado_en >= ? ORDER BY m.creado_en DESC LIMIT 15", (tid, cid, desde)).fetchall():
            ev.append({"cuando": m["creado_en"], "tipo": "mensaje", "titulo": _("Te hemos escrito: %(asunto)s", asunto=m["asunto"]), "detalle": "", "url": url_for("portal_cliente.conversacion", conversacion_id=m["id"])})
    finally:
        conn.close()
    ev.sort(key=lambda e: e["cuando"], reverse=True)
    for e in ev:
        try:
            e["fecha"] = datetime.fromisoformat(e["cuando"]).date().isoformat()
        except ValueError:
            e["fecha"] = e["cuando"][:10]
    return ev[:limite]


def resumen(ev: list[dict]) -> dict:
    """Totales para la portada: cuántos modelos presentados y facturas revisadas en el periodo."""
    return {"presentados": sum(1 for e in ev if e["tipo"] == "presentado"), "documentos": sum(1 for e in ev if e["tipo"] == "documento"), "hechos": len(ev)}
