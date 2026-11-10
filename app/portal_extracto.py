"""«Revisar mi extracto»: el cliente carga el extracto de su banco (un CSV que descarga de su banco) y el portal le enseña qué pagos no tienen factura ni tiquet anotado, para que anote lo que falte.

La lectura del extracto y la comparación se hacen **en el navegador del cliente**: el extracto no se envía ni se guarda. Desde aquí solo sale hacia el navegador la lista mínima para comparar (fecha e importe de sus facturas y de sus tiquets
ya anotados) y solo viaja de vuelta lo que el cliente decide anotar como tiquet, con el formulario de siempre."""
from __future__ import annotations

from datetime import date, timedelta

from . import db

MESES_ATRAS = 24


def datos(cliente) -> dict:
    """{facturas: [{f: fecha, t: total en céntimos, e: 1 si es emitida, n: número}], justificantes: [{f: fecha, i: importe en céntimos con signo}]} de ese cliente, lo bastante para comparar con un extracto."""
    desde = (date.today() - timedelta(days=MESES_ATRAS * 31)).isoformat()
    conn = db.get_connection()
    try:
        facturas = conn.execute("SELECT fecha, total_centimos, tipo, numero FROM facturas_contables WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartada' AND fecha >= ?",
                                (cliente["tenant_id"], cliente["id"], desde)).fetchall()
        justificantes = conn.execute("SELECT fecha, importe_centimos FROM justificantes_pendientes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartado' AND fecha >= ?",
                                     (cliente["tenant_id"], cliente["id"], desde)).fetchall()
    finally:
        conn.close()
    return {"facturas": [{"f": f["fecha"], "t": f["total_centimos"], "e": 1 if f["tipo"] == "emitida" else 0, "n": f["numero"]} for f in facturas], "justificantes": [{"f": j["fecha"], "i": j["importe_centimos"]} for j in justificantes]}
