"""Facturas entre el despacho y el cliente: el despacho devuelve una factura con su motivo, el cliente la corrige o la da por vista desde el portal, y el cliente ve cómo va cada trimestre.

Sin tablas nuevas: «devuelta» es una factura `descartada` cuyo motivo está en la auditoría (`factura_contable.devuelta`); cuando el cliente la atiende (la vuelve a enviar o la da por vista) se anota
`factura_contable.devuelta_atendida` y deja de pedirle nada. Una descartada sin motivo sigue siendo lo que era: «el despacho te contactará»."""
from __future__ import annotations

import json
import re
from datetime import date

from . import auditoria, db, facturas_contables as fc

ACCION_DEVUELTA = "factura_contable.devuelta"
ACCION_ATENDIDA = "factura_contable.devuelta_atendida"
MAX_MOTIVO = 300
MAX_FILAS_TRIMESTRE = 200
MODELOS_DEL_TRIMESTRE = ("303", "130", "131", "115", "111")


# --- El despacho devuelve la factura ------------------------------------------------------------------------------------------------------------------

def devolver(tenant_id: int, usuario_id: int, factura_id: int, motivo: str) -> None:
    """Saca del circuito una factura que anotó el cliente y le dice por qué, para que la corrija o la vuelva a enviar. Solo las del portal, y mientras no estén exportadas."""
    motivo = re.sub(r"\s+", " ", motivo or "").strip()
    if not motivo:
        raise ValueError("Explica al cliente qué ha de corregir.")
    if len(motivo) > MAX_MOTIVO:
        raise ValueError(f"El motivo no puede pasar de {MAX_MOTIVO} caracteres.")
    f = fc.obtener(tenant_id, usuario_id, factura_id)
    if f is None:
        raise ValueError("Factura no encontrada.")
    if f["origen"] != "portal":
        raise ValueError("Solo se pueden devolver las facturas que ha enviado el cliente desde su portal.")
    if f["estado"] not in ("pendiente", "revisada"):
        raise ValueError("Solo se puede devolver una factura pendiente o revisada.")
    ahora = db.now_iso()
    conn = db.get_connection()
    try:
        notas = ((f.get("notas") or "") + f"\nDevuelta al cliente el {ahora[:10]}: {motivo}").strip()
        conn.execute("UPDATE facturas_contables SET estado = 'descartada', actualizado_en = ?, revisado_por = NULL, revisado_en = NULL, lote_id = NULL, notas = ? WHERE id = ? AND tenant_id = ?",
                     (ahora, notas, factura_id, tenant_id))
        auditoria.registrar(tenant_id, usuario_id, ACCION_DEVUELTA, "factura_contable", factura_id, {"motivo": motivo, "antes": f["estado"]}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def _eventos(conn, tenant_id: int, ids: list[int]) -> dict[int, dict]:
    """{factura_id: {motivo, en, atendida}} según el último evento de devolución de cada una."""
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    filas = conn.execute(f"SELECT id, entidad_id, accion, detalle, creado_en FROM auditoria_eventos WHERE tenant_id = ? AND entidad = 'factura_contable' AND accion IN (?, ?) "
                         f"AND entidad_id IN ({marcas}) ORDER BY id", (tenant_id, ACCION_DEVUELTA, ACCION_ATENDIDA, *[str(i) for i in ids])).fetchall()
    res: dict[int, dict] = {}
    for e in filas:
        fid = int(e["entidad_id"])
        if e["accion"] == ACCION_DEVUELTA:
            try:
                motivo = (json.loads(e["detalle"] or "{}") or {}).get("motivo") or ""
            except ValueError:
                motivo = ""
            res[fid] = {"motivo": motivo, "en": e["creado_en"][:10], "atendida": False}
        elif fid in res:
            res[fid]["atendida"] = True
    return res


# --- Lo que ve el cliente ---------------------------------------------------------------------------------------------------------------------------

def facturas_del_cliente(cliente_fiscal_id: int, limite: int = 500) -> list[dict]:
    """Las facturas del cliente con su trimestre y, si el despacho la devolvió, el motivo (`devuelta`) y si ya la atendió (`atendida`)."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        return []
    filas = fc.listar_del_cliente(cliente_fiscal_id, limite)
    conn = db.get_connection()
    try:
        eventos = _eventos(conn, cliente["tenant_id"], [f["id"] for f in filas if f["estado"] == "descartada"])
    finally:
        conn.close()
    for f in filas:
        f["trimestre"] = fc.trimestre_de(f["fecha"])
        ev = eventos.get(f["id"]) if f["estado"] == "descartada" else None
        f["devuelta"] = ev["motivo"] if ev else None
        f["devuelta_en"] = ev["en"] if ev else None
        f["atendida"] = bool(ev and ev["atendida"])
    return filas


def devueltas_sin_atender(cliente_fiscal_id: int) -> list[dict]:
    return [f for f in facturas_del_cliente(cliente_fiscal_id) if f["devuelta"] is not None and not f["atendida"]]


def _devuelta_del_cliente(cliente_fiscal_id: int, factura_id: int) -> dict:
    for f in devueltas_sin_atender(cliente_fiscal_id):
        if f["id"] == factura_id:
            return f
    raise ValueError("Esa factura ya no está pendiente de corregir.")


def _marcar_atendida(cliente: dict, factura_id: int, detalle: dict) -> None:
    auditoria.registrar(cliente["tenant_id"], None, ACCION_ATENDIDA, "factura_contable", factura_id, detalle)


def reenviar(cliente_fiscal_id: int, factura_id: int, archivos: list[tuple[str, str | None, bytes]]) -> list[int]:
    """El cliente sube de nuevo la factura devuelta (la foto o el PDF corregidos). Entra como una factura nueva por leer y la devuelta deja de pedirle nada."""
    previa = _devuelta_del_cliente(cliente_fiscal_id, factura_id)
    ids = fc.subir_desde_portal(cliente_fiscal_id, previa["tipo"], archivos, nota=f"Reenviada por el cliente tras devolverle la factura {previa['numero']}: {previa['devuelta']}"[:300])
    _marcar_atendida(db.obtener_cliente_fiscal_por_id(cliente_fiscal_id), factura_id, {"nueva": ids})
    return ids


def dar_por_vista(cliente_fiscal_id: int, factura_id: int) -> None:
    """El cliente ya ha leído el motivo y no tiene nada que reenviar (no era suya, la ha corregido por otro camino…)."""
    _devuelta_del_cliente(cliente_fiscal_id, factura_id)
    _marcar_atendida(db.obtener_cliente_fiscal_por_id(cliente_fiscal_id), factura_id, {"vista": True})


# --- El tablero del trimestre -----------------------------------------------------------------------------------------------------------------------

def _trimestre_de_periodo(periodo: str | None) -> str | None:
    return periodo if re.fullmatch(r"\d{4}-T[1-4]", periodo or "") else None


def trimestre_actual(hoy: date | None = None) -> str:
    return fc.trimestre_de((hoy or date.today()).isoformat())


def _trimestres_vecinos(base: str, antes: int = 4) -> list[str]:
    anio, t = int(base[:4]), int(base[-1])
    res = []
    for _ in range(antes + 1):
        res.append(f"{anio}-T{t}")
        t -= 1
        if t == 0:
            anio, t = anio - 1, 4
    return res


def etapas(filas: list[dict]) -> dict[str, int]:
    """Cuántas facturas hay en cada etapa para el cliente. Las devueltas ya atendidas no cuentan: el reenvío entró como otra factura."""
    c = {"total": 0, "en_revision": 0, "revisadas": 0, "contabilizadas": 0, "para_corregir": 0, "no_validas": 0}
    for f in filas:
        if f["estado"] == "descartada":
            if f["devuelta"] is not None and not f["atendida"]:
                c["para_corregir"] += 1
            elif f["devuelta"] is None:
                c["no_validas"] += 1
            continue
        c["total"] += 1
        c[{"pendiente": "en_revision", "revisada": "revisadas", "exportada": "contabilizadas"}[f["estado"]]] += 1
    c["total"] += c["para_corregir"]
    return c


def tablero(cliente_fiscal_id: int, trimestre: str | None = None, hoy: date | None = None) -> dict:
    """Todo lo que el cliente necesita saber de un trimestre: sus facturas, en qué etapa está cada una, si el trimestre está cerrado y qué modelos vencen con él.
    Sin trimestre pedido (o uno inválido) enseña el del próximo modelo por presentar y, si no hay, el actual."""
    cliente = db.obtener_cliente_fiscal_por_id(cliente_fiscal_id)
    if cliente is None:
        raise ValueError("Cliente no encontrado.")
    hoy = hoy or date.today()
    todas = facturas_del_cliente(cliente_fiscal_id)
    vencimientos = [v for v in db.listar_vencimientos_fiscales(cliente["tenant_id"], cliente_fiscal_id=cliente_fiscal_id, sin_internos=True)]
    pendientes = [v for v in vencimientos if v["estado"] != "presentado" and v["modelo"] in MODELOS_DEL_TRIMESTRE and _trimestre_de_periodo(v["periodo"])]
    proximo = min(pendientes, key=lambda v: v["fecha_limite"], default=None)
    try:
        fc.rango_del_trimestre(trimestre or "")
    except ValueError:
        trimestre = _trimestre_de_periodo(proximo["periodo"]) if proximo else trimestre_actual(hoy)
    disponibles = sorted({f["trimestre"] for f in todas} | set(_trimestres_vecinos(trimestre_actual(hoy), 3)) | {trimestre}, reverse=True)
    del_trimestre = [f for f in todas if f["trimestre"] == trimestre][:MAX_FILAS_TRIMESTRE]
    cuentas = etapas(del_trimestre)
    cierre = fc.periodos_cerrados(cliente["tenant_id"], cliente_fiscal_id, [trimestre]).get(trimestre)
    modelos = [{"id": v["id"], "modelo": v["modelo"], "fecha_limite": v["fecha_limite"], "presentado": v["estado"] == "presentado"} for v in vencimientos if v["periodo"] == trimestre and v["modelo"] in MODELOS_DEL_TRIMESTRE]
    modelos.sort(key=lambda m: (m["fecha_limite"], m["modelo"]))
    if cuentas["para_corregir"]:
        situacion = "corregir"
    elif cuentas["total"] == 0:
        situacion = "vacio"
    elif cuentas["en_revision"] or cuentas["revisadas"]:
        situacion = "revision"
    else:
        situacion = "al_dia"
    otras_devueltas: dict[str, int] = {}
    for f in todas:
        if f["trimestre"] != trimestre and f["devuelta"] is not None and not f["atendida"]:
            otras_devueltas[f["trimestre"]] = otras_devueltas.get(f["trimestre"], 0) + 1
    atendidas = cuentas["contabilizadas"] + cuentas["revisadas"]
    return {"trimestre": trimestre, "disponibles": disponibles, "facturas": del_trimestre, "cuentas": cuentas, "situacion": situacion, "cerrado": cierre, "modelos": modelos,
            "avance": atendidas, "otras_devueltas": dict(sorted(otras_devueltas.items(), reverse=True)), "hay_mas": len([f for f in todas if f["trimestre"] == trimestre]) > MAX_FILAS_TRIMESTRE}


def etiqueta_trimestre(trimestre: str) -> str:
    """«2026-T2» → «2T 2026»."""
    return f"{trimestre[-1]}T {trimestre[:4]}"


def para_el_inicio(cliente_fiscal_id: int) -> dict:
    """Lo mínimo que la portada del portal necesita de las facturas: cuántas debe corregir y cuántas esperan al despacho."""
    cuentas = etapas(facturas_del_cliente(cliente_fiscal_id))
    return {"para_corregir": cuentas["para_corregir"], "en_revision": cuentas["en_revision"]}

