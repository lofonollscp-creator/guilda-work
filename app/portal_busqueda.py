"""Buscar en el portal: una sola caja que mira las facturas, los modelos y sus documentos, los mensajes y los movimientos del banco del cliente y lleva a donde está cada cosa.

Solo busca lo que el cliente ya puede ver en su portal (nunca notas internas ni documentos internos del despacho). Sin tildes ni mayúsculas: «fernandez» encuentra «Fernández»."""
from __future__ import annotations

import re
import unicodedata

from . import db, facturas_contables as fc, verticales
from .vencimientos_fiscales import MODELOS_INTERNOS

MIN_LETRAS = 2
MAX_POR_GRUPO = 8
MAX_FILAS_REVISADAS = 400


def plano(texto: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", s).strip()


def _coincide(consulta: str, *campos) -> bool:
    texto = plano(" ".join(str(c) for c in campos if c))
    return all(palabra in texto for palabra in consulta.split())


def buscar(cliente, consulta: str) -> dict:
    """{consulta, grupos: [{clave, titulo, items: [{texto, detalle, url}]}], total}. Consultas de menos de 2 letras no buscan nada."""
    from flask import url_for
    from flask_babel import gettext as _
    q = plano(consulta)[:80]
    if len(q.replace(" ", "")) < MIN_LETRAS:
        return {"consulta": consulta.strip()[:80], "grupos": [], "total": 0, "corta": bool(q)}
    tid, cid = cliente["tenant_id"], cliente["id"]
    con_facturas = verticales.esta_activo(tid, "contabilizacion")
    grupos: list[dict] = []

    if con_facturas:
        items = []
        for f in fc.listar_del_cliente(cid, MAX_FILAS_REVISADAS):
            if _coincide(q, f["tercero_nombre"], f["numero"], f["fecha"], f"{f['total_centimos'] / 100:.2f}"):
                trimestre = fc.trimestre_de(f["fecha"])
                items.append({"texto": f"{f['tercero_nombre'] or _('(por leer)')} · {f['numero']}" if f["numero"] != "(por leer)" else (f["tercero_nombre"] or _("(por leer)")),
                              "detalle": f"{f['fecha']} · {f['total_centimos'] / 100:.2f} €", "url": url_for("portal_cliente.factura", factura_id=f["id"])})
        if items:
            grupos.append({"clave": "facturas", "titulo": _("Facturas"), "items": items})

    conn = db.get_connection()
    try:
        internos = sorted(MODELOS_INTERNOS)
        venc = conn.execute(f"SELECT id, modelo, periodo, fecha_limite, estado, documento_solicitado FROM vencimientos_fiscales WHERE tenant_id = ? AND cliente_fiscal_id = ? AND papelera_en IS NULL "
                            f"AND modelo NOT IN ({','.join('?' * len(internos))}) ORDER BY fecha_limite DESC LIMIT ?", (tid, cid, *internos, MAX_FILAS_REVISADAS)).fetchall()
        docs = conn.execute(f"SELECT d.id, d.vencimiento_id, d.nombre_archivo, v.modelo, v.periodo FROM vencimientos_fiscales_documentos d JOIN vencimientos_fiscales v ON v.id = d.vencimiento_id "
                            f"WHERE v.tenant_id = ? AND v.cliente_fiscal_id = ? AND v.papelera_en IS NULL AND d.origen NOT IN ({','.join('?' * len(db.ORIGENES_INTERNOS_DOCUMENTO_VENCIMIENTO))}) "
                            f"AND v.modelo NOT IN ({','.join('?' * len(internos))}) ORDER BY d.id DESC LIMIT ?", (tid, cid, *db.ORIGENES_INTERNOS_DOCUMENTO_VENCIMIENTO, *internos, MAX_FILAS_REVISADAS)).fetchall()
        msgs_v = conn.execute(f"SELECT m.vencimiento_id AS ref, m.texto, m.creado_en, v.modelo, v.periodo FROM vencimientos_fiscales_mensajes m JOIN vencimientos_fiscales v ON v.id = m.vencimiento_id "
                              f"WHERE v.tenant_id = ? AND v.cliente_fiscal_id = ? AND v.papelera_en IS NULL AND v.modelo NOT IN ({','.join('?' * len(internos))}) ORDER BY m.id DESC LIMIT ?",
                              (tid, cid, *internos, MAX_FILAS_REVISADAS)).fetchall()
        msgs_f = conn.execute("SELECT m.factura_id AS ref, m.texto, m.creado_en, x.tercero_nombre, x.numero FROM facturas_contables_mensajes m JOIN facturas_contables x ON x.id = m.factura_id AND x.tenant_id = m.tenant_id "
                              "WHERE m.tenant_id = ? AND x.cliente_fiscal_id = ? ORDER BY m.id DESC LIMIT ?", (tid, cid, MAX_FILAS_REVISADAS)).fetchall() if con_facturas else []
        movs = conn.execute("SELECT id, fecha, importe_centimos, concepto, estado FROM justificantes_pendientes WHERE tenant_id = ? AND cliente_fiscal_id = ? AND estado != 'descartado' ORDER BY fecha DESC, id DESC LIMIT ?",
                            (tid, cid, MAX_FILAS_REVISADAS)).fetchall() if con_facturas else []
    finally:
        conn.close()

    modelos = [{"texto": f"{v['modelo']} {v['periodo']}", "detalle": v["documento_solicitado"] or v["fecha_limite"][:10], "url": url_for("portal_cliente.impuestos") + f"#vencimiento-{v['id']}"}
               for v in venc if _coincide(q, v["modelo"], v["periodo"], v["documento_solicitado"], v["fecha_limite"][:10])]
    if modelos:
        grupos.append({"clave": "modelos", "titulo": _("Modelos e impuestos"), "items": modelos})
    archivos = [{"texto": d["nombre_archivo"], "detalle": f"{d['modelo']} {d['periodo']}", "url": url_for("portal_cliente.documentos_vencimiento", vencimiento_id=d["vencimiento_id"])} for d in docs if _coincide(q, d["nombre_archivo"])]
    if archivos:
        grupos.append({"clave": "documentos", "titulo": _("Documentos"), "items": archivos})
    mensajes = ([{"texto": m["texto"][:120], "detalle": f"{m['modelo']} {m['periodo']}", "url": url_for("portal_cliente.mensajes_vencimiento", vencimiento_id=m["ref"])} for m in msgs_v if _coincide(q, m["texto"])]
                + [{"texto": m["texto"][:120], "detalle": f"{m['tercero_nombre']} · {m['numero']}", "url": url_for("portal_cliente.factura", factura_id=m["ref"]) + "#mensajes"} for m in msgs_f if _coincide(q, m["texto"])])
    if mensajes:
        grupos.append({"clave": "mensajes", "titulo": _("Mensajes"), "items": mensajes})
    banco = [{"texto": m["concepto"], "detalle": f"{m['fecha']} · {m['importe_centimos'] / 100:.2f} €", "url": url_for("portal_cliente.justificantes_cliente") + f"#justificante-{m['id']}"} for m in movs if _coincide(q, m["concepto"], m["fecha"], f"{abs(m['importe_centimos']) / 100:.2f}")]
    if banco:
        grupos.append({"clave": "banco", "titulo": _("Movimientos del banco"), "items": banco})

    total = sum(len(g["items"]) for g in grupos)
    for g in grupos:
        g["mas"] = max(0, len(g["items"]) - MAX_POR_GRUPO)
        g["items"] = g["items"][:MAX_POR_GRUPO]
    return {"consulta": consulta.strip()[:80], "grupos": grupos, "total": total, "corta": False}
