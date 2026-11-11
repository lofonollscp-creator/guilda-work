"""Passkeys del portal: entrar con la huella, la cara o el PIN del dispositivo, sin esperar el correo ni escribir nada.

Es WebAuthn con credenciales «descubribles»: el navegador ofrece las passkeys de este sitio y la persona elige, sin teclear su email. Se exige verificación de usuario (huella/PIN), así que una passkey vale como entrada con
segundo factor y no se pide el código de la aplicación de autenticación. El enlace del correo sigue funcionando siempre: es el respaldo si se pierde el dispositivo. Una passkey se registra desde «Mi cuenta» y es de
una persona (su email) para un cliente; se puede quitar cuando se quiera. Los desafíos viajan en la sesión firmada y caducan a los 5 minutos."""
from __future__ import annotations

import hashlib
import json
import os
import logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS portal_passkeys (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cliente_fiscal_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    credencial_id TEXT NOT NULL,
    clave_publica TEXT NOT NULL,
    contador INTEGER NOT NULL DEFAULT 0,
    transportes TEXT NOT NULL DEFAULT '',
    nombre TEXT NOT NULL DEFAULT '',
    rp_id TEXT NOT NULL DEFAULT '',
    creada_en TEXT NOT NULL,
    ultimo_uso TEXT,
    UNIQUE (tenant_id, credencial_id)
);
CREATE INDEX IF NOT EXISTS idx_portal_passkeys_credencial ON portal_passkeys(credencial_id);
CREATE INDEX IF NOT EXISTS idx_portal_passkeys_persona ON portal_passkeys(tenant_id, cliente_fiscal_id, email);
"""

logger = logging.getLogger("guilda")

RP_NOMBRE = "Guilda Work"
VIGENCIA_DESAFIO = timedelta(minutes=5)
MAX_POR_PERSONA = 10
MAX_NOMBRE = 60


class ErrorPasskey(ValueError):
    """Algo no cuadró al registrar o usar una passkey; el mensaje es apto para enseñarlo."""


def crear_esquema(conn) -> None:
    conn.executescript(ESQUEMA)
    db._asegurar_columna(conn, "portal_passkeys", "rp_id", "TEXT NOT NULL DEFAULT ''")          # el dominio en el que se creó: una passkey solo funciona en él


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _email(e: str | None) -> str:
    return (e or "").strip().lower()


def contexto(base_url: str) -> tuple[str, str]:
    """(rp_id, origen) a partir de la dirección pública del portal: el rp_id es el dominio, sin puerto."""
    partes = urlsplit(base_url)
    return partes.hostname or "localhost", f"{partes.scheme}://{partes.netloc}"


def _usuario_id(cliente_id: int, email: str) -> bytes:
    return hashlib.sha256(f"guilda-portal:{cliente_id}:{_email(email)}".encode()).digest()[:32]


def _guardar_desafio(sesion, clave: str, desafio: bytes, extra: dict | None = None) -> None:
    sesion[clave] = {"c": desafio.hex(), "hasta": (datetime.now() + VIGENCIA_DESAFIO).isoformat(timespec="seconds"), **(extra or {})}


def _tomar_desafio(sesion, clave: str) -> tuple[bytes, dict]:
    d = sesion.pop(clave, None)
    if not d or datetime.fromisoformat(d["hasta"]) < datetime.now():
        raise ErrorPasskey("Se ha agotado el tiempo. Inténtalo de nuevo.")
    return bytes.fromhex(d["c"]), d


# --- Lo guardado --------------------------------------------------------------------------------------------------------------------------------------------

def listar(cliente, email: str) -> list[dict]:
    conn = db.get_connection()
    try:
        return [dict(f) for f in conn.execute("SELECT id, nombre, creada_en, ultimo_uso, rp_id FROM portal_passkeys WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ? ORDER BY id",
                                              (cliente["tenant_id"], cliente["id"], _email(email))).fetchall()]
    finally:
        conn.close()


def rp_de_origen_antiguo() -> str:
    """El dominio en el que se crearon las passkeys anteriores a registrar el dominio de cada una (rp_id vacío): la dirección pública de siempre."""
    return (urlsplit(os.environ.get("GUILDA_URL_PUBLICA", "").strip()).hostname or "").lower()


def funcionan_aqui(passkeys: list[dict], base_url: str) -> list[dict]:
    """Las passkeys que el navegador ofrecerá en esta dirección: las creadas en este mismo dominio (las anteriores se suponen de la dirección pública de siempre)."""
    aqui = contexto(base_url)[0].lower()
    antiguo = rp_de_origen_antiguo() or aqui
    return [k for k in passkeys if (k.get("rp_id") or antiguo).lower() == aqui]


def quitar(cliente, email: str, passkey_id: int) -> bool:
    conn = db.get_connection()
    try:
        n = conn.execute("DELETE FROM portal_passkeys WHERE id = ? AND tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (passkey_id, cliente["tenant_id"], cliente["id"], _email(email))).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def quitar_de_persona(cliente, email: str) -> None:
    """Al retirar a una persona del portal, sus passkeys dejan de valer."""
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM portal_passkeys WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], _email(email)))
        conn.commit()
    finally:
        conn.close()


# --- Alta (desde Mi cuenta) ---------------------------------------------------------------------------------------------------------------------------------

def opciones_registro(cliente, email: str, base_url: str, sesion) -> dict:
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement
    from webauthn.helpers import base64url_to_bytes
    if len(listar(cliente, email)) >= MAX_POR_PERSONA:
        raise ErrorPasskey("Ya tienes el máximo de passkeys. Quita alguna para añadir otra.")
    rp_id, _origen = contexto(base_url)
    conn = db.get_connection()
    try:
        ya = [f["credencial_id"] for f in conn.execute("SELECT credencial_id FROM portal_passkeys WHERE tenant_id = ? AND cliente_fiscal_id = ? AND email = ?", (cliente["tenant_id"], cliente["id"], _email(email))).fetchall()]
    finally:
        conn.close()
    opciones = generate_registration_options(
        rp_id=rp_id, rp_name=RP_NOMBRE, user_id=_usuario_id(cliente["id"], email), user_name=_email(email), user_display_name=cliente["nombre"][:60],
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in ya],
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED))
    _guardar_desafio(sesion, "pk_registro", opciones.challenge, {"cliente": cliente["id"], "email": _email(email)})
    return json.loads(options_to_json(opciones))


def verificar_registro(cliente, email: str, credencial: dict, nombre: str, base_url: str, sesion) -> int:
    from webauthn import verify_registration_response
    from webauthn.helpers import bytes_to_base64url
    desafio, datos = _tomar_desafio(sesion, "pk_registro")
    if datos.get("cliente") != cliente["id"] or datos.get("email") != _email(email):
        raise ErrorPasskey("Esa solicitud no era de tu cuenta. Inténtalo de nuevo.")
    rp_id, origen = contexto(base_url)
    try:
        r = verify_registration_response(credential=credencial, expected_challenge=desafio, expected_rp_id=rp_id, expected_origin=origen, require_user_verification=True)
    except Exception as e:  # noqa: BLE001 -- la librería lanza varias clases de error: todas significan «no vale»
        logger.info("Passkey rechazada al registrar: %r", e)
        raise ErrorPasskey("No hemos podido verificar la passkey. Inténtalo de nuevo.") from None
    transportes = ",".join(t for t in (credencial.get("response", {}).get("transports") or []) if isinstance(t, str))[:80]
    nombre = " ".join((nombre or "").split())[:MAX_NOMBRE] or "Passkey"
    conn = db.get_connection()
    try:
        if conn.execute("SELECT 1 FROM portal_passkeys WHERE credencial_id = ?", (bytes_to_base64url(r.credential_id),)).fetchone():
            raise ErrorPasskey("Esa passkey ya está registrada.")
        cur = conn.execute("INSERT INTO portal_passkeys (tenant_id, cliente_fiscal_id, email, credencial_id, clave_publica, contador, transportes, nombre, rp_id, creada_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (cliente["tenant_id"], cliente["id"], _email(email), bytes_to_base64url(r.credential_id), bytes_to_base64url(r.credential_public_key), r.sign_count, transportes, nombre, rp_id, _ahora()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --- Entrada ------------------------------------------------------------------------------------------------------------------------------------------------

def opciones_entrada(base_url: str, sesion) -> dict:
    """Sin lista de credenciales: el navegador enseña las passkeys que tenga para este sitio y la persona elige."""
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement
    rp_id, _origen = contexto(base_url)
    opciones = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    _guardar_desafio(sesion, "pk_entrada", opciones.challenge)
    return json.loads(options_to_json(opciones))


def verificar_entrada(credencial: dict, base_url: str, sesion) -> dict:
    """{cliente_fiscal_id, email} de la persona que se ha identificado con su passkey. `ErrorPasskey` si no vale."""
    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes
    desafio, _d = _tomar_desafio(sesion, "pk_entrada")
    cid = credencial.get("id") if isinstance(credencial, dict) else None
    if not isinstance(cid, str):
        raise ErrorPasskey("No se ha podido entrar con la passkey.")
    conn = db.get_connection()
    try:
        filas = conn.execute("SELECT id, tenant_id, cliente_fiscal_id, email, clave_publica, contador FROM portal_passkeys WHERE credencial_id = ?", (cid,)).fetchall()
    finally:
        conn.close()
    if not filas:
        raise ErrorPasskey("Esta passkey ya no está registrada. Entra con el enlace del correo.")
    rp_id, origen = contexto(base_url)
    f = r = None
    for fila in filas:                                   # el identificador es único por despacho, no entre despachos: la que firma de verdad es la que vale
        try:
            r = verify_authentication_response(credential=credencial, expected_challenge=desafio, expected_rp_id=rp_id, expected_origin=origen, credential_public_key=base64url_to_bytes(fila["clave_publica"]),
                                               credential_current_sign_count=fila["contador"], require_user_verification=True)
            f = fila
            break
        except Exception as e:  # noqa: BLE001
            logger.info("Passkey rechazada al entrar: %r", e)
    if f is None:
        raise ErrorPasskey("No se ha podido entrar con la passkey.")
    conn = db.get_connection()
    try:
        conn.execute("UPDATE portal_passkeys SET contador = ?, ultimo_uso = ? WHERE id = ? AND tenant_id = ?", (r.new_sign_count, _ahora(), f["id"], f["tenant_id"]))
        conn.commit()
    finally:
        conn.close()
    return {"cliente_fiscal_id": f["cliente_fiscal_id"], "email": f["email"]}
