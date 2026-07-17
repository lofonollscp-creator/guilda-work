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
"""
import urllib.error
import urllib.request

from flask import Blueprint, Response, request

from . import kratos as kratos_modulo

kratos_proxy_bp = Blueprint("kratos_proxy", __name__, url_prefix="/.ory")

# Cabeceras que no tiene sentido reenviar tal cual (largo/encoding los
# recalcula Flask al construir su propia Response; host es el de Kratos,
# no el nuestro).
_CABECERAS_A_IGNORAR = {"content-length", "transfer-encoding", "connection", "host"}


@kratos_proxy_bp.route("/<path:subruta>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def proxy(subruta: str):
    destino = f"{kratos_modulo.KRATOS_PUBLIC_URL}/{subruta}"
    if request.query_string:
        destino += f"?{request.query_string.decode('utf-8')}"

    cabeceras = {
        clave: valor
        for clave, valor in request.headers.items()
        if clave.lower() not in _CABECERAS_A_IGNORAR
    }

    peticion = urllib.request.Request(
        destino, data=request.get_data() or None, headers=cabeceras, method=request.method
    )
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
    return respuesta
