"""Guilda Fiscal · panel de vencimientos y recordatorios a los clientes: lo que falta de cada declaración trimestral (apuntes sin revisar, facturas por registrar, estado de la declaración) y los avisos
que se sugieren y se envían con confirmación. Lee del núcleo (`fiscal_nucleo`); nada aquí escribe apuntes ni declaraciones."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from . import acceso, auditoria, db
from .fiscal_nucleo import contadores_facturas, motor_303_en_periodo
from .fiscal_perfiles import ErrorFiscal


def _periodo_de_vencimiento(texto: str) -> tuple[int, str] | None:
    """«2T 2026» o «2026-T2» -> (2026, «2T»); los demás formatos (anual, mensual) no corresponden a una declaración trimestral del 303."""
    m = re.fullmatch(r"([1-4])T (\d{4})", texto or "") or None
    if m:
        return int(m.group(2)), f"{m.group(1)}T"
    m = re.fullmatch(r"(\d{4})-T([1-4])", texto or "")
    return (int(m.group(1)), f"{m.group(2)}T") if m else None


MODELOS_CON_APUNTES = ("303", "130", "131")                                                              # los modelos trimestrales que se calculan con los apuntes del trimestre
PESO_DECLARACION = {None: 3, "borrador": 2, "revisada": 1, "exportada": 1, "presentada": 0}          # lo que falta de un 303 según el estado de su declaración


def panel_vencimientos(tenant_id: int, usuario_id: int, *, dias: int = 60, hoy: date | None = None) -> dict:
    """Vencimientos pendientes de los titulares que la persona ve, con la carga de trabajo que cada uno lleva detrás. La carga se mide en «puntos de trabajo», no en horas: 1 por vencimiento, más 1 por
    cada factura aún sin revisar o sin registrar (en los modelos de IVA) y lo que falta de la declaración del 303 (3 sin crear, 2 en borrador, 1 revisada o exportada). Los vencidos van primero; se agrupan por
    semana (lunes) y por responsable. Devuelve `{"filas", "semanas", "responsables", "vencidos"}`."""
    hoy = hoy or date.today()
    limite = (hoy + timedelta(days=dias)).isoformat()
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    facturas = contadores_facturas(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute(
            "SELECT v.id, v.cliente_fiscal_id, v.modelo, v.periodo, v.fecha_limite, v.usuario_id AS responsable_id, c.nombre AS cliente, u.email AS responsable_email "
            "FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id AND c.tenant_id = v.tenant_id LEFT JOIN usuarios u ON u.id = v.usuario_id "
            "WHERE v.tenant_id = ? AND v.estado <> 'presentado' AND v.papelera_en IS NULL AND c.papelera_en IS NULL AND substr(v.fecha_limite, 1, 10) <= ? ORDER BY v.fecha_limite, c.nombre",
            (tenant_id, limite)).fetchall()]
        estado_decl = {(f["cliente_fiscal_id"], f["ejercicio"], f["periodo"]): (f["estado"], f["id"]) for f in conn.execute(
            "SELECT id, cliente_fiscal_id, ejercicio, periodo, estado FROM fiscal_declaraciones WHERE tenant_id = ? AND modelo = '303' AND estado <> 'anulada' ORDER BY id", (tenant_id,)).fetchall()}
        periodos = [_periodo_de_vencimiento(f["periodo"]) for f in filas]
        desde = min([date(e, int(t[0]) * 3 - 2, 1) for e, t in (p for p in periodos if p)], default=None)
        meses = {}
        if desde:                                                                                       # apuntes vivos por titular y mes: el aviso «sin apuntes» sale de aquí
            for f in conn.execute("SELECT cliente_fiscal_id, substr(fecha_expedicion, 1, 7) AS mes, COUNT(*) AS n FROM fiscal_apuntes WHERE tenant_id = ? AND anulado_en IS NULL AND fecha_expedicion >= ? "
                                  "GROUP BY cliente_fiscal_id, substr(fecha_expedicion, 1, 7)", (tenant_id, desde.isoformat())).fetchall():
                meses[(f["cliente_fiscal_id"], f["mes"])] = f["n"]
    finally:
        conn.close()
    salida, semanas, responsables = [], {}, {}
    for f in filas:
        if visibles is not None and f["cliente_fiscal_id"] not in visibles:
            continue
        dia = date.fromisoformat(f["fecha_limite"][:10])
        f["dias"] = (dia - hoy).days
        f["nivel"] = "vencido" if f["dias"] < 0 else ("semana" if f["dias"] <= 7 else "proximo")
        pend = facturas.get(f["cliente_fiscal_id"], {"sin_revisar": 0, "por_registrar": 0}) if f["modelo"] in ("303", "390") else {"sin_revisar": 0, "por_registrar": 0}
        trimestral = _periodo_de_vencimiento(f["periodo"]) if f["modelo"] in MODELOS_CON_APUNTES else None
        per = trimestral if f["modelo"] == "303" else None
        f["ejercicio"], f["trimestre"] = trimestral if trimestral else (None, None)
        f["declaracion"], f["declaracion_id"] = estado_decl.get((f["cliente_fiscal_id"], *per), (None, None)) if per else (None, None)
        f["apuntes"] = sum(meses.get((f["cliente_fiscal_id"], f"{trimestral[0]}-{m:02d}"), 0) for m in range(int(trimestral[1][0]) * 3 - 2, int(trimestral[1][0]) * 3 + 1)) if trimestral else None
        f["sin_apuntes"] = f["apuntes"] == 0                                                           # el trimestre no tiene ningún apunte: o falta trabajo o no hubo actividad (la persona lo decide)
        f["sin_revisar"], f["por_registrar"] = pend["sin_revisar"], pend["por_registrar"]
        f["carga"] = 1 + pend["sin_revisar"] + pend["por_registrar"] + (PESO_DECLARACION.get(f["declaracion"], 1) if per else 0)
        f["responsable"] = (f.pop("responsable_email") or "").split("@")[0]
        lunes = dia - timedelta(days=dia.weekday()) if f["dias"] >= 0 else None
        f["semana"] = lunes.isoformat() if lunes else None
        clave_semana = f["semana"] or "vencidos"
        s = semanas.setdefault(clave_semana, {"inicio": f["semana"], "vencimientos": 0, "carga": 0})
        s["vencimientos"] += 1
        s["carga"] += f["carga"]
        r = responsables.setdefault(f["responsable"] or "", {"responsable": f["responsable"], "vencimientos": 0, "carga": 0})
        r["vencimientos"] += 1
        r["carga"] += f["carga"]
        salida.append(f)
    orden_semanas = sorted(semanas.values(), key=lambda s: s["inicio"] or "")
    return {"filas": salida, "semanas": orden_semanas, "responsables": sorted(responsables.values(), key=lambda r: -r["carga"]), "vencidos": sum(1 for f in salida if f["nivel"] == "vencido"),
            "carga_maxima": max([s["carga"] for s in orden_semanas] + [1])}


def _pendiente_de_recordar_lote(tenant_id: int, pares: set[tuple[int, int, str]]) -> dict[tuple[int, int, str], dict]:
    """Lo mismo que `pendiente_de_recordar` para muchos `(titular, ejercicio, trimestre)` a la vez, con una consulta de apuntes y otra de facturas en vez de varias por titular. Sin comprobar acceso: quien llama
    ya ha filtrado los titulares visibles. `fecha_limite` queda en None (la rellena quien conoce el vencimiento)."""
    if not pares:
        return {}
    desde, hasta = str(min(e for _, e, _ in pares)), str(max(e for _, e, _ in pares))
    conn = db.get_connection()
    try:
        apuntes: dict[tuple[int, str, str], int] = {}                                                  # (titular, libro, AAAA-MM) -> cuántos
        for f in conn.execute("SELECT cliente_fiscal_id, libro, substr(fecha_expedicion, 1, 7) AS mes, COUNT(*) AS n FROM fiscal_apuntes WHERE tenant_id = ? AND anulado_en IS NULL "
                              "AND substr(fecha_expedicion, 1, 4) BETWEEN ? AND ? GROUP BY cliente_fiscal_id, libro, substr(fecha_expedicion, 1, 7)", (tenant_id, desde, hasta)).fetchall():
            apuntes[(f["cliente_fiscal_id"], f["libro"], f["mes"])] = f["n"]
        sin_apunte = ("f.tenant_id = ? AND f.estado IN ('revisada', 'exportada') AND f.incluir_en_fiscal = 1 AND substr(f.fecha, 1, 4) BETWEEN ? AND ? "
                      "AND f.id NOT IN (SELECT factura_id FROM fiscal_apuntes WHERE tenant_id = ? AND factura_id IS NOT NULL AND anulado_en IS NULL)")
        facturas: dict[tuple[int, str], list[dict]] = {}                                                # (titular, ejercicio) -> facturas revisadas sin apunte
        for f in conn.execute("SELECT f.id, f.cliente_fiscal_id, f.tipo, f.fecha, f.numero, f.tercero_nombre, f.total_centimos, f.abono FROM facturas_contables f WHERE " + sin_apunte + " ORDER BY f.fecha, f.id",
                              (tenant_id, desde, hasta, tenant_id)).fetchall():
            facturas.setdefault((f["cliente_fiscal_id"], f["fecha"][:4]), []).append(dict(f))
        lineas: dict[int, list] = {}
        if facturas:
            for l in conn.execute("SELECT l.factura_id, l.pct_iva, l.pct_recargo, l.sujeta_iva FROM facturas_contables_lineas l JOIN facturas_contables f ON f.id = l.factura_id WHERE " + sin_apunte,
                                  (tenant_id, desde, hasta, tenant_id)).fetchall():
                lineas.setdefault(l["factura_id"], []).append(l)
    finally:
        conn.close()
    salida = {}
    for cliente, ejercicio, periodo in pares:
        meses = [f"{ejercicio}-{m:02d}" for m in range(int(periodo[0]) * 3 - 2, int(periodo[0]) * 3 + 1)]
        sin_registrar = []
        for f in facturas.get((cliente, str(ejercicio)), []):
            if motor_303_en_periodo(f["fecha"], ejercicio, periodo):
                ls = lineas.get(f["id"], [])
                sin_registrar.append({**f, "automatica": bool(ls) and all(l["sujeta_iva"] and l["pct_iva"] in (400, 1000, 2100) and not l["pct_recargo"] for l in ls)})
        salida[(cliente, ejercicio, periodo)] = {"emitidas": sum(apuntes.get((cliente, "E", m), 0) for m in meses), "recibidas": sum(apuntes.get((cliente, "R", m), 0) for m in meses),
                                                 "sin_registrar": sin_registrar, "fecha_limite": None}
    return salida


def recordatorios_sugeridos(tenant_id: int, usuario_id: int, *, dias: int = 21, hoy: date | None = None) -> list[dict]:
    """Los clientes a quienes conviene recordar ya lo que falta para su 303: el vencimiento está pendiente y cae en los próximos `dias` días (o ya pasó), y aún faltan facturas (por registrar, o ningún libro).
    Solo propone: no escribe a nadie. `puede` = tiene email y no se le ha escrito por este periodo en los últimos `DIAS_ENTRE_RECORDATORIOS` días (los mismos que los recordatorios de facturas)."""
    from . import facturas_contables as fc
    hoy = hoy or date.today()
    limite = (hoy + timedelta(days=dias)).isoformat()
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)
    conn = db.get_connection()
    try:
        venc = [dict(f) for f in conn.execute(
            "SELECT v.cliente_fiscal_id, v.periodo, v.fecha_limite, c.nombre, c.email FROM vencimientos_fiscales v JOIN clientes_fiscales c ON c.id = v.cliente_fiscal_id AND c.tenant_id = v.tenant_id "
            "WHERE v.tenant_id = ? AND v.modelo = '303' AND v.estado <> 'presentado' AND v.papelera_en IS NULL AND c.papelera_en IS NULL AND substr(v.fecha_limite, 1, 10) <= ? "
            "ORDER BY v.fecha_limite, c.nombre", (tenant_id, limite)).fetchall()]
        ultimos = {(f["cliente_fiscal_id"], f["trimestre"]): f["ultimo"] for f in conn.execute(
            "SELECT cliente_fiscal_id, trimestre, MAX(enviado_en) AS ultimo FROM contabilidad_recordatorios WHERE tenant_id = ? GROUP BY cliente_fiscal_id, trimestre", (tenant_id,)).fetchall()}
    finally:
        conn.close()
    desde = (datetime.now() - timedelta(days=fc.DIAS_ENTRE_RECORDATORIOS)).isoformat(timespec="seconds")
    salida = []
    venc = [v for v in venc if _periodo_de_vencimiento(v["periodo"]) and (visibles is None or v["cliente_fiscal_id"] in visibles)]
    lote = _pendiente_de_recordar_lote(tenant_id, {(v["cliente_fiscal_id"], *_periodo_de_vencimiento(v["periodo"])) for v in venc})
    for v in venc:
        per = _periodo_de_vencimiento(v["periodo"])
        p = lote[(v["cliente_fiscal_id"], *per)]
        p["fecha_limite"] = v["fecha_limite"][:10]
        if not (p["sin_registrar"] or not p["emitidas"] or not p["recibidas"]):
            continue
        clave = f"{per[0]}-T{per[1][0]}"
        ultimo = ultimos.get((v["cliente_fiscal_id"], clave))
        email = (v["email"] or "").strip()
        salida.append({"cliente_id": v["cliente_fiscal_id"], "nombre": v["nombre"], "email": email, "ejercicio": per[0], "trimestre": per[1], "clave": clave, "fecha_limite": v["fecha_limite"][:10],
                       "dias": (date.fromisoformat(v["fecha_limite"][:10]) - hoy).days, "pendiente": p, "ultimo": ultimo, "reciente": bool(ultimo and ultimo > desde),
                       "puede": bool(email) and not (ultimo and ultimo > desde)})
    return salida


def enviar_recordatorios(tenant_id: int, usuario_id: int, envios: list[dict], url_portal: str, *, dias: int = 21) -> dict:
    """Envía los recordatorios CONFIRMADOS: cada envío es `{cliente_id, ejercicio, trimestre, asunto, texto}` con el texto que la persona ha revisado. Solo se escribe a quien sigue siendo una sugerencia válida
    (visible, con email, sin recordatorio reciente): el destinatario sale siempre de la ficha, nunca de lo enviado. Devuelve `{enviados, omitidos: [(nombre, motivo)]}`."""
    from . import facturas_contables as fc, notificaciones_email as ne, portal_avisos, portal_recordatorios
    if not ne.configurado():
        raise ErrorFiscal("El correo saliente de la plataforma no está configurado: no se puede avisar a los clientes.")
    validas = {(s["cliente_id"], s["ejercicio"], s["trimestre"]): s for s in recordatorios_sugeridos(tenant_id, usuario_id, dias=dias)}
    enviados, omitidos = 0, []
    for e in envios:
        s = validas.get((int(e["cliente_id"]), int(e["ejercicio"]), e["trimestre"]))
        asunto, texto = (e.get("asunto") or "").strip()[:200], (e.get("texto") or "").strip()[:4000]
        if s is None:
            omitidos.append((f"#{e['cliente_id']}", "ya no es una sugerencia válida"))
        elif not s["email"]:
            omitidos.append((s["nombre"], "no tiene email"))
        elif s["reciente"]:
            omitidos.append((s["nombre"], f"ya se le recordó hace menos de {fc.DIAS_ENTRE_RECORDATORIOS} días"))
        elif not asunto or not texto:
            omitidos.append((s["nombre"], "falta el asunto o el texto"))
        else:
            ficha = db.obtener_cliente_fiscal(tenant_id, s["cliente_id"])
            enlace = portal_recordatorios.con_destino(url_portal, "/portal/facturas" + (f"?trimestre={s['clave']}" if re.fullmatch(r"\d{4}-T[1-4]", str(s.get("clave") or "")) else ""), s["cliente_id"])
            fallos: list[str] = []
            if portal_avisos.correo_directo(ficha, lambda e: ne.enviar_recordatorio_fiscal(e, asunto, texto, enlace, tenant_id=tenant_id), urgente=True, accion="subir", errores=fallos) == 0:
                omitidos.append((s["nombre"], fallos[0] if fallos else "nadie con acceso quiere recibir este aviso"))
                continue
            conn = db.get_connection()
            try:
                conn.execute("INSERT INTO contabilidad_recordatorios (tenant_id, cliente_fiscal_id, trimestre, enviado_por, enviado_en) VALUES (?, ?, ?, ?, ?)",
                             (tenant_id, s["cliente_id"], s["clave"], usuario_id, db.now_iso()))
                auditoria.registrar(tenant_id, usuario_id, "fiscal.recordatorio.enviar", "cliente_fiscal", s["cliente_id"], {"periodo": s["clave"], "asunto": asunto}, conn=conn)
                conn.commit()
            finally:
                conn.close()
            enviados += 1
    return {"enviados": enviados, "omitidos": omitidos}
