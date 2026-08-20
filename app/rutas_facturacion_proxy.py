"""Proxy hacia la instancia FacturaScripts del tenant del usuario, expuesta
en un subdominio propio (facturacion.guildawork.com) en vez de la URL
interna 127.0.0.1:PUERTO que usaba el enlace "Abrir FacturaScripts" hasta
ahora -- solo alcanzable desde dentro del propio VPS, nunca desde el
navegador de un usuario real (ver app/facturascripts.py, cada tenant tiene
su propio contenedor con su propio puerto).

Por qué no se reutiliza la sesión de Kratos de app.guildawork.com: su
cookie de sesión está fijada a ese origen (ver
app/kratos.py:_flujo_o_redirigir), no se comparte automáticamente entre
subdominios -- igual que se decidió para el backoffice, login propio e
independiente. Aquí, en vez de un login propio completo, basta con
resolver "a qué tenant pertenece este navegador": /facturacion/abrir
(app/main.py) genera un enlace de un solo uso (facturacion_accesos,
app/db.py) que esta ruta /entrar consume para fijar
session["facturacion_tenant_id"] -- una sesión de Flask normal, propia de
este origen (sin SESSION_COOKIE_DOMAIN configurado en la app, cada
subdominio tiene la suya).

Decisión explícita del usuario (no reabrir sin que lo pida): FacturaScripts
SIGUE pidiendo su propio login (usuario/contraseña generados al
aprovisionar el tenant, ver app/rutas_backoffice.py) -- este proxy solo da
una URL amigable y dirige a la instancia correcta, no sustituye su
autenticación. Un SSO real necesitaría que FacturaScripts soportara OIDC,
no confirmado en esta investigación.

**Sin verificar en vivo todavía** (mismo criterio de honestidad que Cal.diy/
Jitsi en este proyecto): FacturaScripts no fija ningún FS_COREURL/base URL
en su config.php (ver app/facturascripts.py:_generar_config_php, FS_ROUTE
va vacío), lo que sugiere que genera URLs relativas y este proxy debería
funcionar tal cual -- pero no se ha probado contra una instancia real
todavía. Si algún recurso (CSS/JS/redirección) sale roto, lo más probable
es una URL absoluta con el host interno que FacturaScripts generó por su
cuenta; revisar entonces."""
import os
import urllib.error
import urllib.request

from flask import Blueprint, Response, redirect, request, session

from . import db

facturacion_proxy_bp = Blueprint("facturacion_proxy", __name__, url_prefix="/facturacion-proxy")

FACTURACION_ORIGIN = os.environ.get("FACTURACION_ORIGIN", "https://facturacion.guildawork.com")
TIMEOUT_SEGUNDOS = 20

# Mismo criterio que app/rutas_kratos_proxy.py: cabeceras que Flask recalcula
# al construir su propia Response, o que apuntan al host equivocado.
_CABECERAS_A_IGNORAR = {"content-length", "transfer-encoding", "connection", "host"}


def _opener_sin_redireccion() -> urllib.request.OpenerDirector:
    class _SinRedireccion(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    return urllib.request.build_opener(_SinRedireccion)


@facturacion_proxy_bp.route("/entrar")
def entrar():
    token = request.args.get("token", "")
    tenant_id = db.consumir_acceso_facturacion(token) if token else None
    if tenant_id is None:
        return Response(
            "Este enlace ha caducado o ya se ha usado. Vuelve a Guilda Work y abre "
            "\"Facturación\" de nuevo desde /herramientas.",
            status=403,
        )
    session["facturacion_tenant_id"] = tenant_id
    # Relativa a facturacion.guildawork.com (NO al prefijo /facturacion-proxy
    # de este blueprint) -- Caddy reescribe */ -> /facturacion-proxy/uri en
    # cada petición pública que llega, así que añadir el prefijo aquí
    # quedaría duplicado. Ver la nota de Location en proxy() más abajo.
    return redirect("/")


@facturacion_proxy_bp.route("/", defaults={"subruta": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@facturacion_proxy_bp.route("/<path:subruta>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def proxy(subruta: str):
    tenant_id = session.get("facturacion_tenant_id")
    if tenant_id is None:
        return Response(
            "No has entrado desde Guilda Work todavía. Abre \"Facturación\" desde /herramientas.",
            status=403,
        )
    tenant = db.obtener_tenant(tenant_id)
    facturascripts_url = tenant["facturascripts_url"] if tenant else None
    if not facturascripts_url:
        return Response("Tu gestoría no tiene FacturaScripts aprovisionado todavía.", status=404)

    base = facturascripts_url.rstrip("/")
    destino = f"{base}/{subruta}"
    if request.query_string:
        destino += f"?{request.query_string.decode('utf-8')}"

    cabeceras = {
        clave: valor
        for clave, valor in request.headers.items()
        if clave.lower() not in _CABECERAS_A_IGNORAR
    }
    cuerpo = request.get_data() or None

    peticion = urllib.request.Request(destino, data=cuerpo, headers=cabeceras, method=request.method)
    opener = _opener_sin_redireccion()
    try:
        with opener.open(peticion, timeout=TIMEOUT_SEGUNDOS) as resp:
            cuerpo_resp = resp.read()
            estado = resp.status
            cabeceras_resp = resp.headers
    except urllib.error.HTTPError as e:
        cuerpo_resp = e.read()
        estado = e.code
        cabeceras_resp = e.headers
    except urllib.error.URLError as e:
        return Response(f"No se ha podido conectar con FacturaScripts: {e.reason}", status=502)

    respuesta = Response(cuerpo_resp, status=estado)
    for clave, valor in cabeceras_resp.items():
        if clave.lower() in _CABECERAS_A_IGNORAR:
            continue
        if clave.lower() == "location" and valor.startswith(base):
            # Igual que app/rutas_kratos_proxy.py: una redirección que
            # FacturaScripts emitió con su propio host interno (127.0.0.1:PUERTO)
            # se reescribe a una ruta relativa -- el navegador la vuelve a
            # pedir a facturacion.guildawork.com, y Caddy la reenvía de
            # nuevo a este mismo proxy (rewrite */facturacion-proxy{uri}),
            # así que aquí NUNCA hay que añadir el prefijo /facturacion-proxy
            # a mano, o quedaría duplicado en la siguiente vuelta.
            valor = valor[len(base):] or "/"
        respuesta.headers.add(clave, valor)
    return respuesta
