"""Política de acceso del despacho (Y8): la dirección puede exigir a todo el equipo un segundo factor (app de autenticación) o una passkey, con una fecha límite.

Sin bloqueos bruscos: la fecha límite es siempre de al menos `MIN_DIAS` días a partir de hoy; hasta entonces cada persona que no cumple ve un aviso con los días que le quedan, y pasada la fecha solo puede entrar a
Ajustes → Contraseña y email (y salir) hasta que lo active. Cumple quien tiene `totp` o `passkey` en Kratos. Si Kratos no responde, **se da por cumplida** (una avería nunca deja a nadie fuera).
Las cuentas locales de escritorio, el soporte «ver como» y la API con token no se ven afectados."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from . import db, kratos

MIN_DIAS = 7
METODOS_VALIDOS = {"totp", "passkey"}
_CACHE: dict[int, tuple[float, bool | None]] = {}
SEGUNDOS_CACHE = 60
_POLITICA: dict[int, tuple[float, dict]] = {}                    # la política de cada despacho, 30 s: se pide en cada pantalla y casi nunca cambia
SEGUNDOS_POLITICA = 30


def olvidar_todo() -> None:
    _CACHE.clear()
    _POLITICA.clear()


def obtener(tenant_id: int) -> dict:
    """{exigir: bool, limite: 'AAAA-MM-DD' | None}"""
    ahora = time.monotonic()
    hit = _POLITICA.get(tenant_id)
    if hit and ahora - hit[0] < SEGUNDOS_POLITICA:
        return hit[1]
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT exigir_segundo_factor, segundo_factor_limite FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()
    res = {"exigir": bool(f and f["exigir_segundo_factor"]), "limite": (f["segundo_factor_limite"] if f else None) or None}
    _POLITICA[tenant_id] = (ahora, res)
    return res


def fijar(tenant_id: int, usuario_id: int, exigir: bool, limite: str | None, hoy: date | None = None) -> None:
    """Activa o quita la política. Al activarla la fecha límite es obligatoria y como pronto dentro de `MIN_DIAS` días (`ValueError` con un mensaje legible si no)."""
    from . import auditoria
    hoy = hoy or date.today()
    if exigir:
        try:
            fecha = date.fromisoformat((limite or "")[:10])
        except ValueError:
            raise ValueError("Indica la fecha límite para que el equipo active la verificación.") from None
        if fecha < hoy + timedelta(days=MIN_DIAS):
            raise ValueError(f"La fecha límite debe dejar al equipo al menos {MIN_DIAS} días.")
        limite = fecha.isoformat()
    else:
        limite = None
    conn = db.get_connection()
    try:
        conn.execute("UPDATE tenants SET exigir_segundo_factor = ?, segundo_factor_limite = ? WHERE id = ?", (1 if exigir else 0, limite, tenant_id))
        conn.commit()
    finally:
        conn.close()
    olvidar_todo()
    auditoria.registrar(tenant_id, usuario_id, "seguridad.politica_acceso", "tenant", tenant_id, {"exigir": bool(exigir), "limite": limite})


def cumple(usuario_id: int) -> bool | None:
    """True si la persona tiene un segundo factor o una passkey, False si no, None si no se pudo comprobar (cuenta sin Kratos o Kratos caído)."""
    ahora = time.monotonic()
    hit = _CACHE.get(usuario_id)
    if hit and ahora - hit[0] < SEGUNDOS_CACHE:
        return hit[1]
    u = db.obtener_usuario(usuario_id)
    res: bool | None = None
    if u is not None and not u["es_local"] and u["kratos_identity_id"]:
        try:
            creds = kratos.credenciales_de(u["kratos_identity_id"])
        except Exception:  # noqa: BLE001
            creds = None
        res = None if creds is None else bool(creds & METODOS_VALIDOS)
    _CACHE[usuario_id] = (ahora, res)
    return res


def olvidar(usuario_id: int) -> None:
    """Descarta lo recordado de esta persona (al visitar sus ajustes, para que active el segundo factor y siga sin esperar)."""
    _CACHE.pop(usuario_id, None)


def pendiente(usuario_id: int, tenant_id: int | None, hoy: date | None = None) -> dict | None:
    """None si no hay nada que hacer; si la política está activa y la persona no cumple, `{limite, dias, vencida}` (`dias` negativo = pasada la fecha)."""
    if tenant_id is None:
        return None
    p = obtener(tenant_id)
    if not p["exigir"] or not p["limite"]:
        return None
    if cumple(usuario_id) is not False:
        return None
    dias = (date.fromisoformat(p["limite"]) - (hoy or date.today())).days
    return {"limite": p["limite"], "dias": dias, "vencida": dias < 0}


def incumplen(tenant_id: int) -> list[int]:
    """Las personas del despacho que, con la política activa, no cumplen (para la pantalla de la dirección)."""
    return [uid for uid in db.usuarios_de_tenant(tenant_id) if cumple(uid) is False]
