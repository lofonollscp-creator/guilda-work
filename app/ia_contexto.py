"""Copiloto en contexto (W2): en la ficha de un cliente, «qué toca ahora» con un botón para hacerlo, sin salir de la pantalla.

Reúne, con reglas y datos que ya existen (nada se inventa): las propuestas pendientes de ese cliente (W3, se aprueban allí mismo), sus alertas (app/anomalias.py), el próximo modelo que vence y las
facturas que esperan revisión. Y una pregunta ya escrita para el asistente con el contexto del cliente, que la persona envía si quiere."""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from . import anomalias, db, ia_propuestas

DIAS_PROXIMO = 14
MAX_SUGERENCIAS = 5


def sugerencias(tenant_id: int, cliente_fiscal_id: int, hoy: date | None = None) -> dict:
    """{propuestas: [...], avisos: [{titulo, detalle, destino}], pregunta}: lo que hay que mirar de este cliente ahora, lo más urgente primero."""
    from flask import url_for
    from flask_babel import gettext as _
    hoy = hoy or date.today()
    ia_propuestas.generar_si_toca(tenant_id)                                     # las alertas de este cliente pasan a propuestas (idempotente, como mucho una vez por hora)
    propuestas = ia_propuestas.pendientes(tenant_id, cliente_fiscal_id)[:MAX_SUGERENCIAS]
    avisos: list[dict] = []
    conn = db.get_connection()
    try:
        v = conn.execute("SELECT id, modelo, periodo, fecha_limite, COALESCE(documento_solicitado, '') AS pedido FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'pendiente' AND papelera_en IS NULL "
                         "AND fecha_limite >= ? AND fecha_limite <= ? ORDER BY fecha_limite LIMIT 1", (tenant_id, cliente_fiscal_id, hoy.isoformat(), (hoy + timedelta(days=DIAS_PROXIMO)).isoformat())).fetchone()
        pendientes = conn.execute("SELECT COUNT(*) FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado = 'pendiente'", (tenant_id, cliente_fiscal_id)).fetchone()[0]
        nombre = (conn.execute("SELECT nombre FROM clientes_fiscales WHERE id = ? AND tenant_id = ?", (cliente_fiscal_id, tenant_id)).fetchone() or {"nombre": ""})["nombre"]
    finally:
        conn.close()
    if v:
        dias = (date.fromisoformat(v["fecha_limite"][:10]) - hoy).days
        avisos.append({"titulo": _("El modelo %(m)s (%(p)s) vence en %(n)s días", m=v["modelo"], p=v["periodo"], n=dias),
                       "detalle": _("Falta por llegar: %(p)s.", p=v["pedido"]) if v["pedido"] else _("No se ha pedido documentación."), "destino": url_for("fiscal.editar_vencimiento", vencimiento_id=v["id"])})
    if pendientes:
        avisos.append({"titulo": _("%(n)s facturas esperan revisión", n=pendientes) if pendientes != 1 else _("1 factura espera revisión"), "detalle": "", "destino": url_for("contabilidad.lista", cliente_id=cliente_fiscal_id, estado="pendiente", orden="confianza")})
    pregunta = _("Hazme un resumen de la situación de %(c)s: qué tiene pendiente, qué vence pronto y qué debería hacer yo primero.", c=nombre)
    from . import cliente_memoria
    memoria = cliente_memoria.obtener(tenant_id, cliente_fiscal_id)["texto"]
    if memoria:                                                                                # lo que el equipo ya sabe del cliente viaja con la pregunta
        pregunta += " " + _("Esto es lo que ya sabemos de él: %(m)s", m=" ".join(memoria.split()))
    return {"propuestas": propuestas, "avisos": avisos, "pregunta": pregunta, "pregunta_url": url_for("ia.asistente_vista") + "?q=" + quote(pregunta)}
