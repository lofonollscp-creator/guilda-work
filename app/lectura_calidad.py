"""Calidad de la lectura de facturas (R9): ¿acierta la lectura? ¿qué corrigen las personas? ¿cuánto cuesta y cuánto se tarda?

La medida sale de comparar lo que LEYÓ el sistema (guardado en el momento de leer) con lo que la persona dio por bueno al revisar la factura. Cada dato corregido cuenta como un fallo de ese dato;
una factura revisada sin cambios, como acierto. Las revisadas solas por la IA no entran en la tasa de acierto (nadie las comprobó) pero se cuentan aparte. Todo se calcula con lo ya guardado: no
hace falta ninguna tabla nueva."""
from __future__ import annotations

import json
from datetime import datetime

from . import db, ia_uso

CAMPOS = ("numero", "fecha", "total", "nif", "tercero", "base", "iva")
ETIQUETAS = {"numero": "Número", "fecha": "Fecha", "total": "Total", "nif": "NIF", "tercero": "Proveedor/cliente", "base": "Base imponible", "iva": "Cuota de IVA"}


def tipos_de(f) -> list[str]:
    """A qué clases de documento pertenece una factura, para ver dónde falla más la lectura: abonos, tiquets (sin NIF), emitidas o recibidas, y quién la subió. Una factura cuenta en varias."""
    res = ["abono"] if f["abono"] else []
    if not (f["tercero_nif"] or "").strip():
        res.append("sin_nif")
    res.append("emitida" if f["tipo"] == "emitida" else "recibida")
    res.append("portal" if f["origen"] == "portal" else "despacho")
    return res


def valores_de(f: dict) -> dict[str, str]:
    """Los siete datos que se comparan, tal como están en la factura (importes en céntimos, para que «100,00» y «100.0» sean lo mismo)."""
    lineas = f.get("lineas") or []
    return {"numero": str(f.get("numero") or "").strip().upper(), "fecha": str(f.get("fecha") or "")[:10], "total": str(f.get("total_centimos") if f.get("total_centimos") is not None else ""),
            "nif": str(f.get("tercero_nif") or "").replace(" ", "").replace("-", "").upper(), "tercero": " ".join(str(f.get("tercero_nombre") or "").split()).upper(),
            "base": str(sum(l.get("base_centimos") or 0 for l in lineas)), "iva": str(sum(l.get("cuota_iva") or 0 for l in lineas))}


def guardar_lo_leido(conn, tenant_id: int, factura_id: int, f: dict) -> None:
    """Deja en `lectura_evidencia` lo que se leyó (para compararlo cuando alguien revise la factura)."""
    fila = conn.execute("SELECT lectura_evidencia FROM facturas_contables WHERE id = ? AND tenant_id = ?", (factura_id, tenant_id)).fetchone()
    try:
        e = json.loads(fila["lectura_evidencia"] or "{}") if fila else {}
    except ValueError:
        e = {}
    e["leido"] = valores_de(f)
    e.pop("correcciones", None)
    conn.execute("UPDATE facturas_contables SET lectura_evidencia = ? WHERE id = ? AND tenant_id = ?", (json.dumps(e, ensure_ascii=False), factura_id, tenant_id))


def anotar_correcciones(tenant_id: int, factura_id: int, f: dict) -> list[str]:
    """Al revisar una persona la factura: qué datos cambió respecto de lo leído. Devuelve los campos corregidos (vacío si dio por buena la lectura tal cual)."""
    conn = db.get_connection()
    try:
        fila = conn.execute("SELECT lectura_evidencia FROM facturas_contables WHERE id = ? AND tenant_id = ?", (factura_id, tenant_id)).fetchone()
        try:
            e = json.loads((fila["lectura_evidencia"] if fila else "") or "{}")
        except ValueError:
            return []
        leido = e.get("leido")
        if not isinstance(leido, dict):
            return []
        final = valores_de(f)
        cambiados = [c for c in CAMPOS if c in leido and leido[c] != final[c]]
        e["correcciones"] = {c: {"leido": leido[c], "final": final[c]} for c in cambiados}
        e["revisada_en"] = datetime.now().isoformat(timespec="seconds")
        conn.execute("UPDATE facturas_contables SET lectura_evidencia = ? WHERE id = ? AND tenant_id = ?", (json.dumps(e, ensure_ascii=False), factura_id, tenant_id))
        conn.commit()
        return cambiados
    finally:
        conn.close()


def resumen(tenant_id: int, desde: str | None = None, cliente_fiscal_id: int | None = None) -> dict:
    """{por_fuente: {fuente: {...}}, campos: {campo: {leidas, corregidas, pct_acierto}}, proveedores: [...], auto, pendientes_de_revisar, coste}. `desde`: fecha AAAA-MM-DD (por defecto, últimos 90 días)."""
    desde = desde or (datetime.now().date().replace(day=1)).isoformat()
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, estado, lectura, lectura_fuente, lectura_confianza, revision_auto, lectura_evidencia, tercero_nombre, tercero_nif, tipo, abono, origen, creado_en, revisado_en FROM facturas_contables "
                             "WHERE tenant_id = ? AND lectura IN ('ia', 'xml') AND creado_en >= ? AND estado != 'descartada'" + (" AND cliente_fiscal_id = ?" if cliente_fiscal_id else ""),
                             (tenant_id, desde, *([cliente_fiscal_id] if cliente_fiscal_id else []))).fetchall()
    finally:
        conn.close()
    por_fuente: dict[str, dict] = {}
    por_tipo: dict[str, dict] = {}
    campos = {c: {"revisadas": 0, "corregidas": 0} for c in CAMPOS}
    proveedores: dict[str, dict] = {}
    horas: list[float] = []
    auto = pendientes = 0
    for f in filas:
        fuente = f["lectura_fuente"] or ("xml" if f["lectura"] == "xml" else "imagen")
        d = por_fuente.setdefault(fuente, {"facturas": 0, "confianza_suma": 0, "con_confianza": 0, "revisadas": 0, "sin_correcciones": 0})
        grupos = [por_tipo.setdefault(k, {"facturas": 0, "confianza_suma": 0, "con_confianza": 0, "revisadas": 0, "sin_correcciones": 0}) for k in tipos_de(f)]
        for x in (d, *grupos):
            x["facturas"] += 1
            if f["lectura_confianza"] is not None:
                x["confianza_suma"] += f["lectura_confianza"]
                x["con_confianza"] += 1
        if f["revision_auto"]:
            auto += 1
            continue
        if f["estado"] == "pendiente":
            pendientes += 1
            continue
        try:
            e = json.loads(f["lectura_evidencia"] or "{}")
        except ValueError:
            continue
        correcciones = e.get("correcciones")
        if not isinstance(correcciones, dict) or not isinstance(e.get("leido"), dict):
            continue
        for x in (d, *grupos):
            x["revisadas"] += 1
            x["sin_correcciones"] += 0 if correcciones else 1
        for c in CAMPOS:
            if c in e["leido"]:
                campos[c]["revisadas"] += 1
                campos[c]["corregidas"] += 1 if c in correcciones else 0
        if correcciones:
            p = proveedores.setdefault((f["tercero_nombre"] or "?").strip(), {"nombre": (f["tercero_nombre"] or "?").strip(), "facturas": 0, "correcciones": 0})
            p["correcciones"] += len(correcciones)
        if f["revisado_en"] and f["creado_en"]:
            try:
                horas.append((datetime.fromisoformat(f["revisado_en"][:19]) - datetime.fromisoformat(f["creado_en"][:19])).total_seconds() / 3600)
            except ValueError:
                pass
    for f in filas:                                                                                # facturas por proveedor (para la tasa de correcciones)
        n = (f["tercero_nombre"] or "?").strip()
        if n in proveedores:
            proveedores[n]["facturas"] += 1
    for d in (*por_fuente.values(), *por_tipo.values()):
        d["confianza_media"] = round(d["confianza_suma"] / d["con_confianza"]) if d["con_confianza"] else None
        d["pct_sin_correcciones"] = round(100 * d["sin_correcciones"] / d["revisadas"]) if d["revisadas"] else None
    for c, d in campos.items():
        d["pct_acierto"] = round(100 * (d["revisadas"] - d["corregidas"]) / d["revisadas"]) if d["revisadas"] else None
    uso = ia_uso.resumen(tenant_id)
    facturas_uso = [x for x in uso["filas"] if x["tarea"] == "facturas"]
    llamadas, coste = sum(x["llamadas"] for x in facturas_uso), round(sum(x["coste_usd"] for x in facturas_uso), 4)
    return {"desde": desde, "total": len(filas), "por_fuente": por_fuente, "por_tipo": por_tipo, "campos": campos, "auto": auto, "pendientes_de_revisar": pendientes,
            "proveedores": sorted(proveedores.values(), key=lambda p: -p["correcciones"])[:10], "horas_hasta_revisar": round(sorted(horas)[len(horas) // 2], 1) if horas else None,
            "coste_usd": coste, "llamadas": llamadas, "coste_por_factura": round(coste / llamadas, 4) if llamadas else None, "sin_tarifa": uso["hay_sin_tarifa"]}
