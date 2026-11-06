"""Seguridad de la cuenta de cada persona del portal: sus sesiones abiertas (se pueden cerrar desde otro dispositivo), el aviso por correo cuando entra desde un dispositivo que no
conocíamos y un segundo factor opcional (códigos de una aplicación de autenticación).

Las sesiones del portal viven en la cookie firmada; `portal_sesiones` guarda una huella de cada una (nunca el identificador en claro) para poder listarlas y revocarlas: en cada
petición se comprueba que la huella no esté revocada. El segundo factor es por persona y despacho (`tenant_id` + email): el secreto se guarda cifrado con la clave de la aplicación y
los códigos de recuperación (un solo uso) solo como huellas. Todo es opcional y no cambia cómo entra quien no lo activa."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_sesiones (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    sid_hash TEXT NOT NULL,
    dispositivo TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL,
    ultimo_uso_en TEXT NOT NULL,
    revocada_en TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_sesiones_sid ON portal_sesiones(tenant_id, sid_hash);
CREATE INDEX IF NOT EXISTS idx_portal_sesiones_persona ON portal_sesiones(tenant_id, email, revocada_en);

CREATE TABLE IF NOT EXISTS portal_segundo_factor (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    secreto TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 0,
    ultimo_paso INTEGER NOT NULL DEFAULT 0,
    recuperacion TEXT NOT NULL DEFAULT '[]',
    creado_en TEXT NOT NULL,
    activado_en TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_segundo_factor ON portal_segundo_factor(tenant_id, email);
"""

RETENCION_DIAS = 90                  # las sesiones cerradas o sin uso se borran pasado este tiempo
MINUTOS_ENTRE_TOQUES = 5
CODIGOS_RECUPERACION = 8
EMISOR = "Guilda Work"


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)


def _ahora(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now()).isoformat(timespec="seconds")


def _huella(valor: str) -> str:
    return hashlib.sha256(("portal-sesion:" + valor).encode()).hexdigest()


def _email(email: str | None) -> str:
    return (email or "").strip().lower()


# --- Qué dispositivo es ----------------------------------------------------------------------------------------------------------------------------------

def dispositivo_de(user_agent: str | None) -> str:
    """«Chrome en Windows», «Safari en iPhone»…: lo bastante claro para que la persona reconozca el suyo y lo bastante grueso para no alarmar con cada actualización del navegador."""
    ua = user_agent or ""
    sistema = next((n for p, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"), ("Mac OS X", "Mac"), ("Macintosh", "Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if p in ua), "")
    navegador = next((n for p, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("SamsungBrowser", "Samsung Internet"), ("Chrome/", "Chrome"), ("CriOS", "Chrome"), ("FxiOS", "Firefox"), ("Safari/", "Safari")) if p in ua), "")
    if navegador and sistema:
        return f"{navegador} en {sistema}"
    return navegador or sistema or "Dispositivo desconocido"


def _ip_gruesa(ip: str | None) -> str:
    """Solo para reconocerla, no para localizar a nadie: se guarda sin el último tramo (IPv4) o sin la mitad final (IPv6)."""
    ip = (ip or "").strip()
    if ":" in ip:
        return ":".join(ip.split(":")[:4]) + "::"
    partes = ip.split(".")
    return ".".join(partes[:3]) + ".0" if len(partes) == 4 else ""


# --- Sesiones --------------------------------------------------------------------------------------------------------------------------------------------

def abrir_sesion(cliente, email: str, user_agent: str | None, ip: str | None, ahora: datetime | None = None) -> tuple[str, bool]:
    """Registra una sesión nueva y devuelve (identificador para la cookie, ¿dispositivo nuevo?). Es «nuevo» si esa persona ya había entrado antes pero nunca desde este dispositivo."""
    email, disp = _email(email), dispositivo_de(user_agent)
    sid = secrets.token_urlsafe(24)
    conn = db.get_connection()
    try:
        previas = conn.execute("SELECT dispositivo FROM portal_sesiones WHERE tenant_id = ? AND email = ?", (cliente["tenant_id"], email)).fetchall()
        nuevo = bool(previas) and disp not in {p["dispositivo"] for p in previas}
        conn.execute("INSERT INTO portal_sesiones (tenant_id, cliente_fiscal_id, email, sid_hash, dispositivo, ip, creado_en, ultimo_uso_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (cliente["tenant_id"], cliente["id"], email, _huella(sid), disp, _ip_gruesa(ip), _ahora(ahora), _ahora(ahora)))
        conn.commit()
    finally:
        conn.close()
    return sid, nuevo


def sesion_valida(tenant_id: int, sid: str | None, ahora: datetime | None = None) -> bool | None:
    """True si la sesión existe y no está revocada; False si la han cerrado; None si no la conocemos (una sesión anterior a esta función). De paso anota que se está usando (como mucho cada pocos minutos)."""
    if not sid:
        return None
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT id, revocada_en, ultimo_uso_en FROM portal_sesiones WHERE tenant_id = ? AND sid_hash = ?", (tenant_id, _huella(sid))).fetchone()
        if f is None:
            return None
        if f["revocada_en"]:
            return False
        if f["ultimo_uso_en"] < _ahora((ahora or datetime.now()) - timedelta(minutes=MINUTOS_ENTRE_TOQUES)):
            conn.execute("UPDATE portal_sesiones SET ultimo_uso_en = ? WHERE id = ?", (_ahora(ahora), f["id"]))
            conn.commit()
        return True
    finally:
        conn.close()


def listar(cliente, email: str, sid_actual: str | None = None) -> list[dict]:
    """Las sesiones abiertas de esa persona en este despacho, la más reciente primero; `actual` marca la de este navegador."""
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT * FROM portal_sesiones WHERE tenant_id = ? AND email = ? AND revocada_en IS NULL ORDER BY ultimo_uso_en DESC, id DESC", (cliente["tenant_id"], _email(email))).fetchall()
    finally:
        conn.close()
    actual = _huella(sid_actual) if sid_actual else None
    return [{"id": f["id"], "dispositivo": f["dispositivo"], "ip": f["ip"], "creado_en": f["creado_en"], "ultimo_uso_en": f["ultimo_uso_en"], "actual": f["sid_hash"] == actual} for f in filas]


def cerrar(cliente, email: str, sesion_id: int) -> bool:
    """Cierra una sesión de esa persona (nunca de otra). False si no existe o ya estaba cerrada."""
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_sesiones SET revocada_en = ? WHERE id = ? AND tenant_id = ? AND email = ? AND revocada_en IS NULL", (_ahora(), sesion_id, cliente["tenant_id"], _email(email))).rowcount
        conn.commit()
    finally:
        conn.close()
    return bool(n)


def cerrar_otras(cliente, email: str, sid_actual: str | None) -> int:
    """Cierra todas las sesiones de esa persona menos la de este navegador. Devuelve cuántas."""
    conn = db.get_connection()
    try:
        n = conn.execute("UPDATE portal_sesiones SET revocada_en = ? WHERE tenant_id = ? AND email = ? AND revocada_en IS NULL AND sid_hash != ?",
                         (_ahora(), cliente["tenant_id"], _email(email), _huella(sid_actual or ""))).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def cerrar_esta(tenant_id: int | None, sid: str | None) -> None:
    if not sid or tenant_id is None:
        return
    conn = db.get_connection()
    try:
        conn.execute("UPDATE portal_sesiones SET revocada_en = ? WHERE tenant_id = ? AND sid_hash = ? AND revocada_en IS NULL", (_ahora(), tenant_id, _huella(sid)))
        conn.commit()
    finally:
        conn.close()


def limpiar(ahora: datetime | None = None) -> int:
    """Borra las sesiones cerradas o sin uso desde hace más de `RETENCION_DIAS`. Devuelve cuántas."""
    limite = _ahora((ahora or datetime.now()) - timedelta(days=RETENCION_DIAS))
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM portal_sesiones WHERE ultimo_uso_en < ?", (limite,)).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


# --- Segundo factor ----------------------------------------------------------------------------------------------------------------------------------------

def _fernet():
    from cryptography.fernet import Fernet
    clave = os.environ.get("GUILDA_SECRET_KEY")
    if not clave:
        from flask import current_app
        clave = str(current_app.secret_key)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("portal-2fa:" + clave).encode()).digest()))


def _hash_recuperacion(codigo: str) -> str:
    return hashlib.sha256(("portal-rec:" + codigo.strip().lower().replace("-", "")).encode()).hexdigest()


def generar_secreto() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def codigo_totp(secreto: str, paso: int) -> str:
    clave = base64.b32decode(secreto + "=" * (-len(secreto) % 8))
    resumen = hmac.new(clave, struct.pack(">Q", paso), hashlib.sha1).digest()
    desplazamiento = resumen[-1] & 0x0F
    valor = (struct.unpack(">I", resumen[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{valor:06d}"


def uri_totp(email: str, secreto: str) -> str:
    return f"otpauth://totp/{quote(EMISOR)}:{quote(email)}?secret={secreto}&issuer={quote(EMISOR)}&digits=6&period=30"


def _paso_valido(secreto: str, codigo: str, minimo_paso: int, ahora_s: float | None = None) -> int | None:
    codigo = (codigo or "").strip().replace(" ", "")
    if len(codigo) != 6 or not codigo.isdigit():
        return None
    actual = int((ahora_s if ahora_s is not None else time.time()) // 30)
    for paso in (actual - 1, actual, actual + 1):
        if paso > minimo_paso and hmac.compare_digest(codigo_totp(secreto, paso), codigo):
            return paso
    return None


def _fila(conn, tenant_id: int, email: str):
    return conn.execute("SELECT * FROM portal_segundo_factor WHERE tenant_id = ? AND email = ?", (tenant_id, _email(email))).fetchone()


def activo(cliente, email: str) -> bool:
    conn = db.get_connection()
    try:
        f = _fila(conn, cliente["tenant_id"], email)
    finally:
        conn.close()
    return bool(f and f["activo"])


def iniciar_alta(cliente, email: str) -> str:
    """Prepara el alta: crea un secreto nuevo (todavía inactivo) y lo devuelve para mostrarlo. ValueError si ya está activado."""
    email = _email(email)
    secreto = generar_secreto()
    conn = db.get_connection()
    try:
        f = _fila(conn, cliente["tenant_id"], email)
        if f and f["activo"]:
            raise ValueError("El segundo factor ya está activado.")
        cifrado = _fernet().encrypt(secreto.encode()).decode()
        if f:
            conn.execute("UPDATE portal_segundo_factor SET secreto = ?, ultimo_paso = 0, creado_en = ? WHERE id = ?", (cifrado, _ahora(), f["id"]))
        else:
            conn.execute("INSERT INTO portal_segundo_factor (tenant_id, email, secreto, creado_en) VALUES (?, ?, ?, ?)", (cliente["tenant_id"], email, cifrado, _ahora()))
        conn.commit()
    finally:
        conn.close()
    return secreto


def secreto_pendiente(cliente, email: str) -> str | None:
    """El secreto del alta en curso (para volver a mostrar el QR si el código falla); None si no hay alta pendiente."""
    conn = db.get_connection()
    try:
        f = _fila(conn, cliente["tenant_id"], email)
    finally:
        conn.close()
    return _fernet().decrypt(f["secreto"].encode()).decode() if f and not f["activo"] else None


def confirmar_alta(cliente, email: str, codigo: str) -> list[str]:
    """Activa el segundo factor si el código es correcto y devuelve los códigos de recuperación (se muestran una sola vez). ValueError si no hay alta en curso o el código no vale."""
    conn = db.get_connection()
    try:
        f = _fila(conn, cliente["tenant_id"], email)
        if f is None or f["activo"]:
            raise ValueError("No hay ningún alta en curso.")
        secreto = _fernet().decrypt(f["secreto"].encode()).decode()
        paso = _paso_valido(secreto, codigo, 0)
        if paso is None:
            raise ValueError("El código no es correcto. Comprueba la hora de tu móvil e inténtalo de nuevo.")
        codigos = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(CODIGOS_RECUPERACION)]
        conn.execute("UPDATE portal_segundo_factor SET activo = 1, ultimo_paso = ?, recuperacion = ?, activado_en = ? WHERE id = ?",
                     (paso, json.dumps([_hash_recuperacion(c) for c in codigos]), _ahora(), f["id"]))
        conn.commit()
    finally:
        conn.close()
    return codigos


def verificar(cliente, email: str, codigo: str) -> bool:
    """Acepta un código de la aplicación (cada uno sirve una vez) o uno de recuperación (que se gasta). False si no vale."""
    texto = (codigo or "").strip()
    conn = db.get_connection()
    try:
        f = _fila(conn, cliente["tenant_id"], email)
        if f is None or not f["activo"]:
            return False
        paso = _paso_valido(_fernet().decrypt(f["secreto"].encode()).decode(), texto, f["ultimo_paso"])
        if paso is not None:
            n = conn.execute("UPDATE portal_segundo_factor SET ultimo_paso = ? WHERE id = ? AND ultimo_paso < ?", (paso, f["id"], paso)).rowcount
            conn.commit()
            return bool(n)
        if re.fullmatch(r"[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}", texto):
            h, restantes = _hash_recuperacion(texto), json.loads(f["recuperacion"] or "[]")
            if h in restantes:
                restantes.remove(h)
                conn.execute("UPDATE portal_segundo_factor SET recuperacion = ? WHERE id = ?", (json.dumps(restantes), f["id"]))
                conn.commit()
                return True
        return False
    finally:
        conn.close()


def codigos_restantes(cliente, email: str) -> int:
    conn = db.get_connection()
    try:
        f = _fila(conn, cliente["tenant_id"], email)
    finally:
        conn.close()
    return len(json.loads(f["recuperacion"] or "[]")) if f and f["activo"] else 0


def desactivar(cliente, email: str, codigo: str) -> bool:
    """Quita el segundo factor si el código (o uno de recuperación) es válido. False si no lo es."""
    if not verificar(cliente, email, codigo):
        return False
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM portal_segundo_factor WHERE tenant_id = ? AND email = ?", (cliente["tenant_id"], _email(email)))
        conn.commit()
    finally:
        conn.close()
    return True


def quitar_a(cliente, email: str) -> None:
    """Para cuando se da de baja a una persona de esta ficha: sus sesiones en ella se cierran al momento (su segundo factor se queda, por si tiene acceso a otras)."""
    conn = db.get_connection()
    try:
        conn.execute("UPDATE portal_sesiones SET revocada_en = ? WHERE tenant_id = ? AND email = ? AND cliente_fiscal_id = ? AND revocada_en IS NULL", (_ahora(), cliente["tenant_id"], _email(email), cliente["id"]))
        conn.commit()
    finally:
        conn.close()
