"""Cuentas de correo con OAuth2 (Gmail y Microsoft 365 / Outlook): inicio de sesión en el proveedor con PKCE,
canje del código, token de refresco guardado en el almacén de credenciales (el mismo sitio que las
contraseñas) y tokens de acceso renovados cuando hacen falta. IMAP y SMTP entran con XOAUTH2.

Cada instalación registra su propia aplicación en Google Cloud / Azure y la configura por entorno
(ver HOSTING.md): GUILDA_OAUTH_GOOGLE_CLIENT_ID / _SECRET y GUILDA_OAUTH_MICROSOFT_CLIENT_ID / _SECRET
(+ GUILDA_OAUTH_MICROSOFT_TENANT, `common` por defecto). Sin configurar, la opción no aparece."""
import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import keyring

logger = logging.getLogger("guilda")

SERVICIO_KEYRING = "guilda-work-correo"
TIMEOUT = 15


class ErrorOAuth(Exception):
    """Error legible para el usuario."""


class TokenOAuth(str):
    """Token de acceso: las funciones de conexión lo distinguen de una contraseña normal."""


PROVEEDORES = {
    "google": {
        "nombre": "Gmail / Google Workspace",
        "autorizar": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scopes": "openid email https://mail.google.com/",
        "extra_autorizar": {"access_type": "offline", "prompt": "consent"},
        "imap": ("imap.gmail.com", 993), "smtp": ("smtp.gmail.com", 587),
    },
    "microsoft": {
        "nombre": "Microsoft 365 / Outlook",
        "autorizar": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "scopes": "openid email offline_access https://outlook.office.com/IMAP.AccessAsUser.All",
        "scopes_smtp": "https://outlook.office.com/SMTP.Send offline_access",
        "extra_autorizar": {"prompt": "select_account"},
        "imap": ("outlook.office365.com", 993), "smtp": ("smtp.office365.com", 587),
    },
}


def _entorno(proveedor: str, sufijo: str) -> str:
    return os.environ.get(f"GUILDA_OAUTH_{proveedor.upper()}_{sufijo}", "").strip()


def disponible(proveedor: str) -> bool:
    return proveedor in PROVEEDORES and bool(_entorno(proveedor, "CLIENT_ID") and _entorno(proveedor, "CLIENT_SECRET"))


def proveedores_disponibles() -> list[dict]:
    return [{"clave": k, "nombre": v["nombre"]} for k, v in PROVEEDORES.items() if disponible(k)]


def _url(proveedor: str, clave: str) -> str:
    tenant = _entorno("microsoft", "TENANT") or "common"
    return PROVEEDORES[proveedor][clave].format(tenant=urllib.parse.quote(tenant, safe=""))


def nuevo_pkce() -> tuple[str, str]:
    """(verificador, desafío S256)."""
    verificador = secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    return verificador, desafio


def url_autorizacion(proveedor: str, redirect_uri: str, estado: str, desafio: str, correo: str | None = None) -> str:
    if not disponible(proveedor):
        raise ErrorOAuth("Este proveedor no está configurado en el servidor.")
    parametros = {
        "client_id": _entorno(proveedor, "CLIENT_ID"), "redirect_uri": redirect_uri, "response_type": "code",
        "scope": PROVEEDORES[proveedor]["scopes"], "state": estado,
        "code_challenge": desafio, "code_challenge_method": "S256", **PROVEEDORES[proveedor]["extra_autorizar"],
    }
    if correo:
        parametros["login_hint"] = correo
    return _url(proveedor, "autorizar") + "?" + urllib.parse.urlencode(parametros)


def _post_form(url: str, datos: dict) -> tuple[int, dict]:
    """POST application/x-www-form-urlencoded -> (estado HTTP, JSON). Aparte para poder sustituirlo en las pruebas."""
    peticion = urllib.request.Request(url, data=urllib.parse.urlencode(datos).encode(), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as r:  # noqa: S310 -- URLs fijas de los proveedores
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError) as e:
        logger.warning("OAuth: fallo de red con el proveedor -- %s", e)
        raise ErrorOAuth("No se ha podido contactar con el proveedor de correo. Inténtalo de nuevo.") from e


def _correo_del_id_token(id_token: str | None) -> str:
    """Dirección del usuario según el id_token (llega directo del proveedor por TLS, no hace falta verificar la firma)."""
    try:
        carga = id_token.split(".")[1]
        datos = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))
    except (AttributeError, IndexError, ValueError):
        return ""
    candidato = str(datos.get("email") or datos.get("preferred_username") or "").strip().lower()
    return candidato if "@" in candidato and len(candidato) <= 254 else ""


def canjear_codigo(proveedor: str, codigo: str, redirect_uri: str, verificador: str) -> dict:
    """Devuelve {refresh_token, access_token, expira_en, email}."""
    estado, r = _post_form(_url(proveedor, "token"), {
        "grant_type": "authorization_code", "code": codigo, "redirect_uri": redirect_uri, "code_verifier": verificador,
        "client_id": _entorno(proveedor, "CLIENT_ID"), "client_secret": _entorno(proveedor, "CLIENT_SECRET"),
    })
    if estado != 200 or not r.get("access_token"):
        logger.warning("OAuth %s: el canje del código falló (%s): %s", proveedor, estado, r.get("error"))
        raise ErrorOAuth("El proveedor no ha aceptado la autorización. Vuelve a intentarlo.")
    if not r.get("refresh_token"):
        raise ErrorOAuth("El proveedor no ha entregado permiso de acceso permanente. Revoca el acceso anterior de Guilda Work en tu cuenta y vuelve a conectar.")
    email = _correo_del_id_token(r.get("id_token"))
    if not email:
        raise ErrorOAuth("No se ha podido saber la dirección de correo de la cuenta.")
    return {"refresh_token": r["refresh_token"], "access_token": r["access_token"], "expira_en": int(r.get("expires_in") or 3600), "email": email}


# --- almacén y renovación ---------------------------------------------------------------------

def _clave(cuenta_id: int) -> str:
    return f"cuenta-{cuenta_id}"          # la misma clave que las contraseñas: aquí vive el token de refresco


def guardar_refresh_token(cuenta_id: int, token: str) -> None:
    keyring.set_password(SERVICIO_KEYRING, _clave(cuenta_id), token)


_cache: dict[tuple[int, str], tuple[str, float]] = {}


def olvidar(cuenta_id: int) -> None:
    for clave in [k for k in _cache if k[0] == cuenta_id]:
        _cache.pop(clave, None)


def token_de_acceso(cuenta_id: int, proveedor: str, recurso: str = "imap") -> TokenOAuth:
    """Token de acceso válido (de la caché o renovado con el de refresco). `recurso`: 'imap' o 'smtp'
    (en Microsoft son recursos distintos y cada uno pide su propio token)."""
    if proveedor not in PROVEEDORES:
        raise ErrorOAuth("Proveedor desconocido.")
    ahora = time.time()
    en_cache = _cache.get((cuenta_id, recurso))
    if en_cache and en_cache[1] - 60 > ahora:
        return TokenOAuth(en_cache[0])
    refresh = keyring.get_password(SERVICIO_KEYRING, _clave(cuenta_id))
    if not refresh:
        raise ErrorOAuth("No se encuentra la autorización de esta cuenta. Vuelve a conectarla.")
    datos = {
        "grant_type": "refresh_token", "refresh_token": refresh,
        "client_id": _entorno(proveedor, "CLIENT_ID"), "client_secret": _entorno(proveedor, "CLIENT_SECRET"),
    }
    if recurso == "smtp" and PROVEEDORES[proveedor].get("scopes_smtp"):
        datos["scope"] = PROVEEDORES[proveedor]["scopes_smtp"]
    elif proveedor == "microsoft":
        datos["scope"] = PROVEEDORES[proveedor]["scopes"]
    estado, r = _post_form(_url(proveedor, "token"), datos)
    if r.get("error") in ("invalid_grant", "interaction_required") or estado in (400, 401) and not r.get("access_token"):
        olvidar(cuenta_id)
        raise ErrorOAuth("La autorización de esta cuenta ha caducado o se ha revocado. Vuelve a conectarla desde Correo → Cuentas.")
    if estado != 200 or not r.get("access_token"):
        raise ErrorOAuth("No se ha podido renovar el acceso a la cuenta (el proveedor no responde). Se reintentará.")
    if r.get("refresh_token") and r["refresh_token"] != refresh:
        guardar_refresh_token(cuenta_id, r["refresh_token"])          # Microsoft rota el token de refresco
    _cache[(cuenta_id, recurso)] = (r["access_token"], ahora + int(r.get("expires_in") or 3600))
    return TokenOAuth(r["access_token"])


def cadena_xoauth2(usuario: str, token: str) -> str:
    return f"user={usuario}\x01auth=Bearer {token}\x01\x01"
