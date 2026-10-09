"""«Ver como»: soporte entra en la plataforma como un usuario, en SOLO LECTURA, durante un tiempo limitado y con
auditoría. El backoffice emite un enlace de un solo uso (caduca en 2 min); la app lo canjea y guarda la
suplantación en la sesión (30 min). Nunca se puede suplantar a un administrador global."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from . import db

CADUCIDAD_ENLACE = timedelta(minutes=2)
DURACION_SESION = timedelta(minutes=30)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def crear_enlace(usuario_id: int, admin: str, motivo: str) -> str:
    motivo = (motivo or "").strip()[:300]
    if len(motivo) < 5:
        raise ValueError("Indica el motivo (mínimo 5 caracteres): queda registrado.")
    conn = db.get_connection()
    try:
        u = conn.execute("SELECT rol FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if u is None:
            raise ValueError("El usuario no existe.")
        if u["rol"] == "admin":
            raise ValueError("No se puede ver como un administrador.")
        token = secrets.token_urlsafe(32)
        ahora = datetime.now()
        conn.execute("DELETE FROM ver_como_tokens WHERE expira_en < ?", (_iso(ahora - timedelta(days=1)),))
        conn.execute(
            "INSERT INTO ver_como_tokens (token_hash, usuario_id, admin, motivo, creado_en, expira_en) VALUES (?, ?, ?, ?, ?, ?)",
            (_hash(token), usuario_id, admin, motivo, _iso(ahora), _iso(ahora + CADUCIDAD_ENLACE)),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def canjear(token: str) -> dict | None:
    """Consume el enlace (una sola vez). Devuelve los datos para la sesión o None si no vale."""
    ahora = datetime.now()
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "UPDATE ver_como_tokens SET usado_en = ? WHERE token_hash = ? AND usado_en IS NULL AND expira_en >= ?",
            (_iso(ahora), _hash(token or ""), _iso(ahora)),
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        f = conn.execute(
            "SELECT t.usuario_id, t.admin, t.motivo, u.email, u.rol FROM ver_como_tokens t JOIN usuarios u ON u.id = t.usuario_id WHERE t.token_hash = ?",
            (_hash(token),),
        ).fetchone()
    finally:
        conn.close()
    if f is None or f["rol"] == "admin":
        return None
    return {"usuario_id": f["usuario_id"], "admin": f["admin"], "email": f["email"], "hasta": _iso(ahora + DURACION_SESION)}


def sesion_valida(ver: dict | None) -> bool:
    return bool(ver) and str(ver.get("hasta", "")) >= _iso(datetime.now())
