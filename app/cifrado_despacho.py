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
import contextvars
import hashlib
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
    frase_cambiada_en TEXT,
    correo_activo INTEGER NOT NULL DEFAULT 0,
    correo_activado_en TEXT
);
CREATE TABLE IF NOT EXISTS accesos_contenido (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    usuario_id INTEGER,
    documento_id INTEGER NOT NULL,
    via TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    tabla TEXT NOT NULL DEFAULT 'documentos'
);
CREATE INDEX IF NOT EXISTS idx_accesos_contenido_tenant ON accesos_contenido(tenant_id, id DESC);
CREATE TABLE IF NOT EXISTS concesiones_clave (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('token', 'oauth')),
    referencia TEXT NOT NULL UNIQUE,
    etiqueta TEXT NOT NULL,
    envoltura TEXT NOT NULL,
    creada_por INTEGER REFERENCES usuarios(id),
    creada_en TEXT NOT NULL,
    caduca_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_concesiones_tenant ON concesiones_clave(tenant_id);
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


_AL_BLOQUEAR: list = []      # funciones `f(tenant_id | None)` que olvidan lo descifrado (p. ej. la caché del correo); `None` = todos


def al_bloquear(funcion) -> None:
    _AL_BLOQUEAR.append(funcion)


def bloquear(tenant_id: int) -> None:
    with _cerrojo:
        _DESBLOQUEOS.pop(tenant_id, None)
    for f in _AL_BLOQUEAR:
        f(tenant_id)


def bloquear_todo() -> None:
    with _cerrojo:
        _DESBLOQUEOS.clear()
        _FALLOS.clear()
    for f in _AL_BLOQUEAR:
        f(None)


def privada_disponible(tenant_id: int) -> bytes | None:
    """La clave privada del despacho si ahora mismo se puede usar: despacho desbloqueado, o la petición en curso trae una concesión válida. Si no, None."""
    return _privada_desbloqueada(tenant_id) or _privada_por_concesion(tenant_id)


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
        sin = sum(conn.execute(f"SELECT COUNT(*) FROM {tabla} WHERE tenant_id = ? AND cifrado = 0", (tenant_id,)).fetchone()[0] for tabla in ("documentos", "cliente_documentos"))
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


def rotar_clave(tenant_id: int, usuario_id: int, frase: str) -> str:
    """Cambia el par de claves del despacho: genera uno nuevo, **re-cifra todo el contenido** y estrena clave de recuperación (la anterior deja de valer). Para cuando se sospeche
    que la clave se ha visto comprometida; cambiar solo la frase no hace falta re-cifrar nada. Exige la frase actual. Las concesiones se **revocan todas** (envolvían la
    clave antigua): hay que volver a darlas. Todo en una transacción. Devuelve la nueva clave de recuperación, que solo se muestra esta vez."""
    from . import almacen_documentos
    desbloquear(tenant_id, usuario_id, frase)
    vieja = _privada_desbloqueada(tenant_id)
    nueva_privada, nueva_publica = generar_par()
    recuperacion = nueva_clave_de_recuperacion()
    frase_protegida, recuperacion_protegida = proteger_con_frase(nueva_privada, frase), proteger_con_recuperacion(nueva_privada, recuperacion)

    def guardar_clave(conn):
        conn.execute("UPDATE cifrado_despacho SET publica = ?, privada_frase = ?, privada_recuperacion = ?, frase_cambiada_en = ? WHERE tenant_id = ?",
                     (_b64(nueva_publica), frase_protegida, recuperacion_protegida, db.now_iso(), tenant_id))
        conn.execute("DELETE FROM concesiones_clave WHERE tenant_id = ?", (tenant_id,))

    def guardar_todo(conn):
        from . import correo_cifrado
        correo_cifrado.resellar(conn, tenant_id, lambda c, sobre: abrir_con_privada(vieja, c, sobre), lambda c: sellar_con_publica(nueva_publica, c))
        guardar_clave(conn)

    almacen_documentos.resellar(tenant_id, lambda c, sobre: abrir_con_privada(vieja, c, sobre), lambda c: sellar_con_publica(nueva_publica, c), guardar_todo)
    from . import correo_cifrado
    correo_cifrado.olvidar_configuracion(); correo_cifrado.olvidar(tenant_id)
    _desbloquear_en_memoria(tenant_id, usuario_id, nueva_privada)
    return recuperacion


def registrar_acceso(tenant_id: int, usuario_id: int | None, documento_id: int, via: str, tabla: str = "documentos") -> None:
    """Quién abrió qué documento cifrado, y por qué vía (persona, enlace, asistente...). Nunca debe romper la lectura."""
    try:
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO accesos_contenido (tenant_id, usuario_id, documento_id, via, creado_en, tabla) VALUES (?, ?, ?, ?, ?, ?)", (tenant_id, usuario_id, documento_id, via[:30], db.now_iso(), tabla))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 -- es un rastro: no puede impedir lo que se está haciendo
        pass


def accesos_recientes(tenant_id: int, limite: int = 100) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT a.*, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS persona, COALESCE(d.nombre_archivo, f.nombre_archivo) AS nombre_archivo FROM accesos_contenido a "
            "LEFT JOIN usuarios u ON u.id = a.usuario_id LEFT JOIN usuario_perfil p ON p.usuario_id = a.usuario_id "
            "LEFT JOIN documentos d ON a.tabla = 'documentos' AND d.id = a.documento_id LEFT JOIN cliente_documentos f ON a.tabla = 'cliente_documentos' AND f.id = a.documento_id WHERE a.tenant_id = ? ORDER BY a.id DESC LIMIT ?",
            (tenant_id, max(1, min(limite, 500)))).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def borrar_datos_de_tenant(conn, tenant_id: int) -> None:
    conn.execute("DELETE FROM cifrado_despacho WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM concesiones_clave WHERE tenant_id = ?", (tenant_id,))
    conn.execute("DELETE FROM accesos_contenido WHERE tenant_id = ?", (tenant_id,))


# --- Concesiones: acceso de API, MCP y OAuth a lo cifrado -------------------------------------------------------------------------------------------
# Una concesión es la clave privada del despacho **envuelta con un secreto que solo tiene quien accede** (el propio token de API, o un secreto que
# viaja dentro del token OAuth). El servidor guarda la envoltura, no el secreto: sin el token no se puede abrir, y revocar = borrar la fila. Se crea
# en un momento en que el despacho está desbloqueado (alguien con la frase) y a partir de ahí sirve **aunque esté bloqueado**.
_CONCESION: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar("_concesion_clave", default=None)


def fijar_concesion(canal: str, secreto: str | None):
    """Anota, para la petición en curso, con qué secreto puede intentar abrir una concesión (y por qué canal: api, mcp). Devuelve el testigo para `restablecer`."""
    return _CONCESION.set((canal, secreto) if secreto else None)


def restablecer_concesion(testigo=None) -> None:
    _CONCESION.set(None) if testigo is None else _CONCESION.reset(testigo)


def canal_actual() -> str | None:
    c = _CONCESION.get()
    return c[0] if c else None


def _referencia(secreto: str) -> str:
    return hashlib.sha256(secreto.encode("utf-8")).hexdigest()


def _clave_de_concesion(secreto: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"guilda-concesion-v1").derive(secreto.encode("utf-8"))


def crear_concesion(tenant_id: int, usuario_id: int, secreto: str, tipo: str, etiqueta: str, caduca_en: str | None = None) -> int:
    """Autoriza a quien tenga `secreto` a leer lo cifrado de este despacho. Exige el despacho desbloqueado ahora mismo."""
    if tipo not in ("token", "oauth"):
        raise ValueError("Tipo de concesión no válido.")
    if not esta_activo(tenant_id):
        raise ValueError("El cifrado de este despacho no está activado.")
    privada = _privada_desbloqueada(tenant_id)
    if privada is None:
        raise DespachoBloqueado("Para dar acceso a lo cifrado hay que desbloquear antes los documentos con la frase de paso.")
    nonce = os.urandom(12)
    envoltura = json.dumps({"v": 1, "n": _b64(nonce), "ct": _b64(AESGCM(_clave_de_concesion(secreto)).encrypt(nonce, privada, b"guilda-concesion"))})
    conn = db.get_connection()
    try:
        cur = conn.execute("INSERT INTO concesiones_clave (tenant_id, tipo, referencia, etiqueta, envoltura, creada_por, creada_en, caduca_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (tenant_id, tipo, _referencia(secreto), (etiqueta or "")[:80] or tipo, envoltura, usuario_id, db.now_iso(), caduca_en))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _privada_por_concesion(tenant_id: int) -> bytes | None:
    c = _CONCESION.get()
    if c is None:
        return None
    secreto = c[1]
    conn = db.get_connection()
    try:
        f = conn.execute("SELECT * FROM concesiones_clave WHERE tenant_id = ? AND referencia = ?", (tenant_id, _referencia(secreto))).fetchone()
        if f is None or (f["caduca_en"] and f["caduca_en"] <= db.now_iso()):
            return None
        if f["tipo"] == "token" and conn.execute("SELECT 1 FROM tokens_api WHERE token_hash = ?", (_referencia(secreto),)).fetchone() is None:
            return None            # el token se revocó o caducó por inactividad: la concesión ya no vale
    finally:
        conn.close()
    try:
        d = json.loads(f["envoltura"])
        return AESGCM(_clave_de_concesion(secreto)).decrypt(_de_b64(d["n"]), _de_b64(d["ct"]), b"guilda-concesion")
    except (InvalidTag, ValueError, KeyError):
        return None


def listar_concesiones(tenant_id: int) -> list[dict]:
    conn = db.get_connection()
    try:
        filas = conn.execute(
            "SELECT c.id, c.tipo, c.etiqueta, c.creada_en, c.caduca_en, COALESCE(NULLIF(p.nombre_mostrado, ''), u.email) AS creada_por_nombre, "
            "(c.tipo = 'token' AND NOT EXISTS (SELECT 1 FROM tokens_api t WHERE t.token_hash = c.referencia)) AS huerfana "
            "FROM concesiones_clave c LEFT JOIN usuarios u ON u.id = c.creada_por LEFT JOIN usuario_perfil p ON p.usuario_id = c.creada_por "
            "WHERE c.tenant_id = ? ORDER BY c.id DESC", (tenant_id,)).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def revocar_concesion(tenant_id: int, concesion_id: int) -> bool:
    """Efecto inmediato: sin envoltura no hay forma de abrir nada con ese secreto."""
    conn = db.get_connection()
    try:
        cur = conn.execute("DELETE FROM concesiones_clave WHERE id = ? AND tenant_id = ?", (concesion_id, tenant_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def tiene_concesion(tenant_id: int) -> bool:
    """¿La petición en curso trae una concesión válida para este despacho?"""
    return _privada_por_concesion(tenant_id) is not None


# --- El `Cifrador` que usa app/almacen_documentos.py ------------------------------------------------------------------------------------------------
class CifradorDespacho:
    """Cifra con la pública del despacho si lo tiene activado; si no, deja el contenido tal cual (sobre vacío = sin cifrar)."""

    def sellar(self, tenant_id: int, contenido: bytes) -> tuple[bytes, str]:
        c = _config(tenant_id)
        if c is None:
            return contenido, ""
        return sellar_con_publica(_de_b64(c["publica"]), contenido)

    def abrir(self, tenant_id: int, contenido: bytes, sobre: str) -> bytes:
        privada = _privada_desbloqueada(tenant_id) or _privada_por_concesion(tenant_id)      # la concesión sirve aunque el despacho esté bloqueado
        if privada is None:
            raise DespachoBloqueado("Los documentos de este despacho están protegidos con su clave: hay que desbloquearlos con la frase de paso.")
        return abrir_con_privada(privada, contenido, sobre)
