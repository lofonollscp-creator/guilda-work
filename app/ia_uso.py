"""Uso y coste de la IA por proveedor (P6): cada consulta que sale bien suma sus llamadas y sus tokens a (despacho, mes, proveedor, tarea, origen de la clave), y se estima su coste en dólares
con la tarifa pública del modelo cuando se conoce. Es una **estimación** para que la dirección vea cuánto se gasta con las claves propias; la factura real es la del proveedor.
OpenRouter manda el coste exacto en cada respuesta y se usa tal cual; los modelos gratuitos cuestan 0. Si el modelo no tiene tarifa conocida, se cuentan los tokens y la consulta se marca
«sin tarifa» (nunca se inventa un precio)."""
from __future__ import annotations

import re
from datetime import datetime

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ia_uso_proveedor (
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    mes TEXT NOT NULL,
    proveedor TEXT NOT NULL,
    tarea TEXT NOT NULL,
    origen TEXT NOT NULL,
    llamadas INTEGER NOT NULL DEFAULT 0,
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_salida INTEGER NOT NULL DEFAULT 0,
    coste_usd REAL NOT NULL DEFAULT 0,
    llamadas_sin_tarifa INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, mes, proveedor, tarea, origen)
);
"""

# Dólares por millón de tokens (entrada, salida). Prefijo del identificador del modelo -> tarifa. Solo lo que se conoce: lo demás sale «sin tarifa».
TARIFAS: tuple[tuple[str, tuple[float, float]], ...] = (
    ("gpt-4o-mini", (0.15, 0.60)), ("gpt-4o", (2.50, 10.00)), ("gpt-4.1-nano", (0.10, 0.40)), ("gpt-4.1-mini", (0.40, 1.60)), ("gpt-4.1", (2.00, 8.00)),
    ("claude-3-5-haiku", (0.80, 4.00)), ("claude-3-5-sonnet", (3.00, 15.00)), ("claude-3-7-sonnet", (3.00, 15.00)),
    ("gemini-2.0-flash", (0.10, 0.40)), ("gemini-2.5-flash", (0.30, 2.50)), ("gemini-2.5-pro", (1.25, 10.00)),
    ("mistral-small", (0.10, 0.30)), ("mistral-large", (2.00, 6.00)), ("pixtral-large", (2.00, 6.00)),
)
TAREAS = ("asistente", "facturas", "otras")


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _mes(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now()).strftime("%Y-%m")


def coste_estimado(proveedor: str, modelo: str, tokens_entrada: int, tokens_salida: int, usage: dict | None = None) -> float | None:
    """El coste en USD de esa consulta, o None si no se conoce la tarifa del modelo."""
    if proveedor == "ollama":
        return 0.0                                                    # en tu propia red
    if proveedor == "openrouter":
        if usage and isinstance(usage.get("cost"), (int, float)):
            return float(usage["cost"])
        if (modelo or "").endswith(":free"):
            return 0.0
    m = (modelo or "").lower()
    m = re.sub(r"^[^/]+/", "", m)                                     # «openai/gpt-4o» (OpenRouter) -> «gpt-4o»
    for prefijo, (entrada, salida) in TARIFAS:
        if m.startswith(prefijo):
            return (tokens_entrada * entrada + tokens_salida * salida) / 1_000_000
    return None


def registrar(tenant_id: int | None, proveedor: str, modelo: str, tarea: str, origen: str, usage: dict | None, ahora: datetime | None = None) -> None:
    """Suma una consulta correcta al uso del mes. Nunca debe romper la consulta que mide."""
    if tenant_id is None:
        return
    usage = usage or {}
    entrada, salida = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    coste = coste_estimado(proveedor, modelo, entrada, salida, usage)
    try:
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO ia_uso_proveedor (tenant_id, mes, proveedor, tarea, origen, llamadas, tokens_entrada, tokens_salida, coste_usd, llamadas_sin_tarifa) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?) "
                         "ON CONFLICT (tenant_id, mes, proveedor, tarea, origen) DO UPDATE SET llamadas = ia_uso_proveedor.llamadas + 1, tokens_entrada = ia_uso_proveedor.tokens_entrada + excluded.tokens_entrada, "
                         "tokens_salida = ia_uso_proveedor.tokens_salida + excluded.tokens_salida, coste_usd = ia_uso_proveedor.coste_usd + excluded.coste_usd, "
                         "llamadas_sin_tarifa = ia_uso_proveedor.llamadas_sin_tarifa + excluded.llamadas_sin_tarifa",
                         (tenant_id, _mes(ahora), proveedor, tarea if tarea in TAREAS else "otras", origen, entrada, salida, coste or 0.0, 1 if coste is None else 0))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 -- medir no puede romper la consulta (por ejemplo, base sin la tabla todavía)
        import logging
        logging.getLogger("guilda").warning("No se pudo anotar el uso de IA", exc_info=True)


def resumen(tenant_id: int, mes: str | None = None) -> dict:
    """{mes, filas: [{proveedor, tarea, origen, llamadas, tokens_entrada, tokens_salida, coste_usd, llamadas_sin_tarifa}], total_usd, total_llamadas, hay_sin_tarifa}."""
    mes = mes or _mes()
    conn = db.get_connection()
    try:
        filas = [dict(f) for f in conn.execute("SELECT proveedor, tarea, origen, llamadas, tokens_entrada, tokens_salida, coste_usd, llamadas_sin_tarifa FROM ia_uso_proveedor "
                                               "WHERE tenant_id = ? AND mes = ? ORDER BY coste_usd DESC, llamadas DESC", (tenant_id, mes)).fetchall()]
    finally:
        conn.close()
    return {"mes": mes, "filas": filas, "total_usd": round(sum(f["coste_usd"] for f in filas), 4), "total_llamadas": sum(f["llamadas"] for f in filas),
            "hay_sin_tarifa": any(f["llamadas_sin_tarifa"] for f in filas)}
