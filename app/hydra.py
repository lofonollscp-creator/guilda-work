"""Cliente de Ory Hydra (Fase 7b — SSO para herramientas externas como
Outline que no tienen login con contraseña propio).

Solo se usa la Admin API (`HYDRA_ADMIN_URL`) — server-to-server, nunca
expuesta al exterior, igual que la Admin API de Kratos (`app/kratos.py`).
El navegador solo habla directamente con la API pública de Hydra
(`HYDRA_PUBLIC_URL`, puerto 4444) para el propio flujo OAuth2/OIDC en sí
— ese tráfico no pasa por aquí, lo inicia el cliente OAuth2 (Outline).

`serve.py`/`GuildaWork.exe` corren FUERA de Docker (ver `app/kratos.py`
para la explicación completa de esta asimetría) — de ahí
`http://127.0.0.1:4445` en vez del nombre de host interno `hydra`."""
import json
import urllib.error
import urllib.request

HYDRA_ADMIN_URL = "http://127.0.0.1:4445"
TIMEOUT_SEGUNDOS = 10


class ErrorHydra(Exception):
    """Error legible para mostrar en la interfaz cuando Hydra falla."""


def _peticion(url: str, *, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras = {"Accept": "application/json"}
    if datos is not None:
        cabeceras["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {})
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error)
        except json.JSONDecodeError:
            return e.code, {"error": cuerpo_error}
    except urllib.error.URLError as e:
        raise ErrorHydra(
            f"No se ha podido conectar con Hydra ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorHydra(f"Tiempo de espera agotado al contactar con Hydra ({url}).") from e


def obtener_login_request(challenge: str) -> dict:
    estado, cuerpo = _peticion(
        f"{HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/login?login_challenge={challenge}"
    )
    if estado != 200:
        raise ErrorHydra("No se ha podido recuperar la solicitud de login de Hydra.")
    return cuerpo


def aceptar_login_request(challenge: str, subject: str, *, remember: bool = True) -> str:
    """Acepta la solicitud de login y devuelve la URL a la que redirigir al
    navegador (`redirect_to`) para continuar el flujo OAuth2."""
    estado, cuerpo = _peticion(
        f"{HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/login/accept?login_challenge={challenge}",
        metodo="PUT",
        cuerpo={"subject": subject, "remember": remember, "remember_for": 3600 * 24 * 30},
    )
    if estado != 200:
        raise ErrorHydra("Hydra ha rechazado la aceptación del login.")
    return cuerpo["redirect_to"]


def obtener_consent_request(challenge: str) -> dict:
    estado, cuerpo = _peticion(
        f"{HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent?consent_challenge={challenge}"
    )
    if estado != 200:
        raise ErrorHydra("No se ha podido recuperar la solicitud de consentimiento de Hydra.")
    return cuerpo


def aceptar_consent_request(challenge: str, *, scopes: list, email: str) -> str:
    """Acepta el consentimiento sin mostrar pantalla intermedia — los únicos
    clientes OAuth2 de este Hydra son los que registra Guilda Work
    (`scripts/registrar_cliente_hydra.py`), todos con `skip_consent: true`,
    así que no hay ningún escenario real de "aplicación de terceros pidiendo
    permiso" que justifique preguntar."""
    estado, cuerpo = _peticion(
        f"{HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/consent/accept?consent_challenge={challenge}",
        metodo="PUT",
        cuerpo={
            "grant_scope": scopes,
            "grant_access_token_audience": [],
            "remember": True,
            "remember_for": 3600 * 24 * 30,
            "session": {"id_token": {"email": email}},
        },
    )
    if estado != 200:
        raise ErrorHydra("Hydra ha rechazado la aceptación del consentimiento.")
    return cuerpo["redirect_to"]


def registrar_cliente(nombre: str, redirect_uri: str) -> dict:
    """Registra un cliente OAuth2 vía Admin API — usado por
    `scripts/registrar_cliente_hydra.py`. `skip_consent: true` porque los
    únicos clientes de este Hydra son los que registra ese mismo script."""
    estado, cuerpo = _peticion(
        f"{HYDRA_ADMIN_URL}/admin/clients",
        metodo="POST",
        cuerpo={
            "client_name": nombre,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "redirect_uris": [redirect_uri],
            "scope": "openid email profile offline_access",
            "token_endpoint_auth_method": "client_secret_post",
            "skip_consent": True,
        },
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("error_description") or cuerpo.get("error") or cuerpo
        raise ErrorHydra(f"No se ha podido registrar el cliente en Hydra: {mensaje}")
    return cuerpo


def aceptar_logout_request(challenge: str) -> str:
    estado, cuerpo = _peticion(
        f"{HYDRA_ADMIN_URL}/admin/oauth2/auth/requests/logout/accept?logout_challenge={challenge}",
        metodo="PUT",
    )
    if estado != 200:
        raise ErrorHydra("Hydra ha rechazado la aceptación del logout.")
    return cuerpo["redirect_to"]
