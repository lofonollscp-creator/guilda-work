"""Cifrado de documentos con la clave del despacho (PLAN_MAESTRO.md §8.1).

Diseño (cifrado de sobre con clave pública):
  - Cada despacho tiene un par X25519. La **pública** se guarda en claro y sirve para cifrar SIN desbloqueo (por eso un documento que llega de madrugada se
    cifra igual). La **privada** solo existe cifrada, de dos formas: con la **frase de paso** (Argon2id) y con la **clave de recuperación** impresa.
  - Cada documento lleva su propia clave de datos AES-256-GCM; esa clave se cifra con la pública del despacho (ECIES: X25519 efímera + HKDF + AES-GCM).
    El «sobre» (texto JSON) viaja junto al documento y no es secreto por sí mismo.
  - **Desbloquear** = descifrar la privada con la frase (o con la clave de recuperación) y guardarla **solo en la memoria del proceso**, con caducidad que se
    renueva con el uso. Nunca va a disco, a logs ni a copias. Reiniciar el servicio bloquea todos los despachos.
  - Sin desbloqueo se puede **escribir** pero no **leer**: leer lanza `DespachoBloqueado`, que la aplicación convierte en un aviso claro (423), no en vacío.

Garantía y límites (decirlo así en la política de privacidad): protege el contenido **en reposo y en las copias de seguridad**; el servidor sí ve el contenido
en el instante en que entra (llega en claro) y mientras el despacho está desbloqueado. Perder la frase y la clave de recuperación hace los documentos
irrecuperables. El desbloqueo es **del despacho** (no de una sesión concreta): cualquier persona autorizada del despacho, y el asistente de IA interno, leen
mientras esté desbloqueado.

Hoy cifra el contenido de `documentos`. El nivel (laxo, medio, estricto) se guarda ya, pero solo gobierna los metadatos y el correo, que entran en la semana 2."""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from . import db

NIVELES = ("laxo", "medio", "estricto")
FRASE_MINIMA = 12
TTL_DESBLOQUEO_SEGUNDOS = 4 * 3600
INTENTOS_MAXIMOS = 5
VENTANA_INTENTOS_SEGUNDOS = 15 * 60
ARGON2 = {"time_cost": 3, "memory_cost": 64 * 1024, "parallelism": 4}   # 64 MiB; los tests lo reducen

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cifrado_despacho (
    tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id),
    nivel TEXT NOT NULL DEFAULT 'medio',
    publica TEXT NOT NULL,
    privada_frase TEXT NOT NULL,
    privada_recuperacion TEXT NOT NULL,
    activado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT NOT NULL,
    frase_cambiada_en TEXT
);
CREATE TABLE IF NOT EXISTS accesos_contenido (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    usuario_id INTEGER,
    documento_id INTEGER NOT NULL,
    via TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accesos_contenido_tenant ON accesos_contenido(tenant_id, id DESC);
"""


class DespachoBloqueado(RuntimeError):
    """El documento está cifrado y el despacho no está desbloqueado."""


class ClaveIncorrecta(Exception):
    pass


class DemasiadosIntentos(Exception):
    pass


class ContenidoAlterado(Exception):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _de_b64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


# --- Primitivas (sin base de datos: se prueban solas) -----------------------------------------------------------------------------------------------
def generar_par() -> tuple[bytes, bytes]:
    """(privada, pública) en bruto, 32 bytes cada una."""
    priv = X25519PrivateKey.generate()
    return priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()), priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _clave_de_envoltura(secreto_compartido: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"guilda-dek-v1").derive(secreto_compartido)


def sellar_con_publica(publica: bytes, contenido: bytes) -> tuple[bytes, str]:
    """(contenido cifrado, sobre). No necesita la clave privada."""
    dek, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    cifrado = AESGCM(dek).encrypt(nonce, contenido, b"guilda-doc-v1")
    efimera = X25519PrivateKey.generate()
    kek = _clave_de_envoltura(efimera.exchange(X25519PublicKey.from_public_bytes(publica)))
    nonce_dek = os.urandom(12)
    sobre = {"v": 1, "epk": _b64(efimera.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)), "nd": _b64(nonce_dek),
             "dek": _b64(AESGCM(kek).encrypt(nonce_dek, dek, b"guilda-dek-v1")), "n": _b64(nonce)}
    return cifrado, json.dumps(sobre, separators=(",", ":"))


def abrir_con_privada(privada: bytes, cifrado: bytes, sobre: str) -> bytes:
    try:
        s = json.loads(sobre)
        kek = _clave_de_envoltura(X25519PrivateKey.from_private_bytes(privada).exchange(X25519PublicKey.from_public_bytes(_de_b64(s["epk"]))))
        dek = AESGCM(kek).decrypt(_de_b64(s["nd"]), _de_b64(s["dek"]), b"guilda-dek-v1")
        return AESGCM(dek).decrypt(_de_b64(s["n"]), cifrado, b"guilda-doc-v1")
    except (InvalidTag, KeyError, ValueError) as e:
        raise ContenidoAlterado("El contenido no se puede verificar: se ha alterado o la clave no corresponde.") from e


def _derivar_de_frase(frase: str, sal: bytes, params: dict) -> bytes:
    return hash_secret_raw(frase.encode("utf-8"), sal, time_cost=params["time_cost"], memory_cost=params["memory_cost"], parallelism=params["parallelism"], hash_len=32, type=Type.ID)


def proteger_con_frase(privada: bytes, frase: str) -> str:
    sal, nonce, params = os.urandom(16), os.urandom(12), dict(ARGON2)
    ct = AESGCM(_derivar_de_frase(frase, sal, params)).encrypt(nonce, privada, b"guilda-privada-frase")
    return json.dumps({"v": 1, "sal": _b64(sal), "n": _b64(nonce), "ct": _b64(ct), **params})


def abrir_con_frase(protegida: str, frase: str) -> bytes:
    d = json.loads(protegida)
    try:
        return AESGCM(_derivar_de_frase(frase, _de_b64(d["sal"]), d)).decrypt(_de_b64(d["n"]), _de_b64(d["ct"]), b"guilda-privada-frase")
    except InvalidTag as e:
        raise ClaveIncorrecta("Frase incorrecta.") from e


def nueva_clave_de_recuperacion() -> str:
    """40 caracteres en base32 (200 bits) en grupos de cuatro, para imprimir y guardar."""
    crudo = base64.b32encode(secrets.token_bytes(25)).decode("ascii")
    return "-".join(crudo[i:i + 4] for i in range(0, 40, 4))


def _bytes_de_recuperacion(clave: str) -> bytes:
    limpia = "".join(c for c in (clave or "").upper() if c.isalnum())
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"guilda-recuperacion-v1").derive(limpia.encode("ascii", "ignore"))


def proteger_con_recuperacion(privada: bytes, clave: str) -> str:
    nonce = os.urandom(12)
    return json.dumps({"v": 1, "n": _b64(nonce), "ct": _b64(AESGCM(_bytes_de_recuperacion(clave)).encrypt(nonce, privada, b"guilda-privada-recuperacion"))})


def abrir_con_recuperacion(protegida: str, clave: str) -> bytes:
    d = json.loads(protegida)
    try:
        return AESGCM(_bytes_de_recuperacion(clave)).decrypt(_de_b64(d["n"]), _de_b64(d["ct"]), b"guilda-privada-recuperacion")
    except InvalidTag as e:
        raise ClaveIncorrecta("Clave de recuperación incorrecta.") from e


# --- Estado en memoria: desbloqueos e intentos fallidos ---------------------------------------------------------------------------------------------
_cerrojo = threading.Lock()
_DESBLOQUEOS: dict[int, dict] = {}
_FALLOS: dict[int, list[float]] = {}


def _comprobar_intentos(tenant_id: int) -> None:
    ahora = time.monotonic()
    with _cerrojo:
        recientes = [t for t in _FALLOS.get(tenant_id, []) if ahora - t < VENTANA_INTENTOS_SEGUNDOS]
        _FALLOS[tenant_id] = recientes
        if len(recientes) >= INTENTOS_MAXIMOS:
            raise DemasiadosIntentos("Demasiados intentos fallidos. Espera unos minutos antes de volver a probar.")


def _fallo(tenant_id: int) -> None:
    with _cerrojo:
        _FALLOS.setdefault(tenant_id, []).append(time.monotonic())


def _desbloquear_en_memoria(tenant_id: int, usuario_id: int | None, privada: bytes) -> None:
    with _cerrojo:
        _FALLOS.pop(tenant_id, None)
        _DESBLOQUEOS[tenant_id] = {"privada": privada, "usuario_id": usuario_id, "expira": time.monotonic() + TTL_DESBLOQUEO_SEGUNDOS, "desde": db.now_iso()}


def _privada_desbloqueada(tenant_id: int) -> bytes | None:
    with _cerrojo:
        d = _DESBLOQUEOS.get(tenant_id)
        if d is None:
            return None
        if time.monotonic() > d["expira"]:
            _DESBLOQUEOS.pop(tenant_id, None)
            return None
        d["expira"] = time.monotonic() + TTL_DESBLOQUEO_SEGUNDOS      # el uso renueva la caducidad
        return d["privada"]


def bloquear(tenant_id: int) -> None:
    with _cerrojo:
        _DESBLOQUEOS.pop(tenant_id, None)


def bloquear_todo() -> None:
    with _cerrojo:
        _DESBLOQUEOS.clear()
        _FALLOS.clear()


# --- Configuración por despacho ---------------------------------------------------------------------------------------------------------------------
def _config(tenant_id: int):
    conn = db.get_connection()
    try:
        return conn.execute("SELECT * FROM cifrado_despacho WHERE tenant_id = ?", (tenant_id,)).fetchone()
    finally:
        conn.close()


def esta_activo(tenant_id: int) -> bool:
    return _config(tenant_id) is not None


def estado(tenant_id: int) -> dict:
    c = _config(tenant_id)
    if c is None:
        return {"activo": False, "desbloqueado": False, "nivel": None, "documentos_sin_cifrar": 0}
    with _cerrojo:
        d = _DESBLOQUEOS.get(tenant_id)
        vivo = d is not None and time.monotonic() <= d["expira"]
        quien = d["usuario_id"] if vivo else None
    conn = db.get_connection()
    try:
        sin = conn.execute("SELECT COUNT(*) FROM documentos WHERE tenant_id = ? AND cifrado = 0", (tenant_id,)).fetchone()[0]
    finally:
        conn.close()
    return {"activo": True, "desbloqueado": vivo, "nivel": c["nivel"], "desbloqueado_por": quien, "activado_en": c["creado_en"], "documentos_sin_cifrar": sin}


def _validar_frase(frase: str) -> None:
    if len(frase or "") < FRASE_MINIMA:
        raise ValueError(f"La frase de paso debe tener al menos {FRASE_MINIMA} caracteres. Una frase de varias palabras es más fácil de recordar y más segura.")


def activar(tenant_id: int, usuario_id: int, frase: str, nivel: str = "medio") -> str:
    """Activa el cifrado del despacho y cifra lo que ya hubiera guardado. Devuelve la **clave de recuperación**, que solo se muestra esta vez.
    Deja el despacho desbloqueado para quien lo activa."""
    if esta_activo(tenant_id):
        raise ValueError("El cifrado de este despacho ya está activado.")
    if nivel not in NIVELES:
        raise ValueError("Nivel de reserva no válido.")
    _validar_frase(frase)
    privada, publica = generar_par()
    recuperacion = nueva_clave_de_recuperacion()
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO cifrado_despacho (tenant_id, nivel, publica, privada_frase, privada_recuperacion, activado_por, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (tenant_id, nivel, _b64(publica), proteger_con_frase(privada, frase), proteger_con_recuperacion(privada, recuperacion), usuario_id, db.now_iso()))
        conn.commit()
    finally:
        conn.close()
    _desbloquear_en_memoria(tenant_id, usuario_id, privada)
    cifrar_existentes(tenant_id)
    return recuperacion


def cifrar_existentes(tenant_id: int) -> int:
    """Cifra los documentos del despacho que se guardaron antes de activar el cifrado (no necesita desbloqueo). La escritura la hace el almacén de documentos."""
    from . import almacen_documentos
    return almacen_documentos.sellar_pendientes(tenant_id) if esta_activo(tenant_id) else 0


def desbloquear(tenant_id: int, usuario_id: int, frase: str) -> None:
    c = _config(tenant_id)
    if c is None:
        raise ValueError("El cifrado de este despacho no está activado.")
    _comprobar_intentos(tenant_id)
    try:
        privada = abrir_con_frase(c["privada_frase"], frase or "")
    except ClaveIncorrecta:
        _fallo(tenant_id)
        raise
    _desbloquear_en_memoria(tenant_id, usuario_id, privada)


def recuperar(tenant_id: int, usuario_id: int, clave_recuperacion: str, frase_nueva: str) -> None:
    """Con la clave de recuperación: desbloquea y fija una frase nueva (la anterior deja de valer)."""
    c = _config(tenant_id)
    if c is None:
        raise ValueError("El cifrado de este despacho no está activado.")
    _validar_frase(frase_nueva)
    _comprobar_intentos(tenant_id)
    try:
        privada = abrir_con_recuperacion(c["privada_recuperacion"], clave_recuperacion)
    except ClaveIncorrecta:
        _fallo(tenant_id)
        raise
    _guardar_frase(tenant_id, privada, frase_nueva)
    _desbloquear_en_memoria(tenant_id, usuario_id, privada)


def cambiar_frase(tenant_id: int, usuario_id: int, frase_actual: str, frase_nueva: str) -> None:
    desbloquear(tenant_id, usuario_id, frase_actual)
    _validar_frase(frase_nueva)
    _guardar_frase(tenant_id, _privada_desbloqueada(tenant_id), frase_nueva)


def _guardar_frase(tenant_id: int, privada: bytes, frase: str) -> None:
    conn = db.get_connection()
    try:
        conn.execute("UPDATE cifrado_despacho SET privada_frase = ?, frase_cambiada_en = ? WHERE tenant_id = ?", (proteger_con_frase(privada, frase), db.now_iso(), tenant_id))
        conn.commit()
    finally:
        conn.close()


def registrar_acceso(tenant_id: int, usuario_id: int | None, documento_id: int, via: str) -> None:
    """Quién abrió qué documento cifrado, y por qué vía (persona, enlace, asistente...). Nunca debe romper la lectura."""
    try:
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO accesos_contenido (tenant_id, usuario_id, documento_id, via, creado_en) VALUES (?, ?, ?, ?, ?)", (tenant_id, usuario_id, documento_id, via[:30], db.now_iso()))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 -- es un rastro: no puede impedir lo que se está haciendo
        pass


def accesos_recientes(tenant_id: int, limite: int = 100) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT a.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS persona, d.nombre_archivo FROM accesos_contenido a LEFT JOIN usuarios u ON u.id = a.usuario_id "
            "LEFT JOIN usuario_perfil p ON p.usuario_id = a.usuario_id LEFT JOIN documentos d ON d.id = a.documento_id WHERE a.tenant_id = ? ORDER BY a.id DESC LIMIT ?",
            (tenant_id, max(1, min(limite, 500)))).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM cifrado_despacho WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM accesos_contenido WHERE tenant_id = ?", (tenant_id,))


# --- El `Cifrador` que usa app/almacen_documentos.py ------------------------------------------------------------------------------------------------
class CifradorDespacho:
    """Cifra con la pública del despacho si lo tiene activado; si no, deja el contenido tal cual (sobre vacío = sin cifrar)."""

    def sellar(self, tenant_id: int, contenido: bytes) -> tuple[bytes, str]:
        c = _config(tenant_id)
        if c is None:
            return contenido, ""
        return sellar_con_publica(_de_b64(c["publica"]), contenido)

    def abrir(self, tenant_id: int, contenido: bytes, sobre: str) -> bytes:
        privada = _privada_desbloqueada(tenant_id)
        if privada is None:
            raise DespachoBloqueado("Los documentos de este despacho están protegidos con su clave: hay que desbloquearlos con la frase de paso.")
        return abrir_con_privada(privada, contenido, sobre)
