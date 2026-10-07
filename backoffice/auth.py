"""Autenticación PROPIA del backoffice, sin relación con Kratos ni con la
sesión de app.guildawork.com: administradores en su propia base SQLite
(data/backoffice.db), contraseñas con scrypt, bloqueo por intentos fallidos,
sesión firmada de cookie propia (bo_session), caducidad por inactividad y
protección CSRF en todo POST."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import sqlite3
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import abort, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import db as plataforma

DB_PATH = Path(os.environ.get("BACKOFFICE_DB") or (plataforma.RAIZ_PROYECTO / "data" / "backoffice.db"))
SECRET_PATH = Path(os.environ.get("BACKOFFICE_SECRET_FILE") or (plataforma.RAIZ_PROYECTO / "data" / "backoffice_secret.key"))

MIN_LONGITUD_CONTRASENA = 12
INTENTOS_MAX_POR_USUARIO = 5
INTENTOS_MAX_POR_IP = 25
VENTANA_BLOQUEO_MIN = 15
INACTIVIDAD_MAX_MIN = 60
SESION_MAX_HORAS = 12
PRE2FA_MAX_SEGUNDOS = 300       # tiempo para teclear el código tras acertar la contraseña
CODIGOS_RECUPERACION = 8


def caducidad_contrasena_dias() -> int:
    """Días de vida de una contraseña (0 = no caduca). BACKOFFICE_CADUCIDAD_DIAS, 180 por defecto."""
    try:
        return max(0, int(os.environ.get("BACKOFFICE_CADUCIDAD_DIAS", "180")))
    except ValueError:
        return 180


def segundo_factor_obligatorio() -> bool:
    return os.environ.get("BACKOFFICE_2FA_OBLIGATORIO") == "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL,
    ultimo_acceso TEXT
);
CREATE TABLE IF NOT EXISTS intentos_login (
    id INTEGER PRIMARY KEY,
    usuario TEXT NOT NULL,
    ip TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY,
    admin_id INTEGER,
    admin_usuario TEXT,
    accion TEXT NOT NULL,
    detalle TEXT,
    ip TEXT,
    creado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cobros (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    concepto TEXT NOT NULL,
    importe_centimos INTEGER NOT NULL,
    stripe_session_id TEXT NOT NULL,
    url TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    admin_usuario TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_cobros_tenant ON cobros(tenant_id);
CREATE TABLE IF NOT EXISTS notas_tenant (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    texto TEXT NOT NULL,
    admin_usuario TEXT,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notas_tenant ON notas_tenant(tenant_id);
CREATE TABLE IF NOT EXISTS snapshots_tenants (
    fecha TEXT NOT NULL,
    tenant_id INTEGER NOT NULL,
    plan_id INTEGER,
    precio_centimos INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    suscripcion_estado TEXT,
    PRIMARY KEY (fecha, tenant_id)
);
CREATE TABLE IF NOT EXISTS auditorias_dependencias (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    resultado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resumenes_enviados (
    clave TEXT PRIMARY KEY,
    enviado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intentos_login ON intentos_login(usuario, creado_en);
"""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def conectar() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(SCHEMA)
    existentes = {f[1] for f in conn.execute("PRAGMA table_info(admins)")}
    for columna, tipo in (
        ("totp_secreto", "TEXT"), ("totp_activo", "INTEGER NOT NULL DEFAULT 0"), ("totp_ultimo_paso", "INTEGER NOT NULL DEFAULT 0"),
        ("codigos_recuperacion", "TEXT"), ("password_cambiada_en", "TEXT"),
    ):
        if columna not in existentes:
            conn.execute(f"ALTER TABLE admins ADD COLUMN {columna} {tipo}")
    conn.commit()
    return conn


def clave_secreta() -> str:
    """Clave de firma de la sesión: variable de entorno o fichero propio (0600),
    generado la primera vez. Distinta de cualquier clave de la app."""
    valor = os.environ.get("BACKOFFICE_SECRET_KEY")
    if valor:
        return valor
    if not SECRET_PATH.exists():
        SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as f:
            f.write(secrets.token_urlsafe(64))
    return SECRET_PATH.read_text().strip()


# --- Administradores ---------------------------------------------------------

def validar_contrasena(contrasena: str) -> None:
    if len(contrasena) < MIN_LONGITUD_CONTRASENA:
        raise ValueError(f"La contraseña debe tener al menos {MIN_LONGITUD_CONTRASENA} caracteres.")


def crear_admin(usuario: str, contrasena: str, nombre: str | None = None) -> int:
    usuario = usuario.strip().lower()
    if not usuario or len(usuario) > 64 or not all(c.isalnum() or c in "._-@" for c in usuario):
        raise ValueError("Usuario no válido (letras, números y . _ - @).")
    validar_contrasena(contrasena)
    conn = conectar()
    try:
        cur = conn.execute(
            "INSERT INTO admins (usuario, nombre, password_hash, creado_en, password_cambiada_en) VALUES (?, ?, ?, ?, ?)",
            (usuario, (nombre or usuario).strip(), generate_password_hash(contrasena), _ahora(), _ahora()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def cambiar_contrasena(usuario: str, contrasena: str) -> bool:
    validar_contrasena(contrasena)
    conn = conectar()
    try:
        cur = conn.execute(
            "UPDATE admins SET password_hash = ?, password_cambiada_en = ? WHERE usuario = ?",
            (generate_password_hash(contrasena), _ahora(), usuario.strip().lower()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


_HASH_FALSO = generate_password_hash("contrasena-que-nadie-tiene")


def bloqueado(conn: sqlite3.Connection, usuario: str, ip: str) -> bool:
    desde = (datetime.now() - timedelta(minutes=VENTANA_BLOQUEO_MIN)).isoformat(timespec="seconds")
    por_usuario = conn.execute(
        "SELECT COUNT(*) FROM intentos_login WHERE usuario = ? AND creado_en >= ?", (usuario, desde)
    ).fetchone()[0]
    por_ip = conn.execute(
        "SELECT COUNT(*) FROM intentos_login WHERE ip = ? AND creado_en >= ?", (ip, desde)
    ).fetchone()[0]
    return por_usuario >= INTENTOS_MAX_POR_USUARIO or por_ip >= INTENTOS_MAX_POR_IP


def verificar(usuario: str, contrasena: str, ip: str) -> tuple[sqlite3.Row | None, str | None]:
    """(admin, None) si las credenciales valen; (None, motivo) si no. El motivo
    es genérico a propósito ("incorrectas") salvo el bloqueo temporal."""
    usuario = usuario.strip().lower()
    conn = conectar()
    try:
        if bloqueado(conn, usuario, ip):
            return None, "bloqueado"
        admin = conn.execute("SELECT * FROM admins WHERE usuario = ? AND activo = 1", (usuario,)).fetchone()
        # Se comprueba siempre un hash (aunque el usuario no exista) para que
        # el tiempo de respuesta no delate qué usuarios existen.
        correcto = check_password_hash(admin["password_hash"] if admin else _HASH_FALSO, contrasena)
        if admin is None or not correcto:
            conn.execute("INSERT INTO intentos_login (usuario, ip, creado_en) VALUES (?, ?, ?)", (usuario, ip, _ahora()))
            conn.commit()
            return None, "incorrectas"
        conn.execute("DELETE FROM intentos_login WHERE usuario = ?", (usuario,))
        conn.execute("UPDATE admins SET ultimo_acceso = ? WHERE id = ?", (_ahora(), admin["id"]))
        conn.commit()
        return admin, None
    finally:
        conn.close()


# --- Caducidad de la contraseña ------------------------------------------------

def dias_para_caducar(admin) -> int | None:
    """Días que le quedan a la contraseña (negativo = caducada); None si no caduca."""
    limite = caducidad_contrasena_dias()
    if not limite:
        return None
    desde = admin["password_cambiada_en"] or admin["creado_en"]
    try:
        edad = (datetime.now() - datetime.fromisoformat(desde)).days
    except (TypeError, ValueError):
        return None
    return limite - edad


# --- Segundo factor (TOTP, RFC 6238: 6 dígitos, 30 s, SHA-1) ---------------------

def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("totp:" + clave_secreta()).encode()).digest()))


def generar_secreto_totp() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def codigo_totp(secreto: str, paso: int) -> str:
    clave = base64.b32decode(secreto + "=" * (-len(secreto) % 8))
    resumen = hmac.new(clave, struct.pack(">Q", paso), hashlib.sha1).digest()
    desplazamiento = resumen[-1] & 0x0F
    valor = (struct.unpack(">I", resumen[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{valor:06d}"


def uri_totp(usuario: str, secreto: str) -> str:
    from urllib.parse import quote
    return f"otpauth://totp/{quote('Guilda Backoffice')}:{quote(usuario)}?secret={secreto}&issuer={quote('Guilda Backoffice')}&digits=6&period=30"


def _paso_actual() -> int:
    return int(time.time() // 30)


def comprobar_codigo_totp(secreto: str, codigo: str, minimo_paso: int = 0) -> int | None:
    """Paso (ventana de 30 s) al que corresponde el código, tolerando ±1 por desfase de
    reloj; None si no vale o si ya se usó (`minimo_paso`: el último aceptado)."""
    codigo = (codigo or "").strip().replace(" ", "")
    if len(codigo) != 6 or not codigo.isdigit():
        return None
    actual = _paso_actual()
    for paso in (actual - 1, actual, actual + 1):
        if paso > minimo_paso and hmac.compare_digest(codigo_totp(secreto, paso), codigo):
            return paso
    return None


def _hash_recuperacion(codigo: str) -> str:
    return hashlib.sha256(("rec:" + clave_secreta() + codigo.strip().lower().replace("-", "")).encode()).hexdigest()


def activar_2fa(admin_id: int, secreto: str, codigo: str) -> list[str]:
    """Confirma el alta del segundo factor con un código válido y devuelve los códigos de
    recuperación (se muestran UNA vez; solo se guarda su hash)."""
    paso = comprobar_codigo_totp(secreto, codigo)
    if paso is None:
        raise ValueError("El código no es correcto. Comprueba la hora del móvil y vuelve a probar.")
    codigos = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(CODIGOS_RECUPERACION)]
    conn = conectar()
    try:
        conn.execute(
            "UPDATE admins SET totp_secreto = ?, totp_activo = 1, totp_ultimo_paso = ?, codigos_recuperacion = ? WHERE id = ?",
            (_fernet().encrypt(secreto.encode()).decode(), paso, json.dumps([_hash_recuperacion(c) for c in codigos]), admin_id),
        )
        conn.commit()
    finally:
        conn.close()
    return codigos


def desactivar_2fa(admin_id: int) -> None:
    conn = conectar()
    try:
        conn.execute(
            "UPDATE admins SET totp_secreto = NULL, totp_activo = 0, totp_ultimo_paso = 0, codigos_recuperacion = NULL WHERE id = ?",
            (admin_id,),
        )
        conn.commit()
    finally:
        conn.close()


def verificar_segundo_factor(admin_id: int, codigo: str, ip: str) -> tuple[sqlite3.Row | None, str | None]:
    """Segundo paso del acceso: código TOTP o uno de recuperación (de un solo uso).
    Comparte el bloqueo por intentos con la contraseña."""
    conn = conectar()
    try:
        admin = conn.execute("SELECT * FROM admins WHERE id = ? AND activo = 1", (admin_id,)).fetchone()
        if admin is None or not admin["totp_activo"]:
            return None, "incorrectas"
        clave_intentos = "2fa:" + admin["usuario"]
        if bloqueado(conn, clave_intentos, ip):
            return None, "bloqueado"
        codigo = (codigo or "").strip()
        secreto = _fernet().decrypt(admin["totp_secreto"].encode()).decode()
        paso = comprobar_codigo_totp(secreto, codigo, admin["totp_ultimo_paso"])
        if paso is not None:
            conn.execute("UPDATE admins SET totp_ultimo_paso = ? WHERE id = ?", (paso, admin_id))
            conn.execute("DELETE FROM intentos_login WHERE usuario = ?", (clave_intentos,))
            conn.commit()
            return admin, None
        hashes = json.loads(admin["codigos_recuperacion"] or "[]")
        candidato = _hash_recuperacion(codigo)
        if candidato in hashes and len(codigo.replace("-", "")) == 8:
            hashes.remove(candidato)
            conn.execute("UPDATE admins SET codigos_recuperacion = ? WHERE id = ?", (json.dumps(hashes), admin_id))
            conn.execute("DELETE FROM intentos_login WHERE usuario = ?", (clave_intentos,))
            conn.commit()
            return admin, "recuperacion"
        conn.execute("INSERT INTO intentos_login (usuario, ip, creado_en) VALUES (?, ?, ?)", (clave_intentos, ip, _ahora()))
        conn.commit()
        return None, "incorrectas"
    finally:
        conn.close()


def obtener_admin(admin_id: int) -> sqlite3.Row | None:
    conn = conectar()
    try:
        return conn.execute("SELECT * FROM admins WHERE id = ? AND activo = 1", (admin_id,)).fetchone()
    finally:
        conn.close()


def auditar(accion: str, detalle: str | None = None) -> None:
    """Registro de acciones del backoffice (quién, qué, desde qué IP). Nunca
    rompe la acción que audita."""
    try:
        conn = conectar()
        try:
            admin = g.get("admin")
            conn.execute(
                "INSERT INTO auditoria (admin_id, admin_usuario, accion, detalle, ip, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
                (admin["id"] if admin else None, admin["usuario"] if admin else None, accion, detalle, ip_cliente(), _ahora()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def listar_auditoria(limite: int = 200) -> list[sqlite3.Row]:
    conn = conectar()
    try:
        return conn.execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    finally:
        conn.close()


# --- Sesión, CSRF y decoradores ---------------------------------------------

def ip_cliente() -> str:
    return request.remote_addr or "desconocida"


def iniciar_sesion(admin: sqlite3.Row) -> None:
    session.clear()  # nueva sesión: evita fijación de sesión
    ahora = int(time.time())
    session["admin_id"] = admin["id"]
    # Hasta cumplir lo que falte (cambiar una contraseña caducada o activar el 2FA si es
    # obligatorio) solo se puede entrar en «Mi cuenta».
    caduca = dias_para_caducar(admin)
    if caduca is not None and caduca < 0:
        session["forzar"] = "clave"
    elif segundo_factor_obligatorio() and not admin["totp_activo"]:
        session["forzar"] = "2fa"
    session["inicio"] = ahora
    session["visto"] = ahora
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = False


def cerrar_sesion() -> None:
    session.clear()


def token_csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def comprobar_csrf() -> None:
    enviado = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
    esperado = session.get("csrf") or ""
    if not esperado or not hmac.compare_digest(enviado, esperado):
        abort(400, "Petición no válida (token CSRF).")


def sesion_valida() -> bool:
    admin_id = session.get("admin_id")
    if not admin_id:
        return False
    ahora = int(time.time())
    if ahora - session.get("inicio", 0) > SESION_MAX_HORAS * 3600:
        return False
    if ahora - session.get("visto", 0) > INACTIVIDAD_MAX_MIN * 60:
        return False
    admin = obtener_admin(admin_id)
    if admin is None:
        return False
    session["visto"] = ahora
    g.admin = admin
    return True


ENDPOINTS_CUENTA = ("rutas.cuenta", "rutas.cuenta_clave", "rutas.cuenta_2fa_activar", "rutas.cuenta_2fa_confirmar",
                    "rutas.cuenta_2fa_desactivar", "rutas.logout")


def login_required(vista):
    @wraps(vista)
    def decorada(*args, **kwargs):
        if not sesion_valida():
            for clave in ("admin_id", "inicio", "visto", "forzar"):
                session.pop(clave, None)  # conserva la verificación en dos pasos en curso, si la hay
            return redirect(url_for("rutas.login", siguiente=request.path if request.method == "GET" else None))
        if session.get("forzar") and request.endpoint not in ENDPOINTS_CUENTA:
            return redirect(url_for("rutas.cuenta"))
        return vista(*args, **kwargs)
    return decorada
