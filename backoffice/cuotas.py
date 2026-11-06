"""Cuotas y uso por despacho: usuarios (tope del plan), almacenamiento de documentos, facturas procesadas en el mes y consultas de IA (tope de la ficha).
Los topes de almacenamiento y facturas se guardan en backoffice.db (`cuotas_despacho`; vacío = sin tope); los de usuarios e IA ya existían (plan y tenant).
Solo avisa, no bloquea nada: pasar del 80 % marca «aviso» y del 100 % «excedido»."""
from __future__ import annotations

from datetime import datetime

from app import db as plataforma

from . import almacen, auth

AVISO_PCT = 80
METRICAS = ("usuarios", "almacenamiento", "facturas", "ia")
ETIQUETAS = {"usuarios": "Usuarios", "almacenamiento": "Almacenamiento (MB)", "facturas": "Facturas del mes", "ia": "Consultas de IA del mes"}


def _celda(usado, limite) -> dict:
    """{usado, limite, pct, nivel}: limite None = sin tope; 0 = no permitido (excedido si hay uso... o aviso si no lo hay)."""
    if limite is None:
        return {"usado": usado, "limite": None, "pct": None, "nivel": "ok"}
    pct = round(usado / limite * 100) if limite else (100 if usado else 0)
    return {"usado": usado, "limite": limite, "pct": pct, "nivel": "excedido" if pct >= 100 else ("aviso" if pct >= AVISO_PCT else "ok")}


def limites_guardados() -> dict[int, dict]:
    bo = auth.conectar()
    try:
        return {f["tenant_id"]: dict(f) for f in bo.execute("SELECT * FROM cuotas_despacho").fetchall()}
    finally:
        bo.close()


def fijar(tenant_id: int, almacenamiento_mb: int | None, facturas_mes: int | None, admin: str | None = None) -> None:
    """Guarda los topes del despacho (None = sin tope). `ValueError` si algún valor es negativo."""
    for v in (almacenamiento_mb, facturas_mes):
        if v is not None and v < 0:
            raise ValueError("Los topes no pueden ser negativos.")
    bo = auth.conectar()
    try:
        bo.execute("INSERT INTO cuotas_despacho (tenant_id, almacenamiento_mb, facturas_mes, actualizado_en, actualizado_por) VALUES (?, ?, ?, ?, ?) "
                   "ON CONFLICT(tenant_id) DO UPDATE SET almacenamiento_mb = excluded.almacenamiento_mb, facturas_mes = excluded.facturas_mes, "
                   "actualizado_en = excluded.actualizado_en, actualizado_por = excluded.actualizado_por",
                   (tenant_id, almacenamiento_mb, facturas_mes, datetime.now().isoformat(timespec="seconds"), admin))
        bo.commit()
    finally:
        bo.close()


def uso(ahora: datetime | None = None) -> list[dict]:
    """Una fila por despacho: {tenant_id, nombre, plan, usuarios, almacenamiento, facturas, ia (cada una con usado/limite/pct/nivel), peor}."""
    ahora = ahora or datetime.now()
    mes, desde = ahora.strftime("%Y-%m"), ahora.strftime("%Y-%m-01")
    conn = plataforma.get_connection()
    try:
        tenants = conn.execute("SELECT t.id, t.nombre, t.ia_limite_mensual, p.nombre AS plan, p.max_usuarios FROM tenants t LEFT JOIN planes_guilda p ON p.id = t.plan_id "
                               "WHERE t.id > 0 ORDER BY t.nombre").fetchall()
        usuarios = {f["tenant_id"]: f["n"] for f in conn.execute("SELECT tenant_id, COUNT(*) AS n FROM usuarios WHERE tenant_id IS NOT NULL GROUP BY tenant_id").fetchall()}
        facturas = {f["tenant_id"]: f["n"] for f in conn.execute("SELECT tenant_id, COUNT(*) AS n FROM facturas_contables WHERE creado_en >= ? GROUP BY tenant_id", (desde,)).fetchall()}
        ia = {f["tenant_id"]: f["usadas"] for f in conn.execute("SELECT tenant_id, usadas FROM ia_consumo WHERE mes = ?", (mes,)).fetchall()}
    finally:
        conn.close()
    mb = {d["tenant_id"]: d["fuera_mb"] + d["dentro_mb"] for d in almacen.resumen()["por_despacho"]}
    guardados = limites_guardados()
    filas = []
    for t in tenants:
        tid, g = t["id"], guardados.get(t["id"], {})
        fila = {"tenant_id": tid, "nombre": t["nombre"], "plan": t["plan"],
                "usuarios": _celda(usuarios.get(tid, 0), t["max_usuarios"]),
                "almacenamiento": _celda(round(mb.get(tid, 0.0), 1), g.get("almacenamiento_mb")),
                "facturas": _celda(facturas.get(tid, 0), g.get("facturas_mes")),
                "ia": _celda(ia.get(tid, 0), t["ia_limite_mensual"])}
        niveles = [fila[m]["nivel"] for m in METRICAS]
        fila["peor"] = "excedido" if "excedido" in niveles else ("aviso" if "aviso" in niveles else "ok")
        filas.append(fila)
    orden = {"excedido": 0, "aviso": 1, "ok": 2}
    return sorted(filas, key=lambda f: (orden[f["peor"]], f["nombre"].lower()))


def avisos(ahora: datetime | None = None) -> list[dict]:
    """Los despachos que están en aviso o excedidos, con el texto de cada métrica afectada (para el resumen semanal)."""
    salida = []
    for f in uso(ahora):
        if f["peor"] == "ok":
            continue
        motivos = [f"{ETIQUETAS[m]}: {f[m]['usado']} de {f[m]['limite']} ({f[m]['pct']} %)" for m in METRICAS if f[m]["nivel"] != "ok"]
        salida.append({"tenant_id": f["tenant_id"], "nombre": f["nombre"], "nivel": f["peor"], "motivos": motivos})
    return salida


def _activado() -> bool:
    import os
    return os.environ.get("GUILDA_AVISOS_CUOTA", "").strip().lower() in ("1", "true", "si", "sí", "yes")


def _reservar(clave: str) -> bool:
    """Apunta el aviso antes de enviarlo (un fallo no se reintenta cada pasada). False si ya estaba apuntado."""
    bo = auth.conectar()
    try:
        if bo.execute("SELECT 1 FROM resumenes_enviados WHERE clave = ?", (clave,)).fetchone():
            return False
        bo.execute("INSERT INTO resumenes_enviados (clave, enviado_en) VALUES (?, ?)", (clave, auth._ahora()))
        bo.commit()
        return True
    finally:
        bo.close()


def _direccion(tenant_id: int) -> list[str]:
    conn = plataforma.get_connection()
    try:
        return sorted({r["email"] for r in conn.execute("SELECT u.email FROM usuarios u WHERE " + plataforma.sql_supervisor(), (tenant_id, tenant_id)).fetchall() if r["email"]})
    finally:
        conn.close()


def avisar_despachos(ahora: datetime | None = None, enviar=None, tenant_id: int | None = None, forzar: bool = False) -> int:
    """Avisa a la dirección de cada despacho que haya pasado del 80 % (o del 100 %) de un tope de su plan: un correo por despacho con lo nuevo, y como mucho una vez al mes por límite y nivel
    (si pasa del 80 % al 100 % se avisa otra vez). Solo si `GUILDA_AVISOS_CUOTA=1`, salvo `forzar` (el botón de la ficha). Devuelve cuántos correos salieron."""
    import os
    from app import notificaciones_email
    if not forzar and not _activado():
        return 0
    ahora = ahora or datetime.now()
    mes = ahora.strftime("%Y-%m")
    url = os.environ.get("GUILDA_URL_PUBLICA", "").rstrip("/") or "https://app.guildawork.com"
    total = 0
    for f in uso(ahora):
        if tenant_id is not None and f["tenant_id"] != tenant_id:
            continue
        metricas = []
        for m in METRICAS:
            c = f[m]
            if c["nivel"] == "ok" or c["limite"] is None:
                continue
            if forzar or _reservar(f"cuota-{f['tenant_id']}-{m}-{c['nivel']}-{mes}"):
                metricas.append({"metrica": m, **{k: c[k] for k in ("usado", "limite", "pct", "nivel")}})
        if not metricas:
            continue
        for destino in _direccion(f["tenant_id"]):
            try:
                (enviar or notificaciones_email.enviar_aviso_cuota)(destino, f["nombre"], metricas, url, tenant_id=f["tenant_id"])
                total += 1
            except Exception:  # noqa: BLE001 -- un destino que falla no frena a los demás
                continue
    return total
