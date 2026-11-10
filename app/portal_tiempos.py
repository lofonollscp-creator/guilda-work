"""Cuánto se tarda en cerrar el ciclo con el cliente (K12): cuánto pasa desde que el despacho pide un documento hasta que el cliente lo sube y hasta que se da por revisado, y cuánto tarda el despacho
en contestar la primera vez a una conversación que abre el cliente. Sirve para ver si las mejoras del portal (plazo visible, acuse, periódicos, escalada) reducen el ir y venir.

Solo cuenta con lo que ya existe (peticiones y conversaciones) y de los últimos 90 días, de los clientes que la persona puede ver. Las cifras son medianas en días naturales (peticiones) y en
días laborables (contestar), que no se dejan arrastrar por un caso excepcional; con menos de 3 casos no se enseña cifra."""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from . import acceso, db, portal_compromiso

VENTANA_DIAS = 90
MIN_CASOS = 3


def _dias(desde: str | None, hasta: str | None) -> float | None:
    try:
        return max(0.0, (datetime.fromisoformat(hasta[:19]) - datetime.fromisoformat(desde[:19])).total_seconds() / 86400)
    except (TypeError, ValueError):
        return None


def _mediana(valores: list[float]) -> float | None:
    return round(median(valores), 1) if len(valores) >= MIN_CASOS else None


def resumen(tenant_id: int, usuario_id: int, ahora: datetime | None = None) -> dict:
    """{peticiones: {n, hasta_subir, hasta_revisar}, conversaciones: {n, primera_respuesta, dentro_de_plazo}, plazo}; las cifras son None si hay pocos casos."""
    ahora = ahora or datetime.now()
    desde = (ahora - timedelta(days=VENTANA_DIAS)).isoformat(timespec="seconds")
    visibles = acceso.clientes_visibles(tenant_id, usuario_id)                    # None = todos
    plazo = portal_compromiso.ajustes(tenant_id)["plazo_respuesta_dias"]
    conn = db.get_connection()
    try:
        pet = [dict(f) for f in conn.execute("SELECT cliente_fiscal_id, creado_en, enviada_en, revisada_en FROM portal_peticiones WHERE tenant_id = ? AND creado_en >= ? AND estado <> 'cancelada'", (tenant_id, desde))]
        conv = [dict(f) for f in conn.execute(
            "SELECT c.id, c.cliente_fiscal_id, MIN(m.creado_en) AS abierta, "
            "(SELECT MIN(r.creado_en) FROM portal_conversaciones_mensajes r WHERE r.tenant_id = c.tenant_id AND r.conversacion_id = c.id AND r.de = 'despacho') AS contestada "
            "FROM portal_conversaciones c JOIN portal_conversaciones_mensajes m ON m.conversacion_id = c.id AND m.tenant_id = c.tenant_id "
            "WHERE c.tenant_id = ? AND c.iniciada_por = 'cliente' AND m.de = 'cliente' GROUP BY c.id, c.cliente_fiscal_id, c.tenant_id HAVING MIN(m.creado_en) >= ?", (tenant_id, desde))]
    finally:
        conn.close()
    if visibles is not None:
        pet = [p for p in pet if p["cliente_fiscal_id"] in visibles]
        conv = [c for c in conv if c["cliente_fiscal_id"] in visibles]
    subir = [d for d in (_dias(p["creado_en"], p["enviada_en"]) for p in pet if p["enviada_en"]) if d is not None]
    revisar = [d for d in (_dias(p["creado_en"], p["revisada_en"]) for p in pet if p["revisada_en"]) if d is not None]
    contestadas = [portal_compromiso.dias_habiles(c["abierta"], datetime.fromisoformat(c["contestada"][:19])) for c in conv if c["contestada"]]
    return {"plazo": plazo, "peticiones": {"n": len(pet), "hasta_subir": _mediana(subir), "hasta_revisar": _mediana(revisar)},
            "conversaciones": {"n": len(conv), "sin_contestar": sum(1 for c in conv if not c["contestada"]), "primera_respuesta": _mediana([float(d) for d in contestadas]),
                               "dentro_de_plazo": round(100 * sum(1 for d in contestadas if d <= plazo) / len(contestadas)) if plazo and len(contestadas) >= MIN_CASOS else None}}
