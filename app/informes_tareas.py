"""Informes de tareas (Fase 5 de docs/guilda-work-implementation-plan.md): abiertas, vencidas y completadas por persona y por cliente, tasa de cumplimiento en plazo, tiempo medio
de cierre, bloqueos con su antigüedad y lo que se acerca.

Reglas para que los números se puedan defender:
- **Alcance**: solo las tareas que la persona puede ver (suyas, asignadas a ella o compartidas con ella), como la carga del equipo: un informe nunca revela tareas privadas de otros,
  tampoco a la dirección.
- **Ventana explícita** (`desde`–`hasta`, ambos días incluidos, máximo 366): lo «histórico» (creadas, completadas, en plazo, tiempo de cierre) se mide dentro de la ventana; lo «ahora»
  (abiertas, vencidas, bloqueadas, próximas) es la foto de hoy y no depende de la ventana. Cada cifra dice de cuál de las dos es.
- **Denominadores a la vista**: la tasa en plazo es «completadas en la ventana que tenían fecha de vencimiento» dividida entre «las que la tenían»; si no hay ninguna, no hay tasa
  (no un 0 % ni un 100 % inventados). Se compara el día, igual que `tareas_trabajo.esta_vencida`.
- **Varios clientes**: una tarea vinculada a dos clientes cuenta en ambos; por eso las filas por cliente pueden sumar más que el total (el total no se duplica).
- Los clientes que la persona no puede ver (otra oficina) no aparecen en el desglose por cliente."""
from __future__ import annotations

from datetime import date, timedelta

from . import acceso, db, tareas_trabajo

MAX_DIAS_VENTANA = 366
LIMITE_TAREAS = 50000


def ventana(desde: str | None, hasta: str | None, hoy: date | None = None) -> tuple[date, date]:
    """(desde, hasta) como fechas. Por defecto, los últimos 30 días hasta hoy. ValueError si no tienen sentido."""
    hoy = hoy or date.today()
    try:
        fin = date.fromisoformat(hasta[:10]) if hasta else hoy
        ini = date.fromisoformat(desde[:10]) if desde else fin - timedelta(days=29)
    except (TypeError, ValueError):
        raise ValueError("Las fechas tienen que ser AAAA-MM-DD.") from None
    if ini > fin:
        raise ValueError("La fecha de inicio no puede ser posterior a la de fin.")
    if (fin - ini).days + 1 > MAX_DIAS_VENTANA:
        raise ValueError(f"La ventana admite como máximo {MAX_DIAS_VENTANA} días.")
    return ini, fin


def _dia(texto: str | None) -> date | None:
    try:
        return date.fromisoformat(texto[:10]) if texto else None
    except ValueError:
        return None


def _porcentaje(num: int, den: int) -> float | None:
    return round(100 * num / den, 1) if den else None


def _tareas_visibles(usuario_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute(
            """SELECT t.id, t.asunto, t.estado, t.prioridad, t.fecha_vencimiento, t.creada_en, t.fecha_completada, t.usuario_id, t.asignada_a, t.cliente_fiscal_id,
                      t.motivo_bloqueo, t.actualizada_en
               FROM tareas_outlook t
               WHERE t.papelera_en IS NULL AND (t.usuario_id = ? OR t.asignada_a = ? OR t.id IN (SELECT tarea_id FROM tareas_participantes_todos WHERE usuario_id = ?))
               LIMIT ?""", (usuario_id, usuario_id, usuario_id, LIMITE_TAREAS)).fetchall()
        tareas = [dict(f) for f in filas]
        vinculos: dict[int, list[int]] = {}
        for i in range(0, len(tareas), 500):
            ids = [t["id"] for t in tareas[i:i + 500]]
            for v in conn.execute(f"SELECT tarea_id, cliente_fiscal_id FROM tarea_clientes WHERE tarea_id IN ({','.join('?' * len(ids))})", ids):
                vinculos.setdefault(v["tarea_id"], []).append(v["cliente_fiscal_id"])
        for t in tareas:
            t["clientes"] = vinculos.get(t["id"]) or ([t["cliente_fiscal_id"]] if t["cliente_fiscal_id"] else [])
        return tareas
    finally:
        conn.close()


def _bloqueada_desde(tarea_ids: list[int]) -> dict[int, str]:
    """Cuándo entró cada tarea en «esperando»: el último cambio de estado a ese valor del historial."""
    if not tarea_ids:
        return {}
    conn = db.get_connection()
    try:
        out: dict[int, str] = {}
        for i in range(0, len(tarea_ids), 500):
            ids = tarea_ids[i:i + 500]
            for f in conn.execute(f"SELECT tarea_id, MAX(creado_en) AS desde FROM tarea_actividad WHERE tarea_id IN ({','.join('?' * len(ids))}) "
                                  "AND ((tipo = 'estado' AND detalle = 'esperando') OR tipo = 'bloqueada') GROUP BY tarea_id", ids):
                out[f["tarea_id"]] = f["desde"]
        return out
    finally:
        conn.close()


def _fila_vacia() -> dict:
    return {"abiertas": 0, "vencidas": 0, "completadas": 0, "con_fecha": 0, "en_plazo": 0}


def _sumar(fila: dict, abierta: bool, vencida: bool, completada_en_ventana: bool, con_fecha: bool, en_plazo: bool) -> None:
    fila["abiertas"] += abierta
    fila["vencidas"] += vencida
    fila["completadas"] += completada_en_ventana
    fila["con_fecha"] += completada_en_ventana and con_fecha
    fila["en_plazo"] += completada_en_ventana and con_fecha and en_plazo


def _con_tasa(fila: dict) -> dict:
    return {**fila, "tasa_en_plazo": _porcentaje(fila["en_plazo"], fila["con_fecha"])}


def calcular(tareas: list[dict], desde: date, hasta: date, hoy: date, bloqueadas_desde: dict[int, str] | None = None) -> dict:
    """La parte pura (sin base de datos), para poder probar las cifras con casos pequeños."""
    bloqueadas_desde = bloqueadas_desde or {}
    total = _fila_vacia()
    por_resp: dict[int, dict] = {}
    por_cli: dict[int | None, dict] = {}
    creadas = 0
    cierres: list[int] = []
    bloqueadas = []
    for t in tareas:
        completada = t["estado"] == "completada"
        fin = _dia(t["fecha_completada"]) if completada else None
        en_ventana = completada and fin is not None and desde <= fin <= hasta
        abierta = not completada
        vencida = tareas_trabajo.esta_vencida(t["fecha_vencimiento"], t["estado"], hoy)
        limite = _dia(t["fecha_vencimiento"])
        en_plazo = en_ventana and limite is not None and fin <= limite
        creada = _dia(t["creada_en"])
        if creada is not None and desde <= creada <= hasta:
            creadas += 1
        if en_ventana and creada is not None:
            cierres.append((fin - creada).days)
        args = (abierta, vencida, en_ventana, limite is not None, en_plazo)
        _sumar(total, *args)
        _sumar(por_resp.setdefault(t["asignada_a"] or t["usuario_id"], _fila_vacia()), *args)
        for c in (t["clientes"] or [None]):
            _sumar(por_cli.setdefault(c, _fila_vacia()), *args)
        if t["estado"] == "esperando":
            origen = _dia(bloqueadas_desde.get(t["id"])) or _dia(t["actualizada_en"]) or _dia(t["creada_en"]) or hoy
            bloqueadas.append({"id": t["id"], "asunto": t["asunto"], "motivo": t["motivo_bloqueo"], "desde": origen.isoformat(), "dias": max((hoy - origen).days, 0)})
    bloqueadas.sort(key=lambda b: -b["dias"])
    return {
        "creadas": creadas,
        "ahora": {"abiertas": total["abiertas"], "vencidas": total["vencidas"], "bloqueadas": len(bloqueadas)},
        "en_ventana": {"completadas": total["completadas"], "con_fecha": total["con_fecha"], "en_plazo": total["en_plazo"], "tasa_en_plazo": _porcentaje(total["en_plazo"], total["con_fecha"]),
                       "tiempo_medio_cierre_dias": round(sum(cierres) / len(cierres), 1) if cierres else None, "tiempo_medio_n": len(cierres)},
        "por_responsable": {k: _con_tasa(v) for k, v in por_resp.items()},
        "por_cliente": {k: _con_tasa(v) for k, v in por_cli.items()},
        "bloqueadas": bloqueadas,
    }


def informe(tenant_id: int, usuario_id: int, desde: str | None = None, hasta: str | None = None, dias_proximos: int = 14, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    ini, fin = ventana(desde, hasta, hoy)
    dias_proximos = max(1, min(int(dias_proximos or 14), 90))
    tareas = _tareas_visibles(usuario_id)
    r = calcular(tareas, ini, fin, hoy, _bloqueada_desde([t["id"] for t in tareas if t["estado"] == "esperando"]))
    visibles = acceso.clientes_visibles(tenant_id, usuario_id) if tenant_id else set()
    nombres_cli = {c["id"]: c["nombre"] for c in db.listar_clientes_fiscales(tenant_id)} if tenant_id else {}
    por_cliente = []
    for cid, fila in r["por_cliente"].items():
        if cid is not None and (cid not in nombres_cli or (visibles is not None and cid not in visibles)):
            continue                                  # cliente de otra oficina o borrado: no se desglosa (sus tareas siguen en el total)
        por_cliente.append({"cliente_fiscal_id": cid, "nombre": nombres_cli.get(cid), **fila})
    por_cliente.sort(key=lambda f: (-f["vencidas"], -f["abiertas"], f["nombre"] or ""))
    por_responsable = [{"usuario_id": uid, "nombre": db.nombre_mostrado_usuario(uid), **fila} for uid, fila in r["por_responsable"].items()]
    por_responsable.sort(key=lambda f: (-f["vencidas"], -f["abiertas"], f["nombre"] or ""))
    limite = hoy + timedelta(days=dias_proximos)
    proximas = sorted(({"id": t["id"], "asunto": t["asunto"], "fecha": t["fecha_vencimiento"][:10]} for t in tareas
                       if t["estado"] != "completada" and t["fecha_vencimiento"] and hoy <= _dia(t["fecha_vencimiento"]) <= limite), key=lambda x: (x["fecha"], x["id"]))
    return {
        "ventana": {"desde": ini.isoformat(), "hasta": fin.isoformat(), "dias": (fin - ini).days + 1}, "hoy": hoy.isoformat(), "alcance": "tareas que la persona puede ver",
        "creadas_en_ventana": r["creadas"], "ahora": r["ahora"], "en_ventana": r["en_ventana"],
        "por_responsable": por_responsable, "por_cliente": por_cliente, "bloqueadas": r["bloqueadas"],
        "proximas": {"dias": dias_proximos, "tareas": proximas, "vencimientos_fiscales": _vencimientos_proximos(tenant_id, usuario_id, hoy, limite, visibles),
                     "certificados": _certificados_proximos(tenant_id, usuario_id, dias_proximos)},
    }


def _vencimientos_proximos(tenant_id: int, usuario_id: int, hoy: date, limite: date, visibles) -> list[dict]:
    if not tenant_id:
        return []
    filas = db.listar_vencimientos_fiscales(tenant_id, desde=hoy.isoformat(), hasta=limite.isoformat(), estado="pendiente")
    return [{"id": v["id"], "cliente": v.get("cliente_nombre") or v.get("cliente"), "modelo": v["modelo"], "periodo": v["periodo"], "fecha_limite": v["fecha_limite"][:10]}
            for v in map(dict, filas) if visibles is None or v["cliente_fiscal_id"] in visibles]


def _certificados_proximos(tenant_id: int, usuario_id: int, dias: int) -> list[dict]:
    """Solo para la dirección (los certificados son información sensible del despacho)."""
    if not tenant_id or not acceso.es_directivo(usuario_id):
        return []
    from . import certificados
    return [{"id": c["id"], "titular": c.get("titular") or c.get("nombre_comun") or c.get("sujeto"), "caduca": (c.get("not_after") or "")[:10], "dias": c.get("dias_restantes")}
            for c in certificados.listar(tenant_id, ahora=None, limite=500) if c.get("dias_restantes") is not None and 0 <= c["dias_restantes"] <= dias]


# --- Salidas: tablas planas para CSV y PDF ----------------------------------------------------------------------------------------

CABECERAS = ("Abiertas", "Vencidas", "Completadas en la ventana", "Con fecha límite", "En plazo", "% en plazo")


def _celdas(f: dict) -> list:
    return [f["abiertas"], f["vencidas"], f["completadas"], f["con_fecha"], f["en_plazo"], "" if f["tasa_en_plazo"] is None else f["tasa_en_plazo"]]


def filas_planas(r: dict) -> list[list]:
    """Una fila por responsable y por cliente: [sección, nombre, abiertas, vencidas, completadas, con fecha, en plazo, % en plazo]."""
    filas = [["Responsable", f["nombre"] or f"#{f['usuario_id']}", *_celdas(f)] for f in r["por_responsable"]]
    filas += [["Cliente", f["nombre"] or "Sin cliente", *_celdas(f)] for f in r["por_cliente"]]
    return filas
