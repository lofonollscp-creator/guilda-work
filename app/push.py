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


def _enviar_a_token(fcm_token: str, titulo: str, cuerpo: str, datos: dict | None, canal: str | None = None) -> bool:
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
    if canal:
        # Canal de notificación de Android (familia del aviso): la app los crea al arrancar; si no existiera, Android usa el predeterminado.
        mensaje["message"]["android"] = {"notification": {"channel_id": canal}}
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


# --- Web Push (VAPID) de la webapp instalada o abierta en el navegador -------------------------------------------------
# Claves en GUILDA_VAPID_PUBLIC_KEY / GUILDA_VAPID_PRIVATE_KEY (base64url, las genera una sola vez quien administra el servidor);
# sin ellas el canal web queda apagado, igual que FCM sin credenciales de Firebase.
VAPID_PUBLICA = os.environ.get("GUILDA_VAPID_PUBLIC_KEY", "")
VAPID_PRIVADA = os.environ.get("GUILDA_VAPID_PRIVATE_KEY", "")
VAPID_CONTACTO = os.environ.get("GUILDA_VAPID_SUBJECT", "mailto:gestio@guilda.cat")
MAX_CUERPO_WEB = 180


def web_configurado() -> bool:
    return bool(VAPID_PUBLICA and VAPID_PRIVADA)


def _ruta_propia(url: str | None) -> str:
    """Solo rutas de la propia app: un aviso nunca puede mandar al navegador a otra web."""
    return url if url and url.startswith("/") and not url.startswith("//") else "/hoy/"


def _enviar_web(suscripcion_json: str, carga: dict) -> bool:
    """True si hay que conservar la suscripción; False si el servicio de push dice que ya no existe (404/410) o está mal formada."""
    from pywebpush import WebPushException, webpush
    try:
        suscripcion = json.loads(suscripcion_json)
        webpush(
            subscription_info=suscripcion,
            data=json.dumps(carga, separators=(",", ":")),
            vapid_private_key=VAPID_PRIVADA,
            vapid_claims={"sub": VAPID_CONTACTO},
            ttl=24 * 3600,
            timeout=TIMEOUT_SEGUNDOS,
        )
        return True
    except WebPushException as e:
        codigo = getattr(getattr(e, "response", None), "status_code", None)
        return codigo not in (404, 410)
    except (ValueError, KeyError):
        return False
    except Exception:
        return True                                   # red, cuota…: se reintenta con el siguiente aviso


def enviar_web_a_usuario(usuario_id: int, titulo: str, cuerpo: str, datos: dict | None = None) -> None:
    from . import db
    suscripciones = db.suscripciones_web_de_usuario(usuario_id)
    if not suscripciones:
        return
    datos = datos or {}
    carga = {"titulo": titulo[:120], "cuerpo": (cuerpo or "")[:MAX_CUERPO_WEB], "url": _ruta_propia(datos.get("url")), "tag": str(datos.get("notificacion_id") or datos.get("tipo") or "guilda")}
    for sus in suscripciones:
        if not _enviar_web(sus, carga):
            try:
                endpoint = json.loads(sus).get("endpoint", "")
            except ValueError:
                endpoint = ""
            if endpoint:
                db.eliminar_suscripcion_web(usuario_id, endpoint)
            else:
                db.eliminar_tokens_push([sus])


# --- Avisos genéricos (privacidad): la persona puede pedir que el móvil y el navegador solo muestren «tienes un aviso» ---------------
_TEXTO_GENERICO = {
    "es": ("Guilda Work", "Tienes un aviso nuevo. Ábrelo para verlo."),
    "ca": ("Guilda Work", "Tens un avís nou. Obre'l per veure'l."),
    "en": ("Guilda Work", "You have a new alert. Open it to see it."),
    "fr": ("Guilda Work", "Vous avez une nouvelle alerte. Ouvrez-la pour la voir."),
}
_CLAVES_SIN_DATOS_PERSONALES = ("tipo", "canal", "destino", "destino_tipo", "destino_id", "despacho_id", "notificacion_id", "url")


def hacer_generico(usuario_id: int, titulo: str, cuerpo: str, datos: dict | None) -> tuple[str, str, dict | None]:
    """Si la persona tiene activados los avisos genéricos, sustituye título y texto por uno fijo en su idioma y deja en `datos` solo lo necesario para abrir la pantalla correcta
    (tipo, ids y ruta: nada con nombres, asuntos ni importes). El aviso completo sigue en la campana de la aplicación."""
    from . import db
    if not db.avisos_genericos(usuario_id):
        return titulo, cuerpo, datos
    t, c = _TEXTO_GENERICO.get(db.idioma_usuario(usuario_id) or "es", _TEXTO_GENERICO["es"])
    return t, c, {k: v for k, v in (datos or {}).items() if k in _CLAVES_SIN_DATOS_PERSONALES}


def enviar_a_usuario(usuario_id: int, titulo: str, cuerpo: str, datos: dict | None = None, ignorar_silencio: bool = False, canal: str | None = None) -> None:
    """Punto de entrada usado desde los puntos de emisión de eventos (ver
    p.ej. `app/correo.py:_emitir_evento_correo_nuevo`) -- manda el push a
    todos los dispositivos del usuario (app móvil por FCM y navegadores por Web Push), limpiando los que
    rechacen como no registrados. No lanza: un fallo aquí no debe impedir que la acción
    que lo disparó se complete (mismo criterio que `eventos.emitir`)."""
    if not configurado() and not web_configurado():
        return
    try:
        from . import db  # import perezoso: evita el ciclo db <-> push
        if not ignorar_silencio and db.en_horas_de_silencio(usuario_id):
            return                                    # «no molestar»: la notificación queda en la app, sin vibrar el móvil
        titulo, cuerpo, datos = hacer_generico(usuario_id, titulo, cuerpo, datos)
        if configurado():
            tokens = db.tokens_push_de_usuario(usuario_id)
            invalidos = [t for t in tokens if not _enviar_a_token(t, titulo, cuerpo, datos, canal)]
            if invalidos:
                db.eliminar_tokens_push(invalidos)
        if web_configurado():
            enviar_web_a_usuario(usuario_id, titulo, cuerpo, datos)
    except Exception:
        pass
