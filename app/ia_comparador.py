"""Comparador de modelos (P7): ¿qué modelo lee mejor las facturas DE ESTE DESPACHO y a qué precio? En vez de fiarse de una tabla de otros, se prueban 2 o 3 modelos sobre una muestra de facturas
que una persona ya revisó (su valor final es la verdad) y se mide, por modelo y por dato, cuánto acierta, cuánto tarda y cuánto cuesta.

Se hace en la cola de fondo (app/ia_trabajos.py): un trabajo por factura de la muestra, que pasa por todos los modelos elegidos con la misma imagen. Siempre con el documento (nunca con el texto
del PDF) para que la comparación sea justa, y sin tocar las facturas: solo lee. Las consultas se anotan como «otras» en el uso de IA (no son lecturas reales) y no gastan el tope mensual."""
from __future__ import annotations

import json
import time

from . import db, facturas_contables as fc, ia_asistente, ia_trabajos, ia_uso, lectura_calidad, lectura_facturas as lf

TIPO = "comparacion"
MUESTRA_MAXIMA = 20
MODELOS_MAXIMOS = 4


def muestra_posible(tenant_id: int, usuario_id: int, n: int = 10) -> list[int]:
    """Las últimas `n` facturas leídas con IA y revisadas a mano (no las revisadas solas) con documento de imagen o PDF, que esta persona puede ver."""
    n = max(1, min(int(n), MUESTRA_MAXIMA))
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id FROM facturas_contables WHERE tenant_id = ? AND lectura = 'ia' AND estado IN ('revisada', 'exportada') AND revision_auto = 0 AND documento_id IS NOT NULL "
                             "ORDER BY id DESC LIMIT ?", (tenant_id, n * 3)).fetchall()
    finally:
        conn.close()
    return [f["id"] for f in filas if fc.obtener(tenant_id, usuario_id, f["id"]) is not None][:n]


def modelos_disponibles(usuario_id: int) -> list[dict]:
    """Los modelos que esta persona puede probar (los suyos y los del despacho para facturas), con un nombre legible."""
    salida = []
    for i, c in enumerate(ia_asistente.candidatos(usuario_id, "facturas")[:MODELOS_MAXIMOS]):
        salida.append({"indice": i, "proveedor": c["proveedor"], "modelo": c["modelo"], "origen": c["origen"], "nombre": f"{c['proveedor']} · {c['modelo']}"})
    return salida


def lanzar(tenant_id: int, usuario_id: int, n: int, indices: list[int]) -> tuple[str, int]:
    """Pone la comparación en la cola. `indices`: posiciones en `modelos_disponibles`. `ValueError` si hay menos de 2 modelos o ninguna factura de muestra."""
    disponibles = modelos_disponibles(usuario_id)
    elegidos = [disponibles[i] for i in dict.fromkeys(indices) if 0 <= i < len(disponibles)]
    if len(elegidos) < 2:
        raise ValueError("Elige al menos dos modelos para compararlos.")
    ids = muestra_posible(tenant_id, usuario_id, n)
    if not ids:
        raise ValueError("Todavía no hay facturas leídas con IA y revisadas a mano con las que comparar.")
    lote = ia_trabajos.encolar(tenant_id, usuario_id, TIPO, ids, datos={"modelos": [{"proveedor": m["proveedor"], "modelo": m["modelo"], "indice": m["indice"]} for m in elegidos]})
    return lote, len(ids)


def _leer_con(usuario_id: int, candidato: dict, doc: dict) -> tuple[dict, dict | None]:
    """(datos que devolvió el modelo, uso). Misma instrucción y mismas partes que la lectura real, con ese modelo y nada más."""
    payload = {"temperature": 0, "messages": [{"role": "system", "content": lf.PROMPT}, {"role": "user", "content": lf._partes(doc)}]}
    respuesta = ia_asistente._llamar(usuario_id, "otras", payload, 90, cands=[candidato])
    return lf._json_de((respuesta["choices"][0]["message"].get("content") or "").strip()), respuesta.get("usage")


def _valores_leidos(datos: dict, factura: dict) -> dict[str, str]:
    """Los siete datos que da el modelo, en la misma forma que `lectura_calidad.valores_de` los saca de la factura revisada."""
    contraparte = "receptor_nif" if factura["tipo"] == "emitida" else "emisor_nif"
    nombre = "receptor_nombre" if factura["tipo"] == "emitida" else "emisor_nombre"
    lineas = [l for l in (datos.get("lineas") if isinstance(datos.get("lineas"), list) else []) if isinstance(l, dict)]

    def centimos(v) -> str:
        try:
            return str(fc.importe_a_centimos(lf._num(v)))
        except ValueError:
            return ""
    try:
        fecha = fc._fecha(datos.get("fecha"), "fecha") if datos.get("fecha") else ""
    except ValueError:
        fecha = ""
    return {"numero": str(datos.get("numero") or "").strip().upper(), "fecha": fecha, "total": centimos(datos.get("total")), "nif": fc._nif(datos.get(contraparte)),
            "tercero": " ".join(str(datos.get(nombre) or "").split()).upper(), "base": str(sum(int(centimos(l.get("base")) or 0) for l in lineas)),
            "iva": str(sum(int(centimos(l.get("cuota_iva")) or 0) for l in lineas))}


def _trabajo(trabajo: dict) -> dict:
    """El trabajo «comparacion»: una factura de la muestra pasa por todos los modelos elegidos. Devuelve, por modelo, qué datos acertó, cuánto tardó y los tokens."""
    from . import almacen_documentos
    t, u, fid = trabajo["tenant_id"], trabajo["usuario_id"], trabajo["referencia"]
    f = fc.obtener(t, u, fid)
    if f is None:
        raise ValueError("La factura de la muestra ya no existe.")
    verdad = lectura_calidad.valores_de(f)
    doc = almacen_documentos.leer_de_cliente_fiscal(t, f["cliente_fiscal_id"], f["documento_id"], u)
    if doc is None:
        raise ValueError("No se encuentra el documento de la factura.")
    candidatos = ia_asistente.candidatos(u, "facturas")
    resultados = []
    for m in trabajo["datos"]["modelos"]:
        c = candidatos[m["indice"]] if m["indice"] < len(candidatos) and candidatos[m["indice"]]["proveedor"] == m["proveedor"] and candidatos[m["indice"]]["modelo"] == m["modelo"] else None
        if c is None:
            resultados.append({**m, "error": "El modelo ya no está disponible."})
            continue
        inicio = time.monotonic()
        try:
            datos, uso = _leer_con(u, c, doc)
        except Exception as e:  # noqa: BLE001 -- un modelo que falla no impide medir a los demás
            resultados.append({**m, "error": str(e)[:200], "segundos": round(time.monotonic() - inicio, 1)})
            continue
        leido = _valores_leidos(datos, f)
        coste = ia_uso.coste_estimado(c["proveedor"], c["modelo"], int((uso or {}).get("prompt_tokens") or 0), int((uso or {}).get("completion_tokens") or 0), uso)
        resultados.append({**m, "aciertos": {k: leido.get(k) == verdad[k] for k in lectura_calidad.CAMPOS}, "segundos": round(time.monotonic() - inicio, 1),
                           "tokens": int((uso or {}).get("prompt_tokens") or 0) + int((uso or {}).get("completion_tokens") or 0), "coste_usd": coste})
    return {"factura": fid, "resultados": resultados}


ia_trabajos.registrar_manejador(TIPO, _trabajo)


def resultado(tenant_id: int, lote: str) -> dict:
    """{progreso, modelos: [{nombre, facturas, errores, acierto_pct, campos: {campo: pct}, segundos_medios, coste_medio_usd, sin_tarifa}], mejor}: lo medido hasta ahora en un lote."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT resultado FROM ia_trabajos WHERE tenant_id = ? AND lote = ? AND tipo = ? AND estado = 'hecha'", (tenant_id, lote, TIPO)).fetchall()
    finally:
        conn.close()
    por_modelo: dict[str, dict] = {}
    for fila in filas:
        try:
            r = json.loads(fila["resultado"] or "{}")
        except ValueError:
            continue
        for m in r.get("resultados", []):
            d = por_modelo.setdefault(f"{m['proveedor']} · {m['modelo']}", {"nombre": f"{m['proveedor']} · {m['modelo']}", "facturas": 0, "errores": 0, "aciertos": {c: 0 for c in lectura_calidad.CAMPOS},
                                                                           "segundos": [], "costes": [], "sin_tarifa": 0})
            if m.get("error"):
                d["errores"] += 1
                continue
            d["facturas"] += 1
            for c, ok in m["aciertos"].items():
                d["aciertos"][c] += 1 if ok else 0
            d["segundos"].append(m["segundos"])
            if m.get("coste_usd") is None:
                d["sin_tarifa"] += 1
            else:
                d["costes"].append(m["coste_usd"])
    modelos = []
    for d in por_modelo.values():
        n = d["facturas"]
        campos = {c: round(100 * v / n) for c, v in d["aciertos"].items()} if n else {}
        modelos.append({"nombre": d["nombre"], "facturas": n, "errores": d["errores"], "campos": campos, "acierto_pct": round(sum(campos.values()) / len(campos)) if campos else None,
                        "segundos_medios": round(sum(d["segundos"]) / len(d["segundos"]), 1) if d["segundos"] else None,
                        "coste_medio_usd": round(sum(d["costes"]) / len(d["costes"]), 5) if d["costes"] else None, "sin_tarifa": d["sin_tarifa"]})
    modelos.sort(key=lambda m: (-(m["acierto_pct"] if m["acierto_pct"] is not None else -1), m["coste_medio_usd"] if m["coste_medio_usd"] is not None else 9e9))
    return {"progreso": ia_trabajos.progreso(tenant_id, lote), "modelos": modelos, "mejor": modelos[0]["nombre"] if modelos and modelos[0]["acierto_pct"] is not None else None}
