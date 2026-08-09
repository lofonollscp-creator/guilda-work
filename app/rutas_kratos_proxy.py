"""Proxy transparente hacia la API pública de Ory Kratos (Fase 7a).

Por qué existe: la cookie de sesión que pone Kratos solo la puede leer
después un navegador que la vea "del mismo sitio" — pero `KRATOS_PUBLIC_URL`
(`http://kratos:4433` dentro de Docker) no es una dirección a la que el
navegador del usuario pueda llegar directamente. Este blueprint expone
`/.ory/<lo-que-sea>` en el propio origen de Guilda Work y reenvía la
petición tal cual a Kratos, devolviendo la respuesta (incluidas las
cabeceras `Set-Cookie`) sin tocarla — así, a efectos del navegador, Kratos
"vive" en el mismo sitio que la app.

No requiere `login_required`: por definición, aquí es donde ocurre el
login (y el logout, y el registro) — todavía no hay sesión en la primera
petición.

## Captcha de respaldo en el login

CrowdSec (ver HOSTING.md) banea una IP tras varios fallos de login
seguidos — pero el bouncer de Caddy que usamos solo soporta baneo, no
captcha (confirmado en la documentación oficial del proyecto). Como este
proxy es el único punto de todo el código por el que pasa un POST de login
antes de llegar a Kratos de verdad, es el sitio donde se puede meter algo
más suave: si una IP acumula 3 fallos en 5 minutos, se le exige resolver
un captcha ALTCHA (ver app/captcha.py) antes de reenviar el siguiente
intento a Kratos. CrowdSec se queda como red de respaldo para quien pase
por encima del captcha de forma automatizada.

El contador es en memoria (se pierde al reiniciar el servicio, igual que
la cola de eventos de app/eventos.py) — no hace falta persistirlo, es una
protección de "ahora mismo", no un historial."""
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

from flask import Blueprint, Response, redirect, request

from . import captcha
from . import kratos as kratos_modulo

kratos_proxy_bp = Blueprint("kratos_proxy", __name__, url_prefix="/.ory")

# Cabeceras que no tiene sentido reenviar tal cual (largo/encoding los
# recalcula Flask al construir su propia Response; host es el de Kratos,
# no el nuestro).
_CABECERAS_A_IGNORAR = {"content-length", "transfer-encoding", "connection", "host"}

# --- Captcha de respaldo en el login (ver docstring del módulo) -----------

_VENTANA_FALLOS_SEGUNDOS = 5 * 60
_UMBRAL_FALLOS = 3
_RUTA_LOGIN_FORM = "self-service/login"
# Kratos reutiliza error.ui_url = /login también para su página de error
# genérica (deploy/kratos/kratos.yml) -- un login que falla no vuelve a
# /login?flow=<mismo-id> como cabría esperar, sino a /login?id=<error-id>.
# Verificado en vivo contra el Kratos real de este despliegue (no es una
# suposición): cualquier redirección de vuelta a /login, con flow= o con
# id=, es un fallo; cualquier otra (a default_browser_return_url) es un
# login correcto.
_RUTA_LOGIN_PAGINA = "/login"

_fallos_por_ip: dict[str, list[float]] = defaultdict(list)

# IPs de confianza (mismo criterio que la whitelist de CrowdSec, pero lista
# aparte: formatos y sistemas distintos) que nunca ven el captcha por
# muchos fallos que acumulen -- ver /etc/guilda-work.env.
_IPS_SIN_CAPTCHA = {ip.strip() for ip in os.environ.get("IPS_SIN_CAPTCHA", "").split(",") if ip.strip()}


def _limpiar_fallos_viejos(ip: str) -> None:
    limite = time.time() - _VENTANA_FALLOS_SEGUNDOS
    vigentes = [t for t in _fallos_por_ip.get(ip, []) if t > limite]
    if vigentes:
        _fallos_por_ip[ip] = vigentes
    else:
        _fallos_por_ip.pop(ip, None)


def ip_requiere_captcha(ip: str | None) -> bool:
    """True si esta IP ha fallado el login 3+ veces en los últimos 5
    minutos -- usado por `/login` (app/main.py) para decidir si mostrar el
    widget en la plantilla."""
    if not ip or ip in _IPS_SIN_CAPTCHA:
        return False
    _limpiar_fallos_viejos(ip)
    return len(_fallos_por_ip.get(ip, [])) >= _UMBRAL_FALLOS


def _registrar_fallo(ip: str) -> None:
    _fallos_por_ip[ip].append(time.time())


def _resetear_fallos(ip: str) -> None:
    _fallos_por_ip.pop(ip, None)


@kratos_proxy_bp.route("/<path:subruta>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def proxy(subruta: str):
    ip = request.remote_addr or ""
    es_login_post = request.method == "POST" and subruta.rstrip("/") == _RUTA_LOGIN_FORM
    vigilar_captcha = es_login_post and ip not in _IPS_SIN_CAPTCHA

    # SIEMPRE antes de tocar request.form: Werkzeug solo cachea el cuerpo
    # crudo con garantías si get_data() es lo primero que lo lee -- pedir
    # .form antes (aunque sea solo para comprobar si existe un campo)
    # dejaba el cuerpo reenviado a Kratos vacío (`Content-Length: 0`) para
    # cualquier login normal sin captcha, rompiendo el login entero.
    # Verificado en vivo con la suite de tests real de este proyecto.
    cuerpo_original = request.get_data() or None

    if vigilar_captcha and ip_requiere_captcha(ip):
        if not captcha.verificar_solucion(request.form.get("altcha")):
            flow_id = request.args.get("flow", "")
            return redirect(f"/login?flow={flow_id}&captcha_error=1")

    destino = f"{kratos_modulo.KRATOS_PUBLIC_URL}/{subruta}"
    if request.query_string:
        destino += f"?{request.query_string.decode('utf-8')}"

    cabeceras = {
        clave: valor
        for clave, valor in request.headers.items()
        if clave.lower() not in _CABECERAS_A_IGNORAR
    }

    if vigilar_captcha and "altcha" in request.form:
        # Kratos rechaza el envío ENTERO si trae un campo que no reconoce
        # entre los nodos de su propio flujo (protección contra manipular
        # el formulario) -- verificado en vivo: un login con credenciales
        # correctas y altcha válido fallaba igual que uno sin captcha,
        # hasta quitar este campo antes de reenviar. El formulario de
        # login es application/x-www-form-urlencoded normal (sin
        # ficheros), así que reconstruirlo así es seguro para esta ruta.
        campos = request.form.to_dict()
        campos.pop("altcha", None)
        cuerpo = urllib.parse.urlencode(campos).encode("utf-8")
    else:
        cuerpo = cuerpo_original

    peticion = urllib.request.Request(destino, data=cuerpo, headers=cabeceras, method=request.method)
    # Sin seguir redirecciones: un 303 de Kratos (p.ej. tras completar login)
    # tiene que llegar TAL CUAL al navegador real para que lo siga él mismo
    # — si urllib lo siguiera aquí, intentaría conectar server-to-server a
    # la propia app (su Location apunta a nuestra ui_url), que ni es la
    # intención ni necesariamente hay nada escuchando ahí en ese momento.
    opener = kratos_modulo.opener_sin_redireccion()
    try:
        with opener.open(peticion, timeout=kratos_modulo.TIMEOUT_SEGUNDOS) as resp:
            cuerpo = resp.read()
            estado = resp.status
            cabeceras_resp = resp.headers
    except urllib.error.HTTPError as e:
        cuerpo = e.read()
        estado = e.code
        cabeceras_resp = e.headers
    except urllib.error.URLError as e:
        return Response(f"No se ha podido conectar con Kratos: {e.reason}", status=502)

    respuesta = Response(cuerpo, status=estado)
    for clave, valor in cabeceras_resp.items():
        if clave.lower() in _CABECERAS_A_IGNORAR:
            continue
        if clave.lower() == "location":
            # Igual que las URLs `action`, la Location de una redirección
            # de Kratos apunta a su host interno — se reescribe a /.ory/
            # para que el navegador pueda seguirla.
            valor = kratos_modulo.reescribir_action_para_navegador(valor)
        respuesta.headers.add(clave, valor)

    if vigilar_captcha:
        location = respuesta.headers.get("Location", "")
        if _RUTA_LOGIN_PAGINA in location:
            _registrar_fallo(ip)  # Kratos vuelve a /login (flujo o error) -> credenciales rechazadas
        elif location:
            _resetear_fallos(ip)  # redirección a otro sitio -> login correcto

    return respuesta
