"""Actividad del portal para el despacho: qué clientes entran, a cuáles se les manda avisos que no abren y cuánto tardan en contestar lo que se les pide. Sirve para decidir a quién llamar.

Solo cuenta con lo que ya existe (entradas al portal, avisos de seguimiento enviados, peticiones y respuestas): nada de seguimiento del navegador. Un cliente «ignora los avisos» si tiene algo pendiente, se le ha recordado y no ha entrado en 14 días."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import acceso, db, verticales

DIAS_SIN_ENTRAR = 14
VENTANA_DIAS = 30
VENTANA_RESPUESTAS_DIAS = 180


def _dias_entre(desde: str | None, hasta: str | None) -> float | None:
    try:
        return (datetime.fromisoformat(hasta[:19]) - datetime.fromisoformat(desde[:19])).total_seconds() / 86400
    except (TypeError, ValueError):
        return None


def filas(tenant_id: int, usuario_id: int, ahora: datetime | None = None) -> list[dict]:
    """Una fila por cliente con acceso al portal (que la persona puede ver): última entrada, entradas y avisos en 30 días, lo pendiente, el tiempo medio de respuesta y si ignora los avisos."""
    ahora = ahora or datetime.now()
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)                    # None = todos
    desde_30 = (ahora - timedelta(days=VENTANA_DIAS)).isoformat(timespec="seconds")
    desde_resp = (ahora - timedelta(days=VENTANA_RESPUESTAS_DIAS)).isoformat(timespec="seconds")
    conn = db.get_connection()
    try:
        clientes = [dict(c) for c in conn.execute("SELECT id, nombre, email FROM clientes_fiscales WHERE tenant_id = ? AND papelera_en IS NULL ORDER BY nombre", (tenant_id,)) if visibles is None or c["id"] in visibles]
        con_acceso = {c["id"] for c in clientes if (c["email"] or "").strip()}
        con_acceso |= {f["cliente_fiscal_id"] for f in conn.execute("SELECT DISTINCT cliente_fiscal_id FROM portal_contactos WHERE tenant_id = ? AND baja_en IS NULL", (tenant_id,))}
        entradas: dict[int, list[str]] = {}
        for e in conn.execute("SELECT entidad_id, creado_en FROM auditoria_eventos WHERE tenant_id = ? AND accion = 'portal.entrada' AND entidad = 'cliente_fiscal' AND creado_en >= ? ORDER BY id", (tenant_id, desde_resp)):
            entradas.setdefault(int(e["entidad_id"]), []).append(e["creado_en"])
        avisos = {f["cliente_fiscal_id"]: f["n"] for f in conn.execute(
            "SELECT cliente_fiscal_id, COUNT(*) AS n FROM portal_avisos_enviados WHERE tenant_id = ? AND destinatario != '' AND enviado_en >= ? GROUP BY cliente_fiscal_id", (tenant_id, desde_30))}
        con_fiscal = verticales.esta_activo(tenant_id, "fiscal")
        con_facturas = verticales.esta_activo(tenant_id, "contabilizacion")
        justificantes = conn.execute("SELECT cliente_fiscal_id, estado, creado_en, respondido_en FROM justificantes_pendientes WHERE tenant_id = ? AND creado_en >= ?", (tenant_id, desde_resp)).fetchall() if con_facturas else []
        firmas = {f["cliente_fiscal_id"]: f["n"] for f in conn.execute(
            "SELECT cliente_fiscal_id, COUNT(*) AS n FROM vencimientos_fiscales WHERE tenant_id = ? AND papelera_en IS NULL AND documenso_documento_id IS NOT NULL AND documenso_firmado_en IS NULL GROUP BY cliente_fiscal_id", (tenant_id,))}
        devueltas = {}
        if con_facturas:
            from . import facturas_portal
            for c in clientes:
                if c["id"] in con_acceso:
                    devueltas[c["id"]] = len(facturas_portal.devueltas_sin_atender(c["id"]))
    finally:
        conn.close()
    conformidades: dict[int, list[dict]] = {}
    tiempos: dict[int, list[float]] = {}
    if con_fiscal:
        from . import conformidad_declaracion
        for c in clientes:
            if c["id"] in con_acceso:
                conformidades[c["id"]] = conformidad_declaracion.pendientes_del_cliente(c["id"])
        conn = db.get_connection()
        try:
            declaraciones = {str(f["id"]): f["cliente_fiscal_id"] for f in conn.execute("SELECT id, cliente_fiscal_id FROM fiscal_declaraciones WHERE tenant_id = ? AND modelo = '303'", (tenant_id,))}
            pedidas: dict[str, str] = {}
            for e in conn.execute("SELECT entidad_id, accion, creado_en FROM auditoria_eventos WHERE tenant_id = ? AND entidad = 'fiscal_declaracion' AND accion IN ('fiscal.conformidad.pedida', 'fiscal.conformidad.respuesta') "
                                  "AND creado_en >= ? ORDER BY id", (tenant_id, desde_resp)):
                if e["accion"] == "fiscal.conformidad.pedida":
                    pedidas[e["entidad_id"]] = e["creado_en"]
                elif e["entidad_id"] in pedidas and e["entidad_id"] in declaraciones:
                    d = _dias_entre(pedidas.pop(e["entidad_id"]), e["creado_en"])
                    if d is not None:
                        tiempos.setdefault(declaraciones[e["entidad_id"]], []).append(d)
        finally:
            conn.close()
    sin_explicar: dict[int, int] = {}
    for j in justificantes:
        if j["estado"] == "pendiente":
            sin_explicar[j["cliente_fiscal_id"]] = sin_explicar.get(j["cliente_fiscal_id"], 0) + 1
        elif j["respondido_en"]:
            d = _dias_entre(j["creado_en"], j["respondido_en"])
            if d is not None:
                tiempos.setdefault(j["cliente_fiscal_id"], []).append(d)
    salida = []
    corte = (ahora - timedelta(days=DIAS_SIN_ENTRAR)).isoformat(timespec="seconds")
    for c in clientes:
        if c["id"] not in con_acceso:
            continue
        e = entradas.get(c["id"], [])
        pendientes = len(conformidades.get(c["id"], [])) + sin_explicar.get(c["id"], 0) + firmas.get(c["id"], 0) + devueltas.get(c["id"], 0)
        ultima = e[-1] if e else None
        recientes = [x for x in e if x >= desde_30]
        t = tiempos.get(c["id"], [])
        salida.append({"id": c["id"], "nombre": c["nombre"], "ultima_entrada": ultima, "entradas_30": len(recientes), "avisos_30": avisos.get(c["id"], 0), "pendientes": pendientes,
                       "respuesta_media_dias": round(sum(t) / len(t), 1) if t else None, "respuestas": len(t),
                       "ignora": pendientes > 0 and avisos.get(c["id"], 0) > 0 and (ultima is None or ultima < corte), "nunca": ultima is None})
    salida.sort(key=lambda f: (not f["ignora"], f["ultima_entrada"] or "", f["nombre"].lower()))
    return salida
