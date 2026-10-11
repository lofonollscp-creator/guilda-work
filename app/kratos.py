"""Cliente de Ory Kratos (Fase 7a — identidad real para el modo hospedado).

Único punto de la app que habla con Kratos por HTTP — mismo criterio que
`app/ai_local.py`/`app/ia_asistente.py`: solo `urllib` de la librería
estándar, sin dependencias nuevas.

Dos APIs de Kratos en juego, con usos distintos:
- **Pública** (`KRATOS_PUBLIC_URL`): flujos self-service (login/registro
  por navegador) y `/sessions/whoami`. Aquí SÍ importan las cookies —
  se reenvían las del navegador y Kratos responde con las suyas.
- **Admin** (`KRATOS_ADMIN_URL`): gestión directa de identidades
  (creación en el registro de la API, verificación de credenciales para
  el login de la API/móvil). No lleva cookies — es server-to-server,
  solo alcanzable dentro de la red de Docker, nunca expuesta al exterior.

`serve.py`/`GuildaWork.exe` corren FUERA de Docker (en el host, ver
`docker-compose.yml`) — igual que ya pasa con Metabase/MinIO/n8n, este
proceso alcanza los contenedores por sus puertos publicados en
`localhost`, no por el nombre de host interno de la red de Docker
(`kratos`, que solo resuelve entre contenedores). `serve.public.base_url`
en `deploy/kratos/kratos.yml` está fijado al mismo `127.0.0.1:4433` por
la misma razón: para que las URLs `action`/`Location` que Kratos genera
sean coherentes con cómo la app las alcanza.

El navegador, a su vez, nunca habla directamente con Kratos — pasa por el
proxy `/.ory/` (`app/rutas_kratos_proxy.py`), que sí está en su mismo
origen. Por eso `reescribir_action_para_navegador` reescribe las URLs
`action`/`Location` que devuelve Kratos para que apunten ahí.
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

KRATOS_PUBLIC_URL = "http://127.0.0.1:4433"
KRATOS_ADMIN_URL = "http://127.0.0.1:4434"
TIMEOUT_SEGUNDOS = 10


class ErrorKratos(Exception):
    """Error legible para mostrar en la interfaz cuando Kratos falla."""


class SinRedireccion(urllib.request.HTTPRedirectHandler):
    """Kratos usa 303 para llevar al navegador de vuelta a nuestra propia
    ui_url con `?flow=<id>` — cuando esta app llama a Kratos por su cuenta
    (no en nombre directo del navegador) queremos ver esa redirección, no
    que urllib la siga sola."""

    def redirect_request(self, *args, **kwargs):
        return None


def opener_sin_redireccion() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SinRedireccion)


def _cabecera_cookie(cookies: dict) -> dict:
    if not cookies:
        return {}
    return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}


def _peticion(url: str, *, metodo: str = "GET", cabeceras: dict | None = None, cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cabeceras_finales = {"Accept": "application/json", **(cabeceras or {})}
    if datos is not None:
        cabeceras_finales["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=datos, headers=cabeceras_finales, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read().decode("utf-8")
            return resp.status, (json.loads(cuerpo_resp) if cuerpo_resp else {}), dict(resp.headers)
    except urllib.error.HTTPError as e:
        cuerpo_error = e.read().decode("utf-8")
        try:
            return e.code, json.loads(cuerpo_error), dict(e.headers)
        except json.JSONDecodeError:
            return e.code, {"error": cuerpo_error}, dict(e.headers)
    except urllib.error.URLError as e:
        raise ErrorKratos(
            f"No se ha podido conectar con Kratos ({url}). ¿Está levantado el contenedor? Detalle: {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ErrorKratos(f"Tiempo de espera agotado al contactar con Kratos ({url}).") from e


def reescribir_action_para_navegador(url: str) -> str:
    """Convierte una URL `action`/`Location` de la API pública de Kratos
    (`http://127.0.0.1:4433/...`) en una ruta `/.ory/...` que el navegador
    sí puede alcanzar, a través del proxy (`app/rutas_kratos_proxy.py`)."""
    if url.startswith(KRATOS_PUBLIC_URL):
        return "/.ory" + url[len(KRATOS_PUBLIC_URL):]
    return url


def _id_de_error(cuerpo) -> str | None:
    error = cuerpo.get("error") if isinstance(cuerpo, dict) else None
    return error.get("id") if isinstance(error, dict) else None


class Requiere2FA(ErrorKratos):
    """El email y la contraseña son correctos pero la cuenta tiene la verificación en dos pasos activada y falta el código."""


def requiere_aal2(cookies: dict) -> bool:
    """¿La cookie de sesión es válida pero la cuenta exige un segundo factor que aún no se ha dado? (Kratos: 403 session_aal2_required.)"""
    if not cookies:
        return False
    estado, cuerpo, _ = _peticion(f"{KRATOS_PUBLIC_URL}/sessions/whoami", cabeceras=_cabecera_cookie(cookies))
    return estado == 403 and _id_de_error(cuerpo) == "session_aal2_required"


def whoami(cookies: dict) -> dict | None:
    """Devuelve la sesión activa (con la identidad) o None si no hay
    ninguna cookie de sesión válida."""
    estado, cuerpo, _ = _peticion(
        f"{KRATOS_PUBLIC_URL}/sessions/whoami", cabeceras=_cabecera_cookie(cookies)
    )
    if estado != 200:
        return None
    return cuerpo


def obtener_identidad(identity_id: str) -> dict | None:
    """Identidad por id vía Admin API — usado por el puente de Hydra
    (`app/rutas_hydra.py`) para provisionar la fila local de un usuario
    cuya identidad ya existe en Kratos pero que Guilda Work todavía no
    había visto (puede pasar si Hydra se salta el paso de login por
    tener ya una sesión recordada de OTRO cliente OAuth2, sin que la
    petición pase nunca por `_resolver_usuario_actual()`)."""
    estado, cuerpo, _ = _peticion(f"{KRATOS_ADMIN_URL}/admin/identities/{identity_id}")
    if estado != 200:
        return None
    return cuerpo


def iniciar_flujo(tipo: str, cookies: dict, aal: str | None = None) -> tuple[str, list[str]]:
    """Inicia un flujo self-service de navegador (login o registro) y
    devuelve (url_de_redireccion_para_el_navegador, cabeceras_set_cookie).

    `tipo` es "login" o "registration". No sigue la redirección 303 de
    Kratos — la propia app redirige ahí al navegador real.

    Las cabeceras `Set-Cookie` de la respuesta (Kratos fija aquí la
    cookie anti-CSRF del flujo recién creado) hay que reenviarlas de
    verdad al navegador -- sin ellas, el POST posterior a
    `/.ory/self-service/{tipo}` falla la validación CSRF de Kratos
    porque el token del formulario no tiene cookie con la que
    contrastarlo (bug real, encontrado al ser esta función la primera
    que llama a `iniciar_flujo` -- hasta ahora nadie la usaba)."""
    opener = opener_sin_redireccion()
    consulta = f"?aal={aal}" if aal else ""      # aal="aal2": segundo factor de una sesión que ya pasó la contraseña
    req = urllib.request.Request(
        f"{KRATOS_PUBLIC_URL}/self-service/{tipo}/browser{consulta}",
        headers={"Accept": "text/html", **_cabecera_cookie(cookies)},
    )
    try:
        with opener.open(req, timeout=TIMEOUT_SEGUNDOS) as resp:
            ubicacion = resp.headers.get("Location", "")
            cabeceras_set_cookie = resp.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        if e.code in (303, 302):
            ubicacion = e.headers.get("Location", "")
            cabeceras_set_cookie = e.headers.get_all("Set-Cookie") or []
        else:
            raise ErrorKratos(f"Kratos devolvió un error al iniciar el flujo de {tipo}: {e.code}") from e
    except urllib.error.URLError as e:
        raise ErrorKratos(f"No se ha podido conectar con Kratos. Detalle: {e.reason}") from e
    return ubicacion, cabeceras_set_cookie


def obtener_flujo(tipo: str, flow_id: str, cookies: dict) -> dict:
    """Recupera los `nodes` (campos del formulario) de un flujo ya
    iniciado, por su id."""
    estado, cuerpo, _ = _peticion(
        f"{KRATOS_PUBLIC_URL}/self-service/{tipo}/flows?id={flow_id}",
        cabeceras=_cabecera_cookie(cookies),
    )
    if estado != 200:
        raise ErrorKratos(f"No se ha podido recuperar el flujo de {tipo} (id {flow_id}).")
    return cuerpo


def logout_url(cookies: dict) -> str | None:
    estado, cuerpo, _ = _peticion(
        f"{KRATOS_PUBLIC_URL}/self-service/logout/browser", cabeceras=_cabecera_cookie(cookies)
    )
    if estado != 200:
        return None
    return reescribir_action_para_navegador(cuerpo.get("logout_url", ""))


def verificar_credenciales_admin(email: str, contrasena: str, codigo_2fa: str | None = None) -> str | None:
    """Verifica un email+contraseña usando el flujo "API-style" de Kratos
    (pensado para clientes que no son navegador — server-to-server, sin
    CSRF/cookies). Devuelve el `identity_id` si son correctas, None si no.
    Usado por `POST /api/v1/auth/login` — el móvil sigue recibiendo el
    token opaco propio de siempre, esto solo cambia qué valida la
    contraseña por debajo.

    Verificación en dos pasos: si la cuenta la tiene activada, con la contraseña sola Kratos da una sesión AAL1 que NO basta.
    Sin `codigo_2fa` se lanza `Requiere2FA`; con él (código de la app de autenticación de 6 dígitos o uno de recuperación) se completa
    el segundo paso y, si es correcto, se devuelve el `identity_id`; si no, None."""
    estado, flujo, _ = _peticion(f"{KRATOS_PUBLIC_URL}/self-service/login/api")
    if estado != 200:
        return None
    flow_id = flujo.get("id")
    estado, resultado, _ = _peticion(
        f"{KRATOS_PUBLIC_URL}/self-service/login?flow={flow_id}",
        metodo="POST",
        cuerpo={"method": "password", "identifier": email, "password": contrasena},
    )
    if estado != 200:
        return None
    # Con un segundo factor pendiente Kratos no incluye la identidad en la sesión AAL1: se recupera con whoami o tras el segundo paso.
    identity_id = ((resultado.get("session") or {}).get("identity") or {}).get("id")
    token = resultado.get("session_token")
    if not token:
        return identity_id
    cabecera = {"X-Session-Token": token}
    estado, cuerpo, _ = _peticion(f"{KRATOS_PUBLIC_URL}/sessions/whoami", cabeceras=cabecera)
    if estado == 200:
        return identity_id or (cuerpo.get("identity") or {}).get("id")
    if not (estado == 403 and _id_de_error(cuerpo) == "session_aal2_required"):
        return None
    codigo = (codigo_2fa or "").replace(" ", "").strip()
    if not codigo:
        raise Requiere2FA("Esta cuenta tiene la verificación en dos pasos: falta el código.")
    estado, flujo2, _ = _peticion(f"{KRATOS_PUBLIC_URL}/self-service/login/api?aal=aal2", cabeceras=cabecera)
    if estado != 200:
        return None
    metodo = {"method": "totp", "totp_code": codigo} if codigo.isdigit() and len(codigo) == 6 else {"method": "lookup_secret", "lookup_secret": codigo}
    estado, resultado2, _ = _peticion(
        f"{KRATOS_PUBLIC_URL}/self-service/login?flow={flujo2.get('id')}", metodo="POST", cabeceras=cabecera, cuerpo=metodo
    )
    if estado != 200:
        return None
    return ((resultado2.get("session") or {}).get("identity") or {}).get("id")


def quitar_segundo_factor(identity_id: str) -> list[str]:
    """Quita la app de autenticación y los códigos de recuperación de una identidad (Admin API). Es la salida cuando alguien pierde el
    móvil Y los códigos. Devuelve los métodos que quitó (los que no tenía no cuentan: 404 se ignora)."""
    quitados = []
    for metodo in ("totp", "lookup_secret"):
        estado, _, _ = _peticion(f"{KRATOS_ADMIN_URL}/admin/identities/{identity_id}/credentials/{metodo}", metodo="DELETE")
        if estado == 204:
            quitados.append(metodo)
        elif estado not in (404,):
            raise ErrorKratos(f"Kratos no pudo quitar «{metodo}» (HTTP {estado}).")
    return quitados


def crear_identidad(email: str, contrasena: str) -> str:
    """Crea una identidad directamente vía la Admin API (usado por el
    registro propio, tanto web como API) — evita orquestar el flujo
    completo de navegador para un caso donde ya tenemos usuario+contraseña
    en la mano. Devuelve el `identity_id` creado."""
    estado, cuerpo, _ = _peticion(
        f"{KRATOS_ADMIN_URL}/admin/identities",
        metodo="POST",
        cuerpo={
            "schema_id": "default",
            "traits": {"email": email.strip().lower()},
            "credentials": {"password": {"config": {"password": contrasena}}},
        },
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("error", {}).get("message") if isinstance(cuerpo.get("error"), dict) else cuerpo.get("error")
        raise ErrorKratos(mensaje or "No se ha podido crear la cuenta en Kratos.")
    return cuerpo["id"]


def importar_identidad_con_hash(email: str, hashed_password_phc: str) -> str:
    """Crea una identidad a partir de un hash de contraseña YA calculado
    (formato PHC de Kratos) — usado por `scripts/migrar_usuarios_a_kratos.py`
    para trasladar las contraseñas existentes sin forzar un cambio."""
    estado, cuerpo, _ = _peticion(
        f"{KRATOS_ADMIN_URL}/admin/identities",
        metodo="POST",
        cuerpo={
            "schema_id": "default",
            "traits": {"email": email.strip().lower()},
            "credentials": {"password": {"config": {"hashed_password": hashed_password_phc}}},
        },
    )
    if estado not in (200, 201):
        mensaje = cuerpo.get("error", {}).get("message") if isinstance(cuerpo.get("error"), dict) else cuerpo.get("error")
        raise ErrorKratos(mensaje or "No se ha podido importar la identidad en Kratos.")
    return cuerpo["id"]
