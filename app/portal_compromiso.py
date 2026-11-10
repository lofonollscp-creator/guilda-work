"""El compromiso del despacho con el cliente en el portal: en cuánto tiempo suele contestar (K2) y quién está fuera (K3), para que una espera no se confunda con un olvido.

Es opcional y sale apagado: cada despacho fija su plazo en días laborables (0 = no se enseña nada). Con plazo, el portal lo dice en Mensajes y tras subir facturas, y la bandeja del equipo marca lo
que ya lo ha superado. Con «mostrar ausencias», el cliente ve que quien lleva su expediente está fuera hasta tal fecha (solo el nombre de pila y la fecha; nunca el motivo)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import db

MAX_PLAZO_DIAS = 10
AJUSTES = {"plazo_respuesta_dias": int, "mostrar_ausencias": int, "voz_cliente": int, "escalada_avisos": int}     # columnas de portal_recordatorios_config que gestiona este módulo (y K7, K9)
DEFECTO = {"plazo_respuesta_dias": 0, "mostrar_ausencias": 0, "voz_cliente": 0, "escalada_avisos": 0}


def ajustes(tenant_id: int) -> dict:
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT plazo_respuesta_dias, mostrar_ausencias, voz_cliente, escalada_avisos FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    return {k: int(f[k] or 0) for k in AJUSTES} if f else dict(DEFECTO)


def fijar(tenant_id: int, **valores) -> dict:
    """Guarda los ajustes indicados. `ValueError` si el plazo no es un número de 0 a 10; lo desconocido se ignora."""
    nuevos = {}
    for k, v in valores.items():
        if k not in AJUSTES:
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ValueError("El plazo debe ser un número de días.")
        if k == "plazo_respuesta_dias" and not 0 <= n <= MAX_PLAZO_DIAS:
            raise ValueError("El plazo debe estar entre 0 y 10 días laborables.")
        nuevos[k] = n if k == "plazo_respuesta_dias" else (1 if n else 0)
    if not nuevos:
        return ajustes(tenant_id)
    conn = db.get_connection()
    try:
        if not conn.execute("SELECT 1 FROM portal_recordatorios_config WHERE tenant_id = ?", (tenant_id,)).fetchone():
            cfg = db.CONFIG_RECORDATORIOS_DEFECTO
            conn.execute("INSERT INTO portal_recordatorios_config (tenant_id, dias_antes, dias_despues, avisar_equipo, asunto, cuerpo, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (tenant_id, ",".join(str(x) for x in cfg["dias_antes"]), "", int(cfg["avisar_equipo"]), "", "", db.now_iso()))
        for k, v in nuevos.items():                                                    # los nombres vienen de la lista blanca AJUSTES, nunca del usuario
            conn.execute(f"UPDATE portal_recordatorios_config SET {k} = ? WHERE tenant_id = ?", (v, tenant_id))
        conn.commit()
    finally:
        conn.close()
    return ajustes(tenant_id)


def dias_habiles(desde: str | None, ahora: datetime | None = None) -> int:
    """Días laborables (lunes a viernes) transcurridos desde `desde` (ISO) hasta ahora. Los festivos no se descuentan: el plazo es una referencia, no un contrato."""
    ahora = ahora or datetime.now()
    try:
        d = datetime.fromisoformat((desde or "")[:19]).date()
    except ValueError:
        return 0
    n, dia = 0, d
    while dia < ahora.date():
        dia += timedelta(days=1)
        if dia.weekday() < 5:
            n += 1
    return n


def fuera_de_plazo(desde: str | None, plazo: int, ahora: datetime | None = None) -> bool:
    return bool(plazo) and dias_habiles(desde, ahora) > plazo


def ausencia_del_responsable(cliente, hoy: date | None = None) -> dict | None:
    """{nombre, hasta} si quien lleva a este cliente tiene una ausencia aprobada que incluye hoy; None si no, si no hay responsable o si el despacho no quiere enseñarlo."""
    uid = cliente["responsable_id"] if "responsable_id" in cliente.keys() else None
    if not uid or not ajustes(cliente["tenant_id"])["mostrar_ausencias"]:
        return None
    hoy_iso = (hoy or date.today()).isoformat()
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT MAX(a.hasta) AS hasta FROM ausencias a WHERE a.tenant_id = ? AND a.usuario_id = ? AND a.estado = 'aprobada' AND a.desde <= ? AND a.hasta >= ?",
                         (cliente["tenant_id"], uid, hoy_iso, hoy_iso)).fetchone()
        if not f or not f["hasta"]:
            return None
        n = conn.execute("SELECT COALESCE(NULLIF(pf.nombre_mostrado, ''), '') AS nombre FROM usuarios u LEFT JOIN usuario_perfil pf ON pf.usuario_id = u.id WHERE u.id = ?", (uid,)).fetchone()
    finally:
        conn.close()
    nombre = ((n["nombre"] if n else "") or "").split(" ")[0]
    return {"nombre": nombre, "hasta": f["hasta"]}


def para_el_cliente(cliente) -> dict:
    """Lo que el portal le cuenta a este cliente: `plazo` (días laborables, 0 si no se enseña) y `ausencia` ({nombre, hasta} o None)."""
    return {"plazo": ajustes(cliente["tenant_id"])["plazo_respuesta_dias"], "ausencia": ausencia_del_responsable(cliente)}
