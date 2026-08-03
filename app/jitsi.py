"""Cliente de Jitsi Meet (videollamadas autoalojadas, ver mcp_tools.py y
HOSTING.md) — licencia Apache-2.0, instancia compartida (una sala es
efímera, no hay datos persistentes que aislar por tenant): el
aislamiento real es que cada tenant solo puede generar JWT válidos para
sus propias salas (nombre de sala con el slug del tenant como prefijo).

## Autenticación — verificado en vivo contra un stack real

`ENABLE_AUTH=1`, `AUTH_TYPE=jwt`, `JWT_APP_ID`/`JWT_APP_SECRET` son
variables de entorno gratuitas del propio `docker-jitsi-meet`
(confirmado en su documentación oficial y en la propia ayuda de la
comunidad) — sin ningún add-on de pago. Se levantó el stack real de 4
contenedores (`web`/`prosody`/`jicofo`/`jvb`) con esta configuración
activa y se confirmó que arranca limpio (Jicofo se autentica contra
Prosody y descubre el JVB con el módulo de autenticación JWT cargado,
sin errores del propio módulo). La verificación completa de punta a
punta (un cliente sin JWT rechazado, uno con JWT válido admitido) no se
pudo completar en este entorno de desarrollo concreto — el navegador sin
cabeza nunca llegó a abrir la conexión WebSocket/XMPP tras pulsar
"Unirse" incluso con dispositivos de medios falsos habilitados,
aparentemente una fricción de WebRTC-en-Docker-Desktop-Windows ajena a
Jitsi — mismo criterio de honestidad que Cal.diy en este proyecto: no se
afirma "verificado en vivo de punta a punta" si no lo está. Queda
pendiente confirmarlo contra un despliegue real (Linux, HOSTING.md).

Firma el JWT a mano (HMAC-SHA256 + base64url, sin librerías) en vez de
añadir una dependencia nueva (`PyJWT`) — mismo criterio de dependencias
mínimas que el resto de `app/*.py`: solo la librería estándar.

No hace falta ningún aprovisionamiento previo por tenant (a diferencia
del resto de integraciones): Jitsi crea la sala sola al primer JWT
válido que llega, no hay usuarios que dar de alta.
"""
import base64
import hashlib
import hmac
import json
import os
import string
import time

JITSI_URL = os.environ.get("HERRAMIENTA_JITSI_URL", "http://127.0.0.1:8028")
JITSI_JWT_APP_ID = os.environ.get("JITSI_JWT_APP_ID")
JITSI_JWT_APP_SECRET = os.environ.get("JITSI_JWT_APP_SECRET")


class ErrorJitsi(Exception):
    """Error legible para mostrar cuando Jitsi Meet falla."""


def _slug(nombre: str) -> str:
    permitidos = string.ascii_lowercase + string.digits
    bruto = "".join(ch if ch in permitidos else "-" for ch in nombre.lower().strip())
    while "--" in bruto:
        bruto = bruto.replace("--", "-")
    return bruto.strip("-") or "tenant"


def _base64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def _firmar_jwt(payload: dict) -> str:
    """HS256 a mano: header.payload firmados con HMAC-SHA256, sin
    depender de PyJWT (ver docstring del módulo)."""
    cabecera = {"alg": "HS256", "typ": "JWT"}
    segmento_cabecera = _base64url(json.dumps(cabecera, separators=(",", ":")).encode("utf-8"))
    segmento_payload = _base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    firmante = f"{segmento_cabecera}.{segmento_payload}".encode("ascii")
    firma = hmac.new(JITSI_JWT_APP_SECRET.encode("utf-8"), firmante, hashlib.sha256).digest()
    return f"{segmento_cabecera}.{segmento_payload}.{_base64url(firma)}"


def nombre_sala(tenant: str, identificador: str) -> str:
    """Nombre de sala con el slug del tenant como prefijo — la propia
    convención de nombrado es lo único que impide que un tenant use el
    JWT de otro para su sala (JITSI_JWT_APP_SECRET es compartido entre
    todos los tenants, así que el aislamiento real está en que cada
    JWT solo es válido para LA SALA que lleva grabada dentro, no en el
    secreto en sí)."""
    return f"{_slug(tenant)}-{identificador}"


def generar_jwt_sala(tenant: str, nombre_mostrado: str, sala: str, moderador: bool = False, minutos_validez: int = 180) -> str:
    """Firma un JWT válido solo para `sala` (debe llevar el prefijo de
    `nombre_sala()`, no se fuerza aquí para no acoplar esta función a un
    formato de identificador concreto). Sin llamada HTTP: Jitsi no
    necesita aprovisionamiento previo, la sala se crea sola al primer
    JWT válido que llega."""
    if not JITSI_JWT_APP_ID or not JITSI_JWT_APP_SECRET:
        raise ErrorJitsi("JITSI_JWT_APP_ID/JITSI_JWT_APP_SECRET no están configuradas.")
    ahora = int(time.time())
    payload = {
        "context": {"user": {"name": nombre_mostrado, "moderator": moderador}},
        "aud": JITSI_JWT_APP_ID,
        "iss": JITSI_JWT_APP_ID,
        "sub": "*",
        "room": sala,
        "iat": ahora,
        "exp": ahora + minutos_validez * 60,
    }
    return _firmar_jwt(payload)


def url_sala(sala: str, jwt: str) -> str:
    return f"{JITSI_URL}/{sala}?jwt={jwt}"
