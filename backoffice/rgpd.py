"""Registro de solicitudes de derechos RGPD de todos los despachos, con su plazo de un mes. Las solicitudes que llegan a la plataforma (la baja de una cuenta, o las que se anotan a mano porque llegaron por correo)
quedan abiertas hasta que alguien las da por atendidas; este panel enseña cuánto queda y avisa de las vencidas. Guilda es encargada del tratamiento: atender la solicitud sobre los datos de un despacho le corresponde
al propio despacho; aquí solo se lleva el control del plazo. Lee y escribe en `registro_rgpd` (la misma tabla que usa la app), sin tocar datos de ningún cliente."""
from __future__ import annotations

from datetime import datetime, timedelta

from app import db as plataforma

PLAZO_DIAS = 30
AVISO_DIAS = 7
TIPOS = {"solicitud_baja": "Baja de cuenta", "solicitud_acceso": "Acceso a los datos", "solicitud_rectificacion": "Rectificación", "solicitud_supresion": "Supresión",
         "solicitud_oposicion": "Oposición", "solicitud_limitacion": "Limitación", "solicitud_portabilidad": "Portabilidad"}
ATENDIDA = "atendida"
assert set(TIPOS) | {ATENDIDA} == {"solicitud_baja", "solicitud_acceso", "solicitud_rectificacion", "solicitud_supresion", "solicitud_oposicion", "solicitud_limitacion", "solicitud_portabilidad", "atendida"}, "la consulta de solicitudes lista los tipos a mano"


def _fecha(texto: str) -> datetime:
    return datetime.fromisoformat(texto)


def solicitudes(ahora: datetime | None = None) -> dict:
    """{abiertas: [...], atendidas: [...]} (las atendidas, las 30 últimas). Cada solicitud: {id, tenant_id, despacho, persona, tipo, etiqueta, detalle, creado_en, vence_en, dias_restantes, nivel}.
    `nivel`: ok, aviso (quedan 7 días o menos) o vencida."""
    ahora = ahora or datetime.now()
    conn = plataforma.get_connection()
    try:
        filas = conn.execute("SELECT r.id, r.tenant_id, r.usuario_id, r.tipo, r.detalle, r.creado_en, t.nombre AS despacho, u.email AS persona FROM registro_rgpd r "
                             "LEFT JOIN tenants t ON t.id = r.tenant_id LEFT JOIN usuarios u ON u.id = r.usuario_id WHERE r.tipo IN ('solicitud_baja', 'solicitud_acceso', 'solicitud_rectificacion', 'solicitud_supresion', 'solicitud_oposicion', 'solicitud_limitacion', 'solicitud_portabilidad', 'atendida') ORDER BY r.id").fetchall()
    finally:
        conn.close()
    cerradas: dict[int, dict] = {}
    for f in filas:
        if f["tipo"] == ATENDIDA and f["detalle"].startswith("solicitud #"):
            try:
                cerradas[int(f["detalle"].split("#", 1)[1].split(":", 1)[0])] = dict(f)
            except ValueError:
                continue
    abiertas, atendidas = [], []
    for f in filas:
        if f["tipo"] not in TIPOS:
            continue
        s = {"id": f["id"], "tenant_id": f["tenant_id"], "despacho": f["despacho"] or f"#{f['tenant_id']}", "persona": f["persona"], "tipo": f["tipo"], "etiqueta": TIPOS[f["tipo"]],
             "detalle": f["detalle"], "creado_en": f["creado_en"]}
        vence = _fecha(f["creado_en"]) + timedelta(days=PLAZO_DIAS)
        s["vence_en"] = vence.isoformat(timespec="seconds")
        if f["id"] in cerradas:
            s["atendida_en"] = cerradas[f["id"]]["creado_en"]
            s["nota"] = cerradas[f["id"]]["detalle"].split(":", 1)[1].strip() if ":" in cerradas[f["id"]]["detalle"] else ""
            atendidas.append(s)
            continue
        s["dias_restantes"] = (vence.date() - ahora.date()).days
        s["nivel"] = "vencida" if s["dias_restantes"] < 0 else ("aviso" if s["dias_restantes"] <= AVISO_DIAS else "ok")
        abiertas.append(s)
    abiertas.sort(key=lambda s: s["dias_restantes"])
    return {"abiertas": abiertas, "atendidas": sorted(atendidas, key=lambda s: s["atendida_en"], reverse=True)[:30]}


def registrar(tenant_id: int, tipo: str, quien: str, detalle: str) -> int:
    """Anota una solicitud recibida por otra vía (por ejemplo por correo). `ValueError` si el tipo no existe o falta la descripción."""
    if tipo not in TIPOS:
        raise ValueError("Elige el tipo de solicitud.")
    texto = " ".join(f"{(quien or '').strip()}: {(detalle or '').strip()}".split()).strip(": ")
    if len(texto) < 5:
        raise ValueError("Describe la solicitud (quién la hace y qué pide).")
    conn = plataforma.get_connection()
    try:
        if conn.execute("SELECT 1 FROM tenants WHERE id = ? AND id > 0", (tenant_id,)).fetchone() is None:
            raise ValueError("Ese despacho no existe.")
        cur = conn.execute("INSERT INTO registro_rgpd (tenant_id, usuario_id, tipo, detalle, creado_en) VALUES (?, NULL, ?, ?, ?)", (tenant_id, tipo, texto[:300], plataforma.now_iso()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def atender(solicitud_id: int, nota: str, admin: str) -> None:
    """Da la solicitud por atendida (con una nota de qué se hizo). `ValueError` si no existe o ya estaba atendida."""
    nota = " ".join((nota or "").split())
    if len(nota) < 5:
        raise ValueError("Escribe qué se ha hecho (mínimo 5 caracteres): queda anotado.")
    if not any(s["id"] == solicitud_id for s in solicitudes()["abiertas"]):
        raise ValueError("Esa solicitud no existe o ya está atendida.")
    conn = plataforma.get_connection()
    try:
        original = conn.execute("SELECT tenant_id, usuario_id FROM registro_rgpd WHERE id = ?", (solicitud_id,)).fetchone()
        conn.execute("INSERT INTO registro_rgpd (tenant_id, usuario_id, tipo, detalle, creado_en) VALUES (?, ?, ?, ?, ?)",
                     (original["tenant_id"], original["usuario_id"], ATENDIDA, f"solicitud #{solicitud_id}: {nota} ({admin})"[:300], plataforma.now_iso()))
        conn.commit()
    finally:
        conn.close()


def vencidas_o_por_vencer(ahora: datetime | None = None) -> list[dict]:
    return [s for s in solicitudes(ahora)["abiertas"] if s["nivel"] != "ok"]
