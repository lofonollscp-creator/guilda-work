"""El buzón único del cliente: todas sus conversaciones con la gestoría en una lista, cada una con lo que la ocasiona — un modelo, una factura o un trabajo en curso — en lugar de tres hilos repartidos por el portal.

No cambia dónde viven los mensajes (cada hilo sigue en su sitio, con su aviso al equipo): solo los reúne, por la última actividad, con lo que está sin leer. Los hilos de los trabajos en curso no llevan marca de leído para el cliente, así que se marcan
como «espera tu respuesta» cuando el último mensaje es de la gestoría."""
from __future__ import annotations

from . import db, portal_conversaciones, tareas_trabajo, verticales
from .vencimientos_fiscales import MODELOS_INTERNOS

MAX_FILAS = 500


def sin_leer_total(cliente: dict) -> int:
    """Mensajes de la gestoría que el cliente no ha leído (de modelos y de facturas): lo que cuenta la insignia de la pestaña."""
    conn = db.get_connection()
    try:
        internos = sorted(MODELOS_INTERNOS)
        n = conn.execute("SELECT COUNT(*) FROM vencimientos_fiscales_mensajes m JOIN vencimientos_fiscales v ON v.id = m.vencimiento_id WHERE v.tenant_id = ? AND v.cliente_fiscal_id = ? AND v.papelera_en IS NULL "
                         f"AND m.autor = 'empleado' AND m.leido_en IS NULL AND v.modelo NOT IN ({','.join('?' * len(internos))})", (cliente["tenant_id"], cliente["id"], *internos)).fetchone()[0]
        if verticales.esta_activo(cliente["tenant_id"], "contabilizacion"):
            n += conn.execute("SELECT COUNT(*) FROM facturas_contables_mensajes m JOIN facturas_contables x ON x.id = m.factura_id AND x.tenant_id = m.tenant_id WHERE m.tenant_id = ? AND x.cliente_fiscal_id = ? "
                              "AND m.autor = 'empleado' AND m.leido_en IS NULL", (cliente["tenant_id"], cliente["id"])).fetchone()[0]
        return n + portal_conversaciones.sin_leer_cliente(cliente)
    finally:
        conn.close()


def _agrupar(filas, tipo: str, titulo, url, hacia_cliente: str) -> list[dict]:
    hilos: dict = {}
    for f in filas:
        h = hilos.setdefault(f["ref"], {"tipo": tipo, "ref": f["ref"], "titulo": titulo(f), "url": url(f), "mensajes": 0, "sin_leer": 0})
        h["mensajes"] += 1
        h["ultimo_texto"], h["ultimo_autor"], h["ultimo_en"] = f["texto"], "cliente" if f["autor"] == "cliente" else "gestoria", f["creado_en"]
        h["visto"] = f["autor"] == "cliente" and f["leido_en"] is not None                # lo último es del cliente y la gestoría ya lo ha abierto (K4)
        if f["autor"] == hacia_cliente and f["leido_en"] is None:
            h["sin_leer"] += 1
    return list(hilos.values())


def conversaciones(cliente: dict) -> list[dict]:
    """Las conversaciones del cliente, la más reciente primero. Cada una: `tipo` (modelo · factura · tarea), `titulo`, `url`, `mensajes`, `sin_leer`, `espera_respuesta` y el último mensaje."""
    from flask import url_for
    tid, cid = cliente["tenant_id"], cliente["id"]
    conn = db.get_connection()
    try:
        venc = [dict(f) for f in conn.execute("SELECT m.vencimiento_id AS ref, v.modelo, v.periodo, m.autor, m.texto, m.creado_en, m.leido_en FROM vencimientos_fiscales_mensajes m JOIN vencimientos_fiscales v ON v.id = m.vencimiento_id "
                                              "WHERE v.tenant_id = ? AND v.cliente_fiscal_id = ? AND v.papelera_en IS NULL ORDER BY m.id", (tid, cid))]
        fact = [dict(f) for f in conn.execute("SELECT m.factura_id AS ref, x.numero, x.tercero_nombre, m.autor, m.texto, m.creado_en, m.leido_en FROM facturas_contables_mensajes m JOIN facturas_contables x ON x.id = m.factura_id AND x.tenant_id = m.tenant_id "
                                              "WHERE m.tenant_id = ? AND x.cliente_fiscal_id = ? ORDER BY m.id", (tid, cid))] if verticales.esta_activo(tid, "contabilizacion") else []
    finally:
        conn.close()
    hilos = _agrupar([f for f in venc if f["modelo"] not in MODELOS_INTERNOS], "modelo", lambda f: f"{f['modelo']} {f['periodo']}", lambda f: url_for("portal_cliente.mensajes_vencimiento", vencimiento_id=f["ref"]), "empleado")
    hilos += _agrupar(fact, "factura", lambda f: f"{f['numero'] if f['numero'] != '(por leer)' else ''} {f['tercero_nombre']}".strip(), lambda f: url_for("portal_cliente.factura", factura_id=f["ref"]) + "#mensajes", "empleado")
    for t in tareas_trabajo.tareas_para_cliente(tid, cid):
        if t["comentarios"]:
            ult = t["comentarios"][-1]
            hilos.append({"tipo": "tarea", "ref": t["id"], "titulo": t["asunto"], "url": url_for("portal_cliente.dashboard") + f"#tarea-{t['id']}", "mensajes": len(t["comentarios"]), "sin_leer": 0,
                          "ultimo_texto": ult["texto"], "ultimo_autor": "cliente" if ult["autor"] == "cliente" else "gestoria", "ultimo_en": ult["creado_en"],
                          "visto": ult["autor"] == "cliente" and bool(ult.get("leido_en"))})
    hilos += portal_conversaciones.para_el_buzon(cliente)
    for h in hilos:
        h["espera_respuesta"] = h["ultimo_autor"] == "gestoria" and not h.get("cerrada")
    hilos.sort(key=lambda h: h["ultimo_en"], reverse=True)
    return hilos[:MAX_FILAS]
