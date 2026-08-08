"""Cliente de Firebase Cloud Messaging (FCM HTTP v1) para las notificaciones
push de la app móvil (Fase 10) — a diferencia del resto de integraciones de
`app/*.py` (solo `urllib`/`subprocess`, ver p.ej. `app/ntfy.py`), esta sí
necesita una dependencia externa (`google-auth`): la API HTTP v1 de FCM
exige autenticarse con un JWT firmado RS256 canjeado por un token OAuth2 de
Google, y reimplementar eso a mano con solo la librería estándar no
compensa frente a la librería oficial mantenida por el propio proveedor.

Requiere `GUILDA_FIREBASE_CREDENTIALS_PATH` apuntando al JSON de cuenta de
servicio descargado de Firebase Console (Project Settings → Service
accounts → Generate new private key). Sin esa variable, `configurado()`
devuelve False y `enviar_a_usuario()` no hace nada — mismo criterio que el
resto de integraciones opcionales de este proyecto (ver
`ntfy.aprovisionar_tenant`), para que el resto de la app funcione con
normalidad mientras Firebase no esté dado de alta."""
import json
import os
import urllib.error
import urllib.request

from google.auth.transport.requests import Request as _PeticionGoogleAuth
from google.oauth2 import service_account

FIREBASE_CREDENTIALS_PATH = os.environ.get("GUILDA_FIREBASE_CREDENTIALS_PATH")
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TIMEOUT_SEGUNDOS = 10

_credenciales = None
_project_id: str | None = None


def configurado() -> bool:
    return bool(FIREBASE_CREDENTIALS_PATH and os.path.exists(FIREBASE_CREDENTIALS_PATH))


def _credenciales_cargadas():
    global _credenciales, _project_id
    if _credenciales is None:
        _credenciales = service_account.Credentials.from_service_account_file(
            FIREBASE_CREDENTIALS_PATH, scopes=[_SCOPE]
        )
        with open(FIREBASE_CREDENTIALS_PATH) as f:
            _project_id = json.load(f)["project_id"]
    return _credenciales


def _access_token() -> str:
    creds = _credenciales_cargadas()
    creds.refresh(_PeticionGoogleAuth())
    return creds.token


def _enviar_a_token(fcm_token: str, titulo: str, cuerpo: str, datos: dict | None) -> bool:
    """True si FCM aceptó la entrega. False si el token ya no es válido
    (app desinstalada, token expirado) -- en ese caso el llamante debe
    limpiarlo de `dispositivos_push` (ver `db.eliminar_tokens_push`). Un
    fallo de red puntual no cuenta como token inválido, se deja tal cual
    para reintentar en el siguiente evento."""
    mensaje = {
        "message": {
            "token": fcm_token,
            "notification": {"title": titulo, "body": cuerpo},
            "data": {k: str(v) for k, v in (datos or {}).items()},
        }
    }
    req = urllib.request.Request(
        f"https://fcm.googleapis.com/v1/projects/{_project_id}/messages:send",
        data=json.dumps(mensaje).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS):
            return True
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8", errors="replace")
        if e.code in (400, 404) and "UNREGISTERED" in cuerpo_error:
            return False
        return True  # otro tipo de rechazo (cuota, credenciales...): no borrar el token por esto
    except urllib.error.URLError:
        return True


def enviar_a_usuario(usuario_id: int, titulo: str, cuerpo: str, datos: dict | None = None) -> None:
    """Punto de entrada usado desde los puntos de emisión de eventos (ver
    p.ej. `app/correo.py:_emitir_evento_correo_nuevo`) -- manda el push a
    todos los dispositivos del usuario, limpiando los que FCM rechace como
    no registrados. No lanza: un fallo aquí no debe impedir que la acción
    que lo disparó se complete (mismo criterio que `eventos.emitir`)."""
    if not configurado():
        return
    try:
        from . import db  # import perezoso: evita el ciclo db <-> push
        tokens = db.tokens_push_de_usuario(usuario_id)
        if not tokens:
            return
        invalidos = [t for t in tokens if not _enviar_a_token(t, titulo, cuerpo, datos)]
        if invalidos:
            db.eliminar_tokens_push(invalidos)
    except Exception:
        pass
